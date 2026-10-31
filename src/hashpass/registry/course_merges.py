"""
A whole fork offered back to the course it came from (spec 2026-10-31 §3.2).

A request lives in the parent's `merges`: `{id, from_id, from_ref, by, comment, state:
open|merged|rejected|withdrawn, reason, at, decided_by, decided_at, base, base_rev, snapshot}`.
`snapshot` is the fork's structure, `base` the parent's when it was offered: the fork must have
pulled the parent first, and a parent changed since makes the request stale (it cannot be taken,
the author pulls and offers again). Taking it makes the parent's structure the snapshot -- its
own open blocks and hidden tasks stay.
"""
import secrets
from typing import TYPE_CHECKING

from hashpass.registry import course_copies as cc

if TYPE_CHECKING:
    from hashpass.registry.courses import Course

REJECTED_SHOWN = 7 * 24 * 60 * 60     # a rejected request stays in its author's sight this long


def offer(parent: "Course", fork: "Course", *, by: str, comment: str, now: float) -> dict:
    """Open (or refresh) the fork's request to `parent`; the fork must have pulled the parent's changes."""
    base = cc.structure(parent)
    if fork.origin.get("base") != base:
        msg = "сначала подтяните изменения исходного курса"
        raise ValueError(msg)
    req = next((r for r in parent.merges if r["state"] == "open" and r["from_id"] == fork.id), None)
    if req is None:
        req = {"id": f"m-{secrets.token_hex(4)}", "from_id": fork.id, "state": "open", "reason": "",
               "decided_by": "", "decided_at": 0.0}
        parent.merges.append(req)
    req.update({"from_ref": fork.ref, "by": by, "comment": comment[:500], "at": now, "base": base,
                "base_rev": parent.rev, "snapshot": cc.structure(fork)})
    return req


def _open(parent: "Course", req_id: str) -> dict:
    req = next((r for r in parent.merges if r["id"] == req_id), None)
    if req is None or req["state"] != "open":
        msg = "такого открытого запроса нет"
        raise ValueError(msg)
    return req


def stale(parent: "Course", req: dict) -> bool:
    """Whether the parent changed since the request was offered."""
    return cc.structure(parent) != req["base"]


def changes(parent: "Course", req: dict) -> list[dict]:
    """Return what taking the request would change in the parent now."""
    return cc.diff(cc.structure(parent), req["snapshot"])


def decide(parent: "Course", req_id: str, *, accept: bool, by: str, now: float,  # noqa: PLR0913
           reason: str = "") -> dict:
    """Take (the parent becomes the snapshot) or reject an open request; a stale one cannot be taken."""
    req = _open(parent, req_id)
    if accept:
        if stale(parent, req):
            msg = "запрос устарел — автору нужно подтянуть изменения и обновить его"
            raise ValueError(msg)
        cc.apply_structure(parent, req["snapshot"])
    req.update({"state": "merged" if accept else "rejected", "reason": reason[:500], "decided_by": by,
                "decided_at": now})
    return req


def withdraw(parent: "Course", req_id: str, *, by: str) -> None:
    """Take an open request back (its author only)."""
    req = _open(parent, req_id)
    if req["by"] != by:
        msg = "отозвать запрос может только его автор"
        raise PermissionError(msg)
    req["state"] = "withdrawn"


def shown(parent: "Course", user: str | None, *, staff: bool, now: float) -> list[dict]:
    """Return the requests `user` sees: the staff -- all; an author -- their own, a rejected one for 7 days."""
    if staff:
        return list(parent.merges)
    return [r for r in parent.merges if user and r["by"] == user
            and not (r["state"] == "rejected" and now - float(r.get("decided_at", 0.0)) > REJECTED_SHOWN)]
