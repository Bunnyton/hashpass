# Task-Authoring DSL (Phase 2A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Phase-1 recipe language into the task-authoring DSL — indentation `stage` blocks (`solve`/`observe`/`exclude`/`neutral`/`check`/`on enter`/`on pass`) plus top-level `hidden`/`readme` — parsing into an extended `Recipe`, and project a task recipe onto the existing `TaskCode` derivation model.

**Architecture:** Three pure-logic units. `recipe/model.py` gains `ExecAction`, `StageSpec`, and three optional `Recipe` fields (`stages`/`hidden`/`readme`) — a recipe with no stages is still a plain Phase-1 image. `recipe/parse.py` becomes indentation-aware: top-level directives at column 0, stage sub-directives indented beneath a `stage` header, and a `solve:` block whose deeper-indented lines are verbatim commands. `recipe/taskbridge.py` projects a task `Recipe` onto `taskcode.model.TaskCode` (setup empty — the environment is baked into the image by `run`/`copy`), so the proven `derive_checks` engine consumes it unchanged in Phase 2B. Phase-3 interactivity directives (`voice`/`hint`/`say`/`show`/`settings`/`react`) are reserved with a clear error.

**Tech Stack:** Python 3.13, stdlib only. Consumes in-repo `hashpass.taskcode.model` (`TaskCode`, `StageCode`). No third-party deps.

**Spec:** `docs/superpowers/specs/2026-08-31-образы-задания-и-dsl-design.md` — §3 (DSL syntax: §3.0 explicit actions, §3.1 structure, §3.2 stage block), §9 phase 2 (the `stage`/`solve`/`observe`/`check` authoring surface), §10 (English keywords, indentation blocks, `exec` delegation, additive syntax).

## Global Constraints

- Python 3.13; stdlib + in-repo only; `encoding="utf-8"` on all file I/O.
- ruff `select=["ALL"]` clean under the repo `ruff.toml` (line-length 96; the project ignore-list already covers `ANN201`/`ANN001`, `D100`/`D102`/`D103`/`D104`, `T201`, `E501`, `S101`, etc.). Module-level constants for `PLR2004` magic values; keep functions ≤5 params (`PLR0913`/`PLR0917`); `# noqa: <code>` only where the repo already does.
- All of Phase 2A is **tier1** (pure logic, no containers): every test carries `@pytest.mark.tier1`.
- Match existing style in `recipe/model.py` and `recipe/parse.py`: frozen dataclasses, single-line docstrings, dispatch tables, `ValueError` with a clear message on malformed input.
- **Backward compatibility is a hard requirement:** every existing `tests/recipe/test_parse.py` case for a pure image must still pass unchanged, except the two reserved-directive cases updated in Task 2 (`stage` now parses; the reserved set moves to the Phase-3 interactivity directives).

---

### Task 1: Recipe model — `ExecAction`, `StageSpec`, task fields on `Recipe`, `is_task`

**Files:**
- Modify: `src/hashpass/recipe/model.py` (add types before `Recipe`; extend `Recipe`; add `is_task`)
- Test: `tests/recipe/test_model.py` (new)

**Interfaces:**
- Consumes: nothing new (stdlib `dataclasses`).
- Produces:
  - `ExecAction(value: str)` — frozen.
  - `StageSpec(message: str, solve: tuple[str, ...], observe=(), exclude=(), neutral=(), check: ExecAction | None = None, on_enter: tuple[ExecAction, ...] = (), on_pass: tuple[ExecAction, ...] = ())` — frozen.
  - `Recipe(name, version, parents, steps, stages: tuple[StageSpec, ...] = (), hidden: str | None = None, readme: str | None = None)` — frozen; first four fields unchanged and still positional.
  - `is_task(recipe: Recipe) -> bool` — True iff `recipe.stages` is non-empty.
  - `image_ref`, `CopyStep`, `RunStep` unchanged.

- [ ] **Step 1: Write the failing test** — `tests/recipe/test_model.py`

