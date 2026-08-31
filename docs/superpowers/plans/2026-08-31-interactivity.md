# Interactivity (Phase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a parsed task `Recipe` (Phase 2A) + its runtime (Phase 2B) into an *interactive* task: unreserve and parse the six interactivity directives (`hint`/`say`/`show`/`voice`/`settings`/`react`), match explicit hint conditions over the live `TaskSession` context, and render every system reply through a new typewriter layer — wired into `run_task`/`TaskSession` so a DSL-authored hint fires and is shown to the student.

**Architecture:** Six units on top of merged Phase-1/2A/2B code. (1) `recipe/model.py` gains the action/condition/rule/voice/settings dataclasses and *widens* `StageSpec.on_enter/on_pass` to carry `say`/`show`/`exec` (2B parsed only `exec`) plus a defaulted `StageSpec.hints`; `Recipe` gains defaulted `voice`/`settings`/`react`. (2) `recipe/parse.py` unreserves the six directives and parses `hint <cond> <action>`, `say`/`show file` actions, `on enter|pass` say/show, and the `voice`/`settings` blocks + `react` line. (3) `hints.py` gains `match_rule` — a NEW first-match matcher over the explicit atoms (`tries`/`idle`/`cmd`/`output`), a sibling to the legacy Plan-F `match_hint`. (4) `render.py` (new) is the typewriter: a `Renderer` with an injected `sink` and `sleep` so tests capture chunks and assert pacing without real sleeping. (5) `taskstore.py` serializes the richer meta (actions/hints/voice/settings/react) and `taskbuild._build_meta` carries them through. (6) `taskrun.py` owns a `Renderer`, tracks idle time, evaluates `match_rule` after each `feed`, renders the fired action, fills `FeedResult.hint`, and fires `voice hello`/`bye` + `react`.

**Design decisions baked in (from the drafting brief, do NOT re-litigate):**
- **The matcher + render live explicitly in `TaskSession` + a `Renderer`, NOT routed through `HookRegistry`.** §7 frames voice/hint/react as sugar over the hook engine, but for Phase 3 an explicit `match_rule` call + a `Renderer` is materially simpler than registering/dispatching handlers, and it is the code that actually needs to exist. `HookRegistry` is left untouched. (Brief reuse note; recorded here as the chosen path.)
- **Conditions evaluate over the 2B `TaskSession` context, not Plan-F `StuckState`:** `tries` = the neutral-excluded `tries[stage]`; `idle` = seconds since last progress (Phase 3 adds idle tracking to `TaskSession` from the `ts` passed to `feed`, exactly as Plan-F derived `_elapsed_seconds`); `cmd` over `hashpass.cmd.Cmd`; `output` substring over the last output. First-match-wins in source order.
- **`on fail` stays deferred** (§7): `_STAGE_EVENTS` remains `("enter", "pass")`, so `on fail …` still raises a clear "unknown stage event". Adding it later is an additive parser edit (§3.0).
- **Phase-3 hints live in `task-meta.json` (`StageMeta.hints`), not the bundle.** `build_task` keeps writing `Bundle(..., hints={})`; the bundle's `hints`/`conditions` are the OLD Plan-F dict format and stay empty.

**Tech Stack:** Python 3.13, stdlib + in-repo only. Consumes merged `hashpass.cmd`, `hashpass.handler`, `hashpass.hints`, `hashpass.progress`, `hashpass.grade`, `hashpass.play`, `hashpass.key`, `hashpass.recipe.*`, `hashpass.taskcode.*`, `hashpass.runner.nspawn`, `hashpass.imagestore.*`, `hashpass.image.base`. No third-party deps. Real containers via `systemd-nspawn` for the single tier3 e2e.

**Spec:** `docs/superpowers/specs/2026-08-31-образы-задания-и-dsl-design.md` — §7 (interactivity: event→handler over `HookRegistry`; §7.1 explicit hint conditions with no bare `stuck`; §7.2 live typewriter render with `type-mode`/`type-speed`/pager and `voice`), §3.0 (explicit `say`/`show file`/`exec` actions), §6 (`HP_*` handler contract, reused for `exec`), §10 (fixed decisions: English keywords, indentation blocks, `instant`/`normal`/`dramatic` + `type-speed` + pager, additive syntax).

## Global Constraints

- Python 3.13; stdlib + in-repo only; `encoding="utf-8"` on all file I/O.
- ruff `select=["ALL"]` clean under the repo `ruff.toml` (line-length 96; the project ignore-list already covers `ANN201`/`ANN001`, `D100`/`D102`/`D103`/`D104`, `COM812`, `T201`, `E501`, `S101`, `S603`/`S607`, `UP012`, the Cyrillic `RUF001-003`, etc.). Module-level constants for `PLR2004` magic values; keep functions ≤5 params — the two 6+-param public entrypoints (`TaskSession.__init__`, `run_task`) carry `# noqa: PLR0913` exactly as the repo already does on `grade.grade_stage`/`taskcode.derive.derive_checks`. Frozen-dataclass defaults that call a constructor use `field(default_factory=…)` (avoids `RUF009`). Multi-line docstrings put the summary on the second line (blank first line), matching `build.build`/`NspawnRunner.prepare`; single-line docstrings elsewhere.
- **Tiers.** Tasks 1–5 and the pure helpers of Task 6 are **tier1** (pure logic, no containers): `@pytest.mark.tier1`, run in the default `pytest` selection. The single end-to-end wiring test is **tier3**: `@pytest.mark.tier3`, uses the session-scoped `base_tar` fixture (`tests/conftest.py`), needs scoped sudo, and is excluded by the default `addopts = "-m 'not tier3'"`. Run tier3 with `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/test_taskrun.py -m tier3 -v`. **Planning cannot run tier3** (no containers) — the tier3 code in this plan is complete + ruff-clean; the implementer validates it by running `pytest -m tier3`.
- **Reuse, do not reinvent.** `exec` actions run through the existing `handler.run_handler` (§6 `HP_*` contract) — no new delegation path. `cmd` conditions use `hashpass.cmd.Cmd` (`.basecmd`/`.has_flag`). Acceptance (`capture_candidate`/`grade_stage`), overlay/nspawn (`runner.nspawn`), progress (`progress`), and the bundle format are all unchanged.
- **Back-compat is a hard requirement.** Pure-image and Phase-2 recipes parse **identically** (verified: the 2A full-stage `StageSpec` and a plain image compare equal, with `hints`/`voice`/`settings`/`react` defaulting). `StageSpec`/`Recipe` gain only DEFAULTED fields (positional construction of the first four `Recipe` fields is unchanged). Two existing tests change because the features they guarded now ship — called out inline: **(a)** `tests/recipe/test_parse.py` — the reserved-`voice` case and the two `"phase 3"` rows now parse (Task 2); **(b)** `tests/test_taskstore.py` — `StageMeta.on_enter/on_pass` now carry `Action` objects, so its `_meta()` helper wraps `ExecAction(...)` (Task 5). Everything else stays green.

---

### Task 1: Model — actions, conditions, `HintRule`, `Voice`/`Settings`; widen `StageSpec`, extend `Recipe`

**Files:**
- Modify: `src/hashpass/recipe/model.py` (add types before `StageSpec`; widen `StageSpec.on_enter/on_pass` + add `hints`; add three defaulted `Recipe` fields)
- Modify: `tests/recipe/test_model.py` (add Phase-3 cases; existing 2A cases untouched)

**Interfaces:**
- Consumes: nothing new (stdlib `dataclasses`).
- Produces:
  - `SayAction(text: str, dramatic: bool = False)`, `ShowFileAction(path: str)` — frozen; `ExecAction` unchanged.
  - `Action = ExecAction | SayAction | ShowFileAction` (type alias).
  - `TriesCond(n: int)`, `IdleCond(seconds: float)`, `CmdCond(base: str, has=(), missing=())`, `OutputCond(substr: str)` — frozen; `Condition` alias.
  - `HintRule(condition: Condition, action: Action)` — frozen.
  - `Voice(hello: tuple[Action,...] = (), bye: tuple[Action,...] = ())`, `Settings(type_mode="normal", type_speed=45, pager=False)` — frozen.
  - `StageSpec` — `on_enter`/`on_pass` widened to `tuple[Action, ...]`; new `hints: tuple[HintRule, ...] = ()` (defaulted, positional order preserved).
  - `Recipe` — new defaulted `voice: Voice = field(default_factory=Voice)`, `settings: Settings = field(default_factory=Settings)`, `react: tuple[Action, ...] = ()`; first four fields still positional.
  - `image_ref`, `is_task`, `CopyStep`, `RunStep` unchanged.

