"""Build a task: image + selective derivation on the image chain + hidden /hp + meta."""
# Per-stage derivation cache (Docker-style prefix layers): derivation -- each stage's `solve` run
# `passes` times in nspawn -- is the slow half of a task build. Stage i is derived from the image,
# the `solve` of stages 0..i-1 (replayed as prep) and its own grading fields, so those (plus the
# runtime user, passes and the engine's own source) fold into the stage's cache key. Edit the last
# stage and only it re-derives; edit an earlier `solve` and that stage and every later one do; a
# hint / message / on-pass / hidden edit re-derives nothing (meta + /hp are always rewritten, cheap).
import hashlib
import itertools
import json
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path

import hashpass
from hashpass.build import build
from hashpass.canon import Observation, canonicalize
from hashpass.hidden import stage_hidden_layer
from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.recipe.model import Recipe, StageSpec, image_ref
from hashpass.recipe.taskbridge import recipe_to_taskcode
from hashpass.runner.nspawn import NspawnRunner
from hashpass.taskcode.bundle import (
    Bundle,
    dump_bundle,
    stage_checks_from_dict,
    stage_checks_to_dict,
)
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskcode.execute import OUTPUT_KEY, run_stage
from hashpass.taskcode.model import StageCode, TaskCode
from hashpass.taskstore import StageMeta, StoredTask, TaskMeta, save_meta

_MIN_PASSES = 2  # differential derivation needs >= 2 passes to cancel run noise
_PERCENT = 100   # `settings similarity` is a percent; the comparator threshold is a 0-1 ratio
_CACHE_DIR = "derive-cache"   # under the task dir: one <key>.json StageChecks per derived stage
# Package sources whose change can alter what derivation produces: editing the engine busts the cache.
_ENGINE_SOURCES = ("taskbuild.py", "canon", "taskcode", "recipe", "runner")


