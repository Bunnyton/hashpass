"""
Server-side console sessions: every command a student ran in a task, with its output.

One JSON file per session, `<root>/<user>/<ref-safe>/<session_id>.json`. The client streams a
session while it runs (`append` with `seq` = how many entries it believes the server has, so a
retry never duplicates), then closes it (`finish`). The latest `passed` session of a task is the
student's solution (spec 2026-10-16): the student sees it in the TUI, the teacher on the site.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

MAX_OUTPUT = 16 * 1024          # one command's output
MAX_ENTRIES = 1000              # commands per session
MAX_SESSION_OUTPUT = 512 * 1024  # output per session; beyond -> truncated
KEEP_ATTEMPTS = 10              # unpassed sessions kept per task (the solution is never dropped)
KEEP_SECONDS = 60 * 24 * 3600   # a passed task's attempts older than this are dropped
LIVE_SECONDS = 60               # an open session updated this recently is «идёт сейчас»
FINALS = ("passed", "abandoned", "failed")
_TRUNC = "\n…обрезано"
_SID_RE = re.compile(r"^[0-9a-f]{32}$")


class SeqMismatch(Exception):  # noqa: N818  (a signal, not a failure)
    """The client's `seq` is not the session's length; `have` tells it where to resume."""

    def __init__(self, have: int) -> None:
        """Remember the session's current length."""
        super().__init__(f"seq mismatch: have {have}")
        self.have = have


def safe_name(ref: str) -> str:
    """Turn a task ref into one path component (`ns/x:1` -> `ns_x_1`); the ref itself lives in the file."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", ref) or "_"


def cap_output(text: str) -> str:
    """Cut one command's output to MAX_OUTPUT, saying so."""
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + _TRUNC


