# Two-Tier Keys + Evidence + Server Re-Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two-tier credential layer on top of the acceptance pipeline: a forgeable local progress key (nonce, already exists), an UNFORGEABLE global key the server issues by RE-VERIFYING per-stage evidence and HMAC-signing it, and the Evidence record itself. All pure logic — no network, no deploy.

**Architecture:** Extend `src/hashpass/key.py` with `global_key` (HMAC). New `src/hashpass/evidence.py` (per-stage Evidence record + build + JSON serialization). New `src/hashpass/server/verify.py` (server RE-VERIFIES a candidate's evidence against the reference `StageChecks` using the SAME pinned comparator, then signs the global key — or refuses). New `src/hashpass/grade.py` (client-side: compose Plan-D `check_stage` + `local_key` + `build_evidence` into one `grade_stage`). The server is PURE FUNCTIONS (verify + sign); HTTP transport and the offline/online loop are explicitly Plan F.

**Tech Stack:** Python 3.13, stdlib only (`hmac`/`hashlib`/`json`/`dataclasses`; `ts` is a caller-supplied ISO-8601 string, so no wall-clock/`datetime` call in the logic). Consumes in-repo `hashpass.taskcode.{derive,checker}`, `hashpass.canon`, `hashpass.key`. NO third-party deps, NO network/http.

**Spec:** `docs/Архитектура (architecture).md` §6 (ключи два уровня + evidence), §7 (проверка/прогресс — local provisional, server truth), §9 (threat model — we do NOT prove the student personally typed; copying the distributed reference is accepted; we DO guarantee result-within-threshold + unforgeable identity-bound credit), §10 (tiers).

## Global Constraints

- Python 3.13; stdlib + in-repo `hashpass.{taskcode,canon,key,compare}` ONLY. No new deps. NO network, NO http server, NO touching the real server (185.212.148.108) — this plan is pure credential LOGIC.
- `encoding="utf-8"` on every text/JSON I/O.
- ruff `select=["ALL"]` clean incl. tests; module constants instead of bare literals where PLR2004 trips.
- **Security invariants (§6, MUST hold):** the `server_secret` is a SERVER-ONLY input — it appears ONLY in `server/verify.py` signing + tests; NO client-side function (`grade_stage`, `local_key`, `build_evidence`) takes or emits it. The local key is a NONCE (already so) — NOT derived from the candidate/acceptance hash. Nothing materializes a key or secret into an overlay/rootfs/readme (Plan E writes no files into any rootfs). No shared master key anywhere.
- src-layout: code in `src/hashpass/` (+ new `src/hashpass/server/` package), tests in `tests/` and `tests/server/` (add `__init__.py`). All tests tier1 (`@pytest.mark.tier1`), pure (no runner needed — build Observations/StageChecks directly as literals).

**Repo commands (from CI):** lint `ruff check src tests runtime`; full test `pytest -q -m "not tier3"` (tier1 runs by default — `addopts = -m 'not tier3'`). Targeted per-step runs use `pytest <path> -v`.

**Decisions beyond the brief (kept minimal, consistent with the pinned signatures):**
- `key.py` imports are written as two sorted lines (`import hashlib` / `import hmac`) rather than the brief's illustrative `import hmac, hashlib` — the one-line form trips ruff `E401`/`I001`. Behaviour is identical.
- `build_evidence` and `grade_stage` carry 8 parameters each → ruff `PLR0913` (>5 args). Each keeps a scoped `# noqa: PLR0913` on its `def` line (the same convention `hashpass.compare.similarity` already uses). No public behaviour change.
- `server/verify.py` and `grade.py` import the type names they annotate (`Evidence`, `StageChecks`, `Observation`); the brief's snippets used these in signatures without listing the imports. Required for runnability / ruff `F821`.
- Near-miss comparator fixtures use the REAL `hashpass.compare.similarity` values: in `mode="line"` it is Jaccard over the line-set, so `"a\nb\nc"` vs `"a\nb\nc\nd"` = 0.75 and vs `"a\nb\nX"` = 0.5. Tests pin `threshold=0.6` so 0.75 verifies and 0.5 is refused. (The value is measured, not assumed.)

---

### Task 1: `key.global_key` (HMAC)

**Files:**
- Modify: `src/hashpass/key.py`
- Test: `tests/test_key_global.py`

**Interfaces:**
- Consumes: stdlib `hmac`, `hashlib`. Existing `local_key(task_id: str, stage: int, nonce: str) -> str` stays unchanged.
- Produces:
  - `global_key(server_secret: bytes, student_id: str, task_id: str) -> str` — returns `"gkey{" + HMAC_SHA256(server_secret, student_id + b"\x00" + task_id).hexdigest() + "}"` (§6). Deterministic; unforgeable without `server_secret`; identity-bound (student_id) with a NUL delimiter so `(student_id, task_id)` cannot collide by concatenation.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_key_global.py
import pytest

from hashpass.key import global_key, local_key

_SECRET = b"server-secret-XYZ"
_OTHER_SECRET = b"different-secret"


@pytest.mark.tier1
def test_global_key_deterministic():
    first = global_key(_SECRET, "alice", "task1")
    second = global_key(_SECRET, "alice", "task1")
    assert first == second
    assert first.startswith("gkey{")


@pytest.mark.tier1
def test_global_key_requires_secret():
    # Unforgeable: a different server_secret yields a different key.
    assert global_key(_SECRET, "alice", "task1") != global_key(_OTHER_SECRET, "alice", "task1")


@pytest.mark.tier1
def test_global_key_identity_bound_and_nul_delimited():
    assert global_key(_SECRET, "alice", "task1") != global_key(_SECRET, "bob", "task1")
    # NUL delimiter prevents (student_id || task_id) concatenation collisions.
    assert global_key(_SECRET, "al", "icetask") != global_key(_SECRET, "alice", "task")


@pytest.mark.tier1
def test_local_key_unchanged_distinct_namespace():
    lk = local_key("task1", 0, "nonce1")
    assert lk.startswith("key{")
    assert not lk.startswith("gkey{")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_key_global.py -v`
Expected: FAIL — `ImportError: cannot import name 'global_key' from 'hashpass.key'`.

- [ ] **Step 3: Add `global_key` to `key.py` (keep `local_key` unchanged)**

```python
# src/hashpass/key.py
import hashlib
import hmac

_GKEY_ALGO = hashlib.sha256


def local_key(task_id: str, stage: int, nonce: str) -> str:
    """
    Generate a deterministic progress key from task_id, stage, and nonce.

    Format: key{<hex16>}
    """
    d = hashlib.sha256(f"{task_id}|{stage}|{nonce}".encode("utf-8")).digest()
    return "key{" + d[:8].hex() + "}"


def global_key(server_secret: bytes, student_id: str, task_id: str) -> str:
    """Unforgeable global credit: HMAC(server_secret, student_id || NUL || task_id). §6."""
    msg = student_id.encode("utf-8") + b"\x00" + task_id.encode("utf-8")
    return "gkey{" + hmac.new(server_secret, msg, _GKEY_ALGO).hexdigest() + "}"
```

- [ ] **Step 4: Run tests + lint to verify green**

Run: `pytest tests/test_key_global.py -v` (PASS), `ruff check src tests runtime` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/key.py tests/test_key_global.py
git commit -m "feat(key): unforgeable global_key (HMAC over student_id||NUL||task_id)"
```

---

### Task 2: Evidence record + build + JSON

**Files:**
- Create: `src/hashpass/evidence.py`
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `hashpass.canon.FileState(kind: str, text: str | None)`, `hashpass.canon.Observation = dict[str, FileState]`; `hashpass.taskcode.derive.StageChecks(canonical: Observation, mode: str = "line", threshold: float = 1.0, k: int = 1, size_threshold: int = 4096)`.
- Produces:
  - `@dataclass(frozen=True) Evidence(task_id: str, stage: int, student_id: str, nonce: str, ts: str, kind: str, candidate: Observation, mode: str, threshold: float, k: int)`.
  - `build_evidence(checks: StageChecks, candidate: Observation, *, task_id: str, stage: int, student_id: str, nonce: str, ts: str, kind: str = "fuzzy") -> Evidence` — stores the candidate and COPIES the pinned comparator params (`mode`/`threshold`/`k`) FROM `checks` so the server later verifies with the same comparator (§5). `ts` is caller-supplied — never read from the wall clock inside the logic (deterministic/testable).
  - `evidence_to_json(ev: Evidence) -> str` — `json.dumps`; `Observation -> {path: {kind, text}}`.
  - `evidence_from_json(s: str) -> Evidence` — reconstruct incl. `FileState` (JSON `null` → `text=None`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_evidence.py
import pytest

from hashpass.canon import FileState
from hashpass.evidence import build_evidence, evidence_from_json, evidence_to_json
from hashpass.taskcode.derive import StageChecks

_TS = "2026-08-30T12:00:00Z"
_THRESHOLD = 0.75
_K = 2
_STAGE = 3


def _checks() -> StageChecks:
    canonical = {"result.txt": FileState("file", "answer")}
    return StageChecks(canonical=canonical, mode="line", threshold=_THRESHOLD, k=_K)


@pytest.mark.tier1
def test_build_evidence_copies_comparator_and_candidate():
    checks = _checks()
    candidate = {"result.txt": FileState("file", "answer")}
    ev = build_evidence(checks, candidate, task_id="task1", stage=_STAGE,
                        student_id="alice", nonce="n1", ts=_TS)
    assert ev.candidate == candidate
    assert ev.mode == "line"
    assert ev.threshold == _THRESHOLD  # copied from checks, not defaulted
    assert ev.k == _K
    assert ev.kind == "fuzzy"
    assert ev.stage == _STAGE
    assert ev.ts == _TS


@pytest.mark.tier1
def test_evidence_json_round_trip_with_null_filestate():
    checks = _checks()
    candidate = {"result.txt": FileState("file", "answer"),
                 "d": FileState("dir", None)}
    ev = build_evidence(checks, candidate, task_id="task1", stage=0,
                        student_id="alice", nonce="n1", ts=_TS)
    again = evidence_from_json(evidence_to_json(ev))
    assert again == ev
    assert again.candidate["d"] == FileState("dir", None)  # FileState(None) via JSON null
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.evidence'`.

- [ ] **Step 3: Write `evidence.py`**

```python
# src/hashpass/evidence.py
"""Per-stage Evidence record: the student's captured signature + pinned comparator params (§6)."""
import json
from dataclasses import dataclass

from hashpass.canon import FileState, Observation
from hashpass.taskcode.derive import StageChecks


@dataclass(frozen=True)
class Evidence:
    """Per-stage acceptance evidence the server re-verifies before signing the global key (§6)."""

    task_id: str
    stage: int
    student_id: str
    nonce: str
    ts: str
    kind: str
    candidate: Observation
    mode: str
    threshold: float
    k: int


def build_evidence(checks: StageChecks, candidate: Observation, *, task_id: str,  # noqa: PLR0913
                   stage: int, student_id: str, nonce: str, ts: str,
                   kind: str = "fuzzy") -> Evidence:
    """Snapshot the candidate + copy the pinned comparator params (mode/threshold/k) from checks."""
    return Evidence(
        task_id=task_id,
        stage=stage,
        student_id=student_id,
        nonce=nonce,
        ts=ts,
        kind=kind,
        candidate=candidate,
        mode=checks.mode,
        threshold=checks.threshold,
        k=checks.k,
    )


def evidence_to_json(ev: Evidence) -> str:
    """Serialize Evidence to JSON; Observation -> {path: {kind, text}}."""
    return json.dumps({
        "task_id": ev.task_id,
        "stage": ev.stage,
        "student_id": ev.student_id,
        "nonce": ev.nonce,
        "ts": ev.ts,
        "kind": ev.kind,
        "candidate": {path: {"kind": fs.kind, "text": fs.text}
                      for path, fs in ev.candidate.items()},
        "mode": ev.mode,
        "threshold": ev.threshold,
        "k": ev.k,
    })


def evidence_from_json(s: str) -> Evidence:
    """Reconstruct Evidence (incl. FileState) from JSON."""
    d = json.loads(s)
    candidate = {path: FileState(fs["kind"], fs["text"])
                 for path, fs in d["candidate"].items()}
    return Evidence(
        task_id=d["task_id"],
        stage=d["stage"],
        student_id=d["student_id"],
        nonce=d["nonce"],
        ts=d["ts"],
        kind=d["kind"],
        candidate=candidate,
        mode=d["mode"],
        threshold=d["threshold"],
        k=d["k"],
    )
```

- [ ] **Step 4: Run tests + lint to verify green**

Run: `pytest tests/test_evidence.py -v` (PASS), `ruff check src tests runtime` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/evidence.py tests/test_evidence.py
git commit -m "feat(evidence): per-stage Evidence record + build + JSON round-trip"
```

---

### Task 3: `server/verify.py` — re-verify + sign

**Files:**
- Create: `src/hashpass/server/__init__.py` (empty package marker)
- Create: `src/hashpass/server/verify.py`
- Create: `tests/server/__init__.py` (empty)
- Test: `tests/server/test_verify.py`

**Interfaces:**
- Consumes: `Evidence` (Task 2); `hashpass.canon.matches(canonical, candidate, *, threshold=1.0, mode="line", k=1) -> bool` (returns `False` on empty canonical); `hashpass.key.global_key` (Task 1); `StageChecks` (Plan D).
- Produces:
  - `verify_evidence(evidence: Evidence, checks: StageChecks) -> bool` — server-side RE-VERIFICATION: recompute acceptance from the submitted candidate against the reference `checks.canonical` using the SERVER's reference `checks.mode/threshold/k` (§6/§5).
  - `issue_global_key(evidence: Evidence, checks: StageChecks, *, server_secret: bytes) -> str | None` — verify, then HMAC-sign the identity-bound global key; `None` if verification fails.

**Security design note (state and enforce):** `verify_evidence` uses the SERVER's reference `checks.mode/threshold/k`, NOT the client-echoed `evidence.mode/threshold/k`. A client cannot widen its own threshold — the echoed fields are informational only. `server_secret` appears ONLY here (and this test); it never reaches a client-side function.

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_verify.py
from dataclasses import replace

import pytest

from hashpass.canon import FileState
from hashpass.evidence import Evidence, build_evidence
from hashpass.key import global_key
from hashpass.server.verify import issue_global_key, verify_evidence
from hashpass.taskcode.derive import StageChecks

_SECRET = b"server-only-secret"
_TS = "2026-08-30T12:00:00Z"
_THRESHOLD = 0.6
_WIDE_OPEN = 0.0


def _checks() -> StageChecks:
    canonical = {"out": FileState("file", "a\nb\nc")}
    return StageChecks(canonical=canonical, mode="line", threshold=_THRESHOLD, k=1)


def _evidence(candidate, checks) -> Evidence:
    return build_evidence(checks, candidate, task_id="task1", stage=0,
                          student_id="alice", nonce="n1", ts=_TS)


@pytest.mark.tier1
def test_correct_evidence_verifies_and_issues_key():
    checks = _checks()
    ev = _evidence({"out": FileState("file", "a\nb\nc")}, checks)
    assert verify_evidence(ev, checks)
    key = issue_global_key(ev, checks, server_secret=_SECRET)
    assert key == global_key(_SECRET, "alice", "task1")
    assert key.startswith("gkey{")


@pytest.mark.tier1
def test_wrong_evidence_refused():
    checks = _checks()
    ev = _evidence({"out": FileState("file", "X\nY\nZ")}, checks)
    assert not verify_evidence(ev, checks)
    assert issue_global_key(ev, checks, server_secret=_SECRET) is None


@pytest.mark.tier1
def test_comparator_threshold_honored():
    checks = _checks()  # threshold 0.6, line mode (Jaccard over lines)
    near = _evidence({"out": FileState("file", "a\nb\nc\nd")}, checks)  # Jaccard 3/4 = 0.75
    assert verify_evidence(near, checks)
    far = _evidence({"out": FileState("file", "a\nb\nX")}, checks)  # Jaccard 2/4 = 0.5
    assert not verify_evidence(far, checks)


@pytest.mark.tier1
def test_server_uses_own_checks_not_client_echoed_fields():
    strict = _checks()  # server reference: threshold 0.6
    ev = _evidence({"out": FileState("file", "X\nY\nZ")}, strict)  # WRONG candidate
    # Attacker widens the ECHOED comparator to trivially accept anything.
    forged = replace(ev, threshold=_WIDE_OPEN)
    # Server re-verifies with its OWN reference checks (0.6), ignoring evidence.* → still refused.
    assert not verify_evidence(forged, strict)
    assert issue_global_key(forged, strict, server_secret=_SECRET) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.server'`.

- [ ] **Step 3: Create the `server` package + `verify.py`**

Create the empty package markers first:

```bash
: > src/hashpass/server/__init__.py
: > tests/server/__init__.py
```

```python
# src/hashpass/server/verify.py
"""Server-side re-verification of evidence + HMAC signing of the global key (§6)."""
from hashpass.canon import matches
from hashpass.evidence import Evidence
from hashpass.key import global_key
from hashpass.taskcode.derive import StageChecks


def verify_evidence(evidence: Evidence, checks: StageChecks) -> bool:
    """Re-verify: recompute acceptance from the submitted candidate against the reference canonical."""
    return matches(checks.canonical, evidence.candidate,
                   threshold=checks.threshold, mode=checks.mode, k=checks.k)


def issue_global_key(evidence: Evidence, checks: StageChecks, *,
                     server_secret: bytes) -> str | None:
    """Verify evidence, then HMAC-sign the identity-bound global key; None if verification fails."""
    if not verify_evidence(evidence, checks):
        return None
    return global_key(server_secret, evidence.student_id, evidence.task_id)
```

- [ ] **Step 4: Run tests + lint to verify green**

Run: `pytest tests/server/test_verify.py -v` (PASS), `ruff check src tests runtime` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/server/__init__.py src/hashpass/server/verify.py tests/server/__init__.py tests/server/test_verify.py
git commit -m "feat(server): re-verify evidence with reference checks, then HMAC-sign global key"
```

---

### Task 4: `grade.py` — client-side compose

**Files:**
- Create: `src/hashpass/grade.py`
- Test: `tests/test_grade.py`

**Interfaces:**
- Consumes: `hashpass.taskcode.checker.check_stage(checks, candidate, *, hooks=None, stage=0, probe_cmd="") -> bool`; `hashpass.key.local_key` (existing); `build_evidence`, `Evidence` (Task 2); `StageChecks`, `Observation`.
- Produces:
  - `@dataclass(frozen=True) Grade(accepted: bool, local_key: str | None, evidence: Evidence | None)`.
  - `grade_stage(checks: StageChecks, candidate: Observation, *, task_id: str, stage: int, student_id: str, nonce: str, ts: str, hooks=None) -> Grade` — accept? → issue the local (nonce) key AND build evidence for later server sign-off. NO `server_secret` parameter (the client never holds the secret).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_grade.py
import inspect

import pytest

from hashpass.canon import FileState
from hashpass.grade import Grade, grade_stage
from hashpass.taskcode.derive import StageChecks

_TS = "2026-08-30T12:00:00Z"


def _checks() -> StageChecks:
    canonical = {"result.txt": FileState("file", "answer")}
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


@pytest.mark.tier1
def test_grade_accept_path_issues_local_key_and_evidence():
    checks = _checks()
    candidate = {"result.txt": FileState("file", "answer")}
    g = grade_stage(checks, candidate, task_id="task1", stage=0,
                    student_id="alice", nonce="n1", ts=_TS)
    assert isinstance(g, Grade)
    assert g.accepted
    assert g.local_key is not None
    assert g.local_key.startswith("key{")
    assert g.evidence is not None
    assert g.evidence.candidate == candidate


@pytest.mark.tier1
def test_grade_reject_path_no_key_no_evidence():
    checks = _checks()
    g = grade_stage(checks, {"result.txt": FileState("file", "WRONG")},
                    task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)
    assert not g.accepted
    assert g.local_key is None
    assert g.evidence is None


@pytest.mark.tier1
def test_grade_stage_never_takes_server_secret():
    # Client never holds the secret: structural guarantee.
    assert "server_secret" not in inspect.signature(grade_stage).parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_grade.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hashpass.grade'`.

- [ ] **Step 3: Write `grade.py`**

```python
# src/hashpass/grade.py
"""Client-side grading: accept? → local (nonce) key + evidence for later server sign-off (§6/§7)."""
from dataclasses import dataclass

from hashpass.canon import Observation
from hashpass.evidence import Evidence, build_evidence
from hashpass.key import local_key
from hashpass.taskcode.checker import check_stage
from hashpass.taskcode.derive import StageChecks


@dataclass(frozen=True)
class Grade:
    """Outcome of client-side grading: acceptance + provisional local key + evidence."""

    accepted: bool
    local_key: str | None
    evidence: Evidence | None


def grade_stage(checks: StageChecks, candidate: Observation, *, task_id: str,  # noqa: PLR0913
                stage: int, student_id: str, nonce: str, ts: str, hooks=None) -> Grade:
    """Client-side: accept? → issue the local (nonce) key AND build evidence for server sign-off."""
    if not check_stage(checks, candidate, hooks=hooks, stage=stage):
        return Grade(accepted=False, local_key=None, evidence=None)
    return Grade(
        accepted=True,
        local_key=local_key(task_id, stage, nonce),
        evidence=build_evidence(checks, candidate, task_id=task_id, stage=stage,
                                student_id=student_id, nonce=nonce, ts=ts),
    )
```

- [ ] **Step 4: Run tests + lint to verify green**

Run: `pytest tests/test_grade.py -v` (PASS), `ruff check src tests runtime` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/grade.py tests/test_grade.py
git commit -m "feat(grade): client-side grade_stage composing check + local_key + evidence"
```

---

### Task 5: Integration spine + threat-model

**Files:**
- Test: `tests/server/test_credential_flow.py`

**Interfaces:**
- Consumes: `grade_stage`, `Grade` (Task 4); `issue_global_key`, `verify_evidence` (Task 3); `global_key`, `local_key` (Task 1); `build_evidence`, `Evidence` (Task 2); `StageChecks`, `FileState`.
- Produces: no new symbols — end-to-end pure-function offline→online flow + the §6/§9 invariants.

**THREAT-MODEL SPINE (§9):** these assertions are load-bearing. If verification is ever replaced by a stubbed always-sign server, `test_server_refuses_forged_claim` and `test_stub_always_sign_server_would_fail_this_spine` MUST break; if a client could self-compute the global key without the secret, `test_global_key_unforgeable_without_secret` MUST break. If any of these regress on the merits, that is a real security finding — report it, do NOT weaken the test.

- [ ] **Step 1: Write the spine + threat-model test**

```python
# tests/server/test_credential_flow.py
import inspect

import pytest

from hashpass.canon import FileState
from hashpass.evidence import Evidence, build_evidence
from hashpass.grade import grade_stage
from hashpass.key import global_key, local_key
from hashpass.server.verify import issue_global_key
from hashpass.taskcode.derive import StageChecks

_SECRET = b"real-server-secret"
_WRONG_SECRET = b"attacker-secret"
_TS = "2026-08-30T12:00:00Z"


def _checks() -> StageChecks:
    canonical = {"result.txt": FileState("file", "answer")}
    return StageChecks(canonical=canonical, mode="line", threshold=1.0, k=1)


@pytest.mark.tier1
def test_offline_then_online_happy_path():
    checks = _checks()
    correct = {"result.txt": FileState("file", "answer")}
    # 1. offline: accept → local key + evidence.
    g = grade_stage(checks, correct, task_id="task1", stage=0,
                    student_id="alice", nonce="n1", ts=_TS)
    assert g.accepted
    assert g.local_key.startswith("key{")
    assert g.evidence is not None
    # 2. online: server re-verifies + signs the identity-bound global key.
    key = issue_global_key(g.evidence, checks, server_secret=_SECRET)
    assert key == global_key(_SECRET, "alice", "task1")


@pytest.mark.tier1
def test_offline_wrong_candidate_gets_no_local_key():
    checks = _checks()
    g = grade_stage(checks, {"result.txt": FileState("file", "WRONG")},
                    task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)
    assert not g.accepted
    assert g.local_key is None


@pytest.mark.tier1
def test_server_refuses_forged_claim():
    checks = _checks()
    # A forged claim: evidence built directly from the WRONG candidate.
    forged = build_evidence(checks, {"result.txt": FileState("file", "WRONG")},
                            task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)
    assert issue_global_key(forged, checks, server_secret=_SECRET) is None


@pytest.mark.tier1
def test_global_key_unforgeable_without_secret():
    # Student cannot self-compute the credit without the server secret.
    assert global_key(_WRONG_SECRET, "alice", "task1") != global_key(_SECRET, "alice", "task1")
    # Structural: no client-side symbol exposes or accepts server_secret.
    for fn in (grade_stage, local_key, build_evidence, Evidence):
        assert "server_secret" not in inspect.signature(fn).parameters


@pytest.mark.tier1
def test_global_key_identity_bound_not_shareable():
    checks = _checks()
    correct = {"result.txt": FileState("file", "answer")}
    alice = build_evidence(checks, correct, task_id="task1", stage=0,
                           student_id="alice", nonce="n1", ts=_TS)
    bob = build_evidence(checks, correct, task_id="task1", stage=0,
                         student_id="bob", nonce="n2", ts=_TS)
    ka = issue_global_key(alice, checks, server_secret=_SECRET)
    kb = issue_global_key(bob, checks, server_secret=_SECRET)
    assert ka is not None
    assert kb is not None
    assert ka != kb  # alice's credit is not bob's


@pytest.mark.tier1
def test_stub_always_sign_server_would_fail_this_spine():
    # Threat-model guard: an always-sign server (ignoring verification) hands out credit
    # for a forged claim, whereas the real server refuses. This makes the WRONG->None
    # assertion load-bearing — swapping verification for a stub breaks the spine.
    checks = _checks()
    forged = build_evidence(checks, {"result.txt": FileState("file", "WRONG")},
                            task_id="task1", stage=0, student_id="alice", nonce="n1", ts=_TS)

    def always_sign(ev, _checks_ignored, *, server_secret) -> str:
        return global_key(server_secret, ev.student_id, ev.task_id)

    stub_key = always_sign(forged, checks, server_secret=_SECRET)
    real_key = issue_global_key(forged, checks, server_secret=_SECRET)
    assert stub_key is not None  # the insecure stub would grant credit
    assert real_key is None  # the real server refuses — the core guarantee
    assert stub_key != real_key
```

- [ ] **Step 2: Run test to verify it PASSES (security gate)**

Run: `pytest tests/server/test_credential_flow.py -v`
Expected: PASS — all six invariants hold. This is the threat-model gate: the WRONG→None and UNFORGEABLE assertions are load-bearing. If any fails on the merits, report it as a security finding rather than adjusting the test.

Then run the full suite + lint: `pytest -q -m "not tier3"` (green), `ruff check src tests runtime` (clean).

- [ ] **Step 3: Commit**

```bash
git add tests/server/test_credential_flow.py
git commit -m "test(server): Plan-E credential-flow spine + threat-model invariants"
```

---

## Out of scope (future plans / user's call)

- **Plan F:** HTTP/registry transport, the offline→online orchestration UX, background re-verification (§7 «фоновая до-сверка»), invisible check, hints runtime. Do NOT add http/sockets, do NOT touch `play.py` (the offline loop stays in Plan F), do NOT touch the real server (185.212.148.108).
- **Deployment (user's call):** any real server. This plan is pure credential LOGIC only.
- **Already clean:** the greenfield rebuild has no masterkey/obfuscation/zip-password to remove (those live only in `origin/dev`). Reference-only (do NOT copy): dev used `calc_key(masterkey+username+image)` sed-patched locally (forgeable) and a bare unauthenticated `/student/confirmed` ping — this plan REPLACES that with server-side HMAC over re-verified evidence; the secret never leaves the server.
