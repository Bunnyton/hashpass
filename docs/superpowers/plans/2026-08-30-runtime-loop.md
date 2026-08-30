# Runtime Loop (offline check + background re-verify + hints) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The runtime student loop (§7): silently (invisibly) check the current stage after each command; on accept advance locally and issue the provisional nonce key + evidence (offline-first); a background re-verification upgrades provisional progress to unforgeable global credit when a server is reachable; and interactive hints fire on triggers. Pure, testable logic — no real network/container.

**Architecture:** New `src/hashpass/progress.py` (per-stage status machine + provisional/server reconciliation), `src/hashpass/hints.py` (trigger→message incl. "stuck" detection), `src/hashpass/sync.py` (`SyncClient` protocol + in-process `LocalSyncClient` that enforces Plan E's principal-binding & checks-by-(task_id,stage) pairing, + `background_reverify`), and a rewritten `src/hashpass/play.py` (`capture_candidate` + a `PlaySession` that feeds command events through the invisible check + hints + local advance, with a `.reverify()` step). Consumes Plan D checker/bundle + Plan E grade/keys/server.

**Tech Stack:** Python 3.13, stdlib only (`dataclasses`/`enum`/`pathlib`/`typing`). Consumes in-repo `hashpass.{taskcode.checker, taskcode.bundle, taskcode.derive, taskcode.execute, canon, grade, evidence, server.verify, key}`. NO third-party deps, NO real network/http/container (the production container-poll adapter is out of scope — the loop is driven by an abstract event source, tested with scripted events + a tmpdir rootfs).

**Spec:** `docs/Архитектура (architecture).md` §7 (проверка незаметна; сеть→глобальный/нет-сети→локальный провизорный; фоновая до-сверка; локальный прогресс провизорный, сервер=истина, при расхождении помечаем не откатываем; интерактивность — hints (триггер→сообщение), «застревание» = N команд или T секунд без прогресса), §6 (keys), §9 (threat model), §10 (tiers). Also resolves Plan E deferrals: pair checks by (task_id, stage); bind authenticated principal to evidence.student_id.

## Global Constraints

- Python 3.13; stdlib + in-repo hashpass modules ONLY. No new deps. NO real network/http/sockets, NO systemd-nspawn — the loop consumes an ABSTRACT event source; tests script events over a tmpdir rootfs.
- `encoding="utf-8"` on every I/O.
- ruff `select=["ALL"]` clean incl. tests; module constants for PLR2004; `# noqa: PLR0913` on wide signatures matching the repo convention.
- **Security (carry Plan E forward):** the client NEVER holds `server_secret`. `LocalSyncClient` models the SERVER side (holds the secret) — it is used in tests/dev, not shipped to the client; the client only holds a `SyncClient` handle. `background_reverify`/`submit` MUST (a) pair `bundle.checks.stages[stage]` with the evidence for THAT stage and assert `evidence.task_id == bundle.checks.task_id` before submitting, and (b) reject when `evidence.student_id != authenticated principal`. Local progress is provisional; server is truth; on mismatch mark, never force-rollback.
- src-layout: code in `src/hashpass/`, tests in `tests/`. All tests tier1 (`@pytest.mark.tier1`) — pure logic + `TmpdirRunner`/tmpdir rootfs where a real fs is needed (no containers).

## Scoping guardrails

- **IN:** the pure runtime logic (progress, hints, sync-with-local-server, invisible-check loop) + tier1 tests.
- **OUT (deployment / user's call):** real HTTP transport, network detection, the production container-poll event source (reading `/.hash/.cmd.log` from a live nspawn container) — the loop takes events from an abstract source; do NOT add http/sockets/nspawn.
- **OUT (later/creation tooling):** interactive observe CURATION UX (§3 author-side), the "free transition" manual-skip UX (note it; keep progress simple).
- **Reference (do NOT copy):** dev polled a `/.hash/.hash.status` file for host↔container IPC and had a bare broken `send_statistic`; we REPLACE that with the provisional-then-reverify model + real evidence.

## Interfaces this plan consumes (already in the repo, do not modify)

```python
# hashpass.taskcode.bundle
@dataclass(frozen=True)
class Bundle: checks: DerivedChecks; conditions: dict; hints: dict
def load_bundle(bundle_dir: Path) -> Bundle
# hashpass.taskcode.derive
@dataclass(frozen=True)
class DerivedChecks: task_id: str; stages: tuple[StageChecks, ...]
@dataclass(frozen=True)
class StageChecks: canonical: Observation; mode: str="line"; threshold: float=1.0; k: int=1; size_threshold: int=4096
# hashpass.taskcode.checker
def check_stage(checks: StageChecks, candidate: Observation, *, hooks=None, stage=0, probe_cmd="") -> bool
# hashpass.taskcode.execute
OUTPUT_KEY = "<output>"
# hashpass.canon
@dataclass(frozen=True)
class FileState: kind: str; text: str | None
Observation = dict[str, FileState]
def capture(rootfs: Path, observe: list[str], *, output_path: str | None = None) -> Observation
# hashpass.grade
@dataclass(frozen=True)
class Grade: accepted: bool; local_key: str | None; evidence: Evidence | None
def grade_stage(checks, candidate, *, task_id, stage, student_id, nonce, ts, hooks=None) -> Grade
# hashpass.evidence.Evidence (frozen; .task_id/.stage/.student_id/.candidate/...); build_evidence(...)
# hashpass.server.verify
def issue_global_key(evidence, checks, *, server_secret: bytes) -> str | None
```

Tests rely on the existing `tests/__init__.py` + `tests/conftest.py` (puts `src/` on `sys.path`). No new conftest is needed.

---

### Task 1: `progress.py` — per-stage status machine

**Files:**
- Create: `src/hashpass/progress.py`
- Test: `tests/test_progress.py`

**Interfaces:**
- Consumes: nothing (pure stdlib `dataclasses`/`enum`).
- Produces:
  - `class StageStatus(Enum)` with members `LOCKED="locked"`, `OPEN="open"`, `PASSED_LOCAL="passed_local"`, `PASSED_GLOBAL="passed_global"`.
  - `@dataclass class TaskProgress: task_id: str; statuses: list[StageStatus]`
  - `new_progress(task_id: str, n_stages: int) -> TaskProgress` — stage 0 OPEN, rest LOCKED.
  - `current_stage(progress: TaskProgress) -> int | None` — first OPEN stage index; None once all passed.
  - `mark_passed_local(progress: TaskProgress, stage: int) -> None` — set PASSED_LOCAL, OPEN the next LOCKED stage.
  - `mark_passed_global(progress: TaskProgress, stage: int) -> None` — upgrade to PASSED_GLOBAL (idempotent).
  - `reconcile(progress: TaskProgress, server_passed: set[int]) -> list[int]` — upgrade server-confirmed stages to GLOBAL; return the PASSED_LOCAL-only stages as mismatches (flagged, NOT rolled back).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_progress.py
import pytest

from hashpass.progress import (
    StageStatus,
    current_stage,
    mark_passed_global,
    mark_passed_local,
    new_progress,
    reconcile,
)


@pytest.mark.tier1
def test_new_progress_opens_first_stage_only():
    progress = new_progress("demo", 3)
    assert progress.task_id == "demo"
    assert progress.statuses == [StageStatus.OPEN, StageStatus.LOCKED, StageStatus.LOCKED]
    assert current_stage(progress) == 0


@pytest.mark.tier1
def test_mark_passed_local_advances_and_opens_next():
    progress = new_progress("demo", 2)
    mark_passed_local(progress, 0)
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL
    assert progress.statuses[1] is StageStatus.OPEN
    assert current_stage(progress) == 1
    mark_passed_local(progress, 1)
    assert current_stage(progress) is None  # all passed


@pytest.mark.tier1
def test_mark_passed_global_is_idempotent():
    progress = new_progress("demo", 1)
    mark_passed_local(progress, 0)
    mark_passed_global(progress, 0)
    mark_passed_global(progress, 0)
    assert progress.statuses[0] is StageStatus.PASSED_GLOBAL


@pytest.mark.tier1
def test_reconcile_upgrades_confirmed_and_flags_local_only_without_rollback():
    progress = new_progress("demo", 3)
    mark_passed_local(progress, 0)  # server will confirm
    mark_passed_local(progress, 1)  # server will NOT confirm -> mismatch
    mismatches = reconcile(progress, {0})
    assert mismatches == [1]
    assert progress.statuses[0] is StageStatus.PASSED_GLOBAL   # upgraded
    assert progress.statuses[1] is StageStatus.PASSED_LOCAL    # flagged, NOT rolled back
    assert progress.statuses[2] is StageStatus.OPEN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_progress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.progress'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/progress.py
"""Per-stage progress state machine + provisional/server reconciliation (§7)."""
from dataclasses import dataclass
from enum import Enum


class StageStatus(Enum):
    """Lifecycle of one stage: locked -> open -> passed_local -> passed_global."""

    LOCKED = "locked"
    OPEN = "open"
    PASSED_LOCAL = "passed_local"
    PASSED_GLOBAL = "passed_global"


@dataclass
class TaskProgress:
    """Mutable per-stage progress for one task (stage 0 OPEN, the rest LOCKED at start)."""

    task_id: str
    statuses: list[StageStatus]


def new_progress(task_id: str, n_stages: int) -> TaskProgress:
    """Fresh progress: stage 0 OPEN, the rest LOCKED."""
    statuses = [StageStatus.LOCKED] * n_stages
    if statuses:
        statuses[0] = StageStatus.OPEN
    return TaskProgress(task_id=task_id, statuses=statuses)


def current_stage(progress: TaskProgress) -> int | None:
    """First OPEN stage index; None once every stage is passed."""
    for i, status in enumerate(progress.statuses):
        if status is StageStatus.OPEN:
            return i
    return None


def mark_passed_local(progress: TaskProgress, stage: int) -> None:
    """Mark a stage locally passed and OPEN the next LOCKED stage."""
    progress.statuses[stage] = StageStatus.PASSED_LOCAL
    nxt = stage + 1
    if nxt < len(progress.statuses) and progress.statuses[nxt] is StageStatus.LOCKED:
        progress.statuses[nxt] = StageStatus.OPEN


def mark_passed_global(progress: TaskProgress, stage: int) -> None:
    """Upgrade a stage to PASSED_GLOBAL (idempotent)."""
    progress.statuses[stage] = StageStatus.PASSED_GLOBAL


def reconcile(progress: TaskProgress, server_passed: set[int]) -> list[int]:
    """
    Upgrade server-confirmed stages to GLOBAL; return PASSED_LOCAL-only stages as mismatches.

    Mismatches are flagged (returned), never force-rolled-back. §7.
    """
    mismatches: list[int] = []
    for i, status in enumerate(progress.statuses):
        if i in server_passed:
            mark_passed_global(progress, i)
        elif status is StageStatus.PASSED_LOCAL:
            mismatches.append(i)
    return mismatches
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_progress.py -v` (Expected: PASS), then `ruff check src tests runtime` (Expected: clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/progress.py tests/test_progress.py
git commit -m "feat(progress): per-stage status machine + reconcile"
```

---

### Task 2: `hints.py` — trigger→message + stuck detection

**Files:**
- Create: `src/hashpass/hints.py`
- Test: `tests/test_hints.py`

**Interfaces:**
- Consumes: nothing (pure stdlib `dataclasses`).
- Produces:
  - Module constants `_STUCK_CMDS = 5`, `_STUCK_SECS = 120.0`.
  - `@dataclass class StuckState: commands_since_progress: int = 0; seconds_since_progress: float = 0.0`
  - `match_hint(hints_for_stage: list[dict], *, command: str, output: str, stuck: StuckState, stuck_cmds: int = _STUCK_CMDS, stuck_secs: float = _STUCK_SECS) -> str | None` — each hint is `{"trigger": {...}, "message": str}`; first match wins in list order; trigger kinds checked command→output→stuck: `{"command": <substr>}` → substr in `command`; `{"output": <substr>}` → substr in `output`; `{"stuck": true}` → `commands_since_progress >= stuck_cmds or seconds_since_progress >= stuck_secs`. Returns the matching message, else None.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hints.py
import pytest

from hashpass.hints import StuckState, match_hint

_HINTS = [
    {"trigger": {"command": "rm -rf"}, "message": "careful with rm"},
    {"trigger": {"output": "Permission denied"}, "message": "you need sudo"},
    {"trigger": {"stuck": True}, "message": "try reading the task again"},
]
_STUCK_AT = 5
_SECS_AT = 120.0


@pytest.mark.tier1
def test_command_substring_trigger_fires():
    hint = match_hint(_HINTS, command="rm -rf /", output="", stuck=StuckState())
    assert hint == "careful with rm"


@pytest.mark.tier1
def test_output_substring_trigger_fires():
    hint = match_hint(_HINTS, command="cat x", output="cat: x: Permission denied",
                      stuck=StuckState())
    assert hint == "you need sudo"


@pytest.mark.tier1
def test_stuck_fires_at_threshold_by_commands_or_seconds():
    below = StuckState(commands_since_progress=_STUCK_AT - 1)
    assert match_hint(_HINTS, command="ls", output="", stuck=below) is None
    by_cmds = StuckState(commands_since_progress=_STUCK_AT)
    assert match_hint(_HINTS, command="ls", output="", stuck=by_cmds) == "try reading the task again"
    by_secs = StuckState(seconds_since_progress=_SECS_AT)
    assert match_hint(_HINTS, command="ls", output="", stuck=by_secs) == "try reading the task again"


@pytest.mark.tier1
def test_first_match_wins_in_list_order():
    hints = [
        {"trigger": {"command": "make"}, "message": "first"},
        {"trigger": {"command": "make"}, "message": "second"},
    ]
    assert match_hint(hints, command="make build", output="", stuck=StuckState()) == "first"


@pytest.mark.tier1
def test_no_match_returns_none():
    assert match_hint(_HINTS, command="ls", output="ok", stuck=StuckState()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hints.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.hints'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/hints.py
"""Interactive hints: match a stage's triggers (command / output / stuck) to a message (§7)."""
from dataclasses import dataclass

_STUCK_CMDS = 5
_STUCK_SECS = 120.0


@dataclass
class StuckState:
    """Progress-less streak counters that drive the 'stuck' hint trigger (§7)."""

    commands_since_progress: int = 0
    seconds_since_progress: float = 0.0


def match_hint(hints_for_stage: list[dict], *, command: str, output: str,  # noqa: PLR0913
               stuck: StuckState, stuck_cmds: int = _STUCK_CMDS,
               stuck_secs: float = _STUCK_SECS) -> str | None:
    """
    Return the first matching hint's message (list order), else None. §7.

    Trigger kinds, checked command -> output -> stuck:
      {"command": <substr>} fires when substr is in command;
      {"output": <substr>}  fires when substr is in output;
      {"stuck": true}       fires when commands_since_progress >= stuck_cmds
                            or seconds_since_progress >= stuck_secs.
    """
    stuck_now = (stuck.commands_since_progress >= stuck_cmds
                 or stuck.seconds_since_progress >= stuck_secs)
    for hint in hints_for_stage:
        trigger = hint.get("trigger", {})
        if (("command" in trigger and trigger["command"] in command)
                or ("output" in trigger and trigger["output"] in output)
                or (bool(trigger.get("stuck")) and stuck_now)):
            return hint["message"]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hints.py -v` (Expected: PASS), then `ruff check src tests runtime` (Expected: clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/hints.py tests/test_hints.py
git commit -m "feat(hints): trigger->message + stuck detection"
```

---

### Task 3: `sync.py` — SyncClient + LocalSyncClient + background re-verify

**Files:**
- Create: `src/hashpass/sync.py`
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `Evidence`, `build_evidence` (`hashpass.evidence`); `StageChecks`, `DerivedChecks` (`hashpass.taskcode.derive`); `issue_global_key` (`hashpass.server.verify`); `StageStatus`, `TaskProgress`, `mark_passed_global`, `mark_passed_local`, `new_progress` (`hashpass.progress`, Task 1).
- Produces:
  - `class SyncClient(Protocol)` — `online(self) -> bool`; `submit(self, evidence: Evidence, checks: StageChecks) -> str | None` (global key | None). The client holds only this handle — never `server_secret`.
  - `@dataclass class LocalSyncClient: server_secret: bytes; principal: str; online_flag: bool = True` — models the SERVER side (dev/test only). `online() -> bool` returns `online_flag`; `submit(evidence, checks)` returns `None` when `evidence.student_id != self.principal`, else `issue_global_key(evidence, checks, server_secret=self.server_secret)`.
  - `background_reverify(progress: TaskProgress, evidences: dict[int, Evidence], checks: DerivedChecks, sync: SyncClient) -> list[int]` — offline → `[]`; else for each PASSED_LOCAL stage with an evidence: pair `checks.stages[stage]`, assert `evidence.task_id == checks.task_id` (skip+flag on mismatch), `sync.submit(...)`; on a global key → `mark_passed_global`; on None → flag. Returns the mismatch stages.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync.py
import inspect

import pytest

from hashpass.canon import FileState
from hashpass.evidence import Evidence, build_evidence
from hashpass.progress import StageStatus, TaskProgress, mark_passed_local, new_progress
from hashpass.sync import LocalSyncClient, background_reverify
from hashpass.taskcode.derive import DerivedChecks, StageChecks

_SECRET = b"server-secret-XYZ"
_TS = "2026-08-30T12:00:00Z"
_ANSWER = {"result.txt": FileState("file", "answer")}


def _checks(task_id: str = "demo") -> DerivedChecks:
    stage = StageChecks(canonical=_ANSWER, mode="line", threshold=1.0, k=1)
    return DerivedChecks(task_id=task_id, stages=(stage,))


def _passed_local(task_id: str = "demo") -> TaskProgress:
    progress = new_progress(task_id, 1)
    mark_passed_local(progress, 0)
    return progress


def _evidence(checks: DerivedChecks, candidate, *, student_id="alice", task_id="demo") -> Evidence:
    return build_evidence(checks.stages[0], candidate, task_id=task_id, stage=0,
                          student_id=student_id, nonce="n1", ts=_TS)


@pytest.mark.tier1
def test_online_reverify_upgrades_correct_stage_to_global():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, _ANSWER)
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == []
    assert progress.statuses[0] is StageStatus.PASSED_GLOBAL


@pytest.mark.tier1
def test_forged_candidate_is_rejected_and_flagged():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, {"result.txt": FileState("file", "WRONG")})
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == [0]
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL  # flagged, not upgraded


@pytest.mark.tier1
def test_wrong_principal_is_rejected():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, _ANSWER, student_id="alice")
    sync = LocalSyncClient(server_secret=_SECRET, principal="mallory")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == [0]
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_task_id_mismatch_is_skipped_and_never_signed():
    checks = _checks(task_id="demo")
    progress = _passed_local(task_id="demo")
    # Candidate + principal are correct; ONLY the task_id is wrong -> must be skipped, never signed.
    ev = _evidence(checks, _ANSWER, task_id="other-task")
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == [0]
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_offline_reverify_changes_nothing():
    checks = _checks()
    progress = _passed_local()
    ev = _evidence(checks, _ANSWER)
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice", online_flag=False)
    mismatches = background_reverify(progress, {0: ev}, checks, sync)
    assert mismatches == []
    assert progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_local_sync_client_holds_secret_but_signature_is_narrow():
    # LocalSyncClient models the SERVER; a real client only sees the SyncClient protocol,
    # whose submit/online never expose server_secret.
    params = inspect.signature(background_reverify).parameters
    assert "server_secret" not in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.sync'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/hashpass/sync.py
