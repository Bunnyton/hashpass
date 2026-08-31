# Task Runtime (Phase 2B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a parsed task `Recipe` (Phase 2A) into a runnable task: build the image, derive per-stage acceptance on its overlay chain, stage the hidden `/hp` system layer, and drive a student session where every command runs in a container **without** `/hp` while checks/handlers run in a separate `/hp`-bound run (§4 invisibility-by-namespace, §6 `HP_*` contract).

**Architecture:** Five units on top of the merged Phase-1/2A code. (1) `runner/nspawn.py` gains optional `binds`/`setenv` on `run()` — the one primitive that makes `/hp` visible to a check-run only. (2) `hidden.py` builds the `/hp` host tree (pure filesystem). (3) `handler.py` implements the `HP_*` delegation contract: a pure `build_invocation` (auto-detect file-vs-command + env assembly) plus a thin `run_handler` that binds `/hp`. (4) `taskstore.py` + `taskbuild.py` — dataclasses/JSON for stored task metadata, and `build_task` which reuses the proven `taskcode` derivation engine **selectively** (observed stages derive; `check`/observe-less stages get a handler sentinel). (5) `taskrun.py` — `run_task`/`TaskSession`: a `PlaySession`-free hand-rolled loop that reuses `capture_candidate`/`grade_stage`/`progress`. The legacy `/.hash` `Task`/stub path is untouched.

**Tech Stack:** Python 3.13, stdlib + in-repo only. Consumes merged `hashpass.build`, `hashpass.imagestore.*`, `hashpass.image.base`, `hashpass.taskcode.*`, `hashpass.canon`, `hashpass.play`, `hashpass.grade`, `hashpass.progress`, `hashpass.key`, `hashpass.cmd`, `hashpass.recipe.*`. No third-party deps. Real containers via `systemd-nspawn` for tier3.

**Spec:** `docs/superpowers/specs/2026-08-31-образы-задания-и-dsl-design.md` — §4 (hidden `/hp` layer, invisibility via mount-namespace), §6 (`HP_*` handler contract), §9 phase 2 (task-on-image runtime: `stage`/`solve`/`observe`/`check`, derivation on the mounted chain, `/hp` + `on enter/pass`, clean paths).

## Global Constraints

- Python 3.13; stdlib + in-repo only; `encoding="utf-8"` on all file I/O.
- ruff `select=["ALL"]` clean under the repo `ruff.toml` (line-length 96; the project ignore-list already covers `ANN201`/`ANN001`, `D100`/`D102`/`D103`/`D104`, `T201`, `E501`, `S101`, `S603`/`S607`, `UP012`, etc.). Module-level constants for `PLR2004` magic values; keep functions ≤5 params — a 6-param public entrypoint carries `# noqa: PLR0913` exactly as the repo already does on `taskcode.derive.derive_checks` and `grade.grade_stage`. Multi-line docstrings put the summary on the second line (blank first line), matching `build.build`/`NspawnRunner.prepare`.
- **Tiers.** Task 2 and the `build_invocation` half of Task 3 are **tier1** (pure logic, no containers): `@pytest.mark.tier1`, run in the default `pytest` selection. Everything touching nspawn/overlay/sudo — Task 1, `run_handler` (Task 3), Task 4's `build_task`, Task 5's e2e — is **tier3**: `@pytest.mark.tier3`, uses the session-scoped `base_tar` fixture (`tests/conftest.py`), needs scoped sudo, and is excluded by the default `addopts = "-m 'not tier3'"`. Run tier3 with `TMPDIR=/var/tmp/hp-pytest python3 -m pytest <file> -m tier3 -v`. **Planning cannot run tier3** (no containers) — tier3 code in this plan is complete + ruff-clean; the implementer validates it by running `pytest -m tier3`.
- **Reuse, do not reinvent.** Derivation = `taskcode.execute.run_stage` + `canon.canonicalize`; acceptance = `play.capture_candidate` + `grade.grade_stage`; overlay/nspawn = `runner.nspawn` + `overlay`. The bundle format is `taskcode.bundle.Bundle`/`dump_bundle`/`load_bundle`. Never call `taskcode.bundle.apply_bundle` (it targets the OLD `/.hash/.task` path).
- **Clean paths (§4.1).** The bundle binds to `/hp/task`, the author's hidden dir to `/hp/work`; there is no `/.hash`, no runtime `hash` shell dependency on the new task path. Derived acceptance runs **host-side** on `student.rootfs`; handlers run **in-container** with `/hp` bound. `/hp` is present **only** on handler/check runs, never on a plain student command and never baked as an overlay lower.
- **Back-compat is a hard requirement:** the existing `tests/runner/test_nspawn.py` must pass unchanged — a `run(argv)` with no `binds`/`setenv` must be byte-identical to today's argv.

---

### Task 1: `NspawnRunner.run()` — optional `binds` + `setenv` (the /hp primitive)

**Files:**
- Modify: `src/hashpass/runner/nspawn.py` (the `run` method only — signature + argv assembly)
- Modify: `tests/runner/test_nspawn.py` (add one tier3 test; leave the existing test untouched)

**Interfaces:**
- Consumes: nothing new.
- Produces: `NspawnRunner.run(self, argv: list[str], *, binds: list[tuple[str, str]] | None = None, setenv: dict[str, str] | None = None) -> RunResult`. Each `(host, dst)` in `binds` appends `--bind=<host>:<dst>` (rw); each `k,v` in `setenv` appends `--setenv=<k>=<v>`; both go **before** `-D`. `binds=None, setenv=None` ⇒ argv byte-identical to today. Because each `run()` is its own `systemd-nspawn` process (fresh mount-ns), a bind is visible to that invocation only.

- [ ] **Step 1: Write the failing test** — append to `tests/runner/test_nspawn.py`

```python
@pytest.mark.tier3
def test_nspawn_bind_and_setenv_are_per_run(tmp_path, base_tar):
    hp = tmp_path / "hp"
    hp.mkdir()
    (hp / "token.txt").write_text("SECRET", encoding="utf-8")
    r = NspawnRunner(tmp_path / "run", base_tar=base_tar)
    r.prepare([])
    try:
        # A run WITH the bind + env sees the file and the variable.
        res = r.run(
            ["sh", "-c", "cat /hp/token.txt; printf ':'; printf '%s' \"$HP_TRIES\""],
            binds=[(str(hp), "/hp")],
            setenv={"HP_TRIES": "3"},
        )
        assert res.exit_code == 0
        assert res.stdout.strip() == "SECRET:3"
        # A plain run right after does NOT see /hp (fresh mount-ns, no bind).
        res2 = r.run(["sh", "-c", "test -e /hp; echo $?"])
        assert res2.stdout.strip() == "1"
    finally:
        r.teardown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/runner/test_nspawn.py::test_nspawn_bind_and_setenv_are_per_run -m tier3 -v`
Expected: FAIL — `TypeError: run() got an unexpected keyword argument 'binds'`.

- [ ] **Step 3: Write the implementation** — replace the `run` method in `src/hashpass/runner/nspawn.py`

