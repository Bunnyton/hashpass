"""
Copies of a course (spec 2026-10-31): mirrors follow their parent, forks are one's own.

What a copy takes from its source is the course's *structure*: the blocks (id, name) and their
tasks (`repo, tag, n, pinned, added_by`) in order, and `auto_update`. A hidden task is the
author's draft and is not part of it; whether a block is open is each course's own schedule.
"""
from hashpass.registry.courses import Course


def structure_task(task: dict) -> dict:
    """Return the copyable part of one task."""
    return {"repo": task["repo"], "tag": task["tag"], "n": int(task["n"]),
            "pinned": bool(task.get("pinned", False)), "added_by": str(task.get("added_by", ""))}


def structure(course: Course) -> dict:
    """Return what a copy of `course` holds: blocks and visible tasks in order, and `auto_update`."""
    return {"auto_update": bool(course.auto_update),
            "blocks": [{"id": b["id"], "name": b["name"],
                        "tasks": [structure_task(t) for t in b.get("tasks", []) if not t.get("hidden")]}
                       for b in course.blocks]}


def block_open(course: Course) -> dict[str, bool]:
    """Whether each block of `course` is open, by id."""
    return {b["id"]: bool(b.get("open", True)) for b in course.blocks}


def apply_structure(course: Course, struct: dict, *, source_open: dict[str, bool] | None = None) -> None:
    """
    Make `course`'s structure `struct`, keeping what is its own.

    Its own: whether each of its blocks is open (a new block takes `source_open`, else open) and
    its hidden tasks, which stay at the end of their block (of the last block, if theirs is gone).
    """
    source_open = source_open or {}
    old = {b["id"]: b for b in course.blocks}
    hidden = {b["id"]: [t for t in b.get("tasks", []) if t.get("hidden")] for b in course.blocks}
    blocks = []
    for sb in struct["blocks"]:
        mine = old.get(sb["id"])
        tasks = [structure_task(t) | {"hidden": False} for t in sb["tasks"]]
        is_open = bool(mine.get("open", True)) if mine else bool(source_open.get(sb["id"], True))
        blocks.append({"id": sb["id"], "name": sb["name"], "open": is_open,
                       "tasks": tasks + hidden.pop(sb["id"], [])})
    orphans = [t for ts in hidden.values() for t in ts]
    if orphans:
        if not blocks:
            blocks.append({"id": "hidden", "name": "Скрытые", "open": False, "tasks": []})
        blocks[-1]["tasks"].extend(orphans)
    course.blocks = blocks
    course.auto_update = bool(struct.get("auto_update", course.auto_update))
