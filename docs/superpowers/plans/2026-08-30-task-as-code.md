# Task-as-code + derivation + checker + codegen — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the walking-skeleton task stubs with the real task-as-code pipeline: an author's task (reference-solution commands per stage + observed paths) is run in a `Runner` with k differential passes to DERIVE per-stage acceptance checks (a config bundle), and a checker evaluates a candidate's captured state against that bundle — plus codegen that turns a recorded command transcript into task-as-code.

**Architecture:** New pure-logic package `src/hashpass/taskcode/` on top of existing primitives (`runner`, `canon`, `compare`, `hooks`, `cmd`). A task is authored as TOML → `TaskCode` dataclasses. Derivation runs each stage k times (fresh `Runner` + orthogonal noise) and keeps only fields stable across runs (via `canon.canonicalize`), folding the stage's own stdout into the `Observation` under a reserved `"<output>"` key so FS state and output are canonicalized/compared through ONE path. Derived checks serialize to a machine-only `checks.json`; hand-edited `conditions.toml`/`hints.toml` round out the bundle. A checker consumes the bundle + a candidate `Observation` and accepts via `canon.matches`, with an optional `@check` escape and advisory `conditions`.

**Tech Stack:** Python 3.13, stdlib only (`tomllib`/`json`/`dataclasses`/`pathlib`), pytest, ruff. Consumes in-repo `hashpass.runner`, `hashpass.canon`, `hashpass.compare`, `hashpass.hooks`, `hashpass.cmd`. NO third-party deps.

**Spec:** `docs/Архитектура (architecture).md` — §3 (задание-как-код и генерация), §4 (приём этапа), §5 (канонизация/сравнение; per-stage comparator pinning), §10 (tiers).

## Global Constraints