"""Sync port + in-process server model + background re-verification of provisional progress (§7)."""
from dataclasses import dataclass
from typing import Protocol

from hashpass.evidence import Evidence
from hashpass.progress import StageStatus, TaskProgress, mark_passed_global
from hashpass.server.verify import issue_global_key
from hashpass.taskcode.derive import DerivedChecks, StageChecks


class SyncClient(Protocol):
    """Client-held handle to the server: reachability + a submit that may sign one stage."""

    def online(self) -> bool: ...
    def submit(self, evidence: Evidence, checks: StageChecks) -> str | None: ...


@dataclass
class LocalSyncClient:
    """In-process model of the SERVER side (holds the secret). Dev/test only, never shipped."""

    server_secret: bytes
    principal: str
    online_flag: bool = True

    def online(self) -> bool:
        """Whether the modeled server is reachable."""
        return self.online_flag

    def submit(self, evidence: Evidence, checks: StageChecks) -> str | None:
        """Bind principal to the claimed identity, then re-verify + sign (§6, Plan E #2)."""
        if evidence.student_id != self.principal:
            return None
        return issue_global_key(evidence, checks, server_secret=self.server_secret)


def background_reverify(progress: TaskProgress, evidences: dict[int, Evidence],
                        checks: DerivedChecks, sync: SyncClient) -> list[int]:
    """Upgrade correctly-passed local stages to global credit; flag the rest. Offline -> no-op. §7."""
    if not sync.online():
        return []
    mismatches: list[int] = []
    for stage in sorted(evidences):
        if progress.statuses[stage] is not StageStatus.PASSED_LOCAL:
            continue
        evidence = evidences[stage]
        if evidence.task_id != checks.task_id:   # never sign against the wrong task
            mismatches.append(stage)
            continue
        gkey = sync.submit(evidence, checks.stages[stage])   # pair checks by (task_id, stage)
        if gkey is not None:
            mark_passed_global(progress, stage)
        else:
            mismatches.append(stage)
    return mismatches
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sync.py -v` (Expected: PASS), then `ruff check src tests runtime` (Expected: clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/sync.py tests/test_sync.py
git commit -m "feat(sync): SyncClient + LocalSyncClient + background reverify"
```

