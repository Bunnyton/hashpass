"""
Who may do what in a course (spec 2026-10-21 §5).

`can(user, server_role, course, action)` is the one answer every route asks. Actions, each
including the ones before it for a member: `view` (see the course), `play` (run its tasks, get
credit), `propose` (suggest a change) -- for anyone signed in on a public course, members on a
private one; `add` (add tasks directly, update one's own) -- author; `moderate` (decide
proposals and requests, arrange, hide, remove) -- maintainer; `admin` (settings, roles,
invite, delete) -- owner. The server admin may do everything. An outsider of a private course
gets only `peek`: its title and description, to ask for access.
"""
from hashpass.registry.courses import Course

ACTIONS = ("peek", "view", "play", "propose", "add", "moderate", "admin")
_LEVEL = {"member": 0, "author": 1, "maintainer": 2, "owner": 3}
_NEEDS = {"add": 1, "moderate": 2, "admin": 3}


def can(user: str | None, server_role: str | None, course: Course, action: str) -> bool:
    """Whether `user` (server role `server_role`) may do `action` in `course`."""
    if action not in ACTIONS:
        msg = f"unknown action: {action}"
        raise ValueError(msg)
    if action == "peek":
        return True
    if server_role == "admin":
        return True
    role = course.role_of(user)
    if action in _NEEDS:
        return role is not None and _LEVEL[role] >= _NEEDS[action]
    if action == "view":
        return course.visibility == "public" or role is not None
    return user is not None and (course.visibility == "public" or role is not None)
