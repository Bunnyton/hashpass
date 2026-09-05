"""Build a task: image + selective derivation on the image chain + hidden /hp + meta."""
import itertools
from collections.abc import Callable
from fnmatch import fnmatch
from pathlib import Path

from hashpass.build import build
from hashpass.canon import Observation, canonicalize
from hashpass.hidden import stage_hidden_layer
from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.recipe.model import Recipe, StageSpec, image_ref
from hashpass.recipe.taskbridge import recipe_to_taskcode
from hashpass.runner.nspawn import NspawnRunner
from hashpass.taskcode.bundle import Bundle, dump_bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskcode.execute import OUTPUT_KEY, run_stage
from hashpass.taskcode.model import StageCode, TaskCode
from hashpass.taskstore import StageMeta, StoredTask, TaskMeta, save_meta

_MIN_PASSES = 2  # differential derivation needs >= 2 passes to cancel run noise
_PERCENT = 100   # `settings similarity` is a percent; the comparator threshold is a 0-1 ratio


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
    if stage.observe or stage.match_output:
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
            StageCode(commands=s.commands, observe=s.observe, exclude=(), message=s.message)
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
                  threshold: float = 1.0) -> StageChecks:
    """Run one observed stage `passes` times on FRESH runners, curate, canonicalize."""
    observations: list[Observation] = []
    for p in range(passes):
        _report(progress, f"    pass {p + 1}/{passes}")
        runner = factory()
        try:
            obs = run_stage(runner, deriv_task, stage_index)
        finally:
            runner.teardown()
        observations.append(_curate(obs, exclude))
    canonical = canonicalize(observations)
    if not _has_signal(canonical):
        msg = f"stage {stage_index}: no stable discriminating signal (vacuous canonical)"
        raise ValueError(msg)
    return StageChecks(canonical=canonical, threshold=threshold)


def _selective_derive(factory: Callable[[], NspawnRunner], recipe: Recipe, task: TaskCode,
                      passes: int,
                      progress: Callable[[str], None] | None = None) -> tuple[list[StageChecks], list[str]]:
    """Per stage: handler -> sentinel checks; observed -> derived checks. Returns (checks, modes)."""
    deriv_task = _no_exclude(task)
    checks: list[StageChecks] = []
    acceptance: list[str] = []
    total = len(recipe.stages)
    for i, stage in enumerate(recipe.stages):
        mode = _acceptance_of(stage)
        label = f"  stage {i + 1}/{total}: {stage.message[:56]}"
        if mode in ("handler", "command"):
            _report(progress, f"{label} ({mode})")
            checks.append(StageChecks(canonical={}))       # sentinel; runtime uses handler/accept_cmds
        else:
            _report(progress, label)
            # `observe output` grades stdout with the fuzzy `settings similarity` threshold;
            # plain FS observation stays exact (threshold 1.0).
            threshold = recipe.settings.similarity / _PERCENT if stage.match_output else 1.0
            checks.append(_derive_stage(factory, deriv_task, i, stage.exclude, passes,
                                        progress, threshold))
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
            match_output=s.match_output,
        )
        for i, s in enumerate(recipe.stages)
    )
    return TaskMeta(image_ref=ref, stages=stages, readme=_read_readme(recipe.readme),
                    voice=recipe.voice, settings=recipe.settings, react=recipe.react,
                    intro=recipe.intro, outro=recipe.outro)


def _read_readme(path: str | None) -> str | None:
    """Read the readme file's CONTENT at build (resolved from CWD, like hidden/copy)."""
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
        base: Prebuilt base rootfs layer (the `debian:trixie` image); when given it is
            used directly and `base_tar` is ignored (built once in the store, reused).
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

    stage_checks, acceptance = _selective_derive(factory, recipe, task, passes, progress)

    tdir = store.get(ref).layer.parent / "task"
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
