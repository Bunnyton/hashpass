"""
One-time move of a pre-courses pool to revisions + courses (spec 2026-10-21 §13).

Idempotent: a marker in the store root records it; a second start does nothing. Before any
change the pool's JSON state (catalog, users, config, approved copies index) is copied to
`.backup-courses-<time>/`. Steps:

1. images: every stored `name:version` (not yet a revision) becomes tag `version`, revision
   `_v1` (its directory, attachments and sources renamed); a version already ending in a
   reserved suffix becomes `-vN`/`-latest`. Where the catalog's approved version differs from the
   current one and an approved copy exists, the copy becomes `_v1` and the current `_v2`.
   Parents are pinned to the new revision names; images other than the base stand on it.
2. the catalog becomes course `<owner>/linux` («Linux», public): blocks, order, open/hidden as
   they were; approved tasks at their approved revision (pinned if an update was waiting, with
   an open or rejected `update` proposal); never-approved ones as `add` proposals.
3. users: former authors become authors in that course; a group moves to the front of the
   comment; everyone with progress has started the course.
4. `default_course` names it.
"""
import json
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from hashpass.registry import courses as cm
from hashpass.registry.approved import ApprovedStore
from hashpass.registry.catalog import Catalog
from hashpass.registry.config import save_config
from hashpass.registry.revisions import REVISION_RE, revision_version
from hashpass.taskdigest import task_digest

if TYPE_CHECKING:
    from hashpass.registry.server import PoolServer

MARKER = ".migrated-courses"
PLAN = ".migrate-plan.json"
_RESERVED_END = re.compile(r"_(v[0-9]+|latest)$")


def _safe_version(version: str) -> str:
    return _RESERVED_END.sub(lambda m: "-" + m.group(1), version)


