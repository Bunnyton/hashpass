"""
Copies of a course (spec 2026-10-31): mirrors follow their parent, forks are one's own.

What a copy takes from its source is the course's *structure*: the blocks (id, name, the blocks
each one `needs` solved first) and their
tasks (`repo, tag, n, pinned, added_by`) in order, and `auto_update`. A hidden task is the
author's draft and is not part of it; whether a block is open is each course's own schedule.
"""
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hashpass.registry.courses import Course


def structure_task(task: dict) -> dict:
    """Return the copyable part of one task."""
    return {"repo": task["repo"], "tag": task["tag"], "n": int(task["n"]),
            "pinned": bool(task.get("pinned", False)), "added_by": str(task.get("added_by", ""))}


def structure(course: "Course") -> dict:
    """Return what a copy of `course` holds: blocks and visible tasks in order, and `auto_update`."""
    return {"auto_update": bool(course.auto_update),
            "blocks": [{"id": b["id"], "name": b["name"],
                        "tasks": [structure_task(t) for t in b.get("tasks", []) if not t.get("hidden")]}
                       | ({"needs": list(b["needs"])} if b.get("needs") else {})
                       for b in course.blocks]}


def block_open(course: "Course") -> dict[str, bool]:
    """Whether each block of `course` is open, by id."""
    return {b["id"]: bool(b.get("open", True)) for b in course.blocks}


def apply_structure(course: "Course", struct: dict, *, source_open: dict[str, bool] | None = None) -> None:
    """
    Make `course`'s structure `struct`, keeping what is its own.

    Its own: whether each of its blocks is open (a new block takes `source_open`, else open) and
    its hidden tasks, which stay at the end of their block (of the last block, if theirs is gone).
    """
    source_open = source_open or {}
    old = {b["id"]: b for b in course.blocks}
    brought = {f"{t['repo']}:{t['tag']}" for b in struct["blocks"] for t in b["tasks"]}
    hidden = {b["id"]: [t for t in b.get("tasks", []) if t.get("hidden")
                        and f"{t['repo']}:{t['tag']}" not in brought] for b in course.blocks}
    blocks = []
    for sb in struct["blocks"]:
        mine = old.get(sb["id"])
        tasks = [structure_task(t) | {"hidden": False} for t in sb["tasks"]]
        is_open = bool(mine.get("open", True)) if mine else bool(source_open.get(sb["id"], True))
        blocks.append({"id": sb["id"], "name": sb["name"], "open": is_open,
                       "tasks": tasks + hidden.pop(sb["id"], [])}
                      | ({"needs": list(sb["needs"])} if sb.get("needs") else {}))
    orphans = [t for ts in hidden.values() for t in ts]
    if orphans:
        if not blocks:
            blocks.append({"id": "hidden", "name": "Скрытые", "open": False, "tasks": []})
        blocks[-1]["tasks"].extend(orphans)
    course.blocks = blocks
    course.auto_update = bool(struct.get("auto_update", course.auto_update))


# -- diff ---------------------------------------------------------------------

def _ref(task: dict) -> str:
    return f"{task['repo']}:{task['tag']}"


