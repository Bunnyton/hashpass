"""
Permission boxes of an admin -- on the pool and in a course (spec 2026-10-25 §1).

`admins` makes and unmakes admins and sets their boxes (within one's own); `content` -- tasks,
blocks, proposals, settings, the catalog; `people` -- members, invites, requests, users;
`progress` -- who takes a course, marks, solutions, history. A new admin gets DEFAULT; the
owner (of the pool, of a course) has ALL, and nobody takes them away.
"""
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hashpass.registry.passwords import UserStore

KEYS = ("admins", "content", "people", "progress")
ALL = frozenset(KEYS)
DEFAULT = frozenset({"content", "people", "progress"})
LABELS = {"admins": "Админы", "content": "Задания и блоки", "people": "Люди и доступ",
          "progress": "Прогресс и решения"}


def clean(value: object, *, default: frozenset[str]) -> frozenset[str]:
    """Return the known keys of a stored list; `None` (never set) is `default`."""
    if value is None:
        return default
    if not isinstance(value, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(k for k in value if k in KEYS)


def pool_owner(users: "UserStore", configured: str) -> str | None:
    """Return the pool's owner: config.json's `owner`, else $HASHPASS_ADMIN, else the earliest admin."""
    admins = [p for p in users.all_users() if p.get("role") == "admin"]
    names = {str(p["user"]) for p in admins}
    for login in (configured, os.environ.get("HASHPASS_ADMIN", "admin")):
        if login and login in names:
            return login
    if not admins:
        return None
    return str(min(admins, key=lambda p: (float(p.get("created_at") or 0.0), str(p["user"])))["user"])


def pool_perms(users: "UserStore", configured_owner: str, user: str | None) -> frozenset[str]:
    """Return `user`'s boxes on the pool: none for a non-admin, ALL for the owner."""
    if not user:
        return frozenset()
    profile = users.get(user)
    if profile is None or profile.get("role") != "admin":
        return frozenset()
    if user == pool_owner(users, configured_owner):
        return ALL
    return clean(profile.get("perms"), default=ALL)    # an admin from before the boxes: all of them


def subset(wanted: Iterable[str], held: frozenset[str]) -> bool:
    """Whether every box in `wanted` is one the giver holds (nobody gives what it lacks)."""
    return set(wanted) <= held
