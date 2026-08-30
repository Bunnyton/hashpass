# Content Migration — Sample Tasks + Pipeline Validation + Playbook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring real task content into the new task-as-code format and prove the whole pipeline (derive → bundle → offline play → server credit) end-to-end on it — since the old 24 tasks cannot be auto-migrated (no stored commands), author a validated representative sample + a playbook for the rest.

**Architecture:** New `content/tasks/<id>/task.toml` source files (task-as-code, loaded by `hashpass.taskcode.model.load_task_code`); tier1 tests that derive each into a bundle and drive it through `PlaySession`; a tier1 codegen-path test; a tier3 nspawn end-to-end; and a playbook doc. NO new production modules — Plan G is content + tests + docs on top of the shipped pipeline.

**Tech Stack:** Python 3.13, stdlib + pytest, consuming in-repo `hashpass.{taskcode.model, taskcode.derive, taskcode.bundle, taskcode.checker, taskcode.codegen, taskcode.execute, canon, grade, play, progress, key, runner.tmpdir, runner.nspawn, image.base}`. NO third-party deps.

**Spec:** `docs/Архитектура (architecture).md` §3 (задание-как-код), §7 (offline loop), §10 (tiers, content migration validates codegen). Modernization plan item 7.

## Why this is not an auto-migration

A survey of `origin/dev` established that the 24 old tasks store **ONLY** one-way Simhash fingerprints of the expected filesystem state (`changes: path -> {hash, state, is_dir}`) plus hint `actions`. They contain **NO reference commands and no recoverable expected bytes**. The new pipeline (Plan D) derives acceptance by **RUNNING reference commands** and canonicalizing their observed effect — so the old tasks **CANNOT be auto-converted**: there is nothing to run and no way to invert a Simhash back into commands or content.

Plan G therefore delivers, instead of a converter:
- **(a)** a validated **SAMPLE** of real tasks AUTHORED as task-as-code (3 tasks: fs-based and output-based, all deterministic in a `TmpdirRunner`);
- **(b)** proof the full Plan-D→E→F pipeline works on real content — tier1 (`TmpdirRunner`) + a real container tier3 (`NspawnRunner`);
- **(c)** validation of the **codegen path** (transcript → code → derive → accept), spec §3 «режим создания = кодогенератор»;
- **(d)** a migration/authoring **PLAYBOOK** for the remaining ~20 tasks.

Bulk authoring the rest is a **content-ops follow-on** using the playbook (especially the container/network tasks like apt/sudo, which must be authored and derived inside a tier2/3 container, not a `TmpdirRunner`).

## Global Constraints

- Python 3.13; stdlib + in-repo hashpass modules only. `encoding="utf-8"` on every read/write.
- ruff `select=["ALL"]` clean incl. tests. Task-source TOML lives under `content/` (not linted as Python).
- Sample tasks must DERIVE DETERMINISTICALLY in a `TmpdirRunner` (tier1): pick commands whose observed output is stable across k passes (redirect to files; avoid time/PID/randomness in the OBSERVED set).
- Tiers: content-authoring + pipeline validation + codegen = tier1 (`@pytest.mark.tier1`, TmpdirRunner); the end-to-end-in-container test = tier3 (`@pytest.mark.tier3`, NspawnRunner + base_tar fixture).
- Do NOT modify shipped production modules; Plan G only ADDS content/tests/docs.

## Exact APIs to consume (verbatim — reference for every task's Interfaces block)