def _kept(old: list[str], new: list[str]) -> set[str]:
    """Items of `old` that stay in place in `new` (a longest common subsequence, earlier ones kept)."""
    dp = [[0] * (len(new) + 1) for _ in range(len(old) + 1)]
    for i in range(len(old) - 1, -1, -1):
        for j in range(len(new) - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if old[i] == new[j] else max(dp[i + 1][j], dp[i][j + 1])
    kept, i, j = set(), 0, 0
    while i < len(old) and j < len(new):
        if old[i] == new[j]:
            kept.add(old[i])
            i, j = i + 1, j + 1
        elif dp[i][j + 1] >= dp[i + 1][j]:
            j += 1
        else:
            i += 1
    return kept


def _after(items: list[str], item: str) -> str:
    idx = items.index(item)
    return items[idx - 1] if idx else "^"


def _tasks_of(struct: dict) -> dict[str, tuple[dict, dict]]:
    return {_ref(t): (b, t) for b in struct["blocks"] for t in b["tasks"]}


def diff(old: dict, new: dict) -> list[dict]:
    """Return the changes that turn structure `old` into `new` (see the `op`s below)."""
    out: list[dict] = []
    old_b = {b["id"]: b for b in old["blocks"]}
    new_b = {b["id"]: b for b in new["blocks"]}
    new_ids = [b["id"] for b in new["blocks"]]
    out += [{"op": "block_add", "id": b["id"], "name": b["name"], "after": _after(new_ids, b["id"])}
            for b in new["blocks"] if b["id"] not in old_b]
    out += [{"op": "block_rename", "id": b["id"], "old": old_b[b["id"]]["name"], "new": b["name"]}
            for b in new["blocks"] if b["id"] in old_b and old_b[b["id"]]["name"] != b["name"]]
    out += [{"op": "block_needs", "id": b["id"], "name": b["name"],
             "old": old_b[b["id"]].get("needs", []), "new": b.get("needs", [])}
            for b in new["blocks"] if b["id"] in old_b and old_b[b["id"]].get("needs", []) != b.get("needs", [])]
    common_new = [i for i in new_ids if i in old_b]
    kept = _kept([i for i in old_b if i in new_b], common_new)
    out += [{"op": "block_move", "id": i, "name": new_b[i]["name"], "after": _after(new_ids, i)}
            for i in common_new if i not in kept]
    old_t, new_t = _tasks_of(old), _tasks_of(new)
    stay: set[str] = set()
    for b in new["blocks"]:                       # tasks that keep their block and their place in it
        if b["id"] in old_b:
            was = [_ref(t) for t in old_b[b["id"]]["tasks"] if _ref(t) in new_t and new_t[_ref(t)][0]["id"] == b["id"]]
            now = [_ref(t) for t in b["tasks"] if _ref(t) in old_t and old_t[_ref(t)][0]["id"] == b["id"]]
            stay |= _kept(was, now)
    for b in new["blocks"]:
        refs = [_ref(t) for t in b["tasks"]]
        for t in b["tasks"]:
            ref = _ref(t)
            place = {"block": b["id"], "block_name": b["name"], "after": _after(refs, ref)}
            if ref not in old_t:
                out.append({"op": "task_add", "ref": ref} | place | {"task": t})
                continue
            if ref not in stay:
                out.append({"op": "task_move", "ref": ref} | place)
            was = old_t[ref][1]
            out.extend({"op": "task_set", "ref": ref, "field": f, "old": was[f], "new": t[f]}
                       for f in ("n", "pinned") if was[f] != t[f])
    out.extend({"op": "task_remove", "ref": ref, "block": b["id"]}
               for ref, (b, _t) in old_t.items() if ref not in new_t)
    out.extend({"op": "block_remove", "id": i, "name": b["name"]} for i, b in old_b.items() if i not in new_b)
    if bool(old["auto_update"]) != bool(new["auto_update"]):
        out.append({"op": "auto_update", "old": bool(old["auto_update"]), "new": bool(new["auto_update"])})
    return out


def describe(change: dict) -> str:  # noqa: C901, PLR0911
    """Say one change in words, for the page and the sync report."""
    op = change["op"]
    if op == "task_add":
        return f"добавлено задание {change['ref']} в блок «{change['block_name']}»"
    if op == "task_remove":
        return f"убрано задание {change['ref']}"
    if op == "task_move":
        return f"задание {change['ref']} перенесено: блок «{change['block_name']}»"
    if op == "task_set" and change["field"] == "n":
        return f"ревизия {change['ref']}: v{change['old']} → v{change['new']}"
    if op == "task_set":
        return f"{change['ref']}: {'закреплено' if change['new'] else 'откреплено'}"
    if op == "block_add":
        return f"новый блок «{change['name']}»"
    if op == "block_remove":
        return f"убран блок «{change['name']}»"
    if op == "block_rename":
        return f"блок «{change['old']}» → «{change['new']}»"
    if op == "block_move":
        return f"блок «{change['name']}» передвинут"
    if op == "block_needs":
        return (f"блок «{change['name']}» открывается после других блоков" if change["new"]
                else f"блок «{change['name']}» открыт без условий")
    return f"автообновление: {'включено' if change['new'] else 'выключено'}"


# -- three-way merge ----------------------------------------------------------

def _key(change: dict) -> tuple[str, str, str]:
    """Return what element, and which side of it, a change touches."""
    op = change["op"]
    if op.startswith("task_"):
        aspect = change["field"] if op == "task_set" else ("place" if op == "task_move" else "exist")
        return ("task", change["ref"], aspect)
    if op.startswith("block_"):
        aspect = {"block_rename": "name", "block_move": "place", "block_needs": "needs"}.get(op, "exist")
        return ("block", change["id"], aspect)
    return ("auto_update", "", "")


def _insert(items: list, item: object, after: str, key: object) -> None:
    keys = [key(x) for x in items]
    if after == "^":
        items.insert(0, item)
    elif after in keys:
        items.insert(keys.index(after) + 1, item)
    else:
        items.append(item)


def _task_block(struct: dict, ref: str) -> dict | None:
    return next((b for b in struct["blocks"] if any(_ref(t) == ref for t in b["tasks"])), None)


def _block_for(struct: dict, change: dict) -> dict:
    block = next((b for b in struct["blocks"] if b["id"] == change["block"]), None)
    if block is None:
        block = {"id": change["block"], "name": change["block_name"], "tasks": []}
        struct["blocks"].append(block)
    return block


def _apply(struct: dict, change: dict) -> None:  # noqa: C901
    op = change["op"]
    blocks = struct["blocks"]
    by_id = {b["id"]: b for b in blocks}
    if op == "block_add" and change["id"] not in by_id:
        _insert(blocks, {"id": change["id"], "name": change["name"], "tasks": []}, change["after"],
                lambda b: b["id"])
    elif op == "block_rename" and change["id"] in by_id:
        by_id[change["id"]]["name"] = change["new"]
    elif op == "block_move" and change["id"] in by_id:
        blocks.remove(by_id[change["id"]])
        _insert(blocks, by_id[change["id"]], change["after"], lambda b: b["id"])
    elif op == "block_needs" and change["id"] in by_id:
        by_id[change["id"]].pop("needs", None)
        # a block id still here, or a task of this course (`owner/name:tag`, user 2026-11-05)
        if needs := [i for i in change["new"] if i in by_id or _task_block(struct, i) is not None]:
            by_id[change["id"]]["needs"] = needs
    elif op == "block_remove" and change["id"] in by_id:
        blocks.remove(by_id[change["id"]])
    elif op == "task_add" and _task_block(struct, change["ref"]) is None:
        _insert(_block_for(struct, change)["tasks"], dict(change["task"]), change["after"], _ref)
    elif op == "task_move" and (src := _task_block(struct, change["ref"])) is not None:
        task = next(t for t in src["tasks"] if _ref(t) == change["ref"])
        src["tasks"].remove(task)
        _insert(_block_for(struct, change)["tasks"], task, change["after"], _ref)
    elif op == "task_remove" and (src := _task_block(struct, change["ref"])) is not None:
        src["tasks"] = [t for t in src["tasks"] if _ref(t) != change["ref"]]
    elif op == "task_set" and (src := _task_block(struct, change["ref"])) is not None:
        next(t for t in src["tasks"] if _ref(t) == change["ref"])[change["field"]] = change["new"]
    elif op == "auto_update":
        struct["auto_update"] = change["new"]


def _same(a: dict, b: dict) -> bool:
    """Whether two changes of one element end the same way."""
    drop = {"block_name", "name", "old"}
    return {k: v for k, v in a.items() if k not in drop} == {k: v for k, v in b.items() if k not in drop}


def merge3(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[dict]]:
    """
    Bring the changes `base -> theirs` (the parent's) into `ours` (a fork); return (result, conflicts).

    A change of the same side of an element (a task's place, revision, pin; a block's name, place)
    that `ours` changed too, to a different end, is a conflict: ours stays and the parent's change
    is reported. So is the parent removing a task ours touched, changing one ours removed, or
    removing a block that still holds tasks of ours.
    """
    mine = diff(base, ours)
    mine_keys = {_key(c): c for c in mine}
    touched = {_key(c)[:2] for c in mine}
    result = json.loads(json.dumps(ours))
    conflicts: list[dict] = []
    late: list[dict] = []
    for change in diff(base, theirs):
        key = _key(change)
        if key in mine_keys:                       # the same side of the same element
            if not _same(change, mine_keys[key]):
                conflicts.append(change)
            continue
        gone_here = (key[0], key[1], "exist") in mine_keys      # ours removed it
        if (change["op"] == "task_remove" and key[:2] in touched) or (
                change["op"] in ("task_set", "task_move", "block_rename", "block_move", "block_needs")
                and gone_here):
            conflicts.append(change)
            continue
        if change["op"] == "block_remove":         # after the tasks: it may still hold ours
            late.append(change)
            continue
        _apply(result, change)
    for change in late:
        block = next((b for b in result["blocks"] if b["id"] == change["id"]), None)
        if block is not None and block["tasks"]:
            conflicts.append(change)
        else:
            _apply(result, change)
    return result, conflicts