---

### Task 4: `play.py` REWRITE — capture_candidate + PlaySession

**Files:**
- Modify (full rewrite): `src/hashpass/play.py`
- Delete: `tests/test_play_tmpdir.py`, `tests/integration/test_walking_skeleton.py` (both exercise the removed walking-skeleton `play(runner, task_dir, *, nonce)` stub)
- Test: `tests/test_play.py`

**Interfaces:**
- Consumes: `FileState`, `Observation`, `capture` (`hashpass.canon`); `grade_stage` (`hashpass.grade`); `StuckState`, `match_hint` (`hashpass.hints`, Task 2); `TaskProgress`, `current_stage`, `mark_passed_local`, `new_progress`, `StageStatus` (`hashpass.progress`, Task 1); `SyncClient`, `background_reverify`, `LocalSyncClient` (`hashpass.sync`, Task 3); `Bundle` (`hashpass.taskcode.bundle`); `DerivedChecks`, `StageChecks` (`hashpass.taskcode.derive`); `OUTPUT_KEY` (`hashpass.taskcode.execute`); `Evidence` (`hashpass.evidence`, type-only).
- Produces:
  - `capture_candidate(rootfs: Path, checks: StageChecks, last_output: str) -> Observation` — capture only the file-path keys of `checks.canonical` (OUTPUT_KEY excluded), then set `candidate[OUTPUT_KEY] = FileState("file", last_output)`.
  - `@dataclass class FeedResult: advanced: bool; stage: int | None; local_key: str | None; hint: str | None`
  - `class PlaySession` — `__init__(self, bundle: Bundle, progress: TaskProgress, *, student_id: str, nonce: str)` holding `evidences: dict[int, Evidence]` and a `StuckState`; `feed(self, *, command: str, rootfs: Path, last_output: str, ts: str, hooks=None) -> FeedResult`; `reverify(self, sync: SyncClient) -> list[int]`.

  Note (decision beyond the brief): `feed` uses the stage that was current at the *start* of the command for both the returned `FeedResult.stage` and the hint lookup (`bundle.hints.get(stage, [])`) — this is the "s_or_current" the brief left open; on an accept, `stuck` is reset first so a stuck-hint cannot fire on the passing command. `feed` bumps `stuck.commands_since_progress` only on a real rejection (never when all stages are already passed).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_play.py