```python
# hashpass.taskcode.model
@dataclass(frozen=True)
class StageCode: commands: tuple[str,...]; observe: tuple[str,...]; exclude: tuple[str,...]=(); message: str=""
@dataclass(frozen=True)
class TaskCode: id: str; setup: tuple[str,...]; stages: tuple[StageCode,...]
def load_task_code(path: Path) -> TaskCode      # parse task.toml
# hashpass.taskcode.derive
def derive_checks(runner_factory: Callable[[], Runner], task: TaskCode, *, passes=3, mode="line",
                  threshold=1.0, noise=None) -> DerivedChecks   # raises ValueError on vacuous canonical
# hashpass.taskcode.bundle
@dataclass(frozen=True) class Bundle: checks: DerivedChecks; conditions: dict; hints: dict
def dump_bundle(bundle: Bundle, out_dir: Path) -> None
def load_bundle(bundle_dir: Path) -> Bundle
def apply_bundle(bundle_dir: Path, rootfs: Path) -> None        # copies into rootfs/.hash/.task/
# hashpass.taskcode.execute
def run_stage(runner, task, stage_index, *, noise=None) -> Observation   # runs setup+prior PREP + target; folds "<output>"
OUTPUT_KEY = "<output>"
# hashpass.taskcode.codegen
@dataclass(frozen=True) class StageTranscript: commands: tuple[str,...]; changed: tuple[str,...]
def codegen_from_transcript(task_id, setup: tuple[str,...], stages: tuple[StageTranscript,...]) -> TaskCode
# hashpass.taskcode.checker
def check_stage(checks: StageChecks, candidate: Observation, *, hooks=None, stage=0, probe_cmd="") -> bool
# hashpass.play
def capture_candidate(rootfs: Path, checks: StageChecks, last_output: str) -> Observation
class PlaySession:
    def __init__(self, bundle: Bundle, progress: TaskProgress, *, student_id: str, nonce: str) -> None: ...
    def feed(self, *, command: str, rootfs: Path, last_output: str, ts: str, hooks=None) -> FeedResult: ...
    # FeedResult(advanced: bool, stage: int | None, local_key: str | None, hint: str | None)
# hashpass.progress.new_progress(task_id, n_stages) -> TaskProgress
# hashpass.key.local_key(task_id, stage, nonce) -> str    # format: "key{<hex16>}"
# hashpass.runner.tmpdir.TmpdirRunner(workdir); .prepare([]); .run(["sh","-c",script]) -> RunResult(stdout,...); .rootfs; .teardown()
# hashpass.runner.nspawn.NspawnRunner(workdir, *, base_tar=None, base_dir=None); same Runner protocol (tier3, scoped sudo)
# hashpass.image.base.build_base(dest, *, from_tar) -> Path    # builds a base rootfs dir from a tarball
```

**Verified facts** (materialized before writing this plan — these are the actual derived canonicals):

| task | observe | derived canonical (per stage 0) | local key on accept |
| --- | --- | --- | --- |
| `hello` | `hello.txt` | `{'hello.txt': ('file','hello\n'), '<output>': ('file','')}` | `key{...}` |
| `list-files` | `listing.txt` | `{'listing.txt': ('file','a\nb\nc\n'), '<output>': ('file','')}` | `key{...}` |
| `grep-todo` | `found.txt` | `{'found.txt': ('file','TODO fix\n'), '<output>': ('file','')}` | `key{...}` |

All three redirect their command output to a file, so the derived `<output>` field is the empty string `""`; the discriminator is the observed file's content. `similarity("", "") == 1.0`, so the empty-output field is satisfied by an empty `last_output`. Each task carries a stable observed-FS field, so `derive_checks` does **not** raise the vacuous-canonical `ValueError`.

---

### Task 1: Author the 3 sample task.toml files + loader test

**Files:**
- Create: `content/tasks/hello/task.toml`
- Create: `content/tasks/list-files/task.toml`
- Create: `content/tasks/grep-todo/task.toml`
- Create: `tests/content/__init__.py` (empty)
- Test: `tests/content/test_task_sources.py`

**Interfaces:**
- Consumes: `hashpass.taskcode.model.load_task_code(path: Path) -> TaskCode`; `TaskCode(id, setup: tuple[str,...], stages: tuple[StageCode,...])`; `StageCode(commands, observe, exclude=(), message="")`.
- Produces: three `content/tasks/<id>/task.toml` source files consumed by Tasks 2–4, and the `tests/content/` package.