```python
import pytest

from hashpass.recipe.model import (
    CopyStep,
    ExecAction,
    Recipe,
    RunStep,
    StageSpec,
    image_ref,
    is_task,
)


@pytest.mark.tier1
def test_plain_image_is_not_a_task():
    r = Recipe("img", "1", (), (RunStep("echo hi"),))
    assert r.stages == ()
    assert r.hidden is None
    assert r.readme is None
    assert is_task(r) is False
    assert image_ref(r) == "img:1"


@pytest.mark.tier1
def test_stage_spec_defaults_and_task_recipe():
    stage = StageSpec(message="do it", solve=("grep x f > o",), observe=("o",))
    assert stage.exclude == ()
    assert stage.neutral == ()
    assert stage.check is None
    assert stage.on_enter == ()
    assert stage.on_pass == ()
    r = Recipe("t", "1", ("base",), (CopyStep("a/", "/b/"),), (stage,), hidden="grade/", readme="r.txt")
    assert is_task(r) is True
    assert r.stages[0].message == "do it"
    assert r.hidden == "grade/"


@pytest.mark.tier1
def test_exec_action_is_frozen_and_equatable():
    assert ExecAction("verify.sh") == ExecAction("verify.sh")
    with pytest.raises(AttributeError):
        ExecAction("x").value = "y"  # frozen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/recipe/test_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ExecAction'` (and `StageSpec`, `is_task`).

- [ ] **Step 3: Write minimal implementation** — edit `src/hashpass/recipe/model.py`

Insert `ExecAction` and `StageSpec` immediately **before** the `Recipe` class (both reference-free / referenced-by `Recipe`):

```python
@dataclass(frozen=True)
class ExecAction:
    """A delegated action: run `value` as a hidden-layer script or shell command (auto-detected at run time)."""

    value: str


@dataclass(frozen=True)
class StageSpec:
    """One `stage` block: reference solution, observed paths, and delegated hooks."""

    message: str
    solve: tuple[str, ...]
    observe: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    neutral: tuple[str, ...] = ()
    check: ExecAction | None = None
    on_enter: tuple[ExecAction, ...] = ()
    on_pass: tuple[ExecAction, ...] = ()
```

Extend the existing `Recipe` dataclass with three defaulted fields (keep the first four exactly as they are):

```python
@dataclass(frozen=True)
class Recipe:
    """A parsed image/task recipe: self-name/version, parents, ordered build steps, optional task logic."""

    name: str
    version: str
    parents: tuple[str, ...]
    steps: tuple[CopyStep | RunStep, ...]  # copy/run in SOURCE order
    stages: tuple[StageSpec, ...] = ()
    hidden: str | None = None
    readme: str | None = None
```

Add after `image_ref`:

```python
def is_task(recipe: Recipe) -> bool:
    """Return True if the recipe carries task logic (has at least one stage)."""
    return bool(recipe.stages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/recipe/test_model.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/recipe/model.py tests/recipe/test_model.py
git commit -m "feat(recipe): task model — ExecAction, StageSpec, Recipe.stages/hidden/readme, is_task"
```

---

### Task 2: Indentation-aware parser — stage blocks, `hidden`/`readme`, Phase-3 reservation

**Files:**
- Modify: `src/hashpass/recipe/parse.py` (rewrite the parse loop; keep top-level `image`/`from`/`copy`/`run` handlers)
- Modify: `tests/recipe/test_parse.py` (update the two reserved-directive cases; add task cases)

**Interfaces:**
- Consumes: `hashpass.recipe.model` — `CopyStep`, `ExecAction`, `Recipe`, `RunStep`, `StageSpec`.
- Produces: `parse_recipe(text: str) -> Recipe` and `load_recipe(path: Path) -> Recipe` (signatures unchanged) now also parse stage blocks + `hidden`/`readme`.

**Grammar (fixed):**
- A **significant line** = a line that is non-blank and not a full-line `#` comment; its indent = count of leading spaces after `expandtabs()`; its content = the `strip()`-ed text (inline `#` preserved verbatim).
- **Top-level** (indent 0): `image <name>[:<ver>]` (required, once), `from <ref>[, <ref> …]`, `copy <src> <dst>`, `run <command>`, `hidden <src>`, `readme <file>`, `stage "<message>"` (opens a block).
- **Stage body** (indent > 0, until the next indent-0 line): `solve <inline command>` OR `solve:` (block — every following line indented deeper than the `solve:` line is one verbatim command), `observe <path…>`, `exclude <pattern…>`, `neutral <cmd…>` (whitespace-split, accumulate across repeats), `check <action>`, `on enter <action>`, `on pass <action>`.
- An **action** is `exec <file-or-command>` → `ExecAction(<rest>)`. Any `say`/`show`/`voice`/… action → `ValueError` naming phase 3.
- **Reserved for Phase 3** anywhere: `voice`, `hint`, `say`, `show`, `settings`, `react` → `ValueError` naming phase 3. Any other unknown directive → `ValueError("unknown directive: …")`.
- A stage with no `solve` → `ValueError`. A significant line at indent > 0 with no open stage → `ValueError("unexpected indentation …")`.