import pytest

from hashpass.canon import FileState
from hashpass.play import FeedResult, PlaySession, capture_candidate
from hashpass.progress import StageStatus, new_progress
from hashpass.sync import LocalSyncClient
from hashpass.taskcode.bundle import Bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskcode.execute import OUTPUT_KEY

_SECRET = b"server-secret-XYZ"
_TS = "2026-08-30T12:00:00Z"


def _stage(canonical) -> StageChecks:
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


def _bundle(hints=None) -> Bundle:
    checks = DerivedChecks(task_id="demo", stages=(
        _stage({"result.txt": FileState("file", "answer")}),
    ))
    return Bundle(checks=checks, conditions={}, hints=hints or {})


@pytest.mark.tier1
def test_capture_candidate_reads_canonical_files_and_folds_output(tmp_path):
    (tmp_path / "result.txt").write_text("answer", encoding="utf-8")
    checks = _stage({"result.txt": FileState("file", "answer"),
                     OUTPUT_KEY: FileState("file", "")})
    candidate = capture_candidate(tmp_path, checks, "hello stdout")
    assert candidate["result.txt"] == FileState("file", "answer")
    assert candidate[OUTPUT_KEY] == FileState("file", "hello stdout")


@pytest.mark.tier1
def test_feed_advances_on_correct_state_and_issues_local_key(tmp_path):
    session = PlaySession(_bundle(), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("answer", encoding="utf-8")
    result = session.feed(command="echo answer > result.txt", rootfs=tmp_path,
                          last_output="answer", ts=_TS)
    assert isinstance(result, FeedResult)
    assert result.advanced is True
    assert result.stage == 0
    assert result.local_key is not None
    assert result.local_key.startswith("key{")
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL
    assert 0 in session.evidences


@pytest.mark.tier1
def test_feed_does_not_advance_on_wrong_state_and_bumps_stuck(tmp_path):
    session = PlaySession(_bundle(), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("WRONG", encoding="utf-8")
    result = session.feed(command="echo WRONG > result.txt", rootfs=tmp_path,
                          last_output="WRONG", ts=_TS)
    assert result.advanced is False
    assert result.local_key is None
    assert session.progress.statuses[0] is StageStatus.OPEN
    assert session.stuck.commands_since_progress == 1


@pytest.mark.tier1
def test_feed_fires_matching_hint(tmp_path):
    hints = {0: [{"trigger": {"command": "sudo"}, "message": "no sudo needed"}]}
    session = PlaySession(_bundle(hints), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("nope", encoding="utf-8")
    result = session.feed(command="sudo rm x", rootfs=tmp_path, last_output="", ts=_TS)
    assert result.advanced is False
    assert result.hint == "no sudo needed"


@pytest.mark.tier1
def test_reverify_upgrades_local_pass_to_global(tmp_path):
    session = PlaySession(_bundle(), new_progress("demo", 1),
                          student_id="alice", nonce="n1")
    (tmp_path / "result.txt").write_text("answer", encoding="utf-8")
    session.feed(command="echo answer > result.txt", rootfs=tmp_path,
                 last_output="answer", ts=_TS)
    sync = LocalSyncClient(server_secret=_SECRET, principal="alice")
    mismatches = session.reverify(sync)
    assert mismatches == []
    assert session.progress.statuses[0] is StageStatus.PASSED_GLOBAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_play.py -v`
Expected: FAIL — `ImportError: cannot import name 'capture_candidate' from 'hashpass.play'` (the current stub only exports `play`).

- [ ] **Step 3: Write minimal implementation (rewrite + remove obsolete tests)**

Replace `src/hashpass/play.py` in full:

```python
# src/hashpass/play.py
"""Runtime student loop: invisible check + local advance + hints + background re-verify (§7)."""
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hashpass.canon import FileState, Observation, capture
from hashpass.grade import grade_stage
from hashpass.hints import StuckState, match_hint
from hashpass.progress import TaskProgress, current_stage, mark_passed_local
from hashpass.sync import SyncClient, background_reverify
from hashpass.taskcode.bundle import Bundle
from hashpass.taskcode.derive import StageChecks
from hashpass.taskcode.execute import OUTPUT_KEY

if TYPE_CHECKING:
    from hashpass.evidence import Evidence


def capture_candidate(rootfs: Path, checks: StageChecks, last_output: str) -> Observation:
    """
    Rebuild a comparable candidate from the student's live rootfs + last command output.

    Captures only the file-path keys of the canonical (OUTPUT_KEY excluded), then folds the
    student's last stdout in under OUTPUT_KEY. `matches` reads only canonical keys.
    """
    observe = [key for key in checks.canonical if key != OUTPUT_KEY]
    candidate = capture(rootfs, observe)
    candidate[OUTPUT_KEY] = FileState("file", last_output)
    return candidate


@dataclass
class FeedResult:
    """Outcome of feeding one command event through the invisible check + hints."""

    advanced: bool
    stage: int | None
    local_key: str | None
    hint: str | None


class PlaySession:
    """Drive one task's runtime loop: invisible check, local advance, hints, re-verify."""

    def __init__(self, bundle: Bundle, progress: TaskProgress, *,
                 student_id: str, nonce: str) -> None:
        """Start a play session over a task's bundle + mutable progress."""
        self.bundle = bundle
        self.progress = progress
        self.student_id = student_id
        self.nonce = nonce
        self.evidences: dict[int, Evidence] = {}
        self.stuck = StuckState()

    def feed(self, *, command: str, rootfs: Path, last_output: str,
             ts: str, hooks=None) -> FeedResult:
        """Invisibly check the current stage; on accept advance locally + issue a local key."""
        stage = current_stage(self.progress)
        advanced = False
        local_key = None
        if stage is not None:
            checks = self.bundle.checks.stages[stage]
            candidate = capture_candidate(rootfs, checks, last_output)
            grade = grade_stage(checks, candidate, task_id=self.bundle.checks.task_id,
                                stage=stage, student_id=self.student_id, nonce=self.nonce,
                                ts=ts, hooks=hooks)
            if grade.accepted:
                self.evidences[stage] = grade.evidence
                mark_passed_local(self.progress, stage)
                self.stuck = StuckState()
                advanced = True
                local_key = grade.local_key
            else:
                self.stuck.commands_since_progress += 1
        hint = match_hint(self.bundle.hints.get(stage, []), command=command,
                          output=last_output, stuck=self.stuck)
        return FeedResult(advanced=advanced, stage=stage, local_key=local_key, hint=hint)

    def reverify(self, sync: SyncClient) -> list[int]:
        """Background up-verification of provisional local passes against the server. §7."""
        return background_reverify(self.progress, self.evidences, self.bundle.checks, sync)
```

Then delete the two tests that import the removed stub:

```bash
git rm tests/test_play_tmpdir.py tests/integration/test_walking_skeleton.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_play.py -v` (Expected: PASS), then `pytest -q -m tier1` (Expected: green — the whole tier1 suite still collects after the stub + its two tests were removed), then `ruff check src tests runtime` (Expected: clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/play.py tests/test_play.py
git commit -m "feat(play): capture_candidate + PlaySession invisible-check loop"
```

---

### Task 5: integration spine — `tests/test_runtime_loop.py`

**Files:**
- Test: `tests/test_runtime_loop.py`

**Interfaces:**
- Consumes: `FileState` (`hashpass.canon`); `_STUCK_CMDS` (`hashpass.hints`); `FeedResult`, `PlaySession` (`hashpass.play`, Task 4); `StageStatus`, `new_progress` (`hashpass.progress`); `LocalSyncClient` (`hashpass.sync`); `Bundle` (`hashpass.taskcode.bundle`); `DerivedChecks`, `StageChecks` (`hashpass.taskcode.derive`).

**LOAD-BEARING SPINE:** this is a genuine end-to-end spine over a real tmpdir rootfs. The negative assertions are the point: a stub that always advances must FAIL `test_offline_correct_advances_and_wrong_stays_locked`, and a `reverify` that signs without server re-verification (or without principal binding) must FAIL `test_forged_evidence_is_not_upgraded` / `test_wrong_principal_is_not_upgraded`. If, while implementing, one of these can only be made green by weakening an assertion, STOP and report — it means the loop lost its guarantee, not that the test is wrong.

- [ ] **Step 1: Write the spine test**

```python
# tests/test_runtime_loop.py
import dataclasses

import pytest

from hashpass.canon import FileState
from hashpass.hints import _STUCK_CMDS
from hashpass.play import FeedResult, PlaySession
from hashpass.progress import StageStatus, new_progress
from hashpass.sync import LocalSyncClient
from hashpass.taskcode.bundle import Bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks

_SECRET = b"server-secret-XYZ"
_TS = "2026-08-30T12:00:00Z"
_STUCK_MSG = "stuck on stage two"


def _stage(canonical) -> StageChecks:
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


def _bundle() -> Bundle:
    checks = DerivedChecks(task_id="demo", stages=(
        _stage({"s0.txt": FileState("file", "zero")}),
        _stage({"s1.txt": FileState("file", "one")}),
    ))
    hints = {1: [{"trigger": {"stuck": True}, "message": _STUCK_MSG}]}
    return Bundle(checks=checks, conditions={}, hints=hints)


def _session() -> PlaySession:
    return PlaySession(_bundle(), new_progress("demo", 2), student_id="alice", nonce="n1")


def _solve(session, rootfs, name, text) -> FeedResult:
    (rootfs / name).write_text(text, encoding="utf-8")
    return session.feed(command=f"echo {text} > {name}", rootfs=rootfs,
                        last_output=text, ts=_TS)


@pytest.mark.tier1
def test_offline_correct_advances_and_wrong_stays_locked(tmp_path):
    session = _session()
    # Wrong state (no s0.txt): must NOT advance, no key, stage stays OPEN.
    wrong = session.feed(command="ls", rootfs=tmp_path, last_output="", ts=_TS)
    assert wrong.advanced is False
    assert wrong.local_key is None
    assert session.progress.statuses[0] is StageStatus.OPEN
    # Correct state: advances offline + issues a local key.
    ok = _solve(session, tmp_path, "s0.txt", "zero")
    assert ok.advanced is True
    assert ok.local_key.startswith("key{")
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL


@pytest.mark.tier1
def test_stuck_sequence_fires_stuck_hint_and_keeps_stage_locked(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")   # advance to stage 1, resets stuck
    result = None
    for _ in range(_STUCK_CMDS):
        result = session.feed(command="ls", rootfs=tmp_path, last_output="", ts=_TS)
    assert result.hint == _STUCK_MSG
    assert result.advanced is False
    assert session.progress.statuses[1] is StageStatus.OPEN   # no key, still locked


@pytest.mark.tier1
def test_offline_then_online_reverify_upgrades_all(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")
    _solve(session, tmp_path, "s1.txt", "one")
    assert session.progress.statuses == [StageStatus.PASSED_LOCAL, StageStatus.PASSED_LOCAL]
    # Offline background re-verify changes nothing.
    offline = LocalSyncClient(server_secret=_SECRET, principal="alice", online_flag=False)
    assert session.reverify(offline) == []
    assert session.progress.statuses == [StageStatus.PASSED_LOCAL, StageStatus.PASSED_LOCAL]
    # Online re-verify with the authenticated principal upgrades both to global credit.
    online = LocalSyncClient(server_secret=_SECRET, principal="alice")
    assert session.reverify(online) == []
    assert session.progress.statuses == [StageStatus.PASSED_GLOBAL, StageStatus.PASSED_GLOBAL]


@pytest.mark.tier1
def test_forged_evidence_is_not_upgraded(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")
    # Forge the stored evidence: swap in a candidate the server will reject.
    session.evidences[0] = dataclasses.replace(
        session.evidences[0], candidate={"s0.txt": FileState("file", "FORGED")})
    online = LocalSyncClient(server_secret=_SECRET, principal="alice")
    assert session.reverify(online) == [0]
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL   # flagged, not upgraded


@pytest.mark.tier1
def test_wrong_principal_is_not_upgraded(tmp_path):
    session = _session()
    _solve(session, tmp_path, "s0.txt", "zero")
    impostor = LocalSyncClient(server_secret=_SECRET, principal="mallory")
    assert session.reverify(impostor) == [0]
    assert session.progress.statuses[0] is StageStatus.PASSED_LOCAL
```

- [ ] **Step 2: Run the spine (all modules exist by now → must PASS)**

Run: `pytest tests/test_runtime_loop.py -v` (Expected: PASS — 5 tests), then `pytest -q -m tier1` (Expected: whole tier1 suite green) and `ruff check src tests runtime` (Expected: clean). Sanity-check that the spine is load-bearing: temporarily forcing `feed` to always advance, or making `reverify` sign without calling the server, MUST turn these tests red.

- [ ] **Step 3: Commit**

```bash
git add tests/test_runtime_loop.py
git commit -m "test(runtime): offline->online loop spine (advance + no-forge load-bearing)"
```

---

## Out of scope (future plans)

- **Real transport / network detection.** `SyncClient` is a protocol; a real HTTP/registry adapter (with auth of the principal) is the user's deployment call — do NOT add http/sockets here.
- **Production container-poll event source.** Reading `/.hash/.cmd.log` from a live `systemd-nspawn` container and turning it into `feed(...)` events is the tier3 driver — this plan drives `feed` from scripted events + a tmpdir rootfs only.
- **"Free transition" manual-skip UX** (§7 fallback) and **interactive observe curation UX** (§3 author-side) — noted; progress stays a simple linear machine.
- **Persisting `TaskProgress`/evidences across runs** — in-memory only here.

## Self-Review (run against the spec before handing off)

- **§7 coverage:** invisible check → `PlaySession.feed` (Task 4); network→global / no-network→local-provisional → `background_reverify` offline `[]` vs online upgrade (Tasks 3+5); фоновая до-сверка → `reverify`/`background_reverify` (Tasks 3–5); provisional, server=truth, mismatch flags-not-rollback → `reconcile` + `background_reverify` return-lists (Tasks 1,3,5); hints (trigger→message) + stuck (N cmds OR T secs) → `match_hint` (Task 2). **§6:** local nonce key issued on accept, `server_secret` only on the modeled server, global key via `issue_global_key` (Tasks 3–4). **§9/§10:** unforgeable, identity-bound credit re-verified server-side (forged/wrong-principal rejected, Tasks 3,5); all tests tier1, no containers, tmpdir rootfs only.
- **Plan E deferrals resolved:** checks paired by (task_id, stage) and `evidence.task_id == checks.task_id` asserted before signing (`background_reverify`, Task 3); authenticated principal bound to `evidence.student_id` (`LocalSyncClient.submit`, Task 3). Verified load-bearing by `test_task_id_mismatch_is_skipped_and_never_signed`, `test_wrong_principal_is_rejected`, and the Task 5 spine.
- **Placeholder scan:** none — every step carries runnable code and an exact command.
- **Type consistency:** `StageStatus`/`TaskProgress`/`current_stage`/`mark_passed_local`/`mark_passed_global`/`reconcile` (Task 1) are used with identical names/signatures by Tasks 3–5; `StuckState`/`match_hint`/`_STUCK_CMDS` (Task 2) by Tasks 4–5; `SyncClient`/`LocalSyncClient`/`background_reverify` (Task 3) by Tasks 4–5; `capture_candidate`/`FeedResult`/`PlaySession` (Task 4) by Task 5. `Evidence`/`StageChecks`/`DerivedChecks`/`Bundle`/`grade_stage`/`issue_global_key`/`OUTPUT_KEY`/`FileState`/`capture` match the in-repo signatures listed above.