**Authoring notes (must-read):**
- The TOML shape mirrors `load_task_code`: top-level `id` (string) and `setup` (array of strings); one or more `[[stage]]` tables each with `commands`, `observe`, `exclude`, `message`.
- Keep command strings simple (no embedded double-quotes or commas) so each TOML string is a trivial one-liner.
- `grep-todo` seeds its input with `printf`. **In a TOML basic (double-quoted) string, `\n` is decoded to a real newline** — so `load_task_code` returns the setup command with actual newline characters embedded, not the two literal characters backslash-n. That is fine: the single-quoted `printf` argument then emits those newlines verbatim, seeding a 3-line `notes.txt` (`alpha` / `TODO fix` / `beta`). The loader test's expected value in Step 3 therefore uses a **real newline**, not `\\n`. (Sanity-check once by hand: run the setup + `grep TODO notes.txt` in a scratch dir and confirm `found.txt` is exactly `TODO fix`.)

- [ ] **Step 1: Write `content/tasks/hello/task.toml`**

```toml
id = "hello"
setup = []

[[stage]]
commands = ["echo hello > hello.txt"]
observe = ["hello.txt"]
exclude = []
message = "Create hello.txt containing the word hello."
```

- [ ] **Step 2: Write `content/tasks/list-files/task.toml`**

```toml
id = "list-files"
setup = ["mkdir -p work", "touch work/a work/b work/c"]

[[stage]]
commands = ["ls work > listing.txt"]
observe = ["listing.txt"]
exclude = []
message = "List work/ into listing.txt."
```

- [ ] **Step 3: Write `content/tasks/grep-todo/task.toml`**

```toml
id = "grep-todo"
setup = ["printf 'alpha\nTODO fix\nbeta\n' > notes.txt"]

[[stage]]
commands = ["grep TODO notes.txt > found.txt"]
observe = ["found.txt"]
exclude = []
message = "Put the TODO line into found.txt."
```

- [ ] **Step 4: Create the test package + write the failing loader test**

Create empty `tests/content/__init__.py`, then `tests/content/test_task_sources.py`:

```python
"""Tier1: the authored sample task.toml files load into well-formed TaskCode."""
from pathlib import Path

import pytest

from hashpass.taskcode.model import TaskCode, load_task_code

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"

EXPECTED = {
    "hello": {
        "setup": (),
        "commands": ("echo hello > hello.txt",),
        "observe": ("hello.txt",),
    },
    "list-files": {
        "setup": ("mkdir -p work", "touch work/a work/b work/c"),
        "commands": ("ls work > listing.txt",),
        "observe": ("listing.txt",),
    },
    "grep-todo": {
        # TOML basic (double-quoted) strings decode \n to a real newline, so the loaded
        # setup command carries actual newlines; printf emits them literally (single-quoted),
        # seeding a 3-line notes.txt.
        "setup": ("printf 'alpha\nTODO fix\nbeta\n' > notes.txt",),
        "commands": ("grep TODO notes.txt > found.txt",),
        "observe": ("found.txt",),
    },
}


@pytest.mark.tier1
@pytest.mark.parametrize("task_id", list(EXPECTED))
def test_sample_task_loads(task_id):
    """Each sample task.toml parses into a one-stage TaskCode with the expected fields."""
    task = load_task_code(CONTENT / task_id / "task.toml")
    exp = EXPECTED[task_id]
    assert isinstance(task, TaskCode)
    assert task.id == task_id
    assert task.setup == exp["setup"]
    assert len(task.stages) == 1
    stage = task.stages[0]
    assert stage.commands == exp["commands"]
    assert stage.observe == exp["observe"]
    assert stage.message
```

- [ ] **Step 5: Run the test → PASS**

Run: `pytest tests/content/test_task_sources.py -m tier1 -v`
Expected: 3 passed (one per task id). If `grep-todo` fails on `setup` with a newline diff, confirm the expected string uses a real newline (see the authoring note), not `\\n`.