def migrate_to_courses(server: "PoolServer", *, owner: str, base_ref: str,  # noqa: C901, PLR0912, PLR0915
                       course_name: str = "linux", title: str = "Linux") -> dict[str, object]:
    """Move the pool to revisions + a default course; return what was done (empty if already)."""
    root = Path(server.store.root)
    if (root / MARKER).exists():
        return {}
    report: dict[str, object] = {"images": 0, "tasks": 0, "proposals": 0}
    catalog_path = Path(server.catalog_path or root / "catalog.json")
    catalog = Catalog(catalog_path)
    entries = {e.ref: e for e in catalog.entries()}
    approved = ApprovedStore(root / "approved")
    plan_path = root / PLAN
    if plan_path.exists():                        # an interrupted run: continue its own plan
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        plan = _plan(server, entries, approved)   # raises on a name collision, before any change
        backup = root / f".backup-courses-{int(time.time())}"
        backup.mkdir(parents=True, exist_ok=True)
        for src in (catalog_path, server.users._path, server.config_path):   # noqa: SLF001
            if src and Path(src).is_file():
                shutil.copy2(src, backup / Path(src).name)
        tmp = plan_path.with_name(plan_path.name + ".tmp")
        tmp.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        tmp.replace(plan_path)

    for ref, p in plan.items():                    # every step checks what is already done
        name, version, current_v = p["name"], p["version"], p["current"].partition(":")[2]
        src, dest = server.store.dir(name, version), server.store.dir(name, current_v)
        if src.is_dir() and not dest.exists():
            src.rename(dest)
        _move_ref_dir(server.attachments()._dir(ref), server.attachments()._dir(p["current"]))  # noqa: SLF001
        _move_ref_dir(server.sources()._dir(ref), server.sources()._dir(p["current"]))  # noqa: SLF001
        if p["two"]:
            _materialize_copy(server, approved, ref, p)
        report["images"] = int(report["images"]) + 1

    current = {ref: p["current"] for ref, p in plan.items()}
    renamed = {ref: p["shown"] for ref, p in plan.items()}
    base_rev = current.get(base_ref) or (base_ref if server.store.exists(base_ref) else None)

    def pin(parent: str) -> str:
        return current.get(parent, parent)

    for ref, p in plan.items():
        name, tag = p["name"], p["tag"]
        revs = [renamed[ref]] + ([current[ref]] if current[ref] != renamed[ref] else [])
        with server.repo(name).locked() as idx:
            for rev_ref in revs:
                n = int(REVISION_RE.match(rev_ref.partition(":")[2]).group("n"))
                rev_dir = server.store.dir(*rev_ref.split(":", 1))
                meta = json.loads((rev_dir / "meta.json").read_text(encoding="utf-8"))
                meta["parents"] = [pin(q) for q in meta.get("parents", [])]
                if base_rev and rev_ref != base_rev and ref != base_ref:
                    meta["base"] = base_rev
                (rev_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                if idx.get(tag, n) is not None:
                    continue
                if idx.peek_next(tag) != n:
                    msg = f"миграция: у {name}:{tag} уже есть ревизии, ожидалась _v{n} — остановлено"
                    raise RuntimeError(msg)
                task = rev_dir / "task"
                idx.add(tag, {"image_digest": meta.get("digest") or "",
                              "task_digest": task_digest(task) if task.is_dir() else "",
                              "parents": meta["parents"], "by": name.partition("/")[0] or owner})

    # the catalog -> the default course
    store = server.course_api.courses
    ref_course = f"{owner}/{course_name}"
    if store.get(ref_course) is None:
        store.create(owner, course_name, title=title)
    with store.edit(ref_course) as course:
        course.blocks, course.proposals = [], []          # rebuilt whole: a resumed run never doubles
        for block in catalog.blocks():
            block_id = cm.add_block(course, block.name)
            cm.set_block_open(course, block_id, open_=block.open)
            for entry in block.entries:
                name, _, version = entry.ref.partition(":")
                tag = _safe_version(version)
                newest = current.get(entry.ref)
                if newest is None:
                    continue
                newest_n = int(REVISION_RE.match(newest.partition(":")[2]).group("n"))
                if entry.approved_digest:
                    shown = int(REVISION_RE.match(renamed[entry.ref].partition(":")[2]).group("n"))
                    task = cm.add_task(course, name, tag, shown, block_id, by=name.partition("/")[0] or owner)
                    task["hidden"] = entry.hidden
                    report["tasks"] = int(report["tasks"]) + 1
                    if newest_n != shown:
                        task["pinned"] = True       # else auto_update would ship the unapproved one
                        prop = cm.propose(course, "update", name, tag, newest_n, block_id,
                                          by=name.partition("/")[0] or owner, comment="", now=time.time())
                        if entry.state == "rejected":
                            cm.decide(course, prop["id"], accept=False, by=owner,
                                      reason=entry.reason, now=time.time())
                        report["proposals"] = int(report["proposals"]) + 1
                else:
                    prop = cm.propose(course, "add", name, tag, newest_n, block_id,
                                      by=name.partition("/")[0] or owner, comment="", now=time.time())
                    if entry.state == "rejected":
                        cm.decide(course, prop["id"], accept=False, by=owner, reason=entry.reason,
                                  now=time.time())
                    report["proposals"] = int(report["proposals"]) + 1
        for profile in server.users.all_users():
            if profile["role"] == "author" and profile["user"] != owner:
                course.members[str(profile["user"])] = "author"
    course_id = store.get(ref_course).id

    for profile in server.users.all_users():
        user, group = str(profile["user"]), str(profile["group"])
        if group and not str(profile["comment"]).startswith(group):
            server.users.set_comment(user, f"{group} · {profile['comment']}".rstrip(" ·"))
    for user in server.progress().all():
        server.course_api.enrollments.enroll(user, course_id)

    server.config.default_course = ref_course
    if server.config_path is not None:
        save_config(server.config_path, server.config)
    (root / MARKER).write_text(json.dumps({"at": time.time(), **report}), encoding="utf-8")
    plan_path.unlink(missing_ok=True)
    return report


def _plan(server: "PoolServer", entries: dict, approved: ApprovedStore) -> dict[str, dict]:
    """Every rename the move will do, computed up front; a collision stops it before any change."""
    plan: dict[str, dict] = {}
    taken: dict[tuple[str, str], str] = {}
    for ref in server.store.list():
        name, _, version = ref.partition(":")
        rev = REVISION_RE.match(version)
        if rev and server.repo(name).get(rev.group("tag"), int(rev.group("n"))) is not None:
            continue                              # a real revision (it is in the index)
        tag = _safe_version(version)
        if (name, tag) in taken:
            msg = f"миграция: {ref} и {taken[(name, tag)]} получили бы один тег {name}:{tag} — переименуйте один"
            raise RuntimeError(msg)
        if server.repo(name).revisions(tag):
            msg = f"миграция: у {name}:{tag} уже есть ревизии — {ref} некуда положить"
            raise RuntimeError(msg)
        taken[(name, tag)] = ref
        entry = entries.get(ref)
        two = bool(entry and entry.approved_digest and entry.approved_digest != entry.digest
                   and approved.task_digest(ref) == entry.approved_digest
                   and approved.blob(ref) is not None)
        plan[ref] = {"name": name, "version": version, "tag": tag, "two": two,
                     "current": f"{name}:{revision_version(tag, 2 if two else 1)}",
                     "shown": f"{name}:{revision_version(tag, 1)}"}
    return plan


def _materialize_copy(server: "PoolServer", approved: ApprovedStore, ref: str, p: dict) -> None:
    """Make the approved copy revision _v1 (built aside, then renamed in: never half-made)."""
    name = p["name"]
    old_dir = server.store.dir(name, p["shown"].partition(":")[2])
    if old_dir.exists():
        return
    work = old_dir.with_name(f".{old_dir.name}.incoming")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    digest = approved.digest(ref) or ""
    blob_name = f"blob-{digest}.tar.gz"
    shutil.copy2(approved.blob(ref), work / blob_name)
    if approved.task_dir(ref):
        shutil.copytree(approved.task_dir(ref), work / "task", symlinks=True)
    meta = {"name": name, "version": old_dir.name, "parents": list(approved.parents(ref)),
            "build_key": None, "digest": digest, "blob": blob_name}
    (work / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    new_files = server.attachments()._dir(p["current"])                  # noqa: SLF001
    old_files = server.attachments()._dir(p["shown"])                    # noqa: SLF001
    if new_files.is_dir() and not old_files.exists():
        shutil.copytree(new_files, old_files, symlinks=True)
    work.rename(old_dir)


def _move_ref_dir(src: Path, dst: Path) -> None:
    if src.is_dir() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