```python
    def run(self, argv: list[str], *, binds: list[tuple[str, str]] | None = None,
            setenv: dict[str, str] | None = None) -> RunResult:
        """
        Run a single command inside the container via systemd-nspawn.

        Args:
            argv: Command and arguments to run.
            binds: Optional (host, dst) pairs bound rw into THIS run's mount-ns only
                (e.g. the hidden `/hp` layer). A run with `binds=None` sees no `/hp`.
            setenv: Optional environment variables set inside the container.

        Returns:
            RunResult with stdout, stderr, and exit code.

        """
        extra = [f"--bind={host}:{dst}" for host, dst in binds or []]
        extra += [f"--setenv={key}={val}" for key, val in (setenv or {}).items()]
        p = subprocess.run(
            ["sudo", "systemd-nspawn", "-q", "--register=no",
             *extra, "-D", str(self._mnt), *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return RunResult(p.stdout, p.stderr, p.returncode)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/runner/test_nspawn.py -m tier3 -v`
Expected: PASS — both the new test and the untouched `test_nspawn_run_and_persist` (the latter calls `run(argv)` with no kwargs → `extra == []` → argv byte-identical to today, verified: `["sudo","systemd-nspawn","-q","--register=no","-D",mnt,*argv]`). `ruff check --config ruff.toml src/hashpass/runner/nspawn.py tests/runner/test_nspawn.py` clean.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/runner/nspawn.py tests/runner/test_nspawn.py
git commit -m "feat(runner): NspawnRunner.run binds/setenv (per-run /hp bind, back-compat default)"
```

---

### Task 2: `hidden.py` — build the `/hp` host tree (tier1)

**Files:**
- Create: `src/hashpass/hidden.py`
- Test: `tests/test_hidden.py` (new)

**Interfaces:**
- Consumes: stdlib only (`shutil`, `pathlib`).
- Produces: `stage_hidden_layer(hp_dir: Path, *, work_src: Path | None = None, bundle_dir: Path | None = None) -> Path` — builds `<hp_dir>/{bin,task,work}` + `state.json`="{}" + `history`="" ; copies `work_src` into `work/` and `bundle_dir` into `task/`; returns `hp_dir`.

- [ ] **Step 1: Write the failing tests** — `tests/test_hidden.py`

```python
import pytest

from hashpass.hidden import stage_hidden_layer


