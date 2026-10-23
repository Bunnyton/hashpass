"""
Which era a pool runs in: courses (the default) or the old single catalog.

`HASHPASS_COURSES=1` used to switch courses on per pool; since 2026-10-23 every pool runs on
courses (user: «COURSE переменную можно уже убирать»). The old catalog web stays only for its
tests, which turn `COURSES` off.
"""
COURSES = True


def courses_on() -> bool:
    """Whether this pool runs on courses."""
    return COURSES
