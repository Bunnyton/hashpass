"""
Who may do what in a course (spec 2026-10-21 §5; roles and boxes 2026-10-25 §3).

`can(user, pool, course, action)` is the one answer every route asks; `pool` is the caller's
permission boxes on the pool (empty for anyone but a pool admin). Course roles: `member`
(plays a private course), `author` (adds tasks at once), `admin` (the boxes in
`course.perms`, DEFAULT when unset), `owner` (all boxes). `peek` -- a private course's title,
for an access request; `view`/`play`; `propose` -- anyone signed in on a public course, anyone
in a private one; `add` -- straight in, no proposal; `content`, `people`, `progress`, `admins`
-- the boxes; `delete` -- the owner. A pool admin sees every course and acts in it with its
own pool boxes.
"""
from hashpass.registry import perms
from hashpass.registry.courses import Course

ACTIONS = ("peek", "view", "play", "propose", "add", "content", "people", "progress", "admins", "delete")


def course_perms(course: Course, user: str | None) -> frozenset[str]:
    """Return `user`'s boxes in `course`: ALL for the owner, the stored ones for an admin, none else."""
    role = course.role_of(user)
    if role == "owner":
        return perms.ALL
    if role == "admin":
        return perms.clean(course.perms.get(user or ""), default=perms.DEFAULT)
    return frozenset()


def can(user: str | None, pool: frozenset[str], course: Course, action: str) -> bool:
    """Whether `user` (pool boxes `pool`) may do `action` in `course`."""
    if action not in ACTIONS:
        msg = f"unknown action: {action}"
        raise ValueError(msg)
    if action == "peek":
        return True
    role = course.role_of(user)
    boxes = course_perms(course, user) | pool
    if action in perms.KEYS:
        return action in boxes
    if action == "delete":
        return role == "owner" or "content" in pool
    if action == "add":
        return role == "author" or "content" in boxes
    if action == "view":
        return course.visibility == "public" or role is not None or bool(pool)
    return user is not None and (course.visibility == "public" or role is not None or bool(pool))