- Python 3.13; stdlib + in-repo `hashpass.{runner,canon,compare,hooks,cmd}` ONLY. No new deps.
- `encoding="utf-8"` on every text read/write.
- ruff `select=["ALL"]` clean under the repo `ruff.toml`; TEST FILES ARE LINTED. Introduce a module constant instead of a bare literal where a comparison would trip `PLR2004` (see canon's `_MIN_K`). Nested/private functions (incl. test helpers) need a return annotation (`ANN202`); dataclasses need a class docstring (`D101`); a pinned signature with 6 params carries `# noqa: PLR0913` (as `compare.similarity` already does).
- The acceptance invariant is DATA, never key material (§6) — Plan D does NOT touch keys/evidence.
- Acceptance is TOLERANT by default (size-adaptive Jaccard/MinHash via `compare`, threshold < 1.0 allowed); exact stages use `compare.exact_hash`/threshold 1.0. Fail CLOSED on an empty canonical (reuse `canon.matches`, which already returns `False` on empty canonical).
- src-layout: code in `src/hashpass/taskcode/`, tests in `tests/taskcode/` (add `__init__.py`).
- All Plan D tests are **tier1** (`@pytest.mark.tier1`) using `TmpdirRunner` + a tiny hand-built rootfs (mkdir + touch/write). NO rootfs extraction, NO overlay, NO nspawn.

### Consumed APIs (verbatim — do not change these)

```python
# hashpass.runner.base
@dataclass
class RunResult: stdout: str; stderr: str; exit_code: int
class Runner(Protocol):
    def prepare(self, lowers: list[Path]) -> None: ...
    def run(self, argv: list[str]) -> RunResult: ...
    @property
    def rootfs(self) -> Path: ...
    def teardown(self) -> None: ...
# hashpass.runner.tmpdir.TmpdirRunner(workdir): rootfs = workdir/"rootfs"; prepare([]) mkdirs it;
#   run(argv) is a FRESH subprocess with cwd=rootfs; teardown rmtrees. To run a shell string:
#   runner.run(["sh", "-c", script]). Multiple commands in ONE stage are newline-joined into ONE
#   `sh -c` so intra-stage cwd/env is preserved.

# hashpass.canon
@dataclass(frozen=True)
class FileState: kind: str; text: str | None      # kind in {"file","dir","absent"}
Observation = dict[str, FileState]
def capture(rootfs: Path, observe: list[str], *, output_path: str | None = None) -> Observation
def canonicalize(observations: list[Observation]) -> Observation   # keep keys present & equal in ALL
def derive_canonical(run_once, *, k: int = 3) -> Observation        # raises ValueError if empty/k<2
def matches(canonical: Observation, candidate: Observation, *, threshold: float = 1.0,
            mode: str = "line", k: int = 1) -> bool                 # returns False if canonical empty
def default_noise() -> list[list[str]]
def run_noise(runner: Runner, noise: list[list[str]] | None = None) -> None

# hashpass.compare
def similarity(a, b, *, mode="word", k=3, size_threshold=4096, num_perm=128) -> float
def accept(a, b, *, threshold, **kw) -> bool
def exact_hash(data: str) -> str

# hashpass.hooks.HookRegistry: .command/.filter/.check(stages) decorators;
#   run_check(cmd, stage) -> bool | None   (first non-None wins; None => defer to comparison).
# hashpass.cmd.Cmd(raw): .basecmd/.short_flags/.long_flags/.args/.is_sudo; .has_flag("-l"/"--long").
#   parse_cmds(raw) -> list[Cmd]   (splits on && / || / ;).
```

---

### Task 1: `model.py` — TaskCode/StageCode + TOML round-trip

**Files:**
- Create: `src/hashpass/taskcode/__init__.py` (empty package marker)
- Create: `src/hashpass/taskcode/model.py`
- Create: `tests/taskcode/__init__.py` (empty)
- Test: `tests/taskcode/test_model.py`

**Interfaces:**
- Consumes: stdlib `tomllib`, `pathlib.Path`.
- Produces:
  - `@dataclass(frozen=True) StageCode(commands: tuple[str, ...], observe: tuple[str, ...], exclude: tuple[str, ...] = (), message: str = "")`
  - `@dataclass(frozen=True) TaskCode(id: str, setup: tuple[str, ...], stages: tuple[StageCode, ...])`
  - `load_task_code(path: Path) -> TaskCode` — parse `task.toml` via `tomllib`.
  - `dump_task_code(task: TaskCode, path: Path) -> None` — hand-serialize `task.toml`.
  - `toml_quote(s: str) -> str`, `toml_list(items: tuple[str, ...]) -> str` — TOML basic-string / string-array serializers, reused by Task 5's bundle serializer.
- TOML shape: top-level `id`, `setup = [...]`; each stage is a `[[stage]]` array-of-tables with `commands = [...]`, `observe = [...]`, `exclude = [...]`, `message = "..."`.

- [ ] **Step 1: Write the failing test**

```python
# tests/taskcode/test_model.py
import pytest

from hashpass.taskcode.model import StageCode, TaskCode, dump_task_code, load_task_code


@pytest.mark.tier1
def test_task_code_toml_round_trip(tmp_path):
    task = TaskCode(
        id="demo",
        setup=("mkdir -p work", "echo seeded > work/base.txt"),
        stages=(
            StageCode(
                commands=("cd work", 'echo "answer" > result.txt'),
                observe=("work/result.txt",),
                exclude=("work/tmp",),
                message="Write the answer.",
            ),
            StageCode(
                commands=("sort work/result.txt > work/sorted.txt",),
                observe=("work/sorted.txt",),
            ),
        ),
    )
    path = tmp_path / "task.toml"
    dump_task_code(task, path)
    assert load_task_code(path) == task  # exact round-trip, incl. escaped quotes + defaults
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/taskcode/test_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.taskcode'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/taskcode/model.py
"""Task-as-code model: TaskCode/StageCode dataclasses + TOML (de)serialization."""
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StageCode:
    """One stage: reference-solution commands + curated observed paths."""

    commands: tuple[str, ...]
    observe: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class TaskCode:
    """A whole task: id, seeded setup commands, and ordered stages."""

    id: str
    setup: tuple[str, ...]
    stages: tuple[StageCode, ...]


def toml_quote(s: str) -> str:
    esc = (s.replace("\\", "\\\\").replace('"', '\\"')
           .replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r"))
    return f'"{esc}"'


def toml_list(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(toml_quote(x) for x in items) + "]"


def dump_task_code(task: TaskCode, path: Path) -> None:
    lines = [f"id = {toml_quote(task.id)}", f"setup = {toml_list(task.setup)}"]
    for stage in task.stages:
        lines.append("")
        lines.append("[[stage]]")
        lines.append(f"commands = {toml_list(stage.commands)}")
        lines.append(f"observe = {toml_list(stage.observe)}")
        lines.append(f"exclude = {toml_list(stage.exclude)}")
        lines.append(f"message = {toml_quote(stage.message)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_task_code(path: Path) -> TaskCode:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    stages = tuple(
        StageCode(
            commands=tuple(s.get("commands", [])),
            observe=tuple(s.get("observe", [])),
            exclude=tuple(s.get("exclude", [])),
            message=s.get("message", ""),
        )
        for s in data.get("stage", [])
    )
    return TaskCode(id=data["id"], setup=tuple(data.get("setup", [])), stages=stages)
```

Also create the two empty package markers:

```python
# src/hashpass/taskcode/__init__.py   (empty file)
```
```python
# tests/taskcode/__init__.py          (empty file)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/taskcode/test_model.py -v` → PASS.
Run: `ruff check src tests runtime` → clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(taskcode): TaskCode/StageCode model + TOML round-trip"
```

---

### Task 2: `execute.py` — run_stage; folds `"<output>"`; noise-before-capture

**Files:**
- Create: `src/hashpass/taskcode/execute.py`
- Test: `tests/taskcode/test_execute.py`

**Interfaces:**
- Consumes: `TaskCode`, `StageCode` (Task 1); `Runner` (`hashpass.runner.base`); `FileState`, `Observation`, `capture`, `run_noise` (`hashpass.canon`).
- Produces:
  - `OUTPUT_KEY = "<output>"`
  - `run_stage(runner: Runner, task: TaskCode, stage_index: int, *, noise: list[list[str]] | None = None) -> Observation`

**Contract (corrected — output is the TARGET stage's own stdout, per §4 "вывод последней команды"):**
1. Run `PREP = task.setup + stages[0..stage_index-1].commands`, newline-joined, as ONE `sh -c` via `runner.run` — DISCARD its stdout (it only mutates the rootfs).
2. Run `TARGET = stages[stage_index].commands`, newline-joined, as a SECOND `sh -c` — capture THIS `RunResult.stdout` as the stage output.
3. `run_noise(runner, noise)` (noise settles AFTER commands, BEFORE capture — §5 guardrail).
4. `obs = capture(runner.rootfs, list(target.observe))`; set `obs[OUTPUT_KEY] = FileState("file", target_stdout)`; drop any key matching an `exclude` prefix; return `obs`.

**Known limitation (state in the plan):** each `runner.run` is a fresh subprocess (`cwd=rootfs`), so cwd/env does NOT carry from PREP into TARGET — only within a single stage's newline-joined block. Task authors put any needed `cd` inside each stage's own commands.

- [ ] **Step 1: Write the failing test**

```python
# tests/taskcode/test_execute.py
import pytest

from hashpass.canon import FileState
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.execute import run_stage
from hashpass.taskcode.model import StageCode, TaskCode


@pytest.mark.tier1
def test_run_stage_captures_state_and_own_output(tmp_path):
    r = TmpdirRunner(tmp_path / "run")
    r.prepare([])
    task = TaskCode(
        id="t",
        setup=("echo SETUP_NOISE",),
        stages=(
            StageCode(commands=("echo hi > out.txt", "echo OUT"), observe=("out.txt",)),
        ),
    )
    obs = run_stage(r, task, 0)
    assert obs["out.txt"] == FileState("file", "hi\n")
    assert obs["<output>"] == FileState("file", "OUT\n")   # target stage's own stdout
    assert "SETUP_NOISE" not in obs["<output>"].text        # setup/prep stdout NOT leaked
    r.teardown()


@pytest.mark.tier1
def test_run_stage_drops_excluded_prefix(tmp_path):
    r = TmpdirRunner(tmp_path / "run")
    r.prepare([])
    task = TaskCode(
        id="t",
        setup=(),
        stages=(
            StageCode(
                commands=("mkdir -p logs", "echo keep > logs/keep.txt",
                          "echo drop > logs/drop.tmp"),
                observe=("logs",),
                exclude=("logs/drop",),
            ),
        ),
    )
    obs = run_stage(r, task, 0)
    assert "logs/keep.txt" in obs
    assert "logs/drop.tmp" not in obs   # dropped by exclude prefix
    r.teardown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/taskcode/test_execute.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.taskcode.execute'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/taskcode/execute.py
"""Run a task stage in a Runner and snapshot its Observation (state + own output)."""
from hashpass.canon import FileState, Observation, capture, run_noise
from hashpass.runner.base import Runner
from hashpass.taskcode.model import TaskCode

OUTPUT_KEY = "<output>"


def _script(commands: tuple[str, ...]) -> str:
    return "\n".join(commands)


def run_stage(runner: Runner, task: TaskCode, stage_index: int,
              *, noise: list[list[str]] | None = None) -> Observation:
    prep: list[str] = list(task.setup)
    for stage in task.stages[:stage_index]:
        prep.extend(stage.commands)
    if prep:
        runner.run(["sh", "-c", _script(tuple(prep))])   # PREP: mutate rootfs, discard stdout
    target = task.stages[stage_index]
    result = runner.run(["sh", "-c", _script(target.commands)])   # TARGET: capture stdout
    run_noise(runner, noise)
    obs = capture(runner.rootfs, list(target.observe))
    obs[OUTPUT_KEY] = FileState("file", result.stdout)
    for key in list(obs):
        if any(key.startswith(prefix) for prefix in target.exclude):
            del obs[key]
    return obs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/taskcode/test_execute.py -v` → PASS.
Run: `ruff check src tests runtime` → clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(taskcode): run_stage folds <output>, noise before capture"
```

---

### Task 3: `observe.py` — classify_observed + apply_curation

**Files:**
- Create: `src/hashpass/taskcode/observe.py`
- Test: `tests/taskcode/test_observe.py`

**Interfaces:**
- Consumes: `FileState`, `Observation` (`hashpass.canon`).
- Produces:
  - `@dataclass(frozen=True) ObserveClassification(stable: tuple[str, ...], pruned: tuple[str, ...])`
  - `classify_observed(observations: list[Observation]) -> ObserveClassification` — union of all keys; a key is `stable` iff present in EVERY obs AND all equal, else `pruned`. Both tuples sorted.
  - `apply_curation(obs: Observation, *, exclude: tuple[str, ...]) -> Observation` — drop keys matching any `exclude` prefix.

- [ ] **Step 1: Write the failing test**

```python
# tests/taskcode/test_observe.py
import pytest

from hashpass.canon import FileState
from hashpass.taskcode.observe import apply_curation, classify_observed


@pytest.mark.tier1
def test_classify_observed_splits_stable_and_pruned():
    const = FileState("file", "answer")
    obs = [
        {"a": const, "t": FileState("file", "1")},
        {"a": const, "t": FileState("file", "2")},
        {"a": const, "t": FileState("file", "3")},
    ]
    result = classify_observed(obs)
    assert result.stable == ("a",)   # present & equal in all runs
    assert result.pruned == ("t",)   # varied → pruned


@pytest.mark.tier1
def test_classify_observed_prunes_key_absent_in_some_run():
    const = FileState("file", "answer")
    obs = [{"a": const, "b": const}, {"a": const}]   # "b" absent in 2nd run
    result = classify_observed(obs)
    assert result.stable == ("a",)
    assert result.pruned == ("b",)


@pytest.mark.tier1
def test_apply_curation_drops_excluded_prefixes():
    obs = {"keep.txt": FileState("file", "k"), "tmp/x": FileState("file", "t")}
    out = apply_curation(obs, exclude=("tmp/",))
    assert "keep.txt" in out
    assert "tmp/x" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/taskcode/test_observe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.taskcode.observe'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/taskcode/observe.py
"""Classify observed keys as stable/pruned across runs, and apply exclude curation."""
from dataclasses import dataclass

from hashpass.canon import Observation


@dataclass(frozen=True)
class ObserveClassification:
    """Split of observed keys into stable (kept) vs pruned (incidental)."""

    stable: tuple[str, ...]
    pruned: tuple[str, ...]


def classify_observed(observations: list[Observation]) -> ObserveClassification:
    keys: set[str] = set().union(*(obs.keys() for obs in observations)) if observations else set()
    stable: list[str] = []
    pruned: list[str] = []
    for key in sorted(keys):
        values = [obs[key] for obs in observations if key in obs]
        if len(values) == len(observations) and all(v == values[0] for v in values):
            stable.append(key)
        else:
            pruned.append(key)
    return ObserveClassification(stable=tuple(stable), pruned=tuple(pruned))


def apply_curation(obs: Observation, *, exclude: tuple[str, ...]) -> Observation:
    return {k: v for k, v in obs.items() if not any(k.startswith(p) for p in exclude)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/taskcode/test_observe.py -v` → PASS.
Run: `ruff check src tests runtime` → clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(taskcode): classify_observed + apply_curation"
```

---

### Task 4: `derive.py` — derive_checks; per-stage canonical + pinned comparator (DERIVATION SPINE)

**Files:**
- Create: `src/hashpass/taskcode/derive.py`
- Test: `tests/taskcode/test_derive.py`

**Interfaces:**
- Consumes: `TaskCode` (Task 1); `run_stage` (Task 2); `Runner` (`hashpass.runner.base`); `Observation`, `canonicalize` (`hashpass.canon`); `collections.abc.Callable`.
- Produces:
  - `_MIN_K = 2`
  - `@dataclass(frozen=True) StageChecks(canonical: Observation, mode: str = "line", threshold: float = 1.0, k: int = 1, size_threshold: int = 4096)`
  - `@dataclass(frozen=True) DerivedChecks(task_id: str, stages: tuple[StageChecks, ...])`
  - `derive_checks(runner_factory: Callable[[], Runner], task: TaskCode, *, passes: int = 3, mode: str = "line", threshold: float = 1.0, noise: list[list[str]] | None = None) -> DerivedChecks`

**Behavior:** for each stage index, run `passes` times — each with a FRESH runner from `runner_factory` (the factory returns a PREPARED runner; for tests it calls `prepare([])`) — collecting `run_stage` Observations; `canonical = canonicalize([...])`; build a `StageChecks` with the pinned comparator params (`mode`/`threshold` from args, `k`/`size_threshold` from `StageChecks` defaults). This is §5 "per-stage comparator pinning": `mode`/`threshold`/`size_threshold` are recorded so client & server compare identically. Raise `ValueError` if `passes < _MIN_K`. It uses `canonicalize` (not `derive_canonical`), so an all-volatile stage yields an EMPTY canonical that fails CLOSED at match time (`canon.matches` returns `False` on empty) rather than raising here.

**This is the Plan-D spine — a GENUINE discrimination test (a vacuous/empty canonical must FAIL it):** a stage writing a constant file + a volatile `date` file; with `passes=3` the constant survives in the canonical and the volatile key is pruned.

- [ ] **Step 1: Write the failing test**

```python
# tests/taskcode/test_derive.py
import itertools
from collections.abc import Callable

import pytest

from hashpass.canon import FileState
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.model import StageCode, TaskCode


def _factory(tmp_path) -> Callable[[], TmpdirRunner]:
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


@pytest.mark.tier1
def test_derive_checks_keeps_stable_prunes_volatile(tmp_path):
    task = TaskCode(
        id="demo",
        setup=(),
        stages=(
            StageCode(
                commands=("echo answer > result.txt", "date +%s%N > time.txt"),
                observe=("result.txt", "time.txt"),
            ),
        ),
    )
    derived = derive_checks(_factory(tmp_path), task, passes=3)
    canonical = derived.stages[0].canonical

    # DISCRIMINATION: a vacuous/empty derivation, or one that fails to prune, must FAIL here.
    assert canonical, "canonical must be non-empty (a vacuous pass fails this)"
    assert canonical["result.txt"] == FileState("file", "answer\n")   # stable field survived
    assert "time.txt" not in canonical                                 # volatile field pruned
    assert derived.task_id == "demo"

    # comparator params pinned per stage (§5)
    assert derived.stages[0].mode == "line"
    assert derived.stages[0].threshold == 1.0


@pytest.mark.tier1
def test_derive_checks_requires_min_passes(tmp_path):
    task = TaskCode(
        id="demo",
        setup=(),
        stages=(StageCode(commands=("echo answer > result.txt",), observe=("result.txt",)),),
    )
    with pytest.raises(ValueError, match="passes must be"):
        derive_checks(_factory(tmp_path), task, passes=1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/taskcode/test_derive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.taskcode.derive'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/taskcode/derive.py
"""Differential derivation of per-stage acceptance checks (canonical + pinned comparator)."""
from collections.abc import Callable
from dataclasses import dataclass

from hashpass.canon import Observation, canonicalize
from hashpass.runner.base import Runner
from hashpass.taskcode.execute import run_stage
from hashpass.taskcode.model import TaskCode

_MIN_K = 2


@dataclass(frozen=True)
class StageChecks:
    """Derived acceptance check for one stage: canonical invariant + pinned comparator."""

    canonical: Observation
    mode: str = "line"
    threshold: float = 1.0
    k: int = 1
    size_threshold: int = 4096


@dataclass(frozen=True)
class DerivedChecks:
    """All per-stage derived checks for a task."""

    task_id: str
    stages: tuple[StageChecks, ...]


def derive_checks(runner_factory: Callable[[], Runner], task: TaskCode, *,  # noqa: PLR0913
                  passes: int = 3, mode: str = "line", threshold: float = 1.0,
                  noise: list[list[str]] | None = None) -> DerivedChecks:
    if passes < _MIN_K:
        msg = "passes must be >= 2 for differential derivation"
        raise ValueError(msg)
    stage_checks: list[StageChecks] = []
    for stage_index in range(len(task.stages)):
        observations: list[Observation] = []
        for _ in range(passes):
            runner = runner_factory()
            try:
                observations.append(run_stage(runner, task, stage_index, noise=noise))
            finally:
                runner.teardown()
        canonical = canonicalize(observations)
        stage_checks.append(StageChecks(canonical=canonical, mode=mode, threshold=threshold))
    return DerivedChecks(task_id=task.id, stages=tuple(stage_checks))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/taskcode/test_derive.py -v` → PASS (constant kept, `date` timestamp pruned).
Run: `ruff check src tests runtime` → clean.

If the discrimination assertions fail on the merits (volatile NOT pruned, or stable pruned, or empty canonical), that is a finding about the derivation approach — report it, do not paper over it.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(taskcode): derive_checks — per-stage canonical + pinned comparator"
```

---

### Task 5: `bundle.py` — dump/load/apply the split bundle

**Files:**
- Create: `src/hashpass/taskcode/bundle.py`
- Test: `tests/taskcode/test_bundle.py`

**Interfaces:**
- Consumes: `DerivedChecks`, `StageChecks` (Task 4); `FileState`, `Observation` (`hashpass.canon`); `toml_quote`, `toml_list` (Task 1); stdlib `json`, `shutil`, `tomllib`.
- Produces:
  - `@dataclass(frozen=True) Bundle(checks: DerivedChecks, conditions: dict, hints: dict)` — `conditions` is `{stage_index: {"deny": [...], "require_flags": [...], "mention": [...]}}`; `hints` is `{stage_index: [{"trigger": ..., "message": ...}, ...]}`.
  - `dump_bundle(bundle: Bundle, out_dir: Path) -> None` — writes `checks.json` (machine-only, §3 "руками не трогать") + `conditions.toml` + `hints.toml` (hand-edited).
  - `load_bundle(bundle_dir: Path) -> Bundle`
  - `apply_bundle(bundle_dir: Path, rootfs: Path) -> None` — copy the 3 files into `rootfs/.hash/.task/`.

**Serialization shapes** (pinned): `checks.json` → `{"task_id", "stages": [{"canonical": {path: {"kind", "text"}}, "mode", "threshold", "k", "size_threshold"}]}`; `conditions.toml` → `[stage.<i>]` tables with string-array keys; `hints.toml` → `[[stage.<i>]]` array-of-tables with `trigger`/`message`. Loaders convert the string stage-index keys back to `int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/taskcode/test_bundle.py
import pytest

from hashpass.canon import FileState
from hashpass.taskcode.bundle import Bundle, apply_bundle, dump_bundle, load_bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks


def _bundle() -> Bundle:
    checks = DerivedChecks(
        task_id="demo",
        stages=(
            StageChecks(
                canonical={"result.txt": FileState("file", "answer\n"),
                           "<output>": FileState("file", "")},
                mode="line",
                threshold=1.0,
            ),
        ),
    )
    conditions = {0: {"deny": ["rm"], "require_flags": ["-l"], "mention": ["sort"]}}
    hints = {0: [{"trigger": "cat", "message": "use ls first"}]}
    return Bundle(checks=checks, conditions=conditions, hints=hints)


@pytest.mark.tier1
def test_bundle_round_trip(tmp_path):
    bundle = _bundle()
    dump_bundle(bundle, tmp_path / "b")
    assert load_bundle(tmp_path / "b") == bundle   # checks + conditions + hints all round-trip


@pytest.mark.tier1
def test_apply_bundle_lands_under_hash_task(tmp_path):
    dump_bundle(_bundle(), tmp_path / "b")
    rootfs = tmp_path / "rootfs"
    rootfs.mkdir()
    apply_bundle(tmp_path / "b", rootfs)
    for name in ("checks.json", "conditions.toml", "hints.toml"):
        assert (rootfs / ".hash" / ".task" / name).is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/taskcode/test_bundle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.taskcode.bundle'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/taskcode/bundle.py
"""Split config bundle: derived checks.json + hand-edited conditions.toml / hints.toml."""
import json
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from hashpass.canon import FileState
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskcode.model import toml_list, toml_quote

_FILES = ("checks.json", "conditions.toml", "hints.toml")


@dataclass(frozen=True)
class Bundle:
    """A task's logic bundle: derived checks + advisory conditions + interactive hints."""

    checks: DerivedChecks
    conditions: dict
    hints: dict


def _checks_to_dict(checks: DerivedChecks) -> dict:
    return {
        "task_id": checks.task_id,
        "stages": [
            {
                "canonical": {k: {"kind": v.kind, "text": v.text}
                              for k, v in st.canonical.items()},
                "mode": st.mode,
                "threshold": st.threshold,
                "k": st.k,
                "size_threshold": st.size_threshold,
            }
            for st in checks.stages
        ],
    }


def _checks_from_dict(data: dict) -> DerivedChecks:
    stages = tuple(
        StageChecks(
            canonical={k: FileState(v["kind"], v["text"]) for k, v in st["canonical"].items()},
            mode=st["mode"],
            threshold=st["threshold"],
            k=st["k"],
            size_threshold=st["size_threshold"],
        )
        for st in data["stages"]
    )
    return DerivedChecks(task_id=data["task_id"], stages=stages)


def _dump_conditions(conditions: dict) -> str:
    lines: list[str] = []
    for idx in sorted(conditions):
        lines.append(f"[stage.{idx}]")
        for field, values in conditions[idx].items():
            lines.append(f"{field} = {toml_list(tuple(values))}")
        lines.append("")
    return "\n".join(lines)


def _dump_hints(hints: dict) -> str:
    lines: list[str] = []
    for idx in sorted(hints):
        for hint in hints[idx]:
            lines.append(f"[[stage.{idx}]]")
            lines.append(f"trigger = {toml_quote(hint['trigger'])}")
            lines.append(f"message = {toml_quote(hint['message'])}")
            lines.append("")
    return "\n".join(lines)


def _load_stage_keyed(text: str) -> dict:
    data = tomllib.loads(text)
    return {int(idx): value for idx, value in data.get("stage", {}).items()}


def dump_bundle(bundle: Bundle, out_dir: Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "checks.json").write_text(
        json.dumps(_checks_to_dict(bundle.checks), indent=2), encoding="utf-8")
    (out / "conditions.toml").write_text(_dump_conditions(bundle.conditions), encoding="utf-8")
    (out / "hints.toml").write_text(_dump_hints(bundle.hints), encoding="utf-8")


def load_bundle(bundle_dir: Path) -> Bundle:
    d = Path(bundle_dir)
    checks = _checks_from_dict(json.loads((d / "checks.json").read_text(encoding="utf-8")))
    conditions = _load_stage_keyed((d / "conditions.toml").read_text(encoding="utf-8"))
    hints = _load_stage_keyed((d / "hints.toml").read_text(encoding="utf-8"))
    return Bundle(checks=checks, conditions=conditions, hints=hints)


def apply_bundle(bundle_dir: Path, rootfs: Path) -> None:
    dest = Path(rootfs) / ".hash" / ".task"
    dest.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        shutil.copy2(Path(bundle_dir) / name, dest / name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/taskcode/test_bundle.py -v` → PASS.
Run: `ruff check src tests runtime` → clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(taskcode): split bundle dump/load/apply (checks.json + conditions/hints.toml)"
```

---

### Task 6: `checker.py` — check_stage (@check → matches); check_conditions (advisory)

**Files:**
- Create: `src/hashpass/taskcode/checker.py`
- Test: `tests/taskcode/test_checker.py`

**Interfaces:**
- Consumes: `StageChecks` (Task 4); `Observation`, `matches` (`hashpass.canon`); `parse_cmds`, `Cmd` (`hashpass.cmd`); `HookRegistry` (`hashpass.hooks`).
- Produces:
  - `check_stage(checks: StageChecks, candidate: Observation, *, hooks: HookRegistry | None = None, stage: int = 0, probe_cmd: str = "") -> bool` — (1) if `hooks` given, `r = hooks.run_check(probe_cmd, stage)`; if `r is not None` return `r` (the `@check` escape, §4); (2) else `matches(checks.canonical, candidate, threshold=checks.threshold, mode=checks.mode, k=checks.k)`. Fails CLOSED on empty canonical (`matches` already does).
  - `check_conditions(conditions: dict, commands: list[str]) -> bool` — advisory; parse via `parse_cmds`; support `{"deny": [basecmds], "require_flags": [...], "mention": [...]}`. Returns `True` if policy is satisfied.

- [ ] **Step 1: Write the failing test**

```python
# tests/taskcode/test_checker.py
import pytest

from hashpass.canon import FileState
from hashpass.hooks import HookRegistry
from hashpass.taskcode.checker import check_conditions, check_stage
from hashpass.taskcode.derive import StageChecks


def _checks(text: str) -> StageChecks:
    return StageChecks(canonical={"result.txt": FileState("file", text)}, mode="line")


@pytest.mark.tier1
def test_check_stage_accepts_correct_rejects_wrong():
    checks = _checks("answer\n")
    assert check_stage(checks, {"result.txt": FileState("file", "answer\n")})
    assert not check_stage(checks, {"result.txt": FileState("file", "WRONG\n")})
    assert not check_stage(checks, {})   # missing stable field → reject


@pytest.mark.tier1
def test_check_stage_check_hook_true_short_circuits():
    hooks = HookRegistry()

    @hooks.check()
    def _c(_cmd, _stage) -> bool:
        return True

    checks = _checks("answer\n")
    # candidate would FAIL matches, but @check True overrides (§4 escape)
    assert check_stage(checks, {"result.txt": FileState("file", "WRONG\n")},
                       hooks=hooks, probe_cmd="anything")


@pytest.mark.tier1
def test_check_stage_check_hook_none_defers_to_matches():
    hooks = HookRegistry()

    @hooks.check()
    def _c(_cmd, _stage) -> None:
        return None

    checks = _checks("answer\n")
    assert check_stage(checks, {"result.txt": FileState("file", "answer\n")}, hooks=hooks)
    assert not check_stage(checks, {"result.txt": FileState("file", "WRONG\n")}, hooks=hooks)


@pytest.mark.tier1
def test_check_conditions_deny_require_flags_mention():
    assert check_conditions({"deny": ["rm"]}, ["ls -l"])
    assert not check_conditions({"deny": ["rm"]}, ["rm -rf /"])        # denied command
    assert check_conditions({"require_flags": ["-l"], "mention": ["sort"]},
                            ["ls -l", "sort file"])
    assert not check_conditions({"require_flags": ["-l"]}, ["ls"])     # missing flag
    assert not check_conditions({"mention": ["sort"]}, ["ls -l"])      # missing mention
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/taskcode/test_checker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.taskcode.checker'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/taskcode/checker.py
"""Stage acceptance: canonical matching with an optional @check escape + advisory conditions."""
from hashpass.canon import Observation, matches
from hashpass.cmd import parse_cmds
from hashpass.hooks import HookRegistry
from hashpass.taskcode.derive import StageChecks


def check_stage(checks: StageChecks, candidate: Observation, *,
                hooks: HookRegistry | None = None, stage: int = 0,
                probe_cmd: str = "") -> bool:
    if hooks is not None:
        result = hooks.run_check(probe_cmd, stage)
        if result is not None:
            return result
    return matches(checks.canonical, candidate,
                   threshold=checks.threshold, mode=checks.mode, k=checks.k)


def check_conditions(conditions: dict, commands: list[str]) -> bool:
    parsed = [c for raw in commands for c in parse_cmds(raw)]
    deny = set(conditions.get("deny", []))
    if any(c.basecmd in deny for c in parsed):
        return False
    for flag in conditions.get("require_flags", []):
        if not any(c.has_flag(flag) for c in parsed):
            return False
    for token in conditions.get("mention", []):
        if not any(token == c.basecmd or token in c.args for c in parsed):
            return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/taskcode/test_checker.py -v` → PASS.
Run: `ruff check src tests runtime` → clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(taskcode): check_stage (@check→matches) + advisory check_conditions"
```

---

### Task 7: `codegen.py` (transcript → TaskCode) + shell transcript-log enhancement

**Files:**
- Create: `src/hashpass/taskcode/codegen.py`
- Test: `tests/taskcode/test_codegen.py`
- Modify: `runtime/usr/bin/hash` (append each command+output to `/.hash/.cmd.log`)
- Test: `tests/test_shell_capture.py` (extend to assert the transcript log accumulates multiple commands)

**Interfaces:**
- Consumes: `StageCode`, `TaskCode` (Task 1).
- Produces:
  - `@dataclass(frozen=True) StageTranscript(commands: tuple[str, ...], changed: tuple[str, ...])`
  - `codegen_from_transcript(task_id: str, setup: tuple[str, ...], stages: tuple[StageTranscript, ...]) -> TaskCode` — pure transform: each `StageTranscript` → `StageCode(commands=commands, observe=changed)` (§3 "режим создания = кодогенератор").

**Decision (beyond the brief):** the shell log is APPEND-only and accumulates the whole authoring session (not truncated at startup); each record is `f"$ {cmd}\n{stdout}"`. Parsing/curating this log into `StageTranscript`s is the interactive creation server (Plan F) — Plan D only writes the log and provides the pure transcript→code transform.

- [ ] **Step 1a: Write the failing codegen test**

```python
# tests/taskcode/test_codegen.py
import pytest

from hashpass.taskcode.codegen import StageTranscript, codegen_from_transcript
from hashpass.taskcode.model import StageCode, TaskCode


@pytest.mark.tier1
def test_codegen_from_transcript_builds_taskcode():
    stages = (
        StageTranscript(commands=("echo a > x", "cat x"), changed=("x",)),
        StageTranscript(commands=("echo b > y",), changed=("y",)),
    )
    task = codegen_from_transcript("demo", ("mkdir work",), stages)
    assert task == TaskCode(
        id="demo",
        setup=("mkdir work",),
        stages=(
            StageCode(commands=("echo a > x", "cat x"), observe=("x",)),
            StageCode(commands=("echo b > y",), observe=("y",)),
        ),
    )
```

- [ ] **Step 1b: Run → FAIL**

Run: `pytest tests/taskcode/test_codegen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.taskcode.codegen'`.

- [ ] **Step 1c: Write minimal implementation**

```python
# src/hashpass/taskcode/codegen.py
"""Creation mode: turn a recorded command transcript into editable task-as-code."""
from dataclasses import dataclass

from hashpass.taskcode.model import StageCode, TaskCode


@dataclass(frozen=True)
class StageTranscript:
    """Recorded author activity for one stage: commands run + paths changed."""

    commands: tuple[str, ...]
    changed: tuple[str, ...]


def codegen_from_transcript(task_id: str, setup: tuple[str, ...],
                            stages: tuple[StageTranscript, ...]) -> TaskCode:
    stage_codes = tuple(
        StageCode(commands=st.commands, observe=st.changed) for st in stages
    )
    return TaskCode(id=task_id, setup=setup, stages=stage_codes)
```

- [ ] **Step 1d: Run → PASS, commit**

Run: `pytest tests/taskcode/test_codegen.py -v` → PASS; `ruff check src tests runtime` → clean.
```bash
git add -A
git commit -m "feat(taskcode): codegen_from_transcript (transcript → TaskCode)"
```

- [ ] **Step 2a: Update the shell-capture test (transcript log)**

```python
# tests/test_shell_capture.py
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.tier1
def test_shell_captures_last_cmd_and_transcript_log(tmp_path):
    root = tmp_path
    (root / ".hash").mkdir()
    shell = Path("runtime/usr/bin/hash").read_text(encoding="utf-8")
    (root / "hash").write_text(shell, encoding="utf-8")
    (root / "hash").chmod(0o755)
    subprocess.run(
        [sys.executable, str(root / "hash")],
        cwd=root,
        input="echo hi\necho bye\nexit\n",
        capture_output=True,
        text=True,
        check=False,
    )
    # back-compat: .cmd / .cmd.out reflect the LAST command
    assert (root / ".hash/.cmd").read_text(encoding="utf-8").strip() == "echo bye"
    assert (root / ".hash/.cmd.out").read_text(encoding="utf-8").strip() == "bye"
    # NEW: the transcript log accumulates ALL commands + their outputs
    log = (root / ".hash/.cmd.log").read_text(encoding="utf-8")
    assert "echo hi" in log
    assert "echo bye" in log
    assert "hi" in log
    assert "bye" in log
```

- [ ] **Step 2b: Run → FAIL**

Run: `pytest tests/test_shell_capture.py -v`
Expected: FAIL — `FileNotFoundError: ... .hash/.cmd.log` (the shell does not write the log yet).

- [ ] **Step 2c: Enhance `runtime/usr/bin/hash`**

Add an append helper `a(...)` alongside the existing overwrite helper `w(...)`, and append each command+output to `.cmd.log` (keeping the existing `.cmd`/`.cmd.out` last-command behavior):

```python
#!/usr/bin/python3
import os
import subprocess
import sys

HASH = "/.hash" if os.path.isdir("/.hash") else os.path.join(os.getcwd(), ".hash")


def w(name, data):
    with open(os.path.join(HASH, name), "w", encoding="utf-8") as f:
        f.write(data)


def a(name, data):
    with open(os.path.join(HASH, name), "a", encoding="utf-8") as f:
        f.write(data)


def main():
    if os.path.isfile("readme.txt"):
        with open("readme.txt", encoding="utf-8") as f:
            print(f.read())
    for line in sys.stdin:
        cmd = line.strip()
        if cmd in ("exit", "task exit"):
            break
        if not cmd:
            continue
        w(".cmd", cmd)
        p = subprocess.run(
            ["/bin/sh", "-c", cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        sys.stdout.write(p.stdout)
        sys.stdout.flush()
        w(".cmd.out", p.stdout)
        a(".cmd.log", f"$ {cmd}\n{p.stdout}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2d: Run → PASS, commit**

Run: `pytest tests/test_shell_capture.py -v` → PASS; `ruff check src tests runtime` → clean.
```bash
git add -A
git commit -m "feat(runtime): shell appends command+output to .cmd.log transcript"
```

---

### Task 8: Integration — end-to-end discrimination spine (tier1)

**Files:**
- Test: `tests/taskcode/test_integration.py`

**Interfaces:**
- Consumes: `TaskCode`, `StageCode` (Task 1); `run_stage` (Task 2); `derive_checks` (Task 4); `Bundle`, `dump_bundle`, `load_bundle` (Task 5); `check_stage` (Task 6); `FileState` (`hashpass.canon`); `TmpdirRunner` (`hashpass.runner.tmpdir`).

End-to-end through the real pipeline with `TmpdirRunner`: author a small `TaskCode` (a constant result file + a volatile timestamp file) → `derive_checks(passes=3)` → `dump_bundle` → `load_bundle` → run a CORRECT solution in a fresh runner, capture, `check_stage` → ACCEPT; run a WRONG solution → REJECT; assert the volatile field was pruned from the canonical. This proves model+execute+derive+observe(via canonicalize)+bundle+checker compose.

**GENUINE discrimination test (a vacuous pass must FAIL it):** a checker that always returns `True` fails the WRONG-rejects assertion; an empty/vacuous canonical fails the CORRECT-accepts assertion (`matches` fails closed); an un-pruned volatile timestamp fails the CORRECT-accepts assertion (the correct solution runs at a different nanosecond).

- [ ] **Step 1: Write the failing test**

```python
# tests/taskcode/test_integration.py
import itertools

import pytest

from hashpass.canon import FileState
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.bundle import Bundle, dump_bundle, load_bundle
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.execute import run_stage
from hashpass.taskcode.model import StageCode, TaskCode


def _stage(result_cmd: str) -> tuple[StageCode, ...]:
    return (
        StageCode(
            commands=(result_cmd, "date +%s%N > time.txt"),
            observe=("result.txt", "time.txt"),
        ),
    )


def _fresh(tmp_path, name) -> TmpdirRunner:
    r = TmpdirRunner(tmp_path / name)
    r.prepare([])
    return r


@pytest.mark.tier1
def test_end_to_end_derive_bundle_check_discriminates(tmp_path):
    task = TaskCode(id="sort-demo", setup=(), stages=_stage("echo answer > result.txt"))

    counter = itertools.count()

    def factory() -> TmpdirRunner:
        return _fresh(tmp_path, f"derive{next(counter)}")

    derived = derive_checks(factory, task, passes=3)
    dump_bundle(Bundle(checks=derived, conditions={}, hints={}), tmp_path / "bundle")
    stage_checks = load_bundle(tmp_path / "bundle").checks.stages[0]

    # the volatile timestamp was pruned; the stable result survived
    assert "time.txt" not in stage_checks.canonical
    assert stage_checks.canonical["result.txt"] == FileState("file", "answer\n")

    # CORRECT solution (fresh runner, different timestamp) → ACCEPT
    good = run_stage(_fresh(tmp_path, "good"), task, 0)
    assert check_stage(stage_checks, good)

    # WRONG solution → REJECT (a vacuous always-True checker would fail here)
    wrong_task = TaskCode(id="sort-demo", setup=(), stages=_stage("echo WRONG > result.txt"))
    wrong = run_stage(_fresh(tmp_path, "wrong"), wrong_task, 0)
    assert not check_stage(stage_checks, wrong)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/taskcode/test_integration.py -v`
Expected: FAIL initially only if a prior module is missing; once Tasks 1–6 are in, run it to confirm the full pipeline is exercised. (If written first against an empty pipeline it FAILs at import.)

- [ ] **Step 3: No new implementation**

Task 8 is a composition test over Tasks 1–6; it needs no new production code. If it fails on the merits (wrong accepted, correct rejected, or volatile not pruned), that is a finding about the pipeline — investigate, do not weaken the assertions.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/taskcode/test_integration.py -v` → PASS.
Run: `pytest -q -m "not tier3"` → green.
Run: `ruff check src tests runtime` → clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test(taskcode): end-to-end derive→bundle→check discrimination spine"
```

---

## Out of scope (future plans)

- **Keys / evidence / server** (Plan E): acceptance is NOT wired into keys; do NOT touch `play.py`/`key.py`. The local key is a nonce (§6), derived elsewhere.
- **Invisible-check / offline-progress / hints-runtime / interactive observe-curation UX** (Plan F), and the interactive creation SERVER (taskcreator TCP server, live watchdog capture) — Plan D builds only the pure transcript→code transform plus the shell transcript log.
- **Content migration** (Plan G).
- Reference (do not copy): the old dev flow used author-set Simhash + TOML config + a sed-patched key placeholder; we REPLACE Simhash with the derived canonical + size-adaptive compare, and keep the `/.hash/.task/` convention and stage-scoped hooks.

## Self-Review

**Spec coverage.** §3 задание-как-код → Task 1 (`TaskCode`/TOML); §3 кодогенератор → Task 7 (`codegen_from_transcript`) + shell `.cmd.log`; §3 split bundle (`checks` machine-only / `conditions`/`hints` hand-edited) → Task 5; §4 приём (толерантное сравнение + `@check` escape + advisory conditions) → Task 6, with output = last command's stdout wired in Task 2; §5 дифф-канонизация + noise-before-capture → Tasks 2 & 4; §5 per-stage comparator pinning → Task 4 (`StageChecks.mode/threshold/size_threshold`); §10 tier1-only → Global Constraints + every task's `@pytest.mark.tier1`. Derivation spine discrimination → Task 4; end-to-end discrimination → Task 8.

**Placeholder scan.** No "TODO"/"similar to Task N"/"add validation"; every code block is real and runnable; run-to-fail steps give exact commands and expected failures.

**Type consistency.** `TaskCode`/`StageCode` fields (`commands`/`observe`/`exclude`/`message`, `id`/`setup`/`stages`) identical across Tasks 1, 2, 7, 8. `Observation`/`FileState` from `hashpass.canon` used unchanged everywhere. `StageChecks(canonical, mode, threshold, k, size_threshold)` and `DerivedChecks(task_id, stages)` identical in Tasks 4, 5, 6, 8. `run_stage(runner, task, stage_index, *, noise)` signature identical in Tasks 2, 4, 8. `OUTPUT_KEY == "<output>"` matches `canon.capture`'s reserved key. `check_stage`/`check_conditions` signatures match Task 6's Interfaces. `toml_quote`/`toml_list` defined in Task 1, reused in Task 5.

### Decisions beyond the brief

1. **run_stage output** = the TARGET stage's own stdout via a SECOND `sh -c` (PREP's stdout discarded), per §4 and the coordinator correction; cwd/env does not carry PREP→TARGET (authors `cd` inside each stage).
2. **TOML helpers** `toml_quote`/`toml_list` are module-public (no underscore) in `model.py` and reused by `bundle.py` — avoids a private cross-module import while staying DRY.
3. **conditions/hints TOML shape** pinned to `[stage.<i>]` (string-array keys, only present keys written for exact round-trip) and `[[stage.<i>]]` (trigger/message); loaders cast the string stage index back to `int`.
4. **StageChecks.size_threshold** is recorded (§5 pinning/evidence) but not threaded into `matches` (which does not accept it and uses `similarity`'s default 4096); the pinned default equals that default, so behavior is identical. Threading a non-default value is out of scope.
5. **derive_checks** uses `canonicalize` (not `derive_canonical`) and raises `ValueError` only for `passes < _MIN_K`; an all-volatile stage yields an empty canonical that fails CLOSED at match time — matching the brief and the fail-closed constraint.
6. **runner_factory returns a PREPARED runner** (`prepare([])`); `derive_checks` calls the factory, runs the stage, then tears down after the in-memory `Observation` is captured.
7. **check_conditions** implements the three checker-pinned keys `deny`/`require_flags`/`mention`; a "mention" is satisfied when the token equals a command's `basecmd` or appears in its `args`.