- [ ] **Step 6: Lint + commit**

Run: `ruff check src tests runtime` (clean).
```bash
git add content/tasks tests/content
git commit -m "feat(content): author 3 sample task.toml + loader test"
```

---

### Task 2: Full-pipeline validation on the sample (tier1)

**Files:**
- Test: `tests/content/test_pipeline.py`

**Interfaces:**
- Consumes:
  - `load_task_code(path) -> TaskCode` (Task 1 sources).
  - `derive_checks(runner_factory: Callable[[], Runner], task, *, passes=3, mode="line", threshold=1.0, noise=None) -> DerivedChecks` — factory returns a **prepared** runner per pass; raises `ValueError` on a vacuous canonical.
  - `Bundle(checks, conditions: dict, hints: dict)`; `dump_bundle(bundle, out_dir) -> None`; `load_bundle(bundle_dir) -> Bundle`.
  - `new_progress(task_id, n_stages) -> TaskProgress`.
  - `PlaySession(bundle, progress, *, student_id, nonce)`; `PlaySession.feed(*, command, rootfs, last_output, ts, hooks=None) -> FeedResult(advanced, stage, local_key, hint)`.
  - `TmpdirRunner(workdir)`, `.prepare([])`, `.run(["sh","-c",script]) -> RunResult(stdout,...)`, `.rootfs`, `.teardown()`.
- Produces: proof that derive → bundle → play accepts the reference solve and rejects a wrong one, on real content.

**Design notes:**
- The `derive_checks` factory must return a **fresh prepared** `TmpdirRunner` on every call (`derive_checks` runs `passes` times per stage and calls `.teardown()` itself). Match the established pattern in `tests/taskcode/test_derive.py`: a `counter` + a `make()` closure.
- SOLVE per the spec: run the task's `setup + stage-0 commands` in **one** fresh `TmpdirRunner` via a single newline-joined `sh -c`, then feed `runner.rootfs` + that script's stdout. For these three tasks the setup commands emit nothing to stdout and each target command redirects to a file, so the joined script's stdout equals the target command's captured stdout (empty) — consistent with `run_stage`'s `OUTPUT_KEY`.
- WRONG solve: a fresh runner that runs `setup` but overwrites the observed file with a wrong value (`echo NOPE > <observed>`); a fresh `PlaySession` must not advance and must return `local_key is None`.

- [ ] **Step 1: Write the failing pipeline test**

```python
"""Tier1: derive->bundle->PlaySession end-to-end on the authored sample tasks."""
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.play import PlaySession
from hashpass.progress import new_progress
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.bundle import Bundle, dump_bundle, load_bundle
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.model import TaskCode, load_task_code

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"
TS = "2026-08-30T12:00:00Z"

# task_id -> the observed file a wrong solution corrupts
OBSERVED = {"hello": "hello.txt", "list-files": "listing.txt", "grep-todo": "found.txt"}


def _factory(tmp_path: Path) -> Callable[[], TmpdirRunner]:
    """Return a factory of fresh, prepared TmpdirRunners under tmp_path."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


def _solve(task: TaskCode, tmp_path: Path, name: str,
           commands: list[str]) -> tuple[Path, str]:
    """Run setup + `commands` in one fresh runner; return its rootfs + last stdout."""
    r = TmpdirRunner(tmp_path / name)
    r.prepare([])
    result = r.run(["sh", "-c", "\n".join([*task.setup, *commands])])
    return r.rootfs, result.stdout


@pytest.mark.tier1
@pytest.mark.parametrize("task_id", list(OBSERVED))
def test_pipeline_accepts_correct_rejects_wrong(task_id, tmp_path):
    """derive->bundle->play accepts the reference solve and rejects a wrong one."""
    task = load_task_code(CONTENT / task_id / "task.toml")
    derived = derive_checks(_factory(tmp_path / "derive"), task, passes=3)
    bundle_dir = tmp_path / "bundle"
    dump_bundle(Bundle(checks=derived, conditions={}, hints={}), bundle_dir)
    bundle = load_bundle(bundle_dir)

    # CORRECT: run the reference commands, feed the live rootfs + last stdout.
    good = PlaySession(bundle, new_progress(task.id, 1), student_id="alice", nonce="n1")
    rootfs, output = _solve(task, tmp_path, "good", list(task.stages[0].commands))
    ok = good.feed(command=task.stages[0].commands[-1], rootfs=rootfs,
                   last_output=output, ts=TS)
    assert ok.advanced
    assert ok.local_key is not None
    assert ok.local_key.startswith("key{")

    # WRONG: corrupt the observed file; a fresh session must not advance.
    bad = PlaySession(bundle, new_progress(task.id, 1), student_id="alice", nonce="n1")
    wrong_cmd = f"echo NOPE > {OBSERVED[task_id]}"
    rootfs_w, output_w = _solve(task, tmp_path, "wrong", [wrong_cmd])
    rejected = bad.feed(command=wrong_cmd, rootfs=rootfs_w, last_output=output_w, ts=TS)
    assert not rejected.advanced
    assert rejected.local_key is None
```