def sanitize_entries(raw: object) -> list[dict[str, object]]:
    """Coerce client-supplied entries into {command, output, ts, typing, pasted}, capped."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, object]] = []
    for item in raw[:MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue
        typing = item.get("typing")
        out.append({"command": str(item.get("command", ""))[:1000],
                    "output": cap_output(str(item.get("output", "") or "")),
                    "ts": str(item.get("ts", ""))[:64],
                    "typing": float(typing) if isinstance(typing, (int, float)) else None,
                    "pasted": bool(item.get("pasted", False))})
    return out


def is_live(rec: dict[str, object], now: float | None = None) -> bool:
    """Whether a session is being solved right now: not closed and touched within a minute."""
    now = time.time() if now is None else now
    updated = rec.get("updated")
    return not rec.get("final") and isinstance(updated, (int, float)) and now - updated <= LIVE_SECONDS


class AttemptStore:
    """user -> task -> sessions, one JSON file per session."""

    def __init__(self, root: Path) -> None:
        """Open (creating on write) the attempts dir."""
        self._root = Path(root)

    def _dir(self, user: str, ref: str) -> Path:
        return self._root / safe_name(user) / safe_name(ref)

    def _path(self, user: str, ref: str, session_id: str) -> Path:
        if not _SID_RE.match(session_id):
            msg = "bad session id"
            raise ValueError(msg)
        return self._dir(user, ref) / f"{session_id}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, object] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _write(path: Path, rec: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def append(self, user: str, ref: str, session_id: str, seq: int,  # noqa: PLR0913
               entries: list[dict[str, object]], *, final: str | None = None,
               now: float | None = None) -> int:
        """Add `entries` at position `seq`; return the new length. Wrong seq -> SeqMismatch."""
        now = time.time() if now is None else now
        path = self._path(user, ref, session_id)
        rec = self._read(path) or {"ref": ref, "session_id": session_id, "started": now,
                                   "updated": now, "final": None, "truncated": False,
                                   "entries": []}
        have: list[dict[str, object]] = rec["entries"]  # type: ignore[assignment]
        if seq != len(have):
            raise SeqMismatch(len(have))
        used = sum(len(str(e.get("output", ""))) for e in have)
        for e in sanitize_entries(entries):
            if len(have) >= MAX_ENTRIES or used + len(str(e["output"])) > MAX_SESSION_OUTPUT:
                rec["truncated"] = True
                break
            used += len(str(e["output"]))
            have.append(e)
        rec["updated"] = now
        if final in FINALS and rec.get("final") != "passed":
            rec["final"] = final
        self._write(path, rec)
        self._rotate(user, ref)
        return len(have)

    def finish(self, user: str, ref: str, session_id: str, final: str,
               *, now: float | None = None) -> None:
        """Close a session (passed / abandoned / failed); a passed session stays passed."""
        if final not in FINALS:
            return
        now = time.time() if now is None else now
        path = self._path(user, ref, session_id)
        rec = self._read(path) or {"ref": ref, "session_id": session_id, "started": now,
                                   "final": None, "truncated": False, "entries": []}
        if rec.get("final") != "passed":
            rec["final"] = final
        rec["updated"] = now
        self._write(path, rec)

    def _rotate(self, user: str, ref: str) -> None:
        """Keep the newest KEEP_ATTEMPTS unpassed sessions of a task; passed ones always stay."""
        unpassed = [s for s in self.sessions(user, ref) if s.get("final") != "passed"]
        for old in unpassed[KEEP_ATTEMPTS:]:
            self._path(user, ref, str(old["session_id"])).unlink(missing_ok=True)

    def prune(self, user: str, *, now: float | None = None) -> None:
        """Drop attempts older than KEEP_SECONDS of the tasks the user has passed (user, 2026-10-16)."""
        cutoff = (time.time() if now is None else now) - KEEP_SECONDS
        for ref, recs in self._all(user).items():
            if not any(r.get("final") == "passed" for r in recs):
                continue                              # still at it: the teacher needs every try
            for r in recs:
                if r.get("final") != "passed" and float(r.get("updated") or 0) < cutoff:
                    self._path(user, ref, str(r["session_id"])).unlink(missing_ok=True)

    def sessions(self, user: str, ref: str) -> list[dict[str, object]]:
        """All sessions of a task, newest first."""
        d = self._dir(user, ref)
        recs = [r for p in d.glob("*.json") if (r := self._read(p))] if d.exists() else []
        return sorted(recs, key=lambda r: float(r.get("started") or 0), reverse=True)

    def _all(self, user: str) -> dict[str, list[dict[str, object]]]:
        base = self._root / safe_name(user)
        out: dict[str, list[dict[str, object]]] = {}
        if not base.exists():
            return out
        for d in base.iterdir():
            for p in d.glob("*.json"):
                rec = self._read(p)
                if rec and rec.get("ref"):
                    out.setdefault(str(rec["ref"]), []).append(rec)
        return out

    def by_task(self, user: str) -> dict[str, list[dict[str, object]]]:
        """Ref -> every stored session of the user (the profile page)."""
        return self._all(user)

    def summary(self, user: str, *, now: float | None = None) -> dict[str, dict[str, object]]:
        """Ref -> {sessions, passed, live}: what the teacher's matrix needs (expired tries pruned)."""
        self.prune(user, now=now)
        return {ref: {"sessions": len(recs),
                      "passed": any(r.get("final") == "passed" for r in recs),
                      "live": any(is_live(r, now) for r in recs)}
                for ref, recs in self._all(user).items()}

    def solution(self, user: str, ref: str) -> dict[str, object] | None:
        """Return the latest passed session of a task, or None."""
        passed = [s for s in self.sessions(user, ref) if s.get("final") == "passed"]
        return max(passed, key=lambda r: float(r.get("updated") or 0)) if passed else None

    def solutions(self, user: str) -> dict[str, dict[str, object]]:
        """Ref -> {session_id, at} of every task the user has a solution for."""
        out: dict[str, dict[str, object]] = {}
        for ref in self._all(user):
            sol = self.solution(user, ref)
            if sol is not None:
                out[ref] = {"session_id": sol["session_id"], "at": sol.get("updated")}
        return out

    def delete_user(self, user: str) -> None:
        """Forget every session of a user (account deleted)."""
        shutil.rmtree(self._root / safe_name(user), ignore_errors=True)
