"""
A task console session on the student's side: stream it to the pool, keep the solution locally.

Spec 2026-10-16: every command the student runs (with its output) goes to the pool almost live,
so a teacher can see on the site what does not work and help remotely. The pool's `/attempt` is
seq-gated (409 tells where to resume), so a lost answer or a retry never duplicates commands.
Nothing here may slow the console: a network failure is retried on the next tick, and what is
still unsent when the session closes lands in an outbox, sent with the next session.

The passed session is the solution: saved under `solutions/` before any network call, and on a
new device `sync_solutions` pulls the ones the pool has.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.error
import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING

from hashpass.registry.attempt_store import safe_name, sanitize_entries

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_GONE = (HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED)   # an old pool: no /attempt
_NET_ERRORS = (urllib.error.URLError, RuntimeError, OSError, ValueError)


class AttemptUploader:
    """Push the growing `history` of one console session to the pool every `interval` seconds."""

    def __init__(self, client, ref: str, history: list[dict[str, object]], *,  # noqa: PLR0913
                 token: str, outbox: Path, session_id: str | None = None,
                 interval: float = 3.0) -> None:
        """Watch `history` (the console appends to it) for the session of task `ref`."""
        self.client = client
        self.ref = ref
        self.history = history
        self.token = token
        self.outbox = outbox
        self.session_id = session_id or uuid.uuid4().hex
        self.interval = interval
        self.started = time.time()
        self.sent = 0          # entries of `history` the pool has
        self.server_len = 0    # the session's length on the pool (less than `sent` if it truncated)
        self.disabled = False  # the pool has no /attempt
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background pusher."""
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.push()

    def push(self, final: str | None = None) -> bool:  # noqa: PLR0911
        """Send what is new (and `final`); True when the pool has everything."""
        with self._lock:
            if self.disabled:
                return True
            for _ in range(3):                     # a 409 resyncs the position, then retries
                entries = list(self.history[self.sent:])
                if not entries and (final is None or self.server_len == 0):
                    return True                    # nothing new; an empty session is not sent
                try:
                    res = self.client.attempt(self.ref, self.session_id, self.server_len, entries,
                                              final=final, token=self.token)
                except urllib.error.HTTPError as exc:
                    if exc.code in _GONE:
                        self.disabled = True
                        return True
                    if exc.code == HTTPStatus.CONFLICT:
                        self._resync(exc)
                        continue
                    return False
                except _NET_ERRORS:
                    return False
                self.sent += len(entries)
                self.server_len = int(res.get("length", self.server_len + len(entries)))
                return True
            return False

    def _resync(self, exc: urllib.error.HTTPError) -> None:
        """Skip what the pool already has (`have` in the 409): a lost reply, applied anyway."""
        try:
            have = int(json.loads(exc.read() or b"{}").get("length", 0))
        except (ValueError, OSError, AttributeError):
            return
        self.sent = max(0, min(len(self.history), self.sent + have - self.server_len))
        self.server_len = have

    def close(self, final: str) -> None:
        """Stop the pusher, send the rest + `final`; still offline -> write it to the outbox."""
        if self._stop.is_set():
            return                                   # closed already (the first verdict wins)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self.push(final=final):
            return
        self.outbox.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            (self.outbox / f"{self.session_id}.json").write_text(json.dumps({
                "ref": self.ref, "session_id": self.session_id, "seq": self.server_len,
                "entries": self.history[self.sent:], "final": final}, ensure_ascii=False),
                encoding="utf-8")

    def record(self, final: str) -> dict[str, object]:
        """Return the session as the pool keeps it -- what `save_solution` stores locally."""
        return {"ref": self.ref, "session_id": self.session_id, "started": self.started,
                "updated": time.time(), "final": final, "truncated": False,
                "entries": sanitize_entries(self.history)}


def flush_outbox(client, outbox: Path, token: str) -> int:
    """Send the sessions left offline; return how many went out."""
    sent = 0
    if not outbox.is_dir():
        return 0
    for path in sorted(outbox.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        seq, entries = int(item.get("seq", 0)), list(item.get("entries") or [])
        for _ in range(2):
            try:
                client.attempt(str(item["ref"]), str(item["session_id"]), seq, entries,
                               final=item.get("final"), token=token)
            except urllib.error.HTTPError as exc:
                if exc.code == HTTPStatus.CONFLICT:
                    with contextlib.suppress(ValueError, OSError, AttributeError):
                        have = int(json.loads(exc.read() or b"{}").get("length", seq))
                        entries, seq = entries[max(0, have - seq):], have
                    continue
                if exc.code in (*_GONE, HTTPStatus.BAD_REQUEST):
                    path.unlink(missing_ok=True)    # nowhere to send it: drop
                break
            except _NET_ERRORS:
                return sent                          # still offline: try again later
            path.unlink(missing_ok=True)
            sent += 1
            break
    return sent


def _solution_path(root: Path, ref: str) -> Path:
    return root / "solutions" / f"{safe_name(ref)}.json"


def save_solution(root: Path, ref: str, record: dict[str, object]) -> None:
    """Keep a solved task's session locally (`~/.hashpass/solutions/<ref>.json`)."""
    path = _solution_path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


def load_solution(root: Path, ref: str) -> dict[str, object] | None:
    """Return the locally kept solution of `ref`, or None."""
    try:
        data = json.loads(_solution_path(root, ref).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def sync_solutions(root: Path, client, token: str,
                   mark: Callable[[str], None] | None = None) -> int:
    """Pull the pool's solutions missing (or older) here; `mark(ref)` records «решено»."""
    try:
        remote = client.solutions(token=token)
    except (urllib.error.HTTPError, *_NET_ERRORS):
        return 0                                     # an old pool or offline: nothing to pull
    pulled = 0
    for ref, meta in remote.items():
        local = load_solution(root, ref)
        at = meta.get("at") if isinstance(meta, dict) else None
        fresh = (local is not None and local.get("session_id") == meta.get("session_id")) or (
            local is not None and isinstance(at, (int, float))
            and float(local.get("updated") or 0) >= at)
        if not fresh:
            try:
                save_solution(root, ref, client.solution(ref, token=token))
            except (urllib.error.HTTPError, *_NET_ERRORS):
                continue
            pulled += 1
        if mark is not None:
            mark(ref)
    return pulled


def solution_text(record: dict[str, object], *, ansi: bool = True) -> str:
    """Return a solution as a terminal log: `$ command` (bold) and its output under it."""
    bold, dim, off = ("\x1b[1m", "\x1b[2m", "\x1b[0m") if ansi else ("", "", "")
    at = record.get("updated")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(at))) if isinstance(
        at, (int, float)) else ""
    lines = [f"{bold}{record.get('ref', '')}{off}  ·  зачтено {when}".rstrip(), ""]
    for e in record.get("entries") or []:   # type: ignore[union-attr]
        lines.append(f"{bold}$ {e.get('command', '')}{off}")
        out = str(e.get("output") or "").rstrip("\n")
        if out:
            lines.append(out)
    if not record.get("entries"):
        lines.append(f"{dim}команды не записаны{off}")
    return "\n".join(lines) + "\n"