- [ ] **Step 2: Run → verify it fails first, then passes**

Run: `pytest tests/content/test_pipeline.py -m tier1 -v`
Expected: 3 passed (`hello`, `list-files`, `grep-todo`). A vacuous/always-true checker would fail the WRONG-solve assertions; a non-deterministic observed field would fail derivation. If a task raises `ValueError: ... vacuous canonical`, its observed file is not stable across passes — re-check the command for time/PID/randomness.

- [ ] **Step 3: Lint + commit**

Run: `ruff check src tests runtime` (clean).
```bash
git add tests/content/test_pipeline.py
git commit -m "test(content): full pipeline validation on sample tasks"
```

---

### Task 3: Codegen-path validation (tier1)

**Files:**
- Test: `tests/content/test_codegen_path.py`

**Interfaces:**
- Consumes:
  - `StageTranscript(commands: tuple[str,...], changed: tuple[str,...])`; `codegen_from_transcript(task_id, setup: tuple[str,...], stages: tuple[StageTranscript,...]) -> TaskCode`.
  - `derive_checks(runner_factory, task, *, passes=3, ...) -> DerivedChecks`.
  - `check_stage(checks: StageChecks, candidate: Observation, *, hooks=None, stage=0, probe_cmd="") -> bool`.
  - `capture_candidate(rootfs: Path, checks: StageChecks, last_output: str) -> Observation`.
  - `TmpdirRunner` (same as Task 2).
- Produces: proof of the creation-mode path — a recorded transcript becomes editable code that derives a discriminating check (spec §3 «режим создания = кодогенератор»).

**Design note:** The `hello` reference is used as a one-stage transcript: commands run + paths changed. `codegen_from_transcript` maps `changed -> observe`, so the generated `TaskCode` is identical in effect to the hand-written `hello/task.toml`. Deriving it and checking a correct vs. wrong in-runner solve proves transcript → code → derive → accept/reject.

- [ ] **Step 1: Write the failing codegen-path test**

