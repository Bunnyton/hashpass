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
    backup = root / f".backup-courses-{int(time.time())}"
    backup.mkdir(parents=True, exist_ok=True)
    catalog_path = Path(server.catalog_path or root / "catalog.json")
    for src in (catalog_path, server.users._path, server.config_path):   # noqa: SLF001
        if src and Path(src).is_file():
            shutil.copy2(src, backup / Path(src).name)

    catalog = Catalog(catalog_path)
    entries = {e.ref: e for e in catalog.entries()}
    approved = ApprovedStore(root / "approved")
    plain = [r for r in server.store.list() if not REVISION_RE.match(r.partition(":")[2])]
    renamed: dict[str, str] = {}          # old ref -> the revision students had (catalogue view)
    current: dict[str, str] = {}          # old ref -> the newest revision
    for ref in plain:
        name, _, version = ref.partition(":")
        tag = _safe_version(version)
        entry = entries.get(ref)
        copy_digest = approved.task_digest(ref)
        two = bool(entry and entry.approved_digest and entry.approved_digest != entry.digest
                   and copy_digest == entry.approved_digest and approved.blob(ref) is not None)
        dest_new = server.store.dir(name, revision_version(tag, 2 if two else 1))
        server.store.dir(name, version).rename(dest_new)
        _move_ref_dir(server.attachments()._dir(ref), server.attachments()._dir(f"{name}:{dest_new.name}"))  # noqa: SLF001
        _move_ref_dir(server.sources()._dir(ref), server.sources()._dir(f"{name}:{dest_new.name}"))  # noqa: SLF001
        current[ref] = f"{name}:{dest_new.name}"
        renamed[ref] = current[ref]
        if two:
            old_dir = server.store.dir(name, revision_version(tag, 1))
            old_dir.mkdir(parents=True)
            digest = approved.digest(ref) or ""
            blob_name = f"blob-{digest}.tar.gz"
            shutil.copy2(approved.blob(ref), old_dir / blob_name)
            if approved.task_dir(ref):
                shutil.copytree(approved.task_dir(ref), old_dir / "task", symlinks=True)
            meta = {"name": name, "version": old_dir.name, "parents": list(approved.parents(ref)),
                    "build_key": None, "digest": digest, "blob": blob_name}
            (old_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            new_files = server.attachments()._dir(current[ref])               # noqa: SLF001
            if new_files.is_dir():
                shutil.copytree(new_files, server.attachments()._dir(f"{name}:{old_dir.name}"),  # noqa: SLF001
                                symlinks=True)
            renamed[ref] = f"{name}:{old_dir.name}"
        report["images"] = int(report["images"]) + 1

    base_rev = current.get(base_ref) or (base_ref if server.store.exists(base_ref) else None)

    def pin(parent: str) -> str:
        return current.get(parent, parent)

    for ref in plain:
        name, _, version = ref.partition(":")
        tag = _safe_version(version)
        revs = [renamed[ref]] + ([current[ref]] if current[ref] != renamed[ref] else [])
        with server.repo(name).locked() as idx:
            for rev_ref in revs:
                rev_dir = server.store.dir(*rev_ref.split(":", 1))
                meta = json.loads((rev_dir / "meta.json").read_text(encoding="utf-8"))
                meta["parents"] = [pin(p) for p in meta.get("parents", [])]
                if base_rev and rev_ref != base_rev and ref != base_ref:
                    meta["base"] = base_rev
                (rev_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
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
    return report


def _move_ref_dir(src: Path, dst: Path) -> None:
    if src.is_dir() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