def _engine_stamp() -> str:
    """Hash the derivation engine's own source, so a grader/derive change re-derives every task."""
    root = Path(hashpass.__file__).parent
    h = hashlib.sha256()
    for name in _ENGINE_SOURCES:
        p = root / name
        files = sorted(p.rglob("*.py")) if p.is_dir() else [p]
        for f in files:
            h.update(str(f.relative_to(root)).encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def _stage_keys(recipe: Recipe, image_key: str | None, passes: int) -> list[str | None]:
    """
    Cache key per stage: image + user/similarity/passes + engine + prior solves + own grading fields.

    `None` for every stage when the image has no build key (pulled/committed): nothing to anchor to.
    """
    if not image_key:
        return [None] * len(recipe.stages)
    head = hashlib.sha256()
    for part in (image_key, repr(recipe.settings.user), repr(recipe.settings.similarity),
                 str(passes), _engine_stamp()):
        head.update(part.encode() + b"\0")
    keys: list[str | None] = []
    for st in recipe.stages:
        own = (st.solve, st.observe, st.observe_bool, st.exclude, st.check, st.accept_cmds,
               st.match_output, st.variants)
        h = head.copy()
        h.update(repr(own).encode())
        keys.append(h.hexdigest())
        head.update(repr(st.solve).encode() + b"\0")    # later stages replay this solve as prep
    return keys


def _cache_get(cache: Path, key: str | None) -> StageChecks | None:
    """Return a cached stage derivation, or None (no key, miss, or an unreadable entry)."""
    if key is None:
        return None
    try:
        return stage_checks_from_dict(json.loads((cache / f"{key}.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _cache_put(cache: Path, key: str | None, checks: StageChecks) -> None:
    """Store one stage's derivation (atomic rename, so an interrupted write never looks cached)."""
    if key is None:
        return
    cache.mkdir(parents=True, exist_ok=True)
    tmp = cache / f"{key}.tmp"
    tmp.write_text(json.dumps(stage_checks_to_dict(checks)), encoding="utf-8")
    tmp.replace(cache / f"{key}.json")


def _cache_prune(cache: Path, keep: list[str | None]) -> None:
    """Drop entries no current stage uses, so the cache never grows past the task's stage count."""
    if not cache.is_dir():
        return
    wanted = {f"{k}.json" for k in keep if k}
    for f in cache.iterdir():
        if f.name not in wanted:
            f.unlink(missing_ok=True)


def _excluded(key: str, patterns: tuple[str, ...]) -> bool:
    """
    Return True if an observed key should be dropped by a DSL `exclude` pattern.

    DSL exclude patterns are GLOBS (`*.log`, `.cache`), not the raw path prefixes
    `taskcode.execute._curate` matches with `str.startswith`. We honor globs here in
    the derivation capture path: a pattern matches if it globs the whole key OR any
    single path segment (so `*.log` drops `home/s/run.log`, `.cache` drops
    `home/s/.cache/x`). This is the chosen resolution of the prefix-vs-glob caveat.
    """
    segments = key.split("/")
    return any(
        fnmatch(key, pat) or any(fnmatch(seg, pat) for seg in segments)
        for pat in patterns
    )


def _curate(obs: Observation, exclude: tuple[str, ...]) -> Observation:
    """Drop DSL-glob-excluded observed keys (never the captured OUTPUT_KEY)."""
    return {k: v for k, v in obs.items()
            if k == OUTPUT_KEY or not _excluded(k, exclude)}


def _has_signal(canonical: Observation) -> bool:
    """Return whether a canonical carries a real signal (an FS field or non-blank output)."""
    if any(k != OUTPUT_KEY for k in canonical):
        return True
    out = canonical.get(OUTPUT_KEY)
    return out is not None and out.text is not None and bool(out.text.strip())


def _acceptance_of(stage: StageSpec) -> str:
    """`check` -> handler; else observed -> derived; else `accept cmd` -> command; else error."""
    if stage.check is not None:
        return "handler"
    if stage.observe or stage.observe_bool or stage.match_output:
        return "derived"       # FS paths and/or `observe output` (command stdout)
    if stage.accept_cmds:
        return "command"       # accepted purely by a matching student command (no FS grading)
    msg = f"stage {stage.message!r} has no `observe`, `check`, or `accept cmd`: cannot be accepted"
    raise ValueError(msg)


def _no_exclude(task: TaskCode) -> TaskCode:
    """Return a derivation copy with per-stage `exclude` cleared (curated via fnmatch instead)."""
    return TaskCode(
        id=task.id,
        setup=task.setup,
        stages=tuple(
            StageCode(commands=s.commands, observe=s.observe, observe_bool=s.observe_bool,
                      exclude=(), message=s.message)
            for s in task.stages
        ),
    )


def _report(progress: Callable[[str], None] | None, msg: str) -> None:
    """Emit a build-progress line if a progress sink is provided (no-op otherwise)."""
    if progress is not None:
        progress(msg)


def _derive_stage(factory: Callable[[], NspawnRunner], deriv_task: TaskCode,  # noqa: PLR0913, PLR0917
                  stage_index: int, exclude: tuple[str, ...], passes: int,
                  progress: Callable[[str], None] | None = None,
                  threshold: float = 1.0, keep_output: bool = False,  # noqa: FBT001, FBT002
                  variants: tuple[tuple[str, ...], ...] = (),
                  user: str | None = None) -> StageChecks:
    """
    Derive one observed stage: run its solution(s) on FRESH runners, curate, canonicalize.

    With no `variants`, the single `solve` runs `passes` times so RUN noise (timestamps, pids)
    cancels. With `variants`, the reference is instead the state COMMON to several DIFFERENT
    solutions -- `solve` and every `variant` run once, and canonicalize keeps only what they all
    agree on. So COMMAND-specific chrome cancels the same way run noise does, leaving the output
    that actually matters (`какой командой -- не важно`); if the solutions disagree, the canonical
    goes vacuous and the build fails loudly.
    """
    # `None` runs the stage's own `solve`; each variant runs as an override. With variants, the
    # solution set is `solve` + every variant (run once each); without, `solve` repeated `passes`x.
    runs: list[tuple[str, ...] | None] = [None, *variants] if variants else [None] * passes
    observations: list[Observation] = []
    for p, override in enumerate(runs):
        _report(progress, f"    solution {p + 1}/{len(runs)}")
        runner = factory()
        try:
            obs = run_stage(runner, deriv_task, stage_index, override=override, user=user)
        finally:
            runner.teardown()
        observations.append(_curate(obs, exclude))
    canonical = canonicalize(observations)
    if not keep_output:
        # `observe <path>` grades FILES only. Drop the captured stdout: live grading compares
        # against a noisy terminal recording, never the clean solve stdout, so keeping OUTPUT_KEY
        # here would make every filesystem stage fail live. `observe output` keeps it (the signal).
        canonical.pop(OUTPUT_KEY, None)
    if not _has_signal(canonical):
        msg = f"stage {stage_index}: no stable discriminating signal (vacuous canonical)"
        raise ValueError(msg)
    return StageChecks(canonical=canonical, threshold=threshold)


def _selective_derive(factory: Callable[[], NspawnRunner], recipe: Recipe, task: TaskCode,  # noqa: PLR0913, PLR0917
                      passes: int,
                      progress: Callable[[str], None] | None = None,
                      cache: Path | None = None,
                      keys: list[str | None] | None = None) -> tuple[list[StageChecks], list[str]]:
    """
    Per stage: handler -> sentinel checks; observed -> derived checks. Returns (checks, modes).

    Solve prep + target both run under the recipe's `settings.user`, so `whoami`/$USER/id
    references derive against the SAME user the live console will run under (§7.2).
    """
    deriv_task = _no_exclude(task)
    user = recipe.settings.user or None                # None keeps nspawn's default (root)
    checks: list[StageChecks] = []
    acceptance: list[str] = []
    total = len(recipe.stages)
    for i, stage in enumerate(recipe.stages):
        mode = _acceptance_of(stage)
        label = f"  stage {i + 1}/{total}: {stage.message[:56] or '(без текста)'}"
        if mode in ("handler", "command"):
            _report(progress, f"{label} ({mode})")
            checks.append(StageChecks(canonical={}))       # sentinel; runtime uses handler/accept_cmds
        elif cache is not None and (hit := _cache_get(cache, keys[i])) is not None:
            _report(progress, f"{label} (не изменилась — из кэша)")
            checks.append(hit)
        else:
            _report(progress, label)
            # `observe output` grades stdout with the fuzzy `settings similarity` threshold;
            # plain FS observation stays exact (threshold 1.0).
            threshold = recipe.settings.similarity / _PERCENT if stage.match_output else 1.0
            derived = _derive_stage(factory, deriv_task, i, stage.exclude, passes,
                                    progress, threshold, keep_output=stage.match_output,
                                    variants=stage.variants, user=user)
            if cache is not None:
                _cache_put(cache, keys[i], derived)
            checks.append(derived)
        acceptance.append(mode)
    return checks, acceptance


def _build_meta(ref: str, recipe: Recipe, acceptance: list[str]) -> TaskMeta:
    """Assemble the runtime TaskMeta from the recipe stages + per-stage acceptance modes."""
    stages = tuple(
        StageMeta(
            message=s.message,
            neutral=s.neutral,
            check=s.check.value if s.check is not None else None,
            on_enter=s.on_enter,
            on_pass=s.on_pass,
            acceptance=acceptance[i],
            hints=s.hints,
            accept_cmds=s.accept_cmds,
            accept_ok=s.accept_ok,
            match_output=s.match_output,
            deny=s.deny,
            allow=s.allow,
        )
        for i, s in enumerate(recipe.stages)
    )
    return TaskMeta(image_ref=ref, stages=stages, readme=_read_readme(recipe.readme),
                    voice=recipe.voice, settings=recipe.settings, react=recipe.react,
                    intro=recipe.intro, outro=recipe.outro)


def _read_readme(path: str | None) -> str | None:
    """Read the readme file's CONTENT at build (the CLI pre-resolves the path to the Taskfile dir)."""
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def build_task(recipe: Recipe, store: ImageStore, *,  # noqa: PLR0913
               base_tar: Path | None = None, base: Path | None = None,
               workdir: Path, passes: int = 3, sudo: bool = True,
               progress: Callable[[str], None] | None = None) -> StoredTask:
    """
    Build a task: bake the image, derive acceptance on its chain, stage `/hp`, write meta.

    Steps: (1) `build` the image (bakes `run`/`copy`); (2) project to TaskCode;
    (3) selective derivation on the built image's overlay chain — observed stages run
    `passes` times on fresh NspawnRunners and canonicalize; `check`/observe-less stages
    get a sentinel + handler acceptance; (4) dump the bundle; (5) stage the hidden `/hp`
    tree from `recipe.hidden`; (6) write `task-meta.json`. Reuses the proven derivation
    engine unchanged (globs are curated in the capture path, not by `run_stage`).

    Args:
        recipe: A task recipe (must declare stages).
        store: Image store to build into and resolve the chain from.
        base_tar: Rootfs tarball for the bottom base layer (fallback when `base` is None).
        base: Prebuilt base rootfs layer -- the base image (`bunnyton/debian:trixie`,
            see `cli.base_ref`); when given it is used directly and `base_tar` is ignored
            (built once in the store, reused).
        workdir: Scratch dir for the image build, base, and per-pass runners.
        passes: Derivation passes per observed stage (>= 2).
        sudo: Whether overlay mounts use sudo (True for real nspawn).
        progress: Optional sink for build-progress lines (image steps, stages, passes).

    Returns:
        The StoredTask (ref, image, bundle dir, hidden `/hp` dir, meta).

    """
    workdir = Path(workdir)
    if passes < _MIN_PASSES:
        msg = f"passes must be >= {_MIN_PASSES} for differential derivation, got {passes}"
        raise ValueError(msg)
    ref = image_ref(recipe)
    _report(progress, f"building image {ref}: {len(recipe.steps)} build step(s)")
    image = build(recipe, store, base_tar=base_tar, base=base, workdir=workdir / "img",
                  sudo=sudo, progress=progress)
    task = recipe_to_taskcode(recipe)

    tdir = store.get(ref).layer.parent / "task"
    cache = tdir / _CACHE_DIR
    keys = _stage_keys(recipe, image.build_key, passes)

    _report(progress, "вывожу приёмку...")
    lowers = resolve_lowers((ref,), store)
    base = base or build_base(workdir / "base", from_tar=base_tar)
    counter = itertools.count()

    def factory() -> NspawnRunner:
        # Derivation is INTERNAL (never seen by the student): a fast, reliable NON-boot nspawn
        # runs the solve + captures the FS. Avoids booting a machine per stage/pass (~6 boots a
        # build) -- much faster and it does not stress the host's machined. The student runtime
        # (run_task/run_image) still boots for a real, live system.
        runner = NspawnRunner(workdir / f"derive{next(counter)}", base_dir=base)
        runner.prepare(lowers)
        return runner

    stage_checks, acceptance = _selective_derive(factory, recipe, task, passes, progress,
                                                 cache=cache, keys=keys)
    _cache_prune(cache, keys)

    bundle_dir = tdir / "bundle"
    derived = DerivedChecks(task_id=task.id, stages=tuple(stage_checks))
    dump_bundle(Bundle(checks=derived, conditions={}, hints={}), bundle_dir)

    hp_dir = tdir / "hp"
    work_src = Path(recipe.hidden) if recipe.hidden else None
    _report(progress, "готовлю скрытый /hp-слой и приёмку")
    stage_hidden_layer(hp_dir, work_src=work_src, bundle_dir=bundle_dir)

    meta = _build_meta(ref, recipe, acceptance)
    save_meta(meta, tdir)
    _report(progress, f"сохранил задание {ref}")
    return StoredTask(ref=ref, image=image, bundle_dir=bundle_dir, hp_src_dir=hp_dir, meta=meta)