```python
"""Tier1: codegen path — transcript -> TaskCode -> derive -> accept/reject (spec §3)."""
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.play import capture_candidate
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.codegen import StageTranscript, codegen_from_transcript
from hashpass.taskcode.derive import derive_checks


def _factory(tmp_path: Path) -> Callable[[], TmpdirRunner]:
    """Return a factory of fresh, prepared TmpdirRunners under tmp_path."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


@pytest.mark.tier1
def test_codegen_transcript_derives_a_working_check(tmp_path):
    """A recorded transcript becomes code that derives a discriminating check."""
    code = codegen_from_transcript(
        "hello",
        (),
        (StageTranscript(commands=("echo hello > hello.txt",), changed=("hello.txt",)),),
    )
    assert code.id == "hello"
    assert code.stages[0].commands == ("echo hello > hello.txt",)
    assert code.stages[0].observe == ("hello.txt",)

    derived = derive_checks(_factory(tmp_path / "derive"), code, passes=3)
    stage_checks = derived.stages[0]

    # CORRECT solve of the generated task is accepted.
    good = TmpdirRunner(tmp_path / "good")
    good.prepare([])
    out = good.run(["sh", "-c", "echo hello > hello.txt"]).stdout
    assert check_stage(stage_checks, capture_candidate(good.rootfs, stage_checks, out))
    good.teardown()

    # WRONG solve is rejected.
    bad = TmpdirRunner(tmp_path / "bad")
    bad.prepare([])
    out_w = bad.run(["sh", "-c", "echo NOPE > hello.txt"]).stdout
    assert not check_stage(stage_checks, capture_candidate(bad.rootfs, stage_checks, out_w))
    bad.teardown()
```

- [ ] **Step 2: Run → PASS**

Run: `pytest tests/content/test_codegen_path.py -m tier1 -v`
Expected: 1 passed.

- [ ] **Step 3: Lint + commit**

Run: `ruff check src tests runtime` (clean).
```bash
git add tests/content/test_codegen_path.py
git commit -m "test(content): codegen-path validation"
```

---

### Task 4: End-to-end in a real container (tier3)

**Files:**
- Test: `tests/content/test_e2e_nspawn.py`

**Interfaces:**
- Consumes:
  - `base_tar` — session-scoped fixture from `tests/conftest.py` (exports a `debian:trixie-slim` rootfs tarball via docker; shared across tier3 tests).
  - `build_base(dest, *, from_tar) -> Path` — builds a base rootfs dir (Debian + runtime layer) from a tarball.
  - `NspawnRunner(workdir, *, base_tar=None, base_dir=None)` — same `Runner` protocol as `TmpdirRunner`; `.prepare([])`, `.run(argv) -> RunResult`, `.rootfs` (the composed overlay mountpoint), `.teardown()`. Needs scoped passwordless sudo for `systemd-nspawn`/`mount`/`umount`/`tar`/`rsync` (§10).
  - `derive_checks` with a host-side `TmpdirRunner` factory (fast); `capture_candidate`; `check_stage`; `load_task_code`.
- Produces: end-to-end-in-container coverage of the REAL pipeline for the `hello` task — the firm requirement restored.

**Design notes:**
- Derive the checks **host-side** with a `TmpdirRunner` factory (fast, deterministic) — the derived canonical is runner-agnostic, so it applies to the container solve.
- The student SOLVES **inside** the container; the container's cwd is `/`, so `echo hello > hello.txt` writes `/hello.txt`, which lands in the overlay upperdir and is visible through `r.rootfs` (the overlay mountpoint). Do **not** write under `/tmp` — systemd-nspawn mounts a private tmpfs over `/tmp` (see `tests/runner/test_nspawn.py`); a root-level path round-trips through the overlay.
- Reuse one container for both checks: capture after the correct solve (accept), then overwrite the file with a wrong value and capture again (reject). `r.teardown()` in a `finally`.
- Mark `@pytest.mark.tier3`. The repo default `addopts = -m 'not tier3'` excludes it from normal runs; if nspawn/sudo/docker is unavailable it simply does not run.

- [ ] **Step 1: Write the tier3 end-to-end test**