- [ ] **Step 1: Write the failing tests** — replace the two reserved cases in `tests/recipe/test_parse.py` and add task cases. Keep the existing `test_parse_full_recipe`, `test_run_before_copy_keeps_source_order`, `test_missing_image_raises`, `test_unknown_directive_raises`, `test_load_recipe_from_disk` untouched.

Replace `test_reserved_stage_directive_raises` with:

```python
@pytest.mark.tier1
def test_reserved_phase3_voice_raises():
    with pytest.raises(ValueError, match="phase 3"):
        parse_recipe("image t:1\nvoice\n")
```

Add (import `ExecAction`, `StageSpec` at the top of the file alongside the existing model imports):

```python
_TASK = """\
image  log-archive:1
from   base, coreutils-lab
readme readme.txt
copy   assets/ /home/student/
run    mkdir -p /var/log/app
hidden grade/

stage "Collect ERROR lines into errors.txt"
  solve   grep -rh ERROR /var/log/app > errors.txt
  observe errors.txt
  exclude .cache *.log
  neutral ls cd cat pwd
  on enter exec seed.sh
  on pass  exec cheer.sh
  check    exec verify.sh
"""


@pytest.mark.tier1
def test_parse_task_recipe_full_stage():
    r = parse_recipe(_TASK)
    assert r.name == "log-archive"
    assert r.parents == ("base", "coreutils-lab")
    assert r.readme == "readme.txt"
    assert r.hidden == "grade/"
    assert r.steps == (CopyStep("assets/", "/home/student/"), RunStep("mkdir -p /var/log/app"))
    assert len(r.stages) == 1
    s = r.stages[0]
    assert s == StageSpec(
        message="Collect ERROR lines into errors.txt",
        solve=("grep -rh ERROR /var/log/app > errors.txt",),
        observe=("errors.txt",),
        exclude=(".cache", "*.log"),
        neutral=("ls", "cd", "cat", "pwd"),
        check=ExecAction("verify.sh"),
        on_enter=(ExecAction("seed.sh"),),
        on_pass=(ExecAction("cheer.sh"),),
    )


@pytest.mark.tier1
def test_parse_solve_block_and_multiple_stages():
    text = (
        "image pipe:1\n\n"
        'stage "one"\n'
        "  solve:\n"
        "    sort f > s\n"
        "    uniq s > u\n"
        "  observe u\n"
        "  on pass exec a.sh\n"
        "  on pass exec b.sh\n\n"
        'stage "two"\n'
        "  solve wc -l < u > n\n"
        "  observe n\n"
    )
    r = parse_recipe(text)
    assert len(r.stages) == 2
    assert r.stages[0].solve == ("sort f > s", "uniq s > u")
    assert r.stages[0].on_pass == (ExecAction("a.sh"), ExecAction("b.sh"))
    assert r.stages[1].solve == ("wc -l < u > n",)


@pytest.mark.tier1
def test_plain_image_recipe_has_no_stages():
    r = parse_recipe("image solo:2\nrun echo hi\n")
    assert r.stages == ()
    assert r.hidden is None


@pytest.mark.tier1
@pytest.mark.parametrize(
    ("text", "match"),
    [
        ('image t:1\nstage "x"\n  observe f\n', "no 'solve'"),
        ('image t:1\nstage "x"\n  solve echo hi\n  hint tries 3 say hi\n', "phase 3"),
        ('image t:1\nstage "x"\n  solve echo hi\n  on pass say "yo"\n', "phase 3"),
        ('image t:1\nstage "x"\n  solve echo hi\n  check verify.sh\n', "expected an 'exec"),
        ("image t:1\n  solve echo hi\n", "unexpected indentation"),
        ('image t:1\nstage "x"\n  solve:\n  observe f\n', "empty 'solve:' block"),
    ],
)
def test_task_parse_errors(text, match):
    with pytest.raises(ValueError, match=match):
        parse_recipe(text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/recipe/test_parse.py -v`