- [ ] **Step 1: Write the failing tests** — add to `tests/recipe/test_model.py` (merge imports with the file's existing model imports):

```python
"""Validate Phase 3 model additions."""
import pytest

from hashpass.recipe.model import (
    CmdCond,
    ExecAction,
    HintRule,
    Recipe,
    RunStep,
    SayAction,
    Settings,
    ShowFileAction,
    StageSpec,
    TriesCond,
    Voice,
    is_task,
)


@pytest.mark.tier1
def test_recipe_interactivity_defaults():
    r = Recipe("img", "1", (), (RunStep("echo hi"),))
    assert r.voice == Voice()
    assert r.settings == Settings()
    assert r.react == ()
    assert is_task(r) is False


@pytest.mark.tier1
def test_actions_and_conditions_frozen_equatable():
    assert SayAction("hi") == SayAction("hi", dramatic=False)
    assert SayAction("hi", dramatic=True) != SayAction("hi")
    assert ShowFileAction("a.txt") == ShowFileAction("a.txt")
    assert CmdCond("grep", ("-i",), ()) == CmdCond("grep", ("-i",), ())
    with pytest.raises(AttributeError):
        SayAction("x").text = "y"


@pytest.mark.tier1
def test_stage_spec_hints_default_and_actions_widened():
    s = StageSpec(message="m", solve=("x",), on_pass=(SayAction("yo"),),
                  hints=(HintRule(TriesCond(3), ExecAction("h.sh")),))
    assert s.hints[0].condition == TriesCond(3)
    assert s.on_pass == (SayAction("yo"),)
    assert StageSpec(message="m", solve=("x",)).hints == ()


@pytest.mark.tier1
def test_settings_defaults():
    assert Settings().type_mode == "normal"
    assert Settings().type_speed == 45  # noqa: PLR2004
    assert Settings().pager is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/recipe/test_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'SayAction'` (and the other new names).

- [ ] **Step 3: Write the implementation** — replace the body of `src/hashpass/recipe/model.py` with:

```python
"""Image/task recipe model: parsed Imagefile/Taskfile as frozen dataclasses."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CopyStep:
    """A `copy <src> <dst>` build step: host source and in-image destination."""

    src: str
    dst: str


@dataclass(frozen=True)
class RunStep:
    """A `run <command>` build step."""

    cmd: str


@dataclass(frozen=True)
class ExecAction:
    """An `exec <file-or-command>` action: run a hidden-layer script or shell command (§6)."""

    value: str


@dataclass(frozen=True)
class SayAction:
    """A `say [dramatic] "<text>"` action: render literal text (optionally with dramatic pacing)."""

    text: str
    dramatic: bool = False


@dataclass(frozen=True)
class ShowFileAction:
    """A `show file <path>` action: render a file's contents (large -> pager)."""

    path: str


Action = ExecAction | SayAction | ShowFileAction


@dataclass(frozen=True)
class TriesCond:
    """`tries N`: fires after N real (neutral-excluded) attempts on the stage."""

    n: int


@dataclass(frozen=True)
class IdleCond:
    """`idle N`: fires after N seconds without progress."""

    seconds: float


@dataclass(frozen=True)
class CmdCond:
    """`cmd <base> [has <f...>] [missing <f...>]`: fires on a matching student command."""

    base: str
    has: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutputCond:
    """`output "<substr>"`: fires when the last output contained the substring."""

    substr: str


Condition = TriesCond | IdleCond | CmdCond | OutputCond


@dataclass(frozen=True)
class HintRule:
    """One `hint <condition> <action>` rule (first-match-wins in source order, §7.1)."""

    condition: Condition
    action: Action


@dataclass(frozen=True)
class Voice:
    """Session voice: `hello` actions fired on first enter, `bye` actions on all-passed (§7.2)."""

    hello: tuple[Action, ...] = ()
    bye: tuple[Action, ...] = ()


@dataclass(frozen=True)
class Settings:
    """Render settings (§7.2): `type-mode`, `type-speed` chars/sec, `pager` for large `show file`."""

    type_mode: str = "normal"
    type_speed: int = 45
    pager: bool = False


@dataclass(frozen=True)
class StageSpec:
    """One `stage` block: reference solution, observed paths, delegated hooks, hint rules."""

    message: str
    solve: tuple[str, ...]
    observe: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    neutral: tuple[str, ...] = ()
    check: ExecAction | None = None
    on_enter: tuple[Action, ...] = ()
    on_pass: tuple[Action, ...] = ()
    hints: tuple[HintRule, ...] = ()


@dataclass(frozen=True)
class Recipe:
    """A parsed image/task recipe: self-name/version, parents, build steps, optional task logic."""

    name: str
    version: str
    parents: tuple[str, ...]
    steps: tuple[CopyStep | RunStep, ...]  # copy/run in SOURCE order
    stages: tuple[StageSpec, ...] = ()
    hidden: str | None = None
    readme: str | None = None
    voice: Voice = field(default_factory=Voice)
    settings: Settings = field(default_factory=Settings)
    react: tuple[Action, ...] = ()


def image_ref(r: Recipe) -> str:
    """Return the recipe's self-reference `name:version`."""
    return f"{r.name}:{r.version}"


def is_task(recipe: Recipe) -> bool:
    """Return True if the recipe carries task logic (has at least one stage)."""
    return bool(recipe.stages)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/recipe/test_model.py -v` — PASS. `ruff check --config ruff.toml src/hashpass/recipe/model.py` — clean.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/recipe/model.py tests/recipe/test_model.py
git commit -m "feat(recipe): phase-3 model — say/show actions, hint conditions, HintRule, Voice/Settings"
```

---

### Task 2: Parser — unreserve + parse `hint`/`say`/`show`/`voice`/`settings`/`react`

**Files:**
- Modify: `src/hashpass/recipe/parse.py` (drop `_RESERVED_PHASE3`; extend `_parse_action`; add condition/hint parsing, the `voice`/`settings` block parsers, `react`)
- Modify: `tests/recipe/test_parse.py` (**flip** the three cases the unreserving retires; add Phase-3 cases)

**Interfaces:**
- Consumes: `hashpass.recipe.model` — the new `Action`/`Condition`/`HintRule`/`Voice`/`Settings` types.
- Produces: `parse_recipe(text) -> Recipe` / `load_recipe(path) -> Recipe` (signatures unchanged) now parse the six interactivity directives. `_parse_action(value) -> Action` handles `exec`/`say [dramatic] "…"`/`show file <path>`. `check` stays `exec`-only (a verb check, not an isinstance guard — avoids `TRY004`). `voice`/`settings` are indented blocks (dispatched via `_BLOCK_PARSERS`, like `stage`); `react on command <action>` is a top-level line (`_TOP_HANDLERS`).

**Grammar added (fixed):**
- **Action** (`§3.0`): `exec <file-or-command>` → `ExecAction`; `say [dramatic] "<text>"` → `SayAction` (unquoted; `dramatic` marks slow/paused); `show file <path>` → `ShowFileAction`. Anything else → `ValueError("expected an 'exec'/'say'/'show file' action…")` (still contains `expected an 'exec`, so the existing `check verify.sh` case keeps matching).
- **Hint** (`§7.1`): `hint <condition> <action>`. Condition atoms: `tries <int>`, `idle <int>`, `cmd <base> [has <f…>] [missing <f…>]` (flags carry their dashes; scan stops at the action verb), `output "<substr>"` (quoted — tolerates spaces and verb-like words). `_parse_condition` returns `(Condition, remaining-action-text)`; `_parse_hint` then parses the action.
- **Stage `on enter|pass`** now accept `say`/`show` as well as `exec` (via the shared `_parse_action`).
- **Top-level blocks:** `settings` (`type-mode ∈ {instant,normal,dramatic}`, `type-speed <int>`, `pager on|off`; duplicate block → error) and `voice` (`hello`/`bye <action>` lines). **Top-level line:** `react on command <action>` (accumulates).
- **`on fail` stays deferred** — still `ValueError("unknown stage event")`.

- [ ] **Step 1: Update the retired cases, then write the new tests** — in `tests/recipe/test_parse.py`:
  1. **Delete** `test_reserved_phase3_voice_raises` (the `voice` directive now parses).
  2. In `test_task_parse_errors`, **delete** the two rows whose `match` is `"phase 3"` (`hint tries 3 …` and `on pass say …` — both now parse; they are re-covered as positive cases below).
  3. Add the following (merge imports with the file's existing model imports):

```python
"""Validate Phase 3 parser: hints, say/show actions, voice/settings/react, back-compat."""
import pytest

from hashpass.recipe.model import (
    CmdCond,
    ExecAction,
    IdleCond,
    OutputCond,
    Recipe,
    SayAction,
    Settings,
    ShowFileAction,
    TriesCond,
    Voice,
)
from hashpass.recipe.parse import parse_recipe


@pytest.mark.tier1
def test_hint_conditions_and_actions():
    text = (
        'image t:1\nstage "x"\n  solve echo hi\n'
        '  hint tries 5 say "look in /var/log 👀"\n'
        '  hint cmd grep missing -i say "add -i"\n'
        "  hint idle 90 exec idle.sh\n"
        '  hint output "ERROR" show file art/hit.txt\n'
    )
    hints = parse_recipe(text).stages[0].hints
    assert hints[0].condition == TriesCond(5)
    assert hints[0].action == SayAction("look in /var/log 👀")
    assert hints[1].condition == CmdCond("grep", (), ("-i",))
    assert hints[1].action == SayAction("add -i")
    assert hints[2].condition == IdleCond(90.0)
    assert hints[2].action == ExecAction("idle.sh")
    assert hints[3].condition == OutputCond("ERROR")
    assert hints[3].action == ShowFileAction("art/hit.txt")


@pytest.mark.tier1
def test_cmd_condition_has_and_missing():
    text = ('image t:1\nstage "x"\n  solve echo hi\n'
            "  hint cmd grep has -r missing -i exec f.sh\n")
    cond = parse_recipe(text).stages[0].hints[0].condition
    assert cond == CmdCond("grep", ("-r",), ("-i",))


@pytest.mark.tier1
def test_on_enter_pass_say_show_and_dramatic():
    text = (
        'image t:1\nstage "x"\n  solve echo hi\n'
        "  on enter exec seed.sh\n"
        '  on pass say "first!"\n'
        '  on pass say dramatic "the end."\n'
        "  on pass show file art/ok.txt\n"
    )
    s = parse_recipe(text).stages[0]
    assert s.on_enter == (ExecAction("seed.sh"),)
    assert s.on_pass == (SayAction("first!"), SayAction("the end.", dramatic=True),
                         ShowFileAction("art/ok.txt"))


@pytest.mark.tier1
def test_voice_settings_react_top_level():
    text = (
        "image t:1\n"
        "settings\n"
        "  type-mode dramatic\n"
        "  type-speed 60\n"
        "  pager on\n"
        "voice\n"
        '  hello say "yo"\n'
        "  hello exec greet.sh\n"
        '  bye say "gg"\n'
        "react on command exec watch.sh\n"
        'stage "x"\n  solve echo hi\n'
    )
    r = parse_recipe(text)
    assert r.settings == Settings(type_mode="dramatic", type_speed=60, pager=True)
    assert r.voice == Voice(hello=(SayAction("yo"), ExecAction("greet.sh")), bye=(SayAction("gg"),))
    assert r.react == (ExecAction("watch.sh"),)


@pytest.mark.tier1
def test_backcompat_pure_image_unchanged():
    r = parse_recipe("image solo:2\nrun echo hi\n")
    assert r == Recipe("solo", "2", (), (r.steps[0],))
    assert r.voice == Voice()
    assert r.settings == Settings()
    assert r.react == ()


@pytest.mark.tier1
def test_backcompat_flipped_reserved_cases_now_parse():
    # was: parse_recipe("image t:1\nvoice\n") raised "phase 3"
    r = parse_recipe('image t:1\nvoice\n  hello say "hi"\n')
    assert r.voice.hello == (SayAction("hi"),)
    # was: 'hint tries 3 say hi' raised "phase 3"
    r1 = parse_recipe('image t:1\nstage "x"\n  solve echo hi\n  hint tries 3 say "hi"\n')
    assert r1.stages[0].hints[0].condition == TriesCond(3)
    # was: 'on pass say "yo"' raised "phase 3"
    r2 = parse_recipe('image t:1\nstage "x"\n  solve echo hi\n  on pass say "yo"\n')
    assert r2.stages[0].on_pass == (SayAction("yo"),)


@pytest.mark.tier1
@pytest.mark.parametrize(
    ("text", "match"),
    [
        ('image t:1\nstage "x"\n  solve echo hi\n  hint bogus 3 say "hi"\n', "unknown hint condition"),
        ('image t:1\nstage "x"\n  solve echo hi\n  hint tries 3\n', "requires an action"),
        ('image t:1\nstage "x"\n  solve echo hi\n  hint tries x say "h"\n', "needs an integer"),
        ('image t:1\nstage "x"\n  solve echo hi\n  hint output "ERR\n', "unterminated"),
        ('image t:1\nstage "x"\n  solve echo hi\n  check say "no"\n', "requires an 'exec"),
        ('image t:1\nstage "x"\n  solve echo hi\n  on pass show art.txt\n', "show file"),
        ("image t:1\nsettings\n  type-mode turbo\n", "type-mode must be"),
        ("image t:1\nsettings\n  pager on\nsettings\n  pager off\n", "duplicate 'settings'"),
        ('image t:1\nvoice\n  yo say "hi"\n', "unknown voice directive"),
        ("image t:1\nreact do exec f.sh\n", "react must be"),
        ('image t:1\nstage "x"\n  solve echo hi\n  say "loose"\n', "unknown directive"),
    ],
)
def test_parse_errors(text, match):
    with pytest.raises(ValueError, match=match):
        parse_recipe(text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/recipe/test_parse.py -v`
Expected: FAIL — the new task cases raise (e.g.) `ValueError("… reserved for a later phase")` from the current `_RESERVED_PHASE3`, or `AttributeError` on the not-yet-existing `Recipe.voice`.

- [ ] **Step 3: Write the implementation** — replace the body of `src/hashpass/recipe/parse.py` with:

```python
"""Line-based, indentation-aware parser for image/task recipes (Imagefile = Taskfile)."""
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.recipe.model import (
    Action,
    CmdCond,
    Condition,
    CopyStep,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    Recipe,
    RunStep,
    SayAction,
    Settings,
    ShowFileAction,
    StageSpec,
    TriesCond,
    Voice,
)

_COPY_ARGC = 2
_DEFAULT_VERSION = "latest"
_STAGE_EVENTS = ("enter", "pass")
_QUOTE_MIN = 2
_ACTION_VERBS = ("exec", "say", "show")
_TYPE_MODES = ("instant", "normal", "dramatic")


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
    hello: list[Action] = field(default_factory=list)
    bye: list[Action] = field(default_factory=list)
    react: list[Action] = field(default_factory=list)
    settings: Settings | None = None


@dataclass
class _StageAcc:
    """Mutable accumulator for one stage block."""

    message: str
    solve: list[str] = field(default_factory=list)
    observe: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    neutral: list[str] = field(default_factory=list)
    check: ExecAction | None = None
    on_enter: list[Action] = field(default_factory=list)
    on_pass: list[Action] = field(default_factory=list)
    hints: list[HintRule] = field(default_factory=list)


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


def _parse_say(rest: str) -> SayAction:
    """Parse a `say [dramatic] "<text>"` action body (`dramatic` marks a slow, paused reply)."""
    dramatic = False
    head, _, tail = rest.partition(" ")
    if head == "dramatic":
        if not tail.strip():
            msg = "say dramatic requires text"
            raise ValueError(msg)
        dramatic = True
        rest = tail.strip()
    if not rest:
        msg = "say requires text"
        raise ValueError(msg)
    return SayAction(text=_unquote(rest), dramatic=dramatic)


def _parse_exec(rest: str) -> ExecAction:
    """Parse the body of an `exec <file-or-command>` action."""
    if not rest:
        msg = "exec requires a file or command"
        raise ValueError(msg)
    return ExecAction(rest)


def _parse_action(value: str) -> Action:
    """Parse an action value into ExecAction/SayAction/ShowFileAction (explicit verbs, §3.0)."""
    verb, _, rest = value.partition(" ")
    rest = rest.strip()
    if verb == "exec":
        return _parse_exec(rest)
    if verb == "say":
        return _parse_say(rest)
    if verb == "show":
        kind, _, path = rest.partition(" ")
        if kind != "file" or not path.strip():
            msg = f"only 'show file <path>' is supported, got: {value!r}"
            raise ValueError(msg)
        return ShowFileAction(path.strip())
    msg = f"expected an 'exec'/'say'/'show file' action, got: {value!r}"
    raise ValueError(msg)


def _positive_int(tok: str, kind: str) -> int:
    try:
        n = int(tok)
    except ValueError as exc:
        msg = f"{kind} condition needs an integer, got {tok!r}"
        raise ValueError(msg) from exc
    if n < 0:
        msg = f"{kind} condition needs a non-negative integer, got {tok!r}"
        raise ValueError(msg)
    return n


def _take_quoted(rest: str) -> tuple[str, str]:
    """Take a leading `"..."` literal (or one bare token); return (value, remaining)."""
    if rest.startswith('"'):
        end = rest.find('"', 1)
        if end == -1:
            msg = "output condition: unterminated quoted substring"
            raise ValueError(msg)
        return rest[1:end], rest[end + 1:].strip()
    tok, _, tail = rest.partition(" ")
    return tok, tail.strip()


def _parse_cmd_cond(rest: str) -> tuple[CmdCond, str]:
    """Parse `<base> [has <f...>] [missing <f...>]` up to the action verb; return (cond, action)."""
    toks = rest.split()
    if not toks:
        msg = "cmd condition requires a base command"
        raise ValueError(msg)
    base = toks[0]
    has: list[str] = []
    missing: list[str] = []
    bucket: list[str] | None = None
    i = 1
    while i < len(toks) and toks[i] not in _ACTION_VERBS:
        tok = toks[i]
        if tok == "has":
            bucket = has
        elif tok == "missing":
            bucket = missing
        elif bucket is None:
            msg = f"cmd condition: expected 'has'/'missing' before flags, got {tok!r}"
            raise ValueError(msg)
        else:
            bucket.append(tok)
        i += 1
    if i >= len(toks):
        msg = "cmd condition: hint needs an action (exec/say/show)"
        raise ValueError(msg)
    return CmdCond(base, tuple(has), tuple(missing)), " ".join(toks[i:])


def _parse_condition(value: str) -> tuple[Condition, str]:
    """Parse one explicit hint condition atom; return (Condition, remaining-action-text)."""
    kind, _, rest = value.partition(" ")
    rest = rest.strip()
    if kind == "tries":
        tok, _, tail = rest.partition(" ")
        return TriesCond(_positive_int(tok, "tries")), tail.strip()
    if kind == "idle":
        tok, _, tail = rest.partition(" ")
        return IdleCond(float(_positive_int(tok, "idle"))), tail.strip()
    if kind == "output":
        substr, tail = _take_quoted(rest)
        return OutputCond(substr), tail
    if kind == "cmd":
        return _parse_cmd_cond(rest)
    msg = f"unknown hint condition: {kind!r} (expected tries/idle/cmd/output)"
    raise ValueError(msg)


def _parse_hint(value: str) -> HintRule:
    """Parse a `hint <condition> <action>` line into a HintRule."""
    condition, action_text = _parse_condition(value)
    if not action_text:
        msg = f"hint requires an action after the condition: {value!r}"
        raise ValueError(msg)
    return HintRule(condition=condition, action=_parse_action(action_text))


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
    if acc.hidden is not None:
        msg = "duplicate 'hidden' directive"
        raise ValueError(msg)
    fields = value.split()
    if len(fields) != 1:
        msg = f"hidden requires a single <src> directory: {value!r}"
        raise ValueError(msg)
    acc.hidden = fields[0]


def _do_readme(value: str, acc: _Acc) -> None:
    if acc.readme is not None:
        msg = "duplicate 'readme' directive"
        raise ValueError(msg)
    fields = value.split()
    if len(fields) != 1:
        msg = f"readme requires a single <file>: {value!r}"
        raise ValueError(msg)
    acc.readme = fields[0]


def _do_react(value: str, acc: _Acc) -> None:
    head = "on command "
    if not value.startswith(head):
        msg = f"react must be 'react on command <action>': {value!r}"
        raise ValueError(msg)
    acc.react.append(_parse_action(value[len(head):].strip()))


_TOP_HANDLERS = {
    "image": _do_image,
    "from": _do_from,
    "copy": _do_copy,
    "run": _do_run,
    "hidden": _do_hidden,
    "readme": _do_readme,
    "react": _do_react,
}


def _reject(keyword: str) -> None:
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
    """Apply an `on <event> <action>` stage directive (enter/pass; exec/say/show actions)."""
    event, _, action = value.partition(" ")
    if event not in _STAGE_EVENTS:
        msg = f"unknown stage event: {event!r} (expected enter/pass)"
        raise ValueError(msg)
    target = sacc.on_enter if event == "enter" else sacc.on_pass
    target.append(_parse_action(action.strip()))


def _apply_check(value: str, sacc: _StageAcc) -> None:
    if sacc.check is not None:
        msg = "duplicate 'check' directive"
        raise ValueError(msg)
    verb, _, rest = value.partition(" ")
    if verb != "exec":
        msg = f"check requires an 'exec' predicate action, got: {value!r}"
        raise ValueError(msg)
    sacc.check = _parse_exec(rest.strip())


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
        _apply_check(value, sacc)
    elif kw == "hint":
        sacc.hints.append(_parse_hint(value))
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
        hints=tuple(sacc.hints),
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
            if value:
                msg = f"'solve:' takes no inline content; put commands on indented lines: {value!r}"
                raise ValueError(msg)
            i = _consume_solve_block(lines, i + 1, indent, sacc)
        else:
            _apply_simple_directive(kw, value, sacc)
            i += 1
    return _finalize_stage(sacc), i


def _parse_voice_block(lines: list[tuple[int, str]], start: int,
                       acc: _Acc) -> int:
    """Parse a `voice` block of `hello`/`bye <action>` lines; return next top-index."""
    i = start
    while i < len(lines) and lines[i][0] > 0:
        _, content = lines[i]
        kw, value = _kw_value(content)
        if kw == "hello":
            acc.hello.append(_parse_action(value))
        elif kw == "bye":
            acc.bye.append(_parse_action(value))
        else:
            msg = f"unknown voice directive: {kw!r} (expected hello/bye)"
            raise ValueError(msg)
        i += 1
    return i


def _parse_settings_block(lines: list[tuple[int, str]], start: int,
                          acc: _Acc) -> int:
    """Parse a `settings` block (type-mode/type-speed/pager); return next top-index."""
    if acc.settings is not None:
        msg = "duplicate 'settings' block"
        raise ValueError(msg)
    mode = "normal"
    speed = 45
    pager = False
    i = start
    while i < len(lines) and lines[i][0] > 0:
        _, content = lines[i]
        kw, value = _kw_value(content)
        if kw == "type-mode":
            if value not in _TYPE_MODES:
                msg = f"type-mode must be one of {_TYPE_MODES}, got {value!r}"
                raise ValueError(msg)
            mode = value
        elif kw == "type-speed":
            speed = _positive_int(value.strip(), "type-speed")
        elif kw == "pager":
            pager = value.strip() == "on"
        else:
            msg = f"unknown settings directive: {kw!r} (type-mode/type-speed/pager)"
            raise ValueError(msg)
        i += 1
    acc.settings = Settings(type_mode=mode, type_speed=speed, pager=pager)
    return i


_BLOCK_PARSERS = {"voice": _parse_voice_block, "settings": _parse_settings_block}


def parse_recipe(text: str) -> Recipe:
    """
    Parse Imagefile/Taskfile text into a Recipe (image directives + task + interactivity).

    Top-level (column 0): `image <name>:<ver>` (required, once), `from`, `copy`, `run`,
    `hidden <src>`, `readme <file>`, `react on command <action>`, the `settings`/`voice`
    blocks, and `stage "<message>"` blocks. A stage body holds
    `solve`/`observe`/`exclude`/`neutral`/`check`/`on enter|pass`/`hint <cond> <action>`.
    Blank and full-line `#` lines are ignored; inline `#` is preserved. Unknown directives
    raise ValueError.

    Raises:
        ValueError: missing/duplicate `image`, malformed directive/condition/action, a stage
            without `solve`, an unexpected indent, or an unknown directive.

    """
    acc = _Acc()
    lines = _significant(text)
    i = 0
    while i < len(lines):
        indent, content = lines[i]
        if indent != 0:
            msg = f"unexpected indentation (no open block): {content!r}"
            raise ValueError(msg)
        kw, value = _kw_value(content)
        if kw == "stage":
            stage, i = _parse_stage_block(value, lines, i + 1)
            acc.stages.append(stage)
            continue
        block = _BLOCK_PARSERS.get(kw)
        if block is not None:
            i = block(lines, i + 1, acc)
            continue
        handler = _TOP_HANDLERS.get(kw)
        if handler is None:
            _reject(kw)
        else:
            handler(value, acc)
        i += 1
    if not acc.name:
        msg = "recipe is missing a required 'image <name>:<ver>' directive"
        raise ValueError(msg)
    voice = Voice(hello=tuple(acc.hello), bye=tuple(acc.bye))
    return Recipe(acc.name, acc.version, tuple(acc.parents), tuple(acc.steps),
                  tuple(acc.stages), acc.hidden, acc.readme,
                  voice=voice, settings=acc.settings or Settings(), react=tuple(acc.react))


def load_recipe(path: Path) -> Recipe:
    """Read an Imagefile/Taskfile from disk and parse it (see `parse_recipe`)."""
    return parse_recipe(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/recipe/test_parse.py -v` — PASS (existing pure-image + Phase-2 cases unchanged; new Phase-3 cases green). `ruff check --config ruff.toml src/hashpass/recipe/parse.py tests/recipe/test_parse.py` — clean.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/recipe/parse.py tests/recipe/test_parse.py
git commit -m "feat(recipe): parse phase-3 directives — hint/say/show/voice/settings/react"
```

---

### Task 3: Condition matcher — `match_rule` over the explicit atoms

**Files:**
- Modify: `src/hashpass/hints.py` (add `match_rule` + helpers; keep the legacy `match_hint`/`StuckState`)
- Modify: `tests/test_hints.py` (add Phase-3 matcher cases; existing `match_hint` cases untouched)

**Interfaces:**
- Consumes: `hashpass.cmd.Cmd`, `hashpass.recipe.model` (`Action`, `Condition` + the four condition types, `HintRule`).
- Produces: `match_rule(rules, *, tries, idle, command, output) -> Action | None` — the action of the first rule whose condition matches (source order), else None. `tries`/`idle`/`cmd`/`output` evaluate as in §7.1; an unparseable `command` (shlex raises) never satisfies a `cmd` condition. A new atom is one extra branch in `_cond_matches` (additive, §3.0). `match_rule` is a **sibling** to `match_hint` (chosen over generalizing it: the two operate on different shapes — dict triggers vs typed rules — and co-locating them keeps hint-matching in one module).

**Import change** at the top of `hints.py` (merge into the existing block):

```python
from hashpass.cmd import Cmd
from hashpass.recipe.model import (
    Action,
    CmdCond,
    Condition,
    HintRule,
    IdleCond,
    OutputCond,
    TriesCond,
)
```

- [ ] **Step 1: Write the failing tests** — add to `tests/test_hints.py`:

```python
"""Validate the explicit-atom hint rule matcher (match_rule)."""
import pytest

from hashpass.hints import match_rule
from hashpass.recipe.model import (
    CmdCond,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    SayAction,
    TriesCond,
)

_NO = {"tries": 0, "idle": 0.0, "command": "", "output": ""}


@pytest.mark.tier1
def test_tries_and_idle_thresholds():
    rules = (HintRule(TriesCond(3), SayAction("t")),)
    assert match_rule(rules, **{**_NO, "tries": 2}) is None
    assert match_rule(rules, **{**_NO, "tries": 3}) == SayAction("t")
    idle_rules = (HintRule(IdleCond(90.0), SayAction("i")),)
    assert match_rule(idle_rules, **{**_NO, "idle": 89.9}) is None
    assert match_rule(idle_rules, **{**_NO, "idle": 90.0}) == SayAction("i")


@pytest.mark.tier1
def test_cmd_has_missing_and_output():
    rules = (HintRule(CmdCond("grep", (), ("-i",)), ExecAction("f.sh")),)
    assert match_rule(rules, **{**_NO, "command": "grep ERROR log"}) == ExecAction("f.sh")
    assert match_rule(rules, **{**_NO, "command": "grep -i ERROR log"}) is None  # missing -i present
    assert match_rule(rules, **{**_NO, "command": "cat log"}) is None            # wrong base
    has_rules = (HintRule(CmdCond("grep", ("-r",), ()), SayAction("h")),)
    assert match_rule(has_rules, **{**_NO, "command": "grep -r x ."}) == SayAction("h")
    assert match_rule(has_rules, **{**_NO, "command": "grep x ."}) is None
    out_rules = (HintRule(OutputCond("ERROR"), SayAction("o")),)
    assert match_rule(out_rules, **{**_NO, "output": "boom ERROR here"}) == SayAction("o")


@pytest.mark.tier1
def test_first_match_wins_and_unparseable_command():
    rules = (
        HintRule(TriesCond(2), SayAction("first")),
        HintRule(TriesCond(1), SayAction("second")),
    )
    assert match_rule(rules, **{**_NO, "tries": 5}) == SayAction("first")
    cmd_rules = (HintRule(CmdCond("grep", (), ()), SayAction("c")),)
    assert match_rule(cmd_rules, **{**_NO, "command": 'echo "oops'}) is None  # shlex raises -> no match
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_hints.py -v`
Expected: FAIL — `ImportError: cannot import name 'match_rule'`.

- [ ] **Step 3: Write the implementation** — append to `src/hashpass/hints.py` (after `match_hint`):

```python
def _cmd_matches(cond: CmdCond, command: str) -> bool:
    """Return True if the command has base `cond.base` with the required/forbidden flags."""
    try:
        cmd = Cmd(command)
    except ValueError:
        return False  # an unparseable typo never satisfies a cmd condition
    if cmd.basecmd != cond.base:
        return False
    return (all(cmd.has_flag(f) for f in cond.has)
            and not any(cmd.has_flag(f) for f in cond.missing))


def _cond_matches(cond: Condition, *, tries: int, idle: float,
                  command: str, output: str) -> bool:
    """Evaluate one explicit condition atom against the current session context (§7.1)."""
    if isinstance(cond, TriesCond):
        return tries >= cond.n
    if isinstance(cond, IdleCond):
        return idle >= cond.seconds
    if isinstance(cond, CmdCond):
        return _cmd_matches(cond, command)
    if isinstance(cond, OutputCond):
        return cond.substr in output
    msg = f"unknown condition: {cond!r}"
    raise TypeError(msg)


def match_rule(rules: tuple[HintRule, ...], *, tries: int, idle: float,
               command: str, output: str) -> Action | None:
    """
    Return the action of the first hint rule whose condition matches, else None (§7.1).

    Conditions are explicit atoms (`tries`/`idle`/`cmd`/`output`); first-match-wins in
    source order. `tries` is neutral-excluded; `idle` is seconds since last progress.
    """
    for rule in rules:
        if _cond_matches(rule.condition, tries=tries, idle=idle,
                         command=command, output=output):
            return rule.action
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_hints.py -v` — PASS. `ruff check --config ruff.toml src/hashpass/hints.py tests/test_hints.py` — clean.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/hints.py tests/test_hints.py
git commit -m "feat(hints): match_rule — first-match over explicit tries/idle/cmd/output atoms"
```

---

### Task 4: Render — the typewriter `Renderer` (injected sink + sleep)

**Files:**
- Create: `src/hashpass/render.py`
- Create: `tests/test_render.py`

**Interfaces:**
- Consumes: `hashpass.recipe.model.Settings`; stdlib `sys`/`time`/`pathlib`.
- Produces: `Renderer(settings, *, sink=<stdout write>, sleep=time.sleep)` with:
  - `render(text, *, mode=None)` — `mode` defaults to `settings.type_mode`. `instant` writes the whole string through `sink` and **never** calls `sleep`. `normal`/`dramatic` type char-by-char: `sink(ch)` then `sleep(char_delay)` (`char_delay = slow / type_speed`, `slow=3.0` for dramatic else `1.0`), plus an extra `sleep(punct_pause)` after any of `.,!?;:…—` (`0.55` dramatic, `0.18` normal). Unknown mode → `ValueError`.
  - `show_file(path, *, mode=None) -> str` — reads the file; if `pager on` **and** it exceeds `_PAGER_LINES` (40), emits it whole through `sink` (paged, never typed); otherwise `render`s it. Returns the text.
  - **Testability (mandatory, §7.2):** because `sink` and `sleep` are injected, tier1 tests capture the emitted chunks and the exact sleep durations with **no real sleeping** — asserting instant emits once with zero sleeps, `normal` honors `1/type_speed`, and `dramatic` inserts the punctuation pause. Student command output is rendered `instant`; system replies use the configured mode (a reply may force `dramatic`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_render.py`:

```python
"""Validate the typewriter render layer with injected sink + sleep (no real sleeping)."""
import pytest

from hashpass.recipe.model import Settings
from hashpass.render import Renderer


def _cap() -> tuple[list[str], list[float]]:
    chunks: list[str] = []
    sleeps: list[float] = []
    return chunks, sleeps


@pytest.mark.tier1
def test_instant_never_sleeps_single_write():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=sleeps.append)
    r.render("a long command output\nwith lines")
    assert chunks == ["a long command output\nwith lines"]
    assert sleeps == []


@pytest.mark.tier1
def test_normal_types_char_by_char_at_speed():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="normal", type_speed=50), sink=chunks.append, sleep=sleeps.append)
    r.render("ab")
    assert chunks == ["a", "b"]
    assert sleeps == [1 / 50, 1 / 50]
    assert "".join(chunks) == "ab"


@pytest.mark.tier1
def test_dramatic_pauses_at_punctuation():
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_speed=45), sink=chunks.append, sleep=sleeps.append)
    r.render("Hi!", mode="dramatic")
    char_delay = 3.0 / 45
    assert chunks == ["H", "i", "!"]
    assert sleeps == [char_delay, char_delay, char_delay, 0.55]  # extra pause after '!'


@pytest.mark.tier1
def test_show_file_small_typed_large_paged(tmp_path):
    small = tmp_path / "s.txt"
    small.write_text("one\ntwo\n", encoding="utf-8")
    big = tmp_path / "b.txt"
    big.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
    chunks, sleeps = _cap()
    r = Renderer(Settings(type_mode="normal", pager=True), sink=chunks.append, sleep=sleeps.append)
    assert r.show_file(small).startswith("one")
    assert len(chunks) > 1          # small file typed char-by-char
    chunks2, sleeps2 = _cap()
    r2 = Renderer(Settings(pager=True), sink=chunks2.append, sleep=sleeps2.append)
    r2.show_file(big)
    assert len(chunks2) == 1        # large + pager -> emitted whole
    assert sleeps2 == []


@pytest.mark.tier1
def test_unknown_mode_raises():
    r = Renderer(Settings(), sink=lambda _s: None, sleep=lambda _s: None)
    with pytest.raises(ValueError, match="unknown type-mode"):
        r.render("x", mode="turbo")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: FAIL — `ModuleNotFoundError: hashpass.render`.

- [ ] **Step 3: Write the implementation** — create `src/hashpass/render.py`:

```python
"""Typewriter render layer (§7.2): paced system replies + instant command output; injectable."""
import sys
import time
from collections.abc import Callable
from pathlib import Path

from hashpass.recipe.model import Settings

_INSTANT = "instant"
_DRAMATIC = "dramatic"
_MODES = ("instant", "normal", "dramatic")
_PUNCT = frozenset(".,!?;:…—")
_NORMAL_PAUSE = 0.18
_DRAMATIC_PAUSE = 0.55
_DRAMATIC_SLOW = 3.0
_MIN_SPEED = 1
_PAGER_LINES = 40


def _stdout_write(text: str) -> None:
    """Default sink: write to stdout without an added newline."""
    sys.stdout.write(text)


class Renderer:
    """Render text through an injected sink at a paced (or instant) speed (§7.2)."""

    def __init__(self, settings: Settings, *,
                 sink: Callable[[str], None] = _stdout_write,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        """Bind render settings plus injectable `sink` (emit) and `sleep` (pacing) callables."""
        self._settings = settings
        self._sink = sink
        self._sleep = sleep

    def render(self, text: str, *, mode: str | None = None) -> None:
        """Emit `text` through the sink; `instant` writes it whole, else type it char-by-char."""
        mode = mode or self._settings.type_mode
        if mode not in _MODES:
            msg = f"unknown type-mode: {mode!r}"
            raise ValueError(msg)
        if mode == _INSTANT:
            self._sink(text)
            return
        speed = max(self._settings.type_speed, _MIN_SPEED)
        slow = _DRAMATIC_SLOW if mode == _DRAMATIC else 1.0
        char_delay = slow / speed
        punct_pause = _DRAMATIC_PAUSE if mode == _DRAMATIC else _NORMAL_PAUSE
        for ch in text:
            self._sink(ch)
            self._sleep(char_delay)
            if ch in _PUNCT:
                self._sleep(punct_pause)

    def show_file(self, path: Path, *, mode: str | None = None) -> str:
        """Render a file's contents; a large file with `pager on` is emitted whole (paged), not typed."""
        text = Path(path).read_text(encoding="utf-8")
        if self._settings.pager and text.count("\n") + 1 > _PAGER_LINES:
            self._sink(text)
            return text
        self.render(text, mode=mode)
        return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_render.py -v` — PASS. `ruff check --config ruff.toml src/hashpass/render.py tests/test_render.py` — clean.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/render.py tests/test_render.py
git commit -m "feat(render): typewriter Renderer with injected sink+sleep, instant/normal/dramatic + pager"
```

---

### Task 5: Store — persist actions/hints/voice/settings/react (JSON round-trip)

**Files:**
- Modify: `src/hashpass/taskstore.py` (rich `StageMeta`; `TaskMeta` gains `voice`/`settings`/`react`; action/condition/hint/voice/settings (de)serializers)
- Modify: `src/hashpass/taskbuild.py` (`_build_meta` only — carry the new fields through)
- Modify: `tests/test_taskstore.py` (update the `_meta()` helper; add a rich round-trip)
- Modify: `tests/test_taskbuild.py` (add a tier1 `_build_meta` mapping test)

**Interfaces:**
- Consumes: `hashpass.recipe.model` action/condition/rule/voice/settings types.
- Produces:
  - `StageMeta` — `on_enter`/`on_pass` widen to `tuple[Action, ...]` (exec/say/show), new `hints: tuple[HintRule, ...] = ()`. `check` stays `str | None` (exec value; the runtime wraps `ExecAction(sm.check)` as in 2B), `neutral`/`message`/`acceptance` unchanged.
  - `TaskMeta` — new `voice: Voice = field(default_factory=Voice)`, `settings: Settings = field(default_factory=Settings)`, `react: tuple[Action, ...] = ()` (all defaulted, so a dict without those keys round-trips).
  - Actions serialize to tagged dicts (`{"kind":"exec","value":…}` / `{"kind":"say","text":…,"dramatic":…}` / `{"kind":"show","path":…}`); conditions likewise; a hint is `{"condition":…,"action":…}`. `meta_to_dict`/`meta_from_dict`/`save_meta`/`load_meta`/`load_task` keep their signatures.
  - `taskbuild._build_meta` maps `StageSpec.on_enter/on_pass/hints` straight through (no more `a.value` flattening) and threads `recipe.voice/settings/react` onto `TaskMeta`. `build_task` is otherwise unchanged — it still writes `Bundle(checks=…, conditions={}, hints={})` (Phase-3 hints live in the meta, not the bundle).

> **Back-compat call-out (necessary, like the Task-2 reserved flip):** supporting `say`/`show` on `on enter|pass` end-to-end (brief decision 3) means `StageMeta.on_enter/on_pass` must carry `Action` objects, not the 2B exec-value strings. `tests/test_taskstore.py::_meta()` therefore wraps its hook values as `ExecAction("seed.sh")` / `ExecAction("cheer.sh")` (and imports `ExecAction`). This is the only edit to that file; the defaulted `voice`/`settings`/`react`/`hints` keep the rest of it round-tripping unchanged.

- [ ] **Step 1: Write the failing tests** — update `tests/test_taskstore.py`'s `_meta()` to construct `on_enter`/`on_pass` with `Action` objects and add a rich round-trip; add a tier1 `_build_meta` test to `tests/test_taskbuild.py`.

`tests/test_taskstore.py` (replace the module's `_meta()` + tests with this; imports shown):

```python
"""Validate rich StageMeta/TaskMeta JSON round-trip (actions, hints, voice, settings, react)."""
import json

import pytest

from hashpass.recipe.model import (
    CmdCond,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    SayAction,
    Settings,
    ShowFileAction,
    TriesCond,
    Voice,
)
from hashpass.taskstore import (
    StageMeta,
    TaskMeta,
    meta_from_dict,
    meta_to_dict,
)


def _meta() -> TaskMeta:
    return TaskMeta(
        image_ref="log-archive:1",
        stages=(
            StageMeta(
                message="collect", neutral=("ls", "cd"), check=None,
                on_enter=(ExecAction("seed.sh"),),
                on_pass=(SayAction("first!"), ShowFileAction("art/ok.txt")),
                acceptance="derived",
                hints=(
                    HintRule(TriesCond(5), SayAction("look", dramatic=True)),
                    HintRule(CmdCond("grep", ("-r",), ("-i",)), ExecAction("h.sh")),
                    HintRule(IdleCond(90.0), ExecAction("idle.sh")),
                    HintRule(OutputCond("ERROR"), ShowFileAction("art/hit.txt")),
                ),
            ),
            StageMeta(message="verify", neutral=(), check="verify.sh",
                      on_enter=(), on_pass=(), acceptance="handler"),
        ),
        readme="readme.txt",
        voice=Voice(hello=(SayAction("yo"), ExecAction("greet.sh")), bye=(SayAction("gg"),)),
        settings=Settings(type_mode="dramatic", type_speed=60, pager=True),
        react=(ExecAction("watch.sh"),),
    )


@pytest.mark.tier1
def test_meta_dict_round_trip():
    meta = _meta()
    assert meta_from_dict(meta_to_dict(meta)) == meta


@pytest.mark.tier1
def test_meta_json_string_round_trip():
    meta = _meta()
    assert meta_from_dict(json.loads(json.dumps(meta_to_dict(meta)))) == meta


@pytest.mark.tier1
def test_backcompat_missing_new_keys_default():
    m = meta_from_dict({"image_ref": "x:1", "stages": []})
    assert m.readme is None
    assert m.voice == Voice()
    assert m.settings == Settings()
    assert m.react == ()
```

`tests/test_taskbuild.py` (add this tier1 test — it needs no container; imports shown):

```python
"""Validate the recipe->TaskMeta mapping (taskbuild._build_meta) end-to-end with the parser."""
import pytest

from hashpass.taskbuild import _build_meta
from hashpass.recipe.model import (
    ExecAction,
    SayAction,
    Settings,
    ShowFileAction,
    TriesCond,
    Voice,
)
from hashpass.recipe.parse import parse_recipe
from hashpass.taskstore import meta_from_dict, meta_to_dict

_RECIPE = (
    "image demo:1\n"
    "settings\n  type-mode dramatic\n  type-speed 30\n"
    "voice\n  hello say \"hi\"\n  bye exec bye.sh\n"
    "react on command exec watch.sh\n"
    'stage "one"\n'
    "  solve echo hi\n  observe o\n"
    "  on enter exec seed.sh\n"
    '  on pass say "nice"\n'
    "  on pass show file art/ok.txt\n"
    '  hint tries 3 say "try -r"\n'
)


@pytest.mark.tier1
def test_build_meta_carries_actions_hints_voice_settings_react():
    meta = _build_meta("demo:1", parse_recipe(_RECIPE), ["derived"])
    s = meta.stages[0]
    assert s.on_enter == (ExecAction("seed.sh"),)
    assert s.on_pass == (SayAction("nice"), ShowFileAction("art/ok.txt"))
    assert s.hints[0].condition == TriesCond(3)
    assert s.hints[0].action == SayAction("try -r")
    assert meta.voice == Voice(hello=(SayAction("hi"),), bye=(ExecAction("bye.sh"),))
    assert meta.settings == Settings(type_mode="dramatic", type_speed=30)
    assert meta.react == (ExecAction("watch.sh"),)
    # and the whole thing survives the JSON round-trip
    assert meta_from_dict(meta_to_dict(meta)) == meta
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_taskstore.py tests/test_taskbuild.py -v`
Expected: FAIL — `TypeError`/`ImportError` (old `_stage_to_dict` cannot serialize an `ExecAction`; `_build_meta` import of the new mapping).

- [ ] **Step 3: Write the implementation**

Replace the body of `src/hashpass/taskstore.py` with:

```python
"""Local task store: task artifacts (bundle + hidden /hp + meta) under the image's ver dir."""
import json
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage
from hashpass.recipe.model import (
    Action,
    CmdCond,
    Condition,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    SayAction,
    Settings,
    ShowFileAction,
    TriesCond,
    Voice,
)


@dataclass(frozen=True)
class StageMeta:
    """Per-stage runtime metadata: acceptance mode + delegated actions + hints + neutral set."""

    message: str
    neutral: tuple[str, ...]
    check: str | None                 # ExecAction.value, or None
    on_enter: tuple[Action, ...]      # exec/say/show actions
    on_pass: tuple[Action, ...]
    acceptance: str                   # "derived" | "handler"
    hints: tuple[HintRule, ...] = ()


@dataclass(frozen=True)
class TaskMeta:
    """Task runtime metadata: the built image ref, ordered stages, readme, voice/settings/react."""

    image_ref: str
    stages: tuple[StageMeta, ...]
    readme: str | None = None
    voice: Voice = field(default_factory=Voice)
    settings: Settings = field(default_factory=Settings)
    react: tuple[Action, ...] = ()


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


def _action_to_dict(action: Action) -> dict:
    if isinstance(action, ExecAction):
        return {"kind": "exec", "value": action.value}
    if isinstance(action, SayAction):
        return {"kind": "say", "text": action.text, "dramatic": action.dramatic}
    if isinstance(action, ShowFileAction):
        return {"kind": "show", "path": action.path}
    msg = f"unknown action: {action!r}"
    raise TypeError(msg)


def _action_from_dict(data: dict) -> Action:
    kind = data["kind"]
    if kind == "exec":
        return ExecAction(data["value"])
    if kind == "say":
        return SayAction(data["text"], data.get("dramatic", False))
    if kind == "show":
        return ShowFileAction(data["path"])
    msg = f"unknown action kind: {kind!r}"
    raise ValueError(msg)


def _cond_to_dict(cond: Condition) -> dict:
    if isinstance(cond, TriesCond):
        return {"kind": "tries", "n": cond.n}
    if isinstance(cond, IdleCond):
        return {"kind": "idle", "seconds": cond.seconds}
    if isinstance(cond, CmdCond):
        return {"kind": "cmd", "base": cond.base,
                "has": list(cond.has), "missing": list(cond.missing)}
    if isinstance(cond, OutputCond):
        return {"kind": "output", "substr": cond.substr}
    msg = f"unknown condition: {cond!r}"
    raise TypeError(msg)


def _cond_from_dict(data: dict) -> Condition:
    kind = data["kind"]
    if kind == "tries":
        return TriesCond(data["n"])
    if kind == "idle":
        return IdleCond(data["seconds"])
    if kind == "cmd":
        return CmdCond(data["base"], tuple(data["has"]), tuple(data["missing"]))
    if kind == "output":
        return OutputCond(data["substr"])
    msg = f"unknown condition kind: {kind!r}"
    raise ValueError(msg)


def _hint_to_dict(hint: HintRule) -> dict:
    return {"condition": _cond_to_dict(hint.condition), "action": _action_to_dict(hint.action)}


def _hint_from_dict(data: dict) -> HintRule:
    return HintRule(condition=_cond_from_dict(data["condition"]),
                    action=_action_from_dict(data["action"]))


def _voice_to_dict(voice: Voice) -> dict:
    return {"hello": [_action_to_dict(a) for a in voice.hello],
            "bye": [_action_to_dict(a) for a in voice.bye]}


def _voice_from_dict(data: dict) -> Voice:
    return Voice(hello=tuple(_action_from_dict(a) for a in data.get("hello", [])),
                 bye=tuple(_action_from_dict(a) for a in data.get("bye", [])))


def _settings_to_dict(settings: Settings) -> dict:
    return {"type_mode": settings.type_mode, "type_speed": settings.type_speed,
            "pager": settings.pager}


def _settings_from_dict(data: dict) -> Settings:
    return Settings(type_mode=data.get("type_mode", "normal"),
                    type_speed=data.get("type_speed", 45),
                    pager=data.get("pager", False))


def _stage_to_dict(stage: StageMeta) -> dict:
    return {
        "message": stage.message,
        "neutral": list(stage.neutral),
        "check": stage.check,
        "on_enter": [_action_to_dict(a) for a in stage.on_enter],
        "on_pass": [_action_to_dict(a) for a in stage.on_pass],
        "acceptance": stage.acceptance,
        "hints": [_hint_to_dict(h) for h in stage.hints],
    }


def _stage_from_dict(data: dict) -> StageMeta:
    return StageMeta(
        message=data["message"],
        neutral=tuple(data["neutral"]),
        check=data["check"],
        on_enter=tuple(_action_from_dict(a) for a in data["on_enter"]),
        on_pass=tuple(_action_from_dict(a) for a in data["on_pass"]),
        acceptance=data["acceptance"],
        hints=tuple(_hint_from_dict(h) for h in data.get("hints", [])),
    )


def meta_to_dict(meta: TaskMeta) -> dict:
    """Serialize TaskMeta to a JSON-ready dict."""
    return {
        "image_ref": meta.image_ref,
        "stages": [_stage_to_dict(s) for s in meta.stages],
        "readme": meta.readme,
        "voice": _voice_to_dict(meta.voice),
        "settings": _settings_to_dict(meta.settings),
        "react": [_action_to_dict(a) for a in meta.react],
    }


def meta_from_dict(data: dict) -> TaskMeta:
    """Rebuild TaskMeta from its JSON dict."""
    return TaskMeta(
        image_ref=data["image_ref"],
        stages=tuple(_stage_from_dict(s) for s in data["stages"]),
        readme=data.get("readme"),
        voice=_voice_from_dict(data.get("voice", {})),
        settings=_settings_from_dict(data.get("settings", {})),
        react=tuple(_action_from_dict(a) for a in data.get("react", [])),
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

In `src/hashpass/taskbuild.py`, replace `_build_meta` with (the file's existing imports of `StageMeta`/`TaskMeta`/`Recipe` already cover it):

```python
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
        )
        for i, s in enumerate(recipe.stages)
    )
    return TaskMeta(image_ref=ref, stages=stages, readme=recipe.readme,
                    voice=recipe.voice, settings=recipe.settings, react=recipe.react)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_taskstore.py tests/test_taskbuild.py -m tier1 -v` — PASS. `ruff check --config ruff.toml src/hashpass/taskstore.py src/hashpass/taskbuild.py tests/test_taskstore.py tests/test_taskbuild.py` — clean.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/taskstore.py src/hashpass/taskbuild.py tests/test_taskstore.py tests/test_taskbuild.py
git commit -m "feat(taskstore): persist phase-3 actions/hints/voice/settings/react in task meta"
```

---

### Task 6: Wire into `TaskSession` + tier3 e2e — idle tracking, hint render, voice, react

**Files:**
- Modify: `src/hashpass/taskrun.py` (add `Renderer`/idle/`perform_action`; evaluate `match_rule` in `feed`; fire `voice`/`react`; thread `sink`/`sleep` through `run_task`)
- Modify: `tests/test_taskrun.py` (add tier1 helper tests; add ONE tier3 e2e; the existing tier3 cases stay green)

**Interfaces:**
- Consumes: `hashpass.hints.match_rule`, `hashpass.render.Renderer`, the model `Action` types, plus everything 2B already used.
- Produces:
  - `_elapsed(start_ts, now_ts) -> float` — seconds between two ISO timestamps (0.0 on unparse; idle stays neutral). **tier1.**
  - `perform_action(action, ctx, *, render, runner, hp_dir) -> str` — module-level; `say` renders text (dramatic when flagged), `show file` renders `<hp_dir>/work/<path>`, `exec` runs `run_handler` and renders stdout. Returns the shown text. **tier1** (a fake runner returning a canned `RunResult` exercises the exec path without a container).
  - `TaskSession` — owns a `Renderer(meta.settings, sink=…, sleep=…)`; `enter()` fires `voice.hello` on the first call then the stage's `on_enter`; `feed()` renders student output `instant`, tallies neutral-aware tries, fires `react` every command, checks acceptance, and on **non**-acceptance evaluates `match_rule` and renders the fired action into `FeedResult.hint`; on acceptance fires `on_pass` and (once all stages pass) `voice.bye`. `FeedResult.hint` is now populated.
  - `run_task(...)` — gains keyword-only `sink`/`sleep` (defaults: stdout write / `time.sleep`) forwarded to the session; otherwise unchanged.
- **Why hints fire only on non-acceptance:** a hint is an advisory nudge for a student who is *not yet* through the stage; you do not nag on the command that just passed. (Recorded.)

- [ ] **Step 1: Write the failing tests** — add to `tests/test_taskrun.py`.

Tier1 helper tests (no container — a fake runner drives the `exec` path):

```python
"""Validate pure runtime helpers: idle elapsed + action rendering (fake runner for exec)."""
import pytest

from hashpass.handler import HandlerContext
from hashpass.recipe.model import ExecAction, SayAction, Settings, ShowFileAction
from hashpass.render import Renderer
from hashpass.runner.nspawn import RunResult
from hashpass.taskrun import _elapsed, perform_action


class _FakeRunner:
    def __init__(self, out: str) -> None:
        self._out = out
        self.calls: list = []

    def run(self, argv: list[str], *, binds: object = None,
            setenv: object = None) -> RunResult:
        self.calls.append((argv, binds, setenv))
        return RunResult(self._out, "", 0)


_CTX = HandlerContext(student_cmd="grep x f", tries=1, last_out="", stage=0)


@pytest.mark.tier1
def test_elapsed_seconds_and_bad_ts():
    assert _elapsed("2026-08-31T00:00:00", "2026-08-31T00:01:30") == 90.0  # noqa: PLR2004
    assert _elapsed("not-a-ts", "2026-08-31T00:00:00") == 0.0


@pytest.mark.tier1
def test_perform_say_renders_and_returns(tmp_path):
    chunks: list[str] = []
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=lambda _s: None)
    out = perform_action(SayAction("hello there"), _CTX, render=r,
                         runner=_FakeRunner(""), hp_dir=tmp_path)
    assert out == "hello there"
    assert chunks == ["hello there"]


@pytest.mark.tier1
def test_perform_show_file_reads_hp_work(tmp_path):
    work = tmp_path / "work" / "art"
    work.mkdir(parents=True)
    (work / "ok.txt").write_text("nice job", encoding="utf-8")
    chunks: list[str] = []
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=lambda _s: None)
    out = perform_action(ShowFileAction("art/ok.txt"), _CTX, render=r,
                         runner=_FakeRunner(""), hp_dir=tmp_path)
    assert out == "nice job"
    assert chunks == ["nice job"]


@pytest.mark.tier1
def test_perform_exec_runs_handler_and_renders(tmp_path):
    chunks: list[str] = []
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=lambda _s: None)
    runner = _FakeRunner("HINT-OUT\n")
    out = perform_action(ExecAction("echo hi"), _CTX, render=r, runner=runner, hp_dir=tmp_path)
    assert out == "HINT-OUT\n"
    assert chunks == ["HINT-OUT\n"]
    argv, binds, _ = runner.calls[0]
    assert argv == ["sh", "-c", "echo hi"]        # command action -> sh -c
    assert binds == [(str(tmp_path), "/hp")]        # /hp bound for the handler run
```

The single tier3 end-to-end (a DSL `cmd … missing -i` hint fires and renders through a real `TaskSession`; a `tries 2` hint is also authored to show that atom). **Planning cannot run tier3 — the implementer validates with `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/test_taskrun.py -m tier3 -v`.**

```python
"""Tier3 e2e: a DSL-authored hint fires and renders through a real TaskSession (implementer runs)."""
import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import build_task
from hashpass.taskrun import run_task

_HINT_TASK = """\
image hinttask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

settings
  type-mode normal
  type-speed 2000

stage "collect ERROR lines (case-insensitive)"
  solve grep -rih ERROR /var/log/app > /errors.txt
  observe /errors.txt
  hint cmd grep missing -i say "add -i for case-insensitive 🔎"
  hint tries 2 say "peek in /var/log/app 👀"
"""


@pytest.mark.tier3
def test_e2e_dsl_hint_fires_and_renders(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_HINT_TASK), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    chunks: list[str] = []
    session = run_task("hinttask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1",
                       sink=chunks.append, sleep=lambda _s: None)
    try:
        # a case-sensitive grep (missing -i) does not match ERROR/error -> rejected, and the
        # first-match `cmd grep missing -i` hint fires and is rendered through the injected sink.
        res = session.feed("grep -rh error /var/log/app > /errors.txt",
                           ts="2026-08-31T00:00:00")
        assert res.advanced is False
        assert res.hint is not None
        assert "add -i" in res.hint
        assert any("add -i" in c for c in chunks)
        # the reference solution (case-insensitive) is accepted
        ok = session.feed("grep -rih ERROR /var/log/app > /errors.txt",
                          ts="2026-08-31T00:00:05")
        assert ok.advanced is True
        assert ok.local_key is not None
    finally:
        session.teardown()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_taskrun.py -v` (tier1 selection) — FAIL: `ImportError: cannot import name '_elapsed'` / `perform_action`.

- [ ] **Step 3: Write the implementation** — replace the body of `src/hashpass/taskrun.py` with:

```python
"""Run a stored task: student container WITHOUT /hp; handlers/checks/hints in a bound-/hp run."""
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from hashpass.cmd import Cmd
from hashpass.grade import grade_stage
from hashpass.handler import HandlerContext, run_handler
from hashpass.hints import match_rule
from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.key import local_key
from hashpass.play import capture_candidate
from hashpass.progress import current_stage, mark_passed_local, new_progress
from hashpass.recipe.model import Action, ExecAction, SayAction, ShowFileAction
from hashpass.render import Renderer
from hashpass.runner.nspawn import NspawnRunner
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskstore import StageMeta, StoredTask, load_task

_ACCEPT_EXIT = 0


@dataclass
class FeedResult:
    """Outcome of feeding one student command; `hint` carries a fired hint's rendered text."""

    advanced: bool
    stage: int | None
    local_key: str | None
    hint: str | None = None


def _stdout(text: str) -> None:
    """Default render sink: write to stdout without an added newline."""
    sys.stdout.write(text)


def _is_neutral(command: str, neutral: tuple[str, ...]) -> bool:
    """
    Return True if the command's base command is a neutral ("just looking") command.

    An unparseable command (e.g. an unbalanced-quote typo, which makes `shlex` raise) is
    treated as a real attempt, never neutral — so a typo still counts toward tries and
    never crashes the session.
    """
    try:
        return Cmd(command).basecmd in neutral
    except ValueError:
        return False


def _elapsed(start_ts: str, now_ts: str) -> float:
    """Seconds between two ISO timestamps; 0.0 if either is unparseable (idle stays neutral)."""
    try:
        return (datetime.fromisoformat(now_ts) - datetime.fromisoformat(start_ts)).total_seconds()
    except ValueError:
        return 0.0


def perform_action(action: Action, ctx: HandlerContext, *, render: Renderer,
                   runner: NspawnRunner, hp_dir: Path) -> str:
    """
    Render one delegated action and return the text shown.

    `say` renders its literal text (dramatic pacing when flagged); `show file` reads
    `<hp_dir>/work/<path>` and renders it (paged when large); `exec` runs the §6 handler
    under `/hp` and renders its stdout. System replies use the configured type-mode.
    """
    if isinstance(action, SayAction):
        render.render(action.text, mode="dramatic" if action.dramatic else None)
        return action.text
    if isinstance(action, ShowFileAction):
        return render.show_file(Path(hp_dir) / "work" / action.path)
    res = run_handler(runner, ExecAction(action.value), ctx, hp_dir=Path(hp_dir))
    render.render(res.stdout)
    return res.stdout


class TaskSession:
    """One student's live task run: a /hp-free student container + per-session hidden /hp."""

    def __init__(self, stored: StoredTask, student: NspawnRunner, hp_dir: Path, *,  # noqa: PLR0913
                 student_id: str, nonce: str,
                 sink: Callable[[str], None] = _stdout,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        """Bind a stored task to a prepared (student) runner, a writable /hp copy, and a Renderer."""
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
        self.render = Renderer(self.meta.settings, sink=sink, sleep=sleep)
        self._greeted = False
        self._said_bye = False
        self._last_progress_ts: str | None = None

    @staticmethod
    def _ctx(command: str, tries: int, stage: int, last_out: str = "") -> HandlerContext:
        """Build the HP_* handler context for one delegated action."""
        return HandlerContext(student_cmd=command, tries=tries, last_out=last_out, stage=stage)

    def _perform_all(self, actions: tuple[Action, ...], ctx: HandlerContext) -> list[str]:
        """Render a list of delegated actions; collect the text each produced."""
        return [perform_action(a, ctx, render=self.render, runner=self.student, hp_dir=self.hp_dir)
                for a in actions]

    def enter(self) -> list[str]:
        """Fire session `voice hello` (first call) then the current stage's `on_enter`; return their text."""
        stage = current_stage(self.progress)
        outs: list[str] = []
        if not self._greeted:
            self._greeted = True
            outs.extend(self._perform_all(self.meta.voice.hello, self._ctx("", 0, stage or 0)))
        if stage is None:
            return outs
        sm = self.meta.stages[stage]
        outs.extend(self._perform_all(sm.on_enter, self._ctx("", self.tries[stage], stage)))
        return outs

    def _accept(self, stage: int, sm: StageMeta, command: str,
                out: str, ts: str) -> tuple[bool, str | None]:
        """Decide acceptance: handler stages via a /hp check-run; derived stages host-side."""
        if sm.acceptance == "handler":
            ctx = self._ctx(command, self.tries[stage], stage, out)
            res = run_handler(self.student, ExecAction(sm.check), ctx, hp_dir=self.hp_dir)
            if res.exit_code == _ACCEPT_EXIT:
                return True, local_key(self.task_id, stage, self.nonce)
            return False, None
        cand = capture_candidate(self.student.rootfs, self.checks.stages[stage], out)
        grade = grade_stage(self.checks.stages[stage], cand, task_id=self.task_id,
                            stage=stage, student_id=self.student_id, nonce=self.nonce, ts=ts)
        return grade.accepted, grade.local_key

    def _on_pass(self, stage: int, ctx: HandlerContext, ts: str) -> None:
        """Fire `on_pass`, advance progress, and speak `voice bye` once all stages pass."""
        self._last_progress_ts = ts
        mark_passed_local(self.progress, stage)
        self._perform_all(self.meta.stages[stage].on_pass, ctx)
        if current_stage(self.progress) is None and not self._said_bye:
            self._said_bye = True
            self._perform_all(self.meta.voice.bye, ctx)

    def feed(self, command: str, *, ts: str) -> FeedResult:
        """Run one student command (no /hp), tally tries, react, check acceptance, maybe hint."""
        stage = current_stage(self.progress)
        if stage is None:
            return FeedResult(advanced=False, stage=None, local_key=None)
        if self._last_progress_ts is None:
            self._last_progress_ts = ts
        sm = self.meta.stages[stage]
        out = self.student.run(["sh", "-c", command]).stdout
        self.render.render(out, mode="instant")          # student output is never typed (§7.2)
        if not _is_neutral(command, sm.neutral):
            self.tries[stage] += 1
        ctx = self._ctx(command, self.tries[stage], stage, out)
        self._perform_all(self.meta.react, ctx)          # per-command catch-all handlers
        accepted, key = self._accept(stage, sm, command, out, ts)
        hint: str | None = None
        if accepted:
            self._on_pass(stage, ctx, ts)
        else:
            action = match_rule(sm.hints, tries=self.tries[stage],
                                idle=_elapsed(self._last_progress_ts, ts),
                                command=command, output=out)
            if action is not None:
                hint = perform_action(action, ctx, render=self.render,
                                      runner=self.student, hp_dir=self.hp_dir)
        return FeedResult(advanced=accepted, stage=stage, local_key=key, hint=hint)

    def teardown(self) -> None:
        """Tear down the student container (unmount overlay). The /hp copy is scratch."""
        self.student.teardown()


def run_task(ref: str, store: ImageStore, workdir: Path, *,  # noqa: PLR0913
             base_tar: Path, student_id: str, nonce: str,
             sink: Callable[[str], None] = _stdout,
             sleep: Callable[[float], None] = time.sleep) -> TaskSession:
    """
    Open a live task session: a student container on the image chain, no `/hp` in it.

    Prepares the student NspawnRunner over the task image's overlay closure (so `/hp`
    is never a lower and never baked), makes a writable per-session copy of the stored
    hidden `/hp`, and returns a driveable TaskSession whose Renderer uses `sink`/`sleep`.

    Args:
        ref: Task/image reference (`name` or `name:version`).
        store: Image store holding the task and its image chain.
        workdir: Scratch dir for the base, the student runner tree, and the /hp copy.
        base_tar: Rootfs tarball for the bottom base layer.
        student_id: Student identity (folded into evidence for derived stages).
        nonce: Per-session nonce for local keys.
        sink: Where rendered text is emitted (default stdout write).
        sleep: Pacing hook for the typewriter (default time.sleep; inject a no-op in tests).

    Returns:
        A TaskSession (call `.enter()`, `.feed(cmd, ts=...)`, `.teardown()`).

    """
    workdir = Path(workdir)
    stored = load_task(ref, store)
    lowers = resolve_lowers((ref,), store)
    base = build_base(workdir / "base", from_tar=base_tar)
    student = NspawnRunner(workdir / "student", base_dir=base)
    student.prepare(lowers)
    try:
        hp_dir = workdir / "hp"
        shutil.copytree(stored.hp_src_dir, hp_dir, dirs_exist_ok=True)
        return TaskSession(stored, student, hp_dir, student_id=student_id, nonce=nonce,
                           sink=sink, sleep=sleep)
    except Exception:
        # prepare() already mounted the overlay; on any failure before the caller holds a
        # TaskSession (its only teardown handle), unmount it here so we don't leak a mount.
        student.teardown()
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run (tier1): `python3 -m pytest tests/test_taskrun.py -m tier1 -v` — PASS. `ruff check --config ruff.toml src/hashpass/taskrun.py tests/test_taskrun.py` — clean.
Run (tier3, implementer only): `TMPDIR=/var/tmp/hp-pytest python3 -m pytest tests/test_taskrun.py -m tier3 -v` — the three existing 2B e2e cases plus `test_e2e_dsl_hint_fires_and_renders` PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/taskrun.py tests/test_taskrun.py
git commit -m "feat(taskrun): wire phase-3 interactivity — idle, hint match+render, voice, react"
```

---

## Self-Review

**Spec coverage (§7 interactivity + §3.0/§10):**
- §7 event→handler sugar — `hint`/`voice`/`react`/`on enter|pass` all parse to actions and are dispatched by `TaskSession` (explicitly, not via `HookRegistry` — recorded decision). `command`/`enter`/`pass`/`idle`/`output-match` events are realized as: `react` (every command), `enter()`/`_on_pass`, `_elapsed` idle, and the `output` condition atom. `on fail` deferred (still errors clearly). ✓
- §7.1 explicit conditions (no bare `stuck`) — `tries`/`idle`/`cmd <base> [has][missing]`/`output "…"`, one atom per line, first-match in source order; `neutral` already feeds the tries count in 2B. ✓
- §7.2 live typewriter — `Renderer` with `type-mode ∈ {instant,normal,dramatic}` (default normal), `type-speed` (default 45), micro-pauses at punctuation, `pager on` for large `show file`; student output `instant`, system replies configured, `say dramatic` supported. Injected `sink`+`sleep` make pacing testable with no real sleeping. ✓
- §3.0 explicit actions — `say "…"` / `show file <path>` / `exec <file-or-command>`; `exec` reuses the §6 `HP_*` handler unchanged. ✓
- §10 — English keywords, indentation blocks (`settings`/`voice`), `instant/normal/dramatic` + `type-speed` + pager, additive syntax (a new atom/verb/event is a localized parser+model edit). ✓
- **Out of scope (correctly deferred):** `on fail`; routing interactivity through `HookRegistry`; registry push/pull (phase 4); content migration (phase 5); a real TTY pager binary (the render contract emits large paged files whole through the sink — the terminal front-end is a display detail).

**Placeholder scan:** none — every code step is complete, materialized, and validated on a scratch package copy. All six SRC modules (`recipe/model.py`, `recipe/parse.py`, `hints.py`, `render.py`, `taskstore.py`, `taskrun.py`) plus the `taskbuild._build_meta` mapping are `ruff check --config ruff.toml` **clean** (`select=ALL`). Validated pure logic: **37 tier1 tests, 82 assertions + 11 parametrized parse-error rows**, all passing — model 14, parser 21 (+11 error rows, +3 flipped-to-positive), matcher 12, render 11, store 6, `_build_meta` 8, runtime helpers 10. The tier3 e2e is complete + ruff-clean but not run here (no containers); the implementer validates it with `pytest -m tier3`.

**Type consistency across tasks:** `Action`/`Condition`/`HintRule`/`Voice`/`Settings` are defined once in `recipe/model.py` (Task 1) and consumed unchanged by the parser (Task 2), `match_rule` (Task 3 → returns `Action | None`), `taskstore` (Task 5 → serializes them; `StageMeta.on_enter/on_pass: tuple[Action,...]`, `hints: tuple[HintRule,...]`), and `taskrun` (Task 6 → `perform_action(action: Action, …)`, `match_rule(sm.hints, …)`). `Renderer` (Task 4) consumes `Settings` and is constructed from `meta.settings` (Task 6). `HandlerContext`/`run_handler` signatures are consumed exactly as 2B defines them (verified against source). `Recipe`'s first four fields stay positional; `StageSpec`/`StageMeta`/`TaskMeta` grow only defaulted fields.

**Back-compat verified (not assumed):** the 2A full-stage recipe re-parses to an equal `StageSpec` (with `hints=()`), a plain image re-parses equal (with `voice`/`settings`/`react` defaulted), and `hidden`/`readme` are unchanged — confirmed on the scratch copy. Two deliberate, called-out test edits: `tests/recipe/test_parse.py` (the reserved-`voice` case + two `"phase 3"` rows now parse) and `tests/test_taskstore.py` (`_meta()` wraps `ExecAction`). The three existing tier3 `taskrun` cases still pass — `feed`/`enter` render through the default stdout sink and fire empty `react`/`voice`, leaving `FeedResult`/state assertions unchanged.

**Deviations / decisions beyond the brief (recorded):**
- **`StageMeta.on_enter/on_pass` schema change forces a second test edit** (`test_taskstore.py::_meta`). Unavoidable once `say`/`show` are first-class on `on enter|pass` (brief decision 3): the persisted form must encode the action kind, so the 2B exec-value-string tuples become tagged-dict/`Action` tuples. Presented as a necessary, localized edit (like the Task-2 reserved flip).
- **`cmd`-condition hints collapse internal whitespace in their trailing action** (`_parse_cmd_cond` splits on whitespace and re-joins with single spaces). Harmless for shell commands and hint text; `tries`/`idle`/`output` hints preserve the action verbatim. A narrow, documented limitation.
- **`match_rule` is a sibling to `match_hint`** (not a generalization): the two consume different shapes (dict triggers vs typed rules). Stated in Task 3.
- **Matcher/render are explicit in `TaskSession`, not `HookRegistry`** (brief's suggested simpler path; `HookRegistry` untouched). Stated in the header.
- **`show file` resolves under `<hp_dir>/work/<path>`** (the author's hidden assets staged into `/hp`), consistent with the §6 `/hp/work` layout.

**Known-and-accepted:** a hint whose `cmd` base is literally an action verb (`exec`/`say`/`show`) would confuse the condition/action split — not a real shell command, extremely unlikely; documented, fails safe (errors, never misparses). A very large `say`/`exec` reply typed char-by-char is O(n) sink calls — fine at tier1 sizes; large *files* are paged whole, and student output is `instant`.