```python
"""Tier3: end-to-end in a real systemd-nspawn container on the `hello` sample task."""
import itertools
from collections.abc import Callable
from pathlib import Path

import pytest

from hashpass.image.base import build_base
from hashpass.play import capture_candidate
from hashpass.runner.nspawn import NspawnRunner
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.derive import derive_checks
from hashpass.taskcode.model import load_task_code

CONTENT = Path(__file__).resolve().parents[2] / "content" / "tasks"


def _tmpdir_factory(tmp_path: Path) -> Callable[[], TmpdirRunner]:
    """Host-side factory: derive the checks fast, off-container."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


@pytest.mark.tier3
def test_hello_end_to_end_in_nspawn(tmp_path, base_tar):
    """Derive host-side, then accept an in-container solve and reject a wrong one."""
    task = load_task_code(CONTENT / "hello" / "task.toml")
    derived = derive_checks(_tmpdir_factory(tmp_path / "derive"), task, passes=3)
    stage_checks = derived.stages[0]

    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = NspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        # Student solves the task INSIDE the container (cwd is / -> writes /hello.txt).
        r.run(["sh", "-c", "echo hello > hello.txt"])
        candidate = capture_candidate(r.rootfs, stage_checks, last_output="")
        assert check_stage(stage_checks, candidate)

        # A wrong in-container solve is rejected.
        r.run(["sh", "-c", "echo NOPE > hello.txt"])
        wrong = capture_candidate(r.rootfs, stage_checks, last_output="")
        assert not check_stage(stage_checks, wrong)
    finally:
        r.teardown()
```

- [ ] **Step 2: Run on a tier3-capable host → PASS**

Run: `pytest tests/content/test_e2e_nspawn.py -m tier3 -v`
Expected: 1 passed on a host with docker + systemd-nspawn + scoped passwordless sudo. On a host without them, the tier3 marker keeps it out of the default `pytest` run; do not weaken the assertions to make it pass elsewhere.

- [ ] **Step 3: Lint + commit**

Run: `ruff check src tests runtime` (clean).
```bash
git add tests/content/test_e2e_nspawn.py
git commit -m "test(content): tier3 nspawn end-to-end on hello"
```

---

### Task 5: Migration / authoring playbook (doc)

**Files:**
- Create: `docs/Миграция контента (content migration).md`

**Interfaces:**
- Consumes: nothing at runtime — a prose doc that references the modules and the Task-2 harness by name.
- Produces: the authoring/migration playbook for the remaining ~20 of the 24 dev tasks (content-ops follow-on).

**Content note:** No test. The doc must cover the five points below and cite the three sample tasks as worked examples. Keep it concise and concrete.

- [ ] **Step 1: Write the playbook doc**

Create `docs/Миграция контента (content migration).md` with these sections:

```markdown
# Миграция контента (content migration)

## 1. Почему это не авто-миграция
Старые 24 задания (`origin/dev`) хранят ТОЛЬКО одностороннюю Simhash-сигнатуру
ожидаемого состояния ФС (`changes: path -> {hash, state, is_dir}`) + hint-`actions`.
Эталонных команд и восстановимых байтов в них НЕТ. Новый конвейер (План D)
деривирует приём, ЗАПУСКАЯ эталонные команды, поэтому старые задания
авто-сконвертировать нельзя — нечего запускать, а Simhash необратим.
Вывод: авторируем задания заново как task-as-код + пишем этот плейбук.

## 2. Паттерн авторинга
1. Пишем `content/tasks/<id>/task.toml`: `id`, `setup=[...]`, один или несколько
   `[[stage]]` с `commands` (эталонное решение), `observe` (наблюдаемые пути),
   опц. `exclude`, `message`.
2. Деривируем бандл: `derive_checks(factory, task, passes=3)` → `Bundle(...)` →
   `dump_bundle`. `factory` отдаёт СВЕЖИЙ подготовленный `TmpdirRunner` на каждый
   проход. `derive_checks` бросает `ValueError`, если канон вакуумный
   (нет стабильного сигнала).
3. Валидируем харнессом Задачи 2 (`tests/content/test_pipeline.py`): верное
   решение → `feed(...).advanced` и `local_key` начинается с `key{`; неверное →
   не `advanced`, `local_key is None`.

## 3. Детерминизм наблюдаемого набора (обязательно)
Наблюдаемые файлы должны быть СТАБИЛЬНЫ на k проходах: перенаправляем вывод в
файл; в наблюдаемом наборе НЕТ времени/PID/случайности. Волатильные поля канон
сам обрежет (дифф-канонизация, §5) — но если стабильного сигнала не осталось,
`derive_checks` упадёт с `vacuous canonical`. Пример волатильного, которое надо
исключать: `date +%s%N`.

## 4. Три задания-примера (worked examples)
- `hello` — output/fs: `echo hello > hello.txt`, observe `hello.txt`;
  канон `{'hello.txt': ('file','hello\n'), '<output>': ('file','')}`.
- `list-files` — `ls` детерминирован (сортировка): `ls work > listing.txt`,
  observe `listing.txt`; канон `listing.txt = "a\nb\nc\n"`.
- `grep-todo` — seed через `printf` (в TOML basic-строке `\n` = реальный
  перевод строки), `grep TODO notes.txt > found.txt`, observe `found.txt`;
  канон `found.txt = "TODO fix\n"`.

## 5. Контейнерные/сетевые задания (apt, sudo, …)
Такие задания НЕЛЬЗЯ деривировать в `TmpdirRunner` (нет пакетов/сети/root).
Авторим и деривируем их В КОНТЕЙНЕРЕ — tier2 (rootless overlay) или tier3
(`NspawnRunner` + `base_tar`), как в `tests/content/test_e2e_nspawn.py`.
Деривацию можно делать host-side на `TmpdirRunner`, только если наблюдаемый
эффект не зависит от контейнерного окружения; иначе — контейнерный фактори.

## 6. Остаток
Оставшиеся ~20 из 24 dev-заданий — content-ops follow-on по этому плейбуку
(в первую очередь контейнерные/сетевые). Каждое: task.toml → derive → валидация
харнессом Задачи 2 (+ tier3 для контейнерных).
```

- [ ] **Step 2: Commit**

```bash
git add "docs/Миграция контента (content migration).md"
git commit -m "docs(content): content migration + authoring playbook"
```

---

## Self-Review

**1. Spec coverage:** §3 (задание-как-код + кодоген) → Tasks 1 & 3; §7 (offline play loop: invisible check → local advance → local key) → Task 2 (`PlaySession.feed`); §10 (three tiers; content migration validates codegen) → Tasks 2/3 (tier1) + Task 4 (tier3) + Task 5 note that container tasks derive in tier2/3. Modernization item 7 (миграция контента, заодно проверка кодогена) → the whole plan, with the auto-migration infeasibility stated in "## Why this is not an auto-migration".

**2. Placeholder scan:** No TBD/TODO-as-instruction, no "add error handling", no "similar to Task N". All three task.toml files and all four test files are written out in full with runnable content; the playbook body is written out in full.

**3. Type consistency:** `derive_checks(factory, task, passes=3)` factory returns a prepared `TmpdirRunner` in every task; `PlaySession(bundle, progress, *, student_id, nonce)` and `.feed(*, command, rootfs, last_output, ts)` used exactly as in `hashpass.play`; `capture_candidate(rootfs, checks, last_output)` and `check_stage(checks, candidate)` take a `StageChecks` (= `derived.stages[0]`); `NspawnRunner(workdir, base_dir=...)` uses the keyword-only `base_dir`; `build_base(dest, from_tar=...)` keyword-only. `local_key` format `key{...}` matches `hashpass.key.local_key`.

**Reframe stated:** Yes — the header carries the "no stored commands → cannot auto-convert" finding and the "## Why this is not an auto-migration" note states the survey result prominently.

## Out of scope (content-ops follow-on)

- **Bulk authoring the remaining ~20 tasks** — a content-ops follow-on using the Task-5 playbook, especially the container/network tasks (apt, sudo, …) authored + derived in a tier2/3 container.
- **Multi-stage tasks + hints/conditions bundles** — the samples are single-stage with empty `conditions`/`hints`; richer tasks add `[[stage]]` tables and hand-edited `hints.toml`/`conditions.toml` (spec §3/§7).
- **Image rebuilds** — new environments (packages, base fs) are an image-tier concern, not part of this content plan (§3, cost tier 3).