Expected: FAIL — the task cases raise `ValueError("directive 'stage' is reserved …")` / import errors, since the current parser reserves `stage`/`hidden`/`readme`.

- [ ] **Step 3: Write the implementation** — replace the body of `src/hashpass/recipe/parse.py` with:

```python
"""Line-based, indentation-aware parser for image/task recipes (Imagefile = Taskfile)."""
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.recipe.model import CopyStep, ExecAction, Recipe, RunStep, StageSpec

_RESERVED_PHASE3 = ("voice", "hint", "say", "show", "settings", "react")
_COPY_ARGC = 2
_DEFAULT_VERSION = "latest"
_EXEC_PREFIX = "exec "
_STAGE_EVENTS = ("enter", "pass")
_QUOTE_MIN = 2


@dataclass
class _Acc:
    """Mutable accumulator for top-level directives."""

    name: str | None = None
    version: str = _DEFAULT_VERSION
    parents: list[str] = field(default_factory=list)
    steps: list[CopyStep | RunStep] = field(default_factory=list)
    stages: list[StageSpec] = field(default_factory=list)
    hidden: str | None = None
    readme: str | None = None


@dataclass
class _StageAcc:
    """Mutable accumulator for one stage block."""

    message: str
    solve: list[str] = field(default_factory=list)
    observe: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)
    check: ExecAction | None = None
    on_enter: list[ExecAction] = field(default_factory=list)
    on_pass: list[ExecAction] = field(default_factory=list)


def _significant(text: str) -> list[tuple[int, str]]:
    """Return (indent, stripped-content) for each non-blank, non-comment line."""
    out: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        expanded = raw.expandtabs()
        indent = len(expanded) - len(expanded.lstrip(" "))
        out.append((indent, stripped))
    return out


def _kw_value(content: str) -> tuple[str, str]:
    parts = content.split(maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _unquote(value: str) -> str:
    if len(value) >= _QUOTE_MIN and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _parse_action(value: str) -> ExecAction:
    """Parse a `<verb> …` action value. Phase 2 supports only `exec <file-or-command>`."""
    if value.startswith(_EXEC_PREFIX):
        body = value[len(_EXEC_PREFIX):].strip()
        if not body:
            msg = "exec requires a file or command"
            raise ValueError(msg)
        return ExecAction(body)
    verb = value.split(maxsplit=1)[0] if value else ""
    if verb in _RESERVED_PHASE3:
        msg = f"action {verb!r} is reserved for a later phase (phase 3 interactivity)"
        raise ValueError(msg)
    msg = f"expected an 'exec …' action, got: {value!r}"
    raise ValueError(msg)


def _do_image(value: str, acc: _Acc) -> None:
    if acc.name is not None:
        msg = "duplicate 'image' directive"
        raise ValueError(msg)
    name, _, version = value.partition(":")
    acc.name = name
    acc.version = version or _DEFAULT_VERSION


def _do_from(value: str, acc: _Acc) -> None:
    acc.parents.extend(ref.strip() for ref in value.split(",") if ref.strip())


def _do_copy(value: str, acc: _Acc) -> None:
    fields = value.split()
    if len(fields) != _COPY_ARGC:
        msg = f"copy requires <src> <dst>: {value!r}"
        raise ValueError(msg)
    acc.steps.append(CopyStep(fields[0], fields[1]))


def _do_run(value: str, acc: _Acc) -> None:
    acc.steps.append(RunStep(value))


def _do_hidden(value: str, acc: _Acc) -> None:
    fields = value.split()
    if len(fields) != 1:
        msg = f"hidden requires a single <src> directory: {value!r}"
        raise ValueError(msg)
    acc.hidden = fields[0]


def _do_readme(value: str, acc: _Acc) -> None:
    fields = value.split()
    if len(fields) != 1:
        msg = f"readme requires a single <file>: {value!r}"
        raise ValueError(msg)
    acc.readme = fields[0]


_TOP_HANDLERS = {
    "image": _do_image,
    "from": _do_from,
    "copy": _do_copy,
    "run": _do_run,
    "hidden": _do_hidden,
    "readme": _do_readme,
}


def _reject(keyword: str) -> None:
    if keyword in _RESERVED_PHASE3:
        msg = f"directive {keyword!r} is reserved for a later phase (phase 3 interactivity)"
        raise ValueError(msg)
    msg = f"unknown directive: {keyword!r}"
    raise ValueError(msg)


def _consume_solve_block(lines: list[tuple[int, str]], start: int, base_indent: int,
                         sacc: _StageAcc) -> int:
    """Append every line indented deeper than `base_indent` as a verbatim command; return next index."""
    i = start
    while i < len(lines) and lines[i][0] > base_indent:
        sacc.solve.append(lines[i][1])
        i += 1
    if not sacc.solve:
        msg = "empty 'solve:' block"
        raise ValueError(msg)
    return i


def _apply_on(value: str, sacc: _StageAcc) -> None:
    """Apply an `on <event> <action>` stage directive."""
    event, _, action = value.partition(" ")
    if event not in _STAGE_EVENTS:
        msg = f"unknown stage event: {event!r} (expected enter/pass)"
        raise ValueError(msg)
    target = sacc.on_enter if event == "enter" else sacc.on_pass
    target.append(_parse_action(action.strip()))


def _apply_simple_directive(kw: str, value: str, sacc: _StageAcc) -> None:
    """Apply one single-line stage sub-directive (everything but the `solve:` block)."""
    if kw == "solve":
        if not value:
            msg = "solve requires an inline command or a 'solve:' block"
            raise ValueError(msg)
        sacc.solve.append(value)
    elif kw == "observe":
        sacc.observe.extend(value.split())
    elif kw == "exclude":
        sacc.exclude.extend(value.split())
    elif kw == "neutral":
        sacc.neutral.extend(value.split())
    elif kw == "check":
        sacc.check = _parse_action(value)
    elif kw == "on":
        _apply_on(value, sacc)
    else:
        _reject(kw)


def _finalize_stage(sacc: _StageAcc) -> StageSpec:
    if not sacc.solve:
        msg = f"stage {sacc.message!r} has no 'solve' reference solution"
        raise ValueError(msg)
    return StageSpec(
        message=sacc.message,
        solve=tuple(sacc.solve),
        observe=tuple(sacc.observe),
        exclude=tuple(sacc.exclude),
        neutral=tuple(sacc.neutral),
        check=sacc.check,
        on_enter=tuple(sacc.on_enter),
        on_pass=tuple(sacc.on_pass),
    )


def _parse_stage_block(header_value: str, lines: list[tuple[int, str]],
                       start: int) -> tuple[StageSpec, int]:
    """Parse a `stage` header + its indented body; return (StageSpec, next-top-index)."""
    if not header_value:
        msg = "stage requires a message"
        raise ValueError(msg)
    sacc = _StageAcc(message=_unquote(header_value))
    i = start
    while i < len(lines) and lines[i][0] > 0:
        indent, content = lines[i]
        kw, value = _kw_value(content)
        if kw == "solve:":
            i = _consume_solve_block(lines, i + 1, indent, sacc)
        else:
            _apply_simple_directive(kw, value, sacc)
            i += 1
    return _finalize_stage(sacc), i


def parse_recipe(text: str) -> Recipe:
    """
    Parse Imagefile/Taskfile text into a Recipe (image directives + optional stage blocks).

    Top-level (column 0): `image <name>:<ver>` (required, once), `from`, `copy`, `run`,
    `hidden <src>`, `readme <file>`, and `stage "<message>"` (opens an indented block of
    `solve`/`observe`/`exclude`/`neutral`/`check`/`on enter`/`on pass`). A `solve:` line
    opens a verbatim command block (deeper-indented lines). Blank and full-line `#` lines
    are ignored; inline `#` is preserved. Phase-3 interactivity directives
    (voice/hint/say/show/settings/react) and unknown directives raise ValueError.

    Raises:
        ValueError: missing/duplicate `image`, malformed directive, a stage without
            `solve`, an unexpected indent, or a reserved/unknown directive.

    """
    acc = _Acc()
    lines = _significant(text)
    i = 0
    while i < len(lines):
        indent, content = lines[i]
        if indent != 0:
            msg = f"unexpected indentation (no open stage): {content!r}"
            raise ValueError(msg)
        kw, value = _kw_value(content)
        if kw == "stage":
            stage, i = _parse_stage_block(value, lines, i + 1)
            acc.stages.append(stage)
            continue
        handler = _TOP_HANDLERS.get(kw)
        if handler is None:
            _reject(kw)
        handler(value, acc)
        i += 1
    if not acc.name:
        msg = "recipe is missing a required 'image <name>:<ver>' directive"
        raise ValueError(msg)
    return Recipe(acc.name, acc.version, tuple(acc.parents), tuple(acc.steps),
                  tuple(acc.stages), acc.hidden, acc.readme)


def load_recipe(path: Path) -> Recipe:
    """Read an Imagefile/Taskfile from disk and parse it (see `parse_recipe`)."""
    return parse_recipe(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/recipe/test_parse.py -v`
Expected: PASS — all existing pure-image cases + the new task cases. `ruff check --config ruff.toml src/hashpass/recipe/parse.py tests/recipe/test_parse.py` clean.

Note for the implementer: `_reject` always raises, so after `if handler is None: _reject(kw)` ruff may flag `handler` as possibly-None on the next line. It is not — `_reject` is `NoReturn`-in-effect — but if ruff complains, keep the current shape (the existing Phase-1 parser used the identical `if handler is None: _reject(...)` / `else: handler(...)` pattern); if lint requires it, mirror Phase-1 exactly by putting the `handler(value, acc)` call in an `else:` branch.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/recipe/parse.py tests/recipe/test_parse.py
git commit -m "feat(recipe): indentation-aware parser — stage blocks, hidden/readme, phase-3 reservation"
```

---

### Task 3: `taskbridge.recipe_to_taskcode` — project a task Recipe onto the derivation model

**Files:**
- Create: `src/hashpass/recipe/taskbridge.py`
- Test: `tests/recipe/test_taskbridge.py` (new)

**Interfaces:**
- Consumes: `hashpass.recipe.model` (`Recipe`, `StageSpec`), `hashpass.taskcode.model` (`TaskCode`, `StageCode`).
- Produces: `recipe_to_taskcode(recipe: Recipe) -> TaskCode` — `id=recipe.name`, `setup=()` (environment is baked into the image by `run`/`copy`), one `StageCode(commands=stage.solve, observe=stage.observe, exclude=stage.exclude, message=stage.message)` per stage in source order. Raises `ValueError` if the recipe has no stages.

**Why setup is empty:** in Phase 2B, derivation runs the `solve` commands on the built image's mounted overlay chain, which already carries the `run`/`copy` environment. `run_stage` (execute.py) still replays prior stages' `commands` as prep, so multi-stage ordering is preserved. The `neutral`/`check`/`on_enter`/`on_pass`/`hidden`/`readme` extras stay on the `Recipe` (consumed directly by the 2B runtime); `TaskCode` intentionally holds only what `derive_checks` needs.

- [ ] **Step 1: Write the failing test** — `tests/recipe/test_taskbridge.py`

```python
import pytest

from hashpass.recipe.parse import parse_recipe
from hashpass.recipe.taskbridge import recipe_to_taskcode
from hashpass.taskcode.model import StageCode, TaskCode


@pytest.mark.tier1
def test_recipe_to_taskcode_projects_stages():
    text = (
        "image pipe:1\n"
        "run seed the env\n"
        'stage "one"\n'
        "  solve sort f > s\n"
        "  observe s\n"
        "  exclude .cache\n"
        'stage "two"\n'
        "  solve:\n"
        "    uniq s > u\n"
        "    wc -l < u > n\n"
        "  observe n\n"
    )
    task = recipe_to_taskcode(parse_recipe(text))
    assert task == TaskCode(
        id="pipe",
        setup=(),
        stages=(
            StageCode(commands=("sort f > s",), observe=("s",), exclude=(".cache",), message="one"),
            StageCode(commands=("uniq s > u", "wc -l < u > n"), observe=("n",), exclude=(), message="two"),
        ),
    )


@pytest.mark.tier1
def test_recipe_to_taskcode_rejects_plain_image():
    with pytest.raises(ValueError, match="no stages"):
        recipe_to_taskcode(parse_recipe("image solo:1\nrun echo hi\n"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/recipe/test_taskbridge.py -v`
Expected: FAIL — `ModuleNotFoundError: hashpass.recipe.taskbridge`.

- [ ] **Step 3: Write the implementation** — `src/hashpass/recipe/taskbridge.py`

```python
"""Bridge a parsed task Recipe onto the taskcode derivation model (TaskCode)."""
from hashpass.recipe.model import Recipe
from hashpass.taskcode.model import StageCode, TaskCode


def recipe_to_taskcode(recipe: Recipe) -> TaskCode:
    """
    Project a task Recipe onto TaskCode for derivation.

    `setup` is empty: the `run`/`copy` environment is baked into the image the task is
    built on, so `solve` commands run against that image directly. Each stage's `solve`
    becomes `StageCode.commands` in source order.

    Raises:
        ValueError: if the recipe declares no stages (it is a plain image, not a task).

    """
    if not recipe.stages:
        msg = f"recipe {recipe.name!r} has no stages; not a task"
        raise ValueError(msg)
    return TaskCode(
        id=recipe.name,
        setup=(),
        stages=tuple(
            StageCode(
                commands=s.solve,
                observe=s.observe,
                exclude=s.exclude,
                message=s.message,
            )
            for s in recipe.stages
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/recipe/test_taskbridge.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/recipe/taskbridge.py tests/recipe/test_taskbridge.py
git commit -m "feat(recipe): recipe_to_taskcode bridge onto the derivation model"
```

---

## Self-Review

**Spec coverage (§3, §9-phase2 authoring surface):**
- §3.1 structure — `image`/`from`/`copy`/`run` (Phase 1, unchanged) + `hidden`/`readme` (Task 2) + `stage` block (Task 2). ✓
- §3.2 stage block — `stage "message"`, `solve` (inline + `solve:` block), `observe`, `exclude`, `neutral`, `check`, `on enter`/`on pass` (Task 2). ✓
- §3.0 explicit actions — `exec <value>` parsed to `ExecAction`; auto-detect (file vs command) is a **run-time** concern deferred to 2B (the model stores the raw value); `say`/`show` reserved (Task 2). ✓
- §3.3 acceptance basis — `solve`+`observe` projected to `TaskCode` for the existing `derive_checks` engine (Task 3). ✓
- §10 — English keywords, indentation blocks, additive syntax (a new verb/event is a localized parser edit), Phase-3 directives reserved. ✓
- **Out of scope (correctly deferred):** run-time `exec` auto-detect, `/hp` hidden layer, `HP_*` contract, derivation-on-image-chain, `build_task`/`run_task` — all Phase 2B. Interactivity (typewriter, conditional hints, `voice`, `settings`) — Phase 3.

**Placeholder scan:** none — every step has complete code (validated in a standalone prototype: 28 assertions pass, ruff-clean on the logic).

**Type consistency:** `ExecAction`/`StageSpec` defined in Task 1, imported by Task 2's parser and returned in `Recipe.stages`; `recipe_to_taskcode` (Task 3) consumes `Recipe.stages: tuple[StageSpec, …]` and maps to `StageCode(commands, observe, exclude, message)` — matching `taskcode.model.StageCode`'s real fields (confirmed: `commands`, `observe`, `exclude=()`, `message=""`). `Recipe`'s first four fields stay positional so Phase-1 construction (`Recipe(name, version, parents, steps)`) and the existing tests are unaffected.

**Deviations from spec (recorded):**
- `hidden <src>` takes a **single** source directory (staged to the fixed `/hp/work` in 2B), not the spec's 2-token `hidden .work grade/`. The `/hp` internal layout (bin/task/work/state.json, §4.1) is fixed by the system, so the author only controls the `work` contents; a single source dir is the faithful, simpler surface. If sub-structure is ever needed it is additive.
- The spec's full stage example (§3.2) includes `hint`/`on pass say`/`show file` — those are Phase 3 and are **reserved** here; Phase-2A recipes use `exec` actions only.