@pytest.mark.tier1
def test_stage_hidden_layer_builds_tree_and_copies(tmp_path):
    work_src = tmp_path / "author_hidden"
    (work_src / "sub").mkdir(parents=True)
    (work_src / "verify.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (work_src / "sub" / "art.txt").write_text("hi", encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "checks.json").write_text('{"task_id":"t","stages":[]}', encoding="utf-8")

    hp = stage_hidden_layer(tmp_path / "hp", work_src=work_src, bundle_dir=bundle)

    assert (hp / "bin").is_dir()
    assert (hp / "task").is_dir()
    assert (hp / "work").is_dir()
    assert (hp / "state.json").read_text(encoding="utf-8") == "{}"
    assert (hp / "history").read_text(encoding="utf-8") == ""
    assert (hp / "work" / "verify.sh").read_text(encoding="utf-8") == "#!/bin/sh\necho ok\n"
    assert (hp / "work" / "sub" / "art.txt").read_text(encoding="utf-8") == "hi"
    assert (hp / "task" / "checks.json").exists()


@pytest.mark.tier1
def test_stage_hidden_layer_bare_layout(tmp_path):
    hp = stage_hidden_layer(tmp_path / "hp")
    assert list((hp / "work").iterdir()) == []
    assert (hp / "state.json").read_text(encoding="utf-8") == "{}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hidden.py -v`
Expected: FAIL — `ModuleNotFoundError: hashpass.hidden`.

- [ ] **Step 3: Write the implementation** — `src/hashpass/hidden.py`

```python
"""Build the hidden `/hp` host tree bound into handler/check runs (§4.1)."""
import shutil
from pathlib import Path

_HP_SUBDIRS = ("bin", "task", "work")


def stage_hidden_layer(hp_dir: Path, *, work_src: Path | None = None,
                       bundle_dir: Path | None = None) -> Path:
    """
    Build the hidden `/hp` host tree that a task binds into handler runs (§4.1).

    Layout: `<hp_dir>/{bin,task,work}` + `state.json`="{}" (rw session) + `history`="".
    `work_src` (the recipe's `hidden` dir) is copied into `work/`; `bundle_dir`
    (the derived acceptance bundle) is copied into `task/`. Pure host filesystem.

    Args:
        hp_dir: Destination host directory for the `/hp` tree (created on demand).
        work_src: Optional author `hidden` directory copied into `work/`.
        bundle_dir: Optional derived-checks bundle directory copied into `task/`.

    Returns:
        The `hp_dir` path (now populated).

    """
    hp_dir = Path(hp_dir)
    for sub in _HP_SUBDIRS:
        (hp_dir / sub).mkdir(parents=True, exist_ok=True)
    (hp_dir / "state.json").write_text("{}", encoding="utf-8")
    (hp_dir / "history").write_text("", encoding="utf-8")
    if work_src is not None:
        shutil.copytree(work_src, hp_dir / "work", dirs_exist_ok=True)
    if bundle_dir is not None:
        shutil.copytree(bundle_dir, hp_dir / "task", dirs_exist_ok=True)
    return hp_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hidden.py -v`
Expected: PASS (2 tests). `ruff check --config ruff.toml src/hashpass/hidden.py tests/test_hidden.py` clean.

> **Validated during planning:** the module + both tests were run as real pytest (2 passed) and are ruff-clean.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/hidden.py tests/test_hidden.py
git commit -m "feat(task): stage_hidden_layer builds the /hp host tree (bin/task/work + state/history)"
```

---

### Task 3: `handler.py` — the `HP_*` delegation contract

**Files:**
- Create: `src/hashpass/handler.py`
- Test: `tests/test_handler.py` (new — tier1 for `build_invocation`, tier3 for `run_handler`)

**Interfaces:**
- Consumes: `hashpass.recipe.model.ExecAction`, `hashpass.runner.nspawn.NspawnRunner` (Task 1's `run(argv, *, binds, setenv)`).
- Produces:
  - `HandlerContext(student_cmd: str, tries: int, last_out: str, stage: int)` — frozen.
  - `HandlerResult(stdout: str, exit_code: int)` — frozen.
  - `build_invocation(action: ExecAction, ctx: HandlerContext, *, hp_work_host: Path) -> tuple[list[str], dict[str, str]]` — auto-detects a file handler (`hp_work_host/<first-token>` is a file → argv `[/hp/work/<tok>, <student_cmd>, *positional]`, `k=v` tokens → `HP_ARG_k`) else `["sh","-c",<value>]`; always returns the full `HP_*` env. Raises `ValueError` on an empty value.
  - `run_handler(runner: NspawnRunner, action: ExecAction, ctx: HandlerContext, *, hp_dir: Path) -> HandlerResult` — `build_invocation(..., hp_work_host=hp_dir/"work")` then `runner.run(argv, binds=[(str(hp_dir), "/hp")], setenv=env)`.

- [ ] **Step 1: Write the failing tier1 tests** — `tests/test_handler.py` (the `build_invocation`/`HandlerResult` cases; the tier3 `run_handler` case is added in Step 6)

```python
import pytest

from hashpass.handler import HandlerContext, HandlerResult, build_invocation
from hashpass.recipe.model import ExecAction


@pytest.fixture
def work(tmp_path):
    (tmp_path / "verify.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "seed.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return tmp_path


@pytest.mark.tier1
def test_file_handler_argv_and_env(work):
    ctx = HandlerContext(student_cmd="grep -i ERROR log", tries=3, last_out="l1\nl2", stage=1)
    argv, env = build_invocation(ExecAction("verify.sh"), ctx, hp_work_host=work)
    assert argv == ["/hp/work/verify.sh", "grep -i ERROR log"]
    assert env["HP_TRIES"] == "3"
    assert env["HP_LAST_OUT"] == "l1\nl2"
    assert env["HP_STAGE"] == "1"
    assert env["HP_STATE"] == "/hp/state.json"
    assert env["HP_ROOTFS"] == "/"
    assert [k for k in env if k.startswith("HP_ARG_")] == []


@pytest.mark.tier1
def test_file_handler_named_and_positional_args(work):
    ctx = HandlerContext(student_cmd="cmd", tries=0, last_out="", stage=0)
    argv, env = build_invocation(
        ExecAction('verify.sh expected="a b" mode=strict'), ctx, hp_work_host=work)
    assert argv == ["/hp/work/verify.sh", "cmd"]
    assert env["HP_ARG_expected"] == "a b"
    assert env["HP_ARG_mode"] == "strict"
    argv2, _ = build_invocation(ExecAction("verify.sh strict"), ctx, hp_work_host=work)
    assert argv2 == ["/hp/work/verify.sh", "cmd", "strict"]


@pytest.mark.tier1
def test_command_handler_falls_through_to_sh_c(work):
    ctx = HandlerContext(student_cmd="cmd", tries=2, last_out="", stage=0)
    argv, env = build_invocation(ExecAction("grep -q ERROR errors.txt"), ctx, hp_work_host=work)
    assert argv == ["sh", "-c", "grep -q ERROR errors.txt"]
    assert env["HP_TRIES"] == "2"


@pytest.mark.tier1
def test_empty_action_raises(work):
    ctx = HandlerContext(student_cmd="cmd", tries=0, last_out="", stage=0)
    with pytest.raises(ValueError, match="empty exec"):
        build_invocation(ExecAction("   "), ctx, hp_work_host=work)


@pytest.mark.tier1
def test_handler_result_is_a_value():
    assert HandlerResult(stdout="hi", exit_code=0).exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_handler.py -m tier1 -v`
Expected: FAIL — `ModuleNotFoundError: hashpass.handler`.

- [ ] **Step 3: Write the implementation** — `src/hashpass/handler.py`

```python
"""HP_* handler contract (§6): build a delegated exec invocation and run it under /hp."""
import shlex
from dataclasses import dataclass
from pathlib import Path

from hashpass.recipe.model import ExecAction
from hashpass.runner.nspawn import NspawnRunner

_HP_WORK = "/hp/work"
_HP_STATE = "/hp/state.json"
_HP_HISTORY = "/hp/history"
_HP_ROOTFS = "/"


@dataclass(frozen=True)
class HandlerContext:
    """Inputs to one handler invocation (the HP_* channel, §6)."""

    student_cmd: str
    tries: int
    last_out: str
    stage: int


@dataclass(frozen=True)
class HandlerResult:
    """A handler's output: stdout (text directives) + exit code (predicate directives)."""

    stdout: str
    exit_code: int


def _split_args(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    """Split a file handler's trailing tokens into positional argv and HP_ARG_* pairs."""
    positional: list[str] = []
    hp_args: dict[str, str] = {}
    for tok in tokens:
        key, sep, val = tok.partition("=")
        if sep and key and " " not in key:
            hp_args[key] = val
        else:
            positional.append(tok)
    return positional, hp_args


def build_invocation(action: ExecAction, ctx: HandlerContext, *,
                     hp_work_host: Path) -> tuple[list[str], dict[str, str]]:
    """
    Build (argv, setenv) for an `exec` handler, auto-detecting file vs shell command.

    File handler: first shlex token names a file under the hidden work dir
    (`hp_work_host/<tok>`) -> run `/hp/work/<tok> <student_cmd> [positional...]`;
    trailing `k=v` tokens become HP_ARG_k. Otherwise the whole value runs as
    `sh -c <value>`. Either way the full HP_* env is set.

    Args:
        action: The `exec` action whose value is the file-or-command.
        ctx: The current handler context (student command, tries, last output, stage).
        hp_work_host: Host path of `/hp/work` (used to detect a file handler).

    Returns:
        (argv, setenv) ready for `NspawnRunner.run(argv, setenv=setenv, ...)`.

    Raises:
        ValueError: if the action value is empty.

    """
    tokens = shlex.split(action.value)
    if not tokens:
        msg = "empty exec action"
        raise ValueError(msg)
    first = tokens[0]
    hp_args: dict[str, str] = {}
    if (hp_work_host / first).is_file():
        positional, hp_args = _split_args(tokens[1:])
        argv = [f"{_HP_WORK}/{first}", ctx.student_cmd, *positional]
    else:
        argv = ["sh", "-c", action.value]
    env = {
        "HP_TRIES": str(ctx.tries),
        "HP_LAST_OUT": ctx.last_out,
        "HP_HISTORY": _HP_HISTORY,
        "HP_STATE": _HP_STATE,
        "HP_ROOTFS": _HP_ROOTFS,
        "HP_STAGE": str(ctx.stage),
    }
    for key, val in hp_args.items():
        env[f"HP_ARG_{key}"] = val
    return argv, env


def run_handler(runner: NspawnRunner, action: ExecAction, ctx: HandlerContext, *,
                hp_dir: Path) -> HandlerResult:
    """
    Run one `exec` handler in a fresh mount-ns with `/hp` bound and HP_* set.

    Binds the host `hp_dir` at `/hp` for this single invocation only (a plain student
    run gets its own ns without `/hp`), then returns the handler's stdout + exit code.

    Args:
        runner: The prepared student NspawnRunner (its overlay is the student rootfs).
        action: The delegated `exec` action to run.
        ctx: The handler context (HP_* inputs).
        hp_dir: Host `/hp` tree to bind (writable this session).

    Returns:
        HandlerResult(stdout, exit_code).

    """
    argv, env = build_invocation(action, ctx, hp_work_host=hp_dir / "work")
    res = runner.run(argv, binds=[(str(hp_dir), "/hp")], setenv=env)
    return HandlerResult(stdout=res.stdout, exit_code=res.exit_code)
```

- [ ] **Step 4: Run tier1 tests to verify they pass**

Run: `python3 -m pytest tests/test_handler.py -m tier1 -v`
Expected: PASS (5 tests). `ruff check --config ruff.toml src/hashpass/handler.py tests/test_handler.py` clean.

> **Validated during planning:** `build_invocation`/`_split_args` transcribed from the 15-assert prototype (`proto_2b_handler.py`); the 5 tier1 tests above were run as real pytest (5 passed) against `ExecAction` imported from `hashpass.recipe.model`, ruff-clean.

- [ ] **Step 5: Commit the tier1 core**

```bash
git add src/hashpass/handler.py tests/test_handler.py
git commit -m "feat(task): HP_* handler contract — build_invocation (file/command auto-detect) + run_handler"
```

- [ ] **Step 6: Add the tier3 `run_handler` tests** — in `tests/test_handler.py`, first REPLACE the import block at the top so the tier3 names are available (each committed state stays ruff-clean — the tier1 commit must not import `run_handler`/`build_base`/`NspawnRunner`):

```python
from pathlib import Path

import pytest

from hashpass.handler import HandlerContext, HandlerResult, build_invocation, run_handler
from hashpass.image.base import build_base
from hashpass.recipe.model import ExecAction
from hashpass.runner.nspawn import NspawnRunner
```

Then append:

```python
def _hp(tmp_path, script_name, script_body) -> Path:
    hp = tmp_path / "hp"
    (hp / "work").mkdir(parents=True)
    s = hp / "work" / script_name
    s.write_text(script_body, encoding="utf-8")
    s.chmod(0o755)
    (hp / "state.json").write_text("{}", encoding="utf-8")
    return hp


@pytest.mark.tier3
def test_run_handler_file_echoes_argv_and_env(tmp_path, base_tar):
    hp = _hp(tmp_path, "say.sh", '#!/bin/sh\necho "cmd=$1 tries=$HP_TRIES"\n')
    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = NspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        ctx = HandlerContext(student_cmd="grep -i err log", tries=4, last_out="", stage=0)
        res = run_handler(r, ExecAction("say.sh"), ctx, hp_dir=hp)
        assert res.exit_code == 0
        assert res.stdout.strip() == "cmd=grep -i err log tries=4"
    finally:
        r.teardown()


@pytest.mark.tier3
def test_run_handler_command_predicate_exit_code(tmp_path, base_tar):
    hp = tmp_path / "hp"
    (hp / "work").mkdir(parents=True)
    (hp / "state.json").write_text("{}", encoding="utf-8")
    base = build_base(tmp_path / "base", from_tar=base_tar)
    r = NspawnRunner(tmp_path / "run", base_dir=base)
    r.prepare([])
    try:
        r.run(["sh", "-c", "printf 'ERROR here\\n' > /errors.txt"])
        ctx = HandlerContext(student_cmd="", tries=0, last_out="", stage=0)
        ok = run_handler(r, ExecAction("grep -q ERROR /errors.txt"), ctx, hp_dir=hp)
        assert ok.exit_code == 0
        no = run_handler(r, ExecAction("grep -q NOPE /errors.txt"), ctx, hp_dir=hp)
        assert no.exit_code != 0
    finally:
        r.teardown()
```

> **Note for the implementer:** hidden scripts must be executable with a valid shebang — `nspawn` execs `argv[0]` directly. The `_hp` helper `chmod 0o755`s the script; `#!/bin/sh` (dash) is the only interpreter guaranteed in `debian:trixie-slim` (no `python3`).

- [ ] **Step 7: Run the tier3 tests, then commit**

Run: `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/test_handler.py -m tier3 -v`
Expected: PASS (2 tests: file handler echoes `$1`+`HP_TRIES`; command handler `grep -q` predicate exit code). `ruff check --config ruff.toml tests/test_handler.py` clean.

```bash
git add tests/test_handler.py
git commit -m "test(task): tier3 run_handler — file handler argv/env + command predicate exit"
```

---

### Task 4: `taskstore.py` + `taskbuild.build_task` — build a task and store its artifacts

**Files:**
- Create: `src/hashpass/taskstore.py` (dataclasses + meta JSON + `load_task`)
- Create: `src/hashpass/taskbuild.py` (`build_task` + selective-derive helpers)
- Test: `tests/test_taskstore.py` (new, tier1), `tests/test_taskbuild.py` (new, tier3)

**Interfaces:**
- Consumes: `hashpass.build.build`; `hashpass.image.base.build_base`; `hashpass.imagestore.resolve.resolve_lowers`; `hashpass.imagestore.store.{ImageStore, StoredImage}`; `hashpass.recipe.model.{Recipe, StageSpec, image_ref}`; `hashpass.recipe.taskbridge.recipe_to_taskcode`; `hashpass.runner.nspawn.NspawnRunner`; `hashpass.taskcode.execute.{OUTPUT_KEY, run_stage}`; `hashpass.taskcode.derive.{DerivedChecks, StageChecks}`; `hashpass.taskcode.bundle.{Bundle, dump_bundle}`; `hashpass.taskcode.model.{StageCode, TaskCode}`; `hashpass.canon.{Observation, canonicalize}`; `hashpass.hidden.stage_hidden_layer`.
- Produces (taskstore):
  - `StageMeta(message: str, neutral: tuple[str,...], check: str | None, on_enter: tuple[str,...], on_pass: tuple[str,...], acceptance: str)` — `check`/`on_enter`/`on_pass` are `ExecAction.value` strings; `acceptance` ∈ {"derived","handler"}.
  - `TaskMeta(image_ref: str, stages: tuple[StageMeta,...], readme: str | None = None)`.
  - `StoredTask(ref: str, image: StoredImage, bundle_dir: Path, hp_src_dir: Path, meta: TaskMeta)`.
  - `task_dir(ref, store) -> Path` (`store.get(ref).layer.parent / "task"`), `meta_to_dict`/`meta_from_dict`, `save_meta(meta, dest)`, `load_meta(src)`, `load_task(ref, store) -> StoredTask`.
- Produces (taskbuild): `build_task(recipe, store, *, base_tar, workdir, passes=3, sudo=True) -> StoredTask`.

**Two decisions beyond the design notes (both recorded in the Self-Review):**
1. **Acceptance keyed on `check` presence, then `observe`.** `_acceptance_of`: `stage.check is not None → "handler"`; `elif stage.observe → "derived"`; else `ValueError` (a stage with neither cannot be accepted). This subsumes the design's "observe → derived, else sentinel" for every case (a `check`-stage is observe-less in practice) and resolves the observe+check ambiguity deterministically (`check` wins).
2. **`exclude` is applied as an fnmatch GLOB in the derivation capture path (chosen resolution of the prefix caveat).** `taskcode.execute.run_stage` curates `exclude` via `str.startswith`, so a DSL glob like `*.log` never matches. `build_task` derives on a `_no_exclude(task)` copy (per-stage `exclude` cleared, so the engine applies **no** curation) and instead curates each returned `Observation` with `_curate`/`_excluded` (fnmatch on the whole key OR any path segment). Because `play.capture_candidate` re-derives its observe list from the surviving canonical keys, curating only during derivation is sufficient and consistent at runtime.

- [ ] **Step 1: Write the failing tier1 meta test** — `tests/test_taskstore.py`

```python
import pytest

from hashpass.taskstore import (
    StageMeta,
    TaskMeta,
    load_meta,
    meta_from_dict,
    meta_to_dict,
    save_meta,
)


def _meta() -> TaskMeta:
    return TaskMeta(
        image_ref="log-archive:1",
        stages=(
            StageMeta(message="collect", neutral=("ls", "cd"), check=None,
                      on_enter=("seed.sh",), on_pass=("cheer.sh",), acceptance="derived"),
            StageMeta(message="verify", neutral=(), check="verify.sh",
                      on_enter=(), on_pass=(), acceptance="handler"),
        ),
        readme="readme.txt",
    )


@pytest.mark.tier1
def test_meta_dict_round_trip():
    meta = _meta()
    assert meta_from_dict(meta_to_dict(meta)) == meta


@pytest.mark.tier1
def test_meta_file_round_trip(tmp_path):
    meta = _meta()
    save_meta(meta, tmp_path / "task")
    assert load_meta(tmp_path / "task") == meta


@pytest.mark.tier1
def test_meta_missing_readme_defaults_none():
    m = meta_from_dict({"image_ref": "x:1", "stages": []})
    assert m.readme is None
    assert m.stages == ()
```

- [ ] **Step 2: Run tier1 test to verify it fails**

Run: `python3 -m pytest tests/test_taskstore.py -v`
Expected: FAIL — `ModuleNotFoundError: hashpass.taskstore`.

- [ ] **Step 3: Write `src/hashpass/taskstore.py`**

```python
"""Local task store: task artifacts (bundle + hidden /hp + meta) under the image's ver dir."""
import json
from dataclasses import dataclass
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage


@dataclass(frozen=True)
class StageMeta:
    """Per-stage runtime metadata: acceptance mode + delegated actions + neutral set."""

    message: str
    neutral: tuple[str, ...]
    check: str | None            # ExecAction.value, or None
    on_enter: tuple[str, ...]    # ExecAction.value list
    on_pass: tuple[str, ...]     # ExecAction.value list
    acceptance: str              # "derived" | "handler"


@dataclass(frozen=True)
class TaskMeta:
    """Task runtime metadata: the built image ref, ordered stages, optional readme."""

    image_ref: str
    stages: tuple[StageMeta, ...]
    readme: str | None = None


@dataclass(frozen=True)
class StoredTask:
    """A stored task: its ref, the built image, and on-disk bundle/hidden/meta artifacts."""

    ref: str
    image: StoredImage
    bundle_dir: Path
    hp_src_dir: Path
    meta: TaskMeta


def task_dir(ref: str, store: ImageStore) -> Path:
    """Return the task-artifacts directory for a stored image ref (`.../ver/task`)."""
    return store.get(ref).layer.parent / "task"


def _stage_to_dict(s: StageMeta) -> dict:
    return {
        "message": s.message,
        "neutral": list(s.neutral),
        "check": s.check,
        "on_enter": list(s.on_enter),
        "on_pass": list(s.on_pass),
        "acceptance": s.acceptance,
    }


def _stage_from_dict(d: dict) -> StageMeta:
    return StageMeta(
        message=d["message"],
        neutral=tuple(d["neutral"]),
        check=d["check"],
        on_enter=tuple(d["on_enter"]),
        on_pass=tuple(d["on_pass"]),
        acceptance=d["acceptance"],
    )


def meta_to_dict(meta: TaskMeta) -> dict:
    """Serialize TaskMeta to a JSON-ready dict."""
    return {
        "image_ref": meta.image_ref,
        "stages": [_stage_to_dict(s) for s in meta.stages],
        "readme": meta.readme,
    }


def meta_from_dict(data: dict) -> TaskMeta:
    """Rebuild TaskMeta from its JSON dict."""
    return TaskMeta(
        image_ref=data["image_ref"],
        stages=tuple(_stage_from_dict(s) for s in data["stages"]),
        readme=data.get("readme"),
    )


def save_meta(meta: TaskMeta, dest: Path) -> None:
    """Write `<dest>/task-meta.json` (dest is the task-artifacts dir)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "task-meta.json").write_text(
        json.dumps(meta_to_dict(meta), indent=2), encoding="utf-8")


def load_meta(src: Path) -> TaskMeta:
    """Read `<src>/task-meta.json` back into a TaskMeta."""
    text = (Path(src) / "task-meta.json").read_text(encoding="utf-8")
    return meta_from_dict(json.loads(text))


def load_task(ref: str, store: ImageStore) -> StoredTask:
    """Load a stored task's artifacts (bundle dir, hidden `/hp` dir, and meta)."""
    tdir = task_dir(ref, store)
    return StoredTask(
        ref=ref,
        image=store.get(ref),
        bundle_dir=tdir / "bundle",
        hp_src_dir=tdir / "hp",
        meta=load_meta(tdir),
    )
```

- [ ] **Step 4: Run the tier1 meta test to verify it passes**

Run: `python3 -m pytest tests/test_taskstore.py -v`
Expected: PASS (3 tests). `ruff check --config ruff.toml src/hashpass/taskstore.py tests/test_taskstore.py` clean.

> **Validated during planning:** the taskstore dataclasses + `meta_to_dict`/`meta_from_dict`/`save_meta`/`load_meta` and the 3 tier1 tests were run as real pytest (3 passed), ruff-clean.

- [ ] **Step 5: Write `src/hashpass/taskbuild.py`**

```python
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
    """`check` present -> handler; else observed -> derived; else an authoring error."""
    if stage.check is not None:
        return "handler"
    if stage.observe:
        return "derived"
    msg = f"stage {stage.message!r} has neither `observe` nor `check`: cannot be accepted"
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


def _derive_stage(factory: Callable[[], NspawnRunner], deriv_task: TaskCode,
                  stage_index: int, exclude: tuple[str, ...], passes: int) -> StageChecks:
    """Run one observed stage `passes` times on FRESH runners, curate, canonicalize."""
    observations: list[Observation] = []
    for _ in range(passes):
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
    return StageChecks(canonical=canonical)


def _selective_derive(factory: Callable[[], NspawnRunner], recipe: Recipe,
                      task: TaskCode, passes: int) -> tuple[list[StageChecks], list[str]]:
    """Per stage: handler -> sentinel checks; observed -> derived checks. Returns (checks, modes)."""
    deriv_task = _no_exclude(task)
    checks: list[StageChecks] = []
    acceptance: list[str] = []
    for i, stage in enumerate(recipe.stages):
        mode = _acceptance_of(stage)
        if mode == "handler":
            checks.append(StageChecks(canonical={}))       # sentinel; runtime uses run_handler
        else:
            checks.append(_derive_stage(factory, deriv_task, i, stage.exclude, passes))
        acceptance.append(mode)
    return checks, acceptance


def _build_meta(ref: str, recipe: Recipe, acceptance: list[str]) -> TaskMeta:
    """Assemble the runtime TaskMeta from the recipe stages + per-stage acceptance modes."""
    stages = tuple(
        StageMeta(
            message=s.message,
            neutral=s.neutral,
            check=s.check.value if s.check is not None else None,
            on_enter=tuple(a.value for a in s.on_enter),
            on_pass=tuple(a.value for a in s.on_pass),
            acceptance=acceptance[i],
        )
        for i, s in enumerate(recipe.stages)
    )
    return TaskMeta(image_ref=ref, stages=stages, readme=recipe.readme)


def build_task(recipe: Recipe, store: ImageStore, *, base_tar: Path,  # noqa: PLR0913
               workdir: Path, passes: int = 3, sudo: bool = True) -> StoredTask:
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
        base_tar: Rootfs tarball for the bottom base layer.
        workdir: Scratch dir for the image build, base, and per-pass runners.
        passes: Derivation passes per observed stage (>= 2).
        sudo: Whether overlay mounts use sudo (True for real nspawn).

    Returns:
        The StoredTask (ref, image, bundle dir, hidden `/hp` dir, meta).

    """
    workdir = Path(workdir)
    image = build(recipe, store, base_tar=base_tar, workdir=workdir / "img", sudo=sudo)
    ref = image_ref(recipe)
    task = recipe_to_taskcode(recipe)

    lowers = resolve_lowers((ref,), store)
    base = build_base(workdir / "base", from_tar=base_tar)
    counter = itertools.count()

    def factory() -> NspawnRunner:
        runner = NspawnRunner(workdir / f"derive{next(counter)}", base_dir=base)
        runner.prepare(lowers)
        return runner

    stage_checks, acceptance = _selective_derive(factory, recipe, task, passes)

    tdir = store.get(ref).layer.parent / "task"
    bundle_dir = tdir / "bundle"
    derived = DerivedChecks(task_id=task.id, stages=tuple(stage_checks))
    dump_bundle(Bundle(checks=derived, conditions={}, hints={}), bundle_dir)

    hp_dir = tdir / "hp"
    work_src = Path(recipe.hidden) if recipe.hidden else None
    stage_hidden_layer(hp_dir, work_src=work_src, bundle_dir=bundle_dir)

    meta = _build_meta(ref, recipe, acceptance)
    save_meta(meta, tdir)
    return StoredTask(ref=ref, image=image, bundle_dir=bundle_dir, hp_src_dir=hp_dir, meta=meta)
```

- [ ] **Step 6: Write the failing tier3 build test** — `tests/test_taskbuild.py`

```python
import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import build_task
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskstore import load_task

_DERIVED = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt

stage "count them"
  solve wc -l < /errors.txt > /count.txt
  observe /count.txt
"""


@pytest.mark.tier3
def test_build_task_derives_and_stores_artifacts(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    stored = build_task(parse_recipe(_DERIVED), store, base_tar=base_tar,
                        workdir=tmp_path / "bt", passes=2)
    # image built + stored
    assert store.exists("logtask:1")
    # bundle: two derived stages, each canonical carries a real signal
    assert (stored.bundle_dir / "checks.json").exists()
    checks = load_bundle(stored.bundle_dir).checks
    assert checks.task_id == "logtask"
    assert len(checks.stages) == 2  # noqa: PLR2004
    assert any(k != "<output>" for k in checks.stages[0].canonical)
    # hidden /hp staged with the bundle under task/
    assert (stored.hp_src_dir / "task" / "checks.json").exists()
    assert (stored.hp_src_dir / "state.json").read_text(encoding="utf-8") == "{}"
    # meta records derived acceptance for both stages
    meta = load_task("logtask:1", store).meta
    assert [s.acceptance for s in meta.stages] == ["derived", "derived"]
    assert meta.image_ref == "logtask:1"
```

- [ ] **Step 7: Run the tier3 build test, then commit**

Run: `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/test_taskbuild.py -m tier3 -v`
Expected: PASS — the image is built, both observed stages derive a non-vacuous canonical over `passes=2` fresh nspawn runners, the bundle + hidden `/hp` land under `<store>/logtask/1/task/`, and `task-meta.json` marks both stages `"derived"`. `ruff check --config ruff.toml src/hashpass/taskbuild.py tests/test_taskbuild.py` clean.

> **Validated during planning:** the selective-derive STRUCTURE (branching, per-stage pass count on fresh runners, fnmatch `_curate`/`_excluded`, `_has_signal`, `_acceptance_of`) was run against a stubbed `run_stage`/`canonicalize` (12 asserts pass); `taskbuild.py` is ruff-clean. The nspawn/overlay wiring is tier3 and is validated by the implementer running `pytest -m tier3`.

```bash
git add src/hashpass/taskstore.py src/hashpass/taskbuild.py tests/test_taskstore.py tests/test_taskbuild.py
git commit -m "feat(task): build_task — selective derivation on the image chain + task store + meta"
```

---

### Task 5: `taskrun.run_task` + `TaskSession` — the student runtime loop (tier3 e2e)

**Files:**
- Create: `src/hashpass/taskrun.py`
- Test: `tests/test_taskrun.py` (new, tier3 e2e)

**Interfaces:**
- Consumes: `hashpass.taskstore.{StageMeta, StoredTask, load_task}`; `hashpass.handler.{HandlerContext, run_handler}`; `hashpass.play.capture_candidate`; `hashpass.grade.grade_stage`; `hashpass.key.local_key`; `hashpass.progress.{current_stage, mark_passed_local, new_progress}`; `hashpass.cmd.Cmd`; `hashpass.taskcode.bundle.load_bundle`; `hashpass.recipe.model.ExecAction`; `hashpass.image.base.build_base`; `hashpass.imagestore.resolve.resolve_lowers`; `hashpass.imagestore.store.ImageStore`; `hashpass.runner.nspawn.NspawnRunner`.
- Produces:
  - `FeedResult(advanced: bool, stage: int | None, local_key: str | None, hint: str | None = None)`.
  - `TaskSession(stored: StoredTask, student: NspawnRunner, hp_dir: Path, *, student_id: str, nonce: str)` with `enter() -> list[str]`, `feed(command: str, *, ts: str) -> FeedResult`, `teardown() -> None`.
  - `run_task(ref, store, workdir, *, base_tar, student_id, nonce) -> TaskSession`.

**Three decisions beyond the design notes (recorded in the Self-Review):**
1. **`task_id` for local keys = `checks.task_id`** (= the recipe name, from `recipe_to_taskcode`), used for BOTH handler and derived acceptance, rather than the raw `ref`. This keeps the handler and derived key namespaces identical and matches the bundle's own identity (the design's `local_key(ref,...)` and this coincide when `ref` is a bare name).
2. **`FeedResult` is defined locally** (with `hint` defaulted `None`) rather than importing `play.FeedResult`, because the 2B loop is `PlaySession`-free and `hint` is a Phase-3 concern (always `None` here). It intentionally mirrors `play.FeedResult`'s shape.
3. **`TaskSession.__init__` derives `checks`/`progress`/`tries` from the `StoredTask`** (5 params, no `# noqa`), so `run_task` only has to build the student runner and the writable `/hp` copy before constructing it.

- [ ] **Step 1: Write the failing e2e tests** — `tests/test_taskrun.py`

```python
import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import build_task
from hashpass.taskrun import run_task

_DERIVED = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt
"""


@pytest.mark.tier3
def test_e2e_derived_stage_accepts_and_rejects(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_DERIVED), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    ts = "2026-08-31T00:00:00"
    session = run_task("logtask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        wrong = session.feed("echo nope > /errors.txt", ts=ts)
        assert wrong.advanced is False
        assert wrong.local_key is None
        right = session.feed("grep -rh ERROR /var/log/app > /errors.txt", ts=ts)
        assert right.advanced is True
        assert right.local_key is not None
    finally:
        session.teardown()


_CHECK = """\
image verifytask:1
hidden {hidden}

stage "create the flag"
  solve touch /done
  check exec verify.sh
"""


@pytest.mark.tier3
def test_e2e_check_exec_stage(tmp_path, base_tar):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    v = hidden / "verify.sh"
    v.write_text("#!/bin/sh\n[ -f /done ]\n", encoding="utf-8")
    v.chmod(0o755)
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_CHECK.format(hidden=hidden)), store, base_tar=base_tar,
               workdir=tmp_path / "bt")
    session = run_task("verifytask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        assert session.feed("ls /", ts="t").advanced is False       # /done absent -> verify exit 1
        assert session.feed("touch /done", ts="t").advanced is True  # now verify exit 0
    finally:
        session.teardown()


_SIDE = """\
image sidetask:1
hidden {hidden}

stage "write the marker"
  solve echo done > /marker
  observe /marker
  on enter exec seed.sh
  on pass  exec cheer.sh
"""


@pytest.mark.tier3
def test_e2e_on_enter_and_on_pass_fire(tmp_path, base_tar):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    for name, body in (("seed.sh", '#!/bin/sh\necho Welcome\necho enter >> "$HP_STATE"\n'),
                       ("cheer.sh", '#!/bin/sh\necho pass >> "$HP_STATE"\n')):
        p = hidden / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_SIDE.format(hidden=hidden)), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    session = run_task("sidetask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        greeting = session.enter()
        assert any("Welcome" in g for g in greeting)                 # on_enter stdout rendered
        state = (session.hp_dir / "state.json").read_text(encoding="utf-8")
        assert "enter" in state                                      # on_enter wrote rw /hp
        res = session.feed("echo done > /marker", ts="t")
        assert res.advanced is True
        state2 = (session.hp_dir / "state.json").read_text(encoding="utf-8")
        assert "pass" in state2                                      # on_pass fired after accept
    finally:
        session.teardown()
```

- [ ] **Step 2: Run the e2e tests to verify they fail**

Run: `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/test_taskrun.py -m tier3 -v`
Expected: FAIL — `ModuleNotFoundError: hashpass.taskrun`.

- [ ] **Step 3: Write `src/hashpass/taskrun.py`**

```python
"""Run a stored task: student container WITHOUT /hp; handlers/checks in a bound-/hp run."""
import shutil
from dataclasses import dataclass
from pathlib import Path

from hashpass.cmd import Cmd
from hashpass.grade import grade_stage
from hashpass.handler import HandlerContext, run_handler
from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.key import local_key
from hashpass.play import capture_candidate
from hashpass.progress import current_stage, mark_passed_local, new_progress
from hashpass.recipe.model import ExecAction
from hashpass.runner.nspawn import NspawnRunner
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskstore import StageMeta, StoredTask, load_task

_ACCEPT_EXIT = 0


@dataclass
class FeedResult:
    """Outcome of feeding one student command (hints deferred to Phase 3, always None here)."""

    advanced: bool
    stage: int | None
    local_key: str | None
    hint: str | None = None


class TaskSession:
    """One student's live task run: a /hp-free student container + per-session hidden /hp."""

    def __init__(self, stored: StoredTask, student: NspawnRunner, hp_dir: Path, *,
                 student_id: str, nonce: str) -> None:
        """Bind a stored task to a prepared (student) runner and a writable /hp copy."""
        self.stored = stored
        self.student = student
        self.hp_dir = Path(hp_dir)
        self.meta = stored.meta
        self.checks = load_bundle(stored.bundle_dir).checks
        self.task_id = self.checks.task_id
        self.student_id = student_id
        self.nonce = nonce
        self.progress = new_progress(self.task_id, len(stored.meta.stages))
        self.tries = [0] * len(stored.meta.stages)

    def _fire(self, actions: tuple[str, ...], ctx: HandlerContext) -> list[str]:
        """Run a list of delegated actions (on_enter/on_pass) under /hp; collect any stdout."""
        outs: list[str] = []
        for value in actions:
            res = run_handler(self.student, ExecAction(value), ctx, hp_dir=self.hp_dir)
            if res.stdout:
                outs.append(res.stdout)
        return outs

    def enter(self) -> list[str]:
        """Fire the current stage's `on_enter` handlers; return their rendered stdout."""
        stage = current_stage(self.progress)
        if stage is None:
            return []
        sm = self.meta.stages[stage]
        ctx = HandlerContext(student_cmd="", tries=self.tries[stage], last_out="", stage=stage)
        return self._fire(sm.on_enter, ctx)

    def _accept(self, stage: int, sm: StageMeta, command: str,
                out: str, ts: str) -> tuple[bool, str | None]:
        """Decide acceptance: handler stages via a /hp check-run; derived stages host-side."""
        if sm.acceptance == "handler":
            ctx = HandlerContext(student_cmd=command, tries=self.tries[stage],
                                 last_out=out, stage=stage)
            res = run_handler(self.student, ExecAction(sm.check), ctx, hp_dir=self.hp_dir)
            if res.exit_code == _ACCEPT_EXIT:
                return True, local_key(self.task_id, stage, self.nonce)
            return False, None
        cand = capture_candidate(self.student.rootfs, self.checks.stages[stage], out)
        grade = grade_stage(self.checks.stages[stage], cand, task_id=self.task_id,
                            stage=stage, student_id=self.student_id, nonce=self.nonce, ts=ts)
        return grade.accepted, grade.local_key

    def feed(self, command: str, *, ts: str) -> FeedResult:
        """Run one student command (no /hp), tally neutral-aware tries, check acceptance."""
        stage = current_stage(self.progress)
        if stage is None:
            return FeedResult(advanced=False, stage=None, local_key=None)
        sm = self.meta.stages[stage]
        out = self.student.run(["sh", "-c", command]).stdout
        if Cmd(command).basecmd not in sm.neutral:
            self.tries[stage] += 1
        accepted, key = self._accept(stage, sm, command, out, ts)
        if accepted:
            mark_passed_local(self.progress, stage)
            ctx = HandlerContext(student_cmd=command, tries=self.tries[stage],
                                 last_out=out, stage=stage)
            self._fire(sm.on_pass, ctx)
        return FeedResult(advanced=accepted, stage=stage, local_key=key)

    def teardown(self) -> None:
        """Tear down the student container (unmount overlay). The /hp copy is scratch."""
        self.student.teardown()


def run_task(ref: str, store: ImageStore, workdir: Path, *,  # noqa: PLR0913
             base_tar: Path, student_id: str, nonce: str) -> TaskSession:
    """
    Open a live task session: a student container on the image chain, no `/hp` in it.

    Prepares the student NspawnRunner over the task image's overlay closure (so `/hp`
    is never a lower and never baked), makes a writable per-session copy of the stored
    hidden `/hp`, and returns a driveable TaskSession.

    Args:
        ref: Task/image reference (`name` or `name:version`).
        store: Image store holding the task and its image chain.
        workdir: Scratch dir for the base, the student runner tree, and the /hp copy.
        base_tar: Rootfs tarball for the bottom base layer.
        student_id: Student identity (folded into evidence for derived stages).
        nonce: Per-session nonce for local keys.

    Returns:
        A TaskSession (call `.enter()`, `.feed(cmd, ts=...)`, `.teardown()`).

    """
    workdir = Path(workdir)
    stored = load_task(ref, store)
    lowers = resolve_lowers((ref,), store)
    base = build_base(workdir / "base", from_tar=base_tar)
    student = NspawnRunner(workdir / "student", base_dir=base)
    student.prepare(lowers)
    hp_dir = workdir / "hp"
    shutil.copytree(stored.hp_src_dir, hp_dir, dirs_exist_ok=True)
    return TaskSession(stored, student, hp_dir, student_id=student_id, nonce=nonce)
```

- [ ] **Step 4: Run the e2e tests to verify they pass**

Run: `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/test_taskrun.py -m tier3 -v`
Expected: PASS (3 tests):
- **derived** — `build_task → run_task`; `feed("grep …")` advances with a `local_key`, `feed("echo nope …")` does not (host-side `capture_candidate` + `grade_stage` on `student.rootfs`).
- **check-exec** — the hidden `#!/bin/sh verify.sh` (`[ -f /done ]`) rejects before `touch /done` and accepts after (handler acceptance via a `/hp`-bound check-run).
- **on_enter/on_pass** — `enter()` returns the `seed.sh` greeting and `seed.sh` wrote to the rw `/hp/state.json`; after the accepting `feed`, `cheer.sh` (on_pass) appended to it too.

`ruff check --config ruff.toml src/hashpass/taskrun.py tests/test_taskrun.py` clean.

> **Validated during planning:** `taskrun.py` is ruff-clean and its types line up with the consumed reuse signatures (`capture_candidate(rootfs, StageChecks, last_output)`, `grade_stage(checks, candidate, *, task_id, stage, student_id, nonce, ts)`, `current_stage`/`mark_passed_local`, `Cmd(cmd).basecmd`, `run_handler(runner, ExecAction, ctx, *, hp_dir)`). The nspawn/overlay e2e is tier3 and is validated by the implementer running `pytest -m tier3`.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/taskrun.py tests/test_taskrun.py
git commit -m "feat(task): run_task + TaskSession — /hp-free student loop, handler + derived acceptance"
```

---

## Self-Review

**1. Spec coverage.**
- **§4.1 clean paths** — bundle → `/hp/task`, author hidden → `/hp/work`, `state.json`/`history` seeded; no `/.hash`, no runtime `hash` dependency on the new path (Task 2 `stage_hidden_layer`; Task 4 wiring). ✓
- **§4.2 invisibility via namespace** — `/hp` is bound only on handler/check runs (`run_handler`), never on a plain student `feed` command and never an overlay lower; each `run()` is a fresh mount-ns (Task 1 primitive; Task 3 `run_handler`; Task 5 loop). Task 1's test asserts a plain run right after a bound run does NOT see `/hp`. ✓
- **§6 `HP_*` contract** — `argv[1]`=student cmd, `HP_TRIES`/`HP_LAST_OUT`/`HP_HISTORY`/`HP_STATE`(rw)/`HP_ROOTFS`/`HP_STAGE`/`HP_ARG_*`; file-vs-command auto-detect; stdout=text, exit=predicate (Task 3, transcribed from the validated prototype). ✓
- **§9 phase 2 runtime** — `stage`/`solve`/`observe`/`check` consumed; derivation on the mounted image chain reusing `taskcode` (Task 4 `_selective_derive` via `run_stage`+`canonicalize`); `on enter`/`on pass` fired with `/hp` (Task 5); acceptance for derived stages host-side, for `check`/handler stages in-container (Task 5). ✓
- **§5 keys** — provisional `local_key(nonce)` minted on accept for both paths; server/global path untouched (reused `grade_stage` still builds evidence for derived stages). ✓
- **Correctly deferred (not built here):** Phase-3 interactivity (typewriter, conditional `hint tries/idle/cmd/output`, `voice`, `say`/`show`, `react`), `--private-users`, `HP_HISTORY` transcript population, a build/run CLI. `FeedResult.hint` is reserved (always `None`).

**2. Placeholder scan.** None. Every code step contains complete, runnable code. Pure-logic units were materialized and validated during planning: `build_invocation` (17 asserts + 5 real pytest tier1 tests), `stage_hidden_layer` (10 asserts + 2 real pytest tier1 tests), taskstore meta (de)serialization (10 asserts + 3 real pytest tier1 tests), and the selective-derive loop structure with stubbed `run_stage`/`canonicalize` (12 asserts). All six module files and all tier1 test files are `ruff check --config ruff.toml` clean.

**3. Type consistency.** `ExecAction` (from `recipe.model`) is the single action type; `HandlerContext`/`HandlerResult` are defined once in `handler.py` and consumed by `taskrun.py`. `StageMeta`/`TaskMeta`/`StoredTask` are defined once in `taskstore.py` and consumed by `taskbuild.py` (writes them) and `taskrun.py` (reads them). `StageChecks`/`DerivedChecks`/`Bundle` are the merged `taskcode` types (never redefined). `build_invocation(action, ctx, *, hp_work_host)` in Task 3 is called by `run_handler` with `hp_work_host=hp_dir/"work"`; `run_handler(runner, action, ctx, *, hp_dir)` in Task 3 is called by `TaskSession._fire`/`_accept` in Task 5 with `hp_dir=self.hp_dir`. `NspawnRunner.run(argv, *, binds, setenv)` (Task 1) is the signature `run_handler` (Task 3) depends on. Reuse call sites match the real signatures verified in-tree: `capture_candidate(rootfs, StageChecks, last_output)`, `grade_stage(checks, candidate, *, task_id, stage, student_id, nonce, ts, hooks=None)`, `run_stage(runner, TaskCode, stage_index)`, `canonicalize(list[Observation])`, `resolve_lowers((ref,), store)`, `store.get(ref).layer.parent`.

**Decisions beyond the design notes (recorded):**
- **Acceptance keyed on `check` then `observe`** (Task 4 `_acceptance_of`): `check` present → handler; else `observe` → derived; else `ValueError`. Refines the notes' "observe → derived else sentinel" and resolves the observe+check ambiguity (`check` wins).
- **`exclude` honored as an fnmatch GLOB in the derivation capture path** (Task 4, chosen option (a) of the caveat): derive on a `_no_exclude` task copy and curate observations with `_excluded` (whole-key or any path-segment glob). Consistent at runtime because `capture_candidate` re-derives its observe list from the surviving canonical keys — curating only during derivation suffices.
- **`task_id` for local keys = `checks.task_id`** (recipe name) for both handler and derived paths (Task 5), rather than the raw `ref`.
- **`FeedResult` defined locally** in `taskrun` with `hint=None` default (Task 5), mirroring `play.FeedResult`; the loop is `PlaySession`-free by design.
- **`TaskSession.__init__` derives `checks`/`progress`/`tries` from the `StoredTask`** (5 params, no `# noqa`).

**Risks / open questions for the tier3 e2e (for the implementer running `pytest -m tier3`):**
- **Derivation cost/time:** each observed stage prepares `passes` fresh nspawn runners (base rsync + overlay mount each). The e2e uses `passes=2` to keep it bounded; if flaky/slow, that is the knob. `build_task`'s default remains `passes=3`.
- **Empty-file observe similarity:** the e2e observes files with content (`echo done > /marker`, grep/wc outputs) to avoid the `similarity("","")` edge in `matches`; a bare `touch`-only observe was deliberately avoided.
- **Executable hidden scripts:** file handlers are exec'd directly by nspawn, so hidden scripts need `chmod +x` + a `#!/bin/sh` shebang (no `python3` in `debian:trixie-slim`). The e2e helpers set `0o755`; author tooling must preserve the mode when staging `recipe.hidden`.
- **`HP_ROOTFS="/"` in-container:** handlers see the student rootfs as `/` (same overlay `mnt`), so `verify.sh` checks `/done` directly. If a future host-side handler variant is wanted, `HP_ROOTFS` would need the host `student.rootfs` path instead — out of scope here.
