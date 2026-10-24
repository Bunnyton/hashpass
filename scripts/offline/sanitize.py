#!/usr/bin/env python3
"""
Copy a pool's data dir into the offline bundle, without anything about people.

    sanitize.py SNAPSHOT OUT [--owner bunnyton ...]

SNAPSHOT is a pool's registry dir (`~/.hashpass/registry` of `hashpass serve`). OUT gets the
repositories, revisions, approved copies, attachments, sources and courses of the given owners,
plus the catalog and the pool settings. Accounts, progress, attempts, enrollments, uploads in
flight, course members and access requests stay behind: the bundle goes to strangers' machines.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

_PER_OWNER = ("", "approved", "attachments", "sources", ".repos", ".courses")


def _owner_of(ref: str) -> str:
    return ref.split("/", 1)[0] if "/" in ref else ""


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_course(path: Path, owners: set[str]) -> None:
    course = _json(path)
    course.update(members={}, requests=[], proposals=[], invite="", history=[])
    for block in course.get("blocks", []):
        block["tasks"] = [t for t in block.get("tasks", []) if _owner_of(str(t.get("repo", ""))) in owners]
    _write(path, course)


def _clean_repo(path: Path) -> None:
    repo = _json(path)
    repo["members"] = {}
    _write(path, repo)


def _clean_catalog(path: Path, owners: set[str]) -> None:
    catalog = _json(path)
    for block in catalog.get("blocks", []) if isinstance(catalog, dict) else []:
        block["tasks"] = [t for t in block.get("tasks", [])
                          if isinstance(t, dict) and _owner_of(str(t.get("name", ""))) in owners]
    _write(path, catalog)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("snapshot", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--owner", action="append", dest="owners", help="whose tasks go in (default bunnyton)")
    args = ap.parse_args(argv)
    owners = set(args.owners or ["bunnyton"])
    src, out = args.snapshot / "store", args.out / "store"
    if not src.is_dir():
        sys.stderr.write(f"нет {src}: это не каталог данных пула\n")
        return 1
    shutil.rmtree(args.out, ignore_errors=True)
    out.mkdir(parents=True)
    for sub in _PER_OWNER:
        for owner in sorted(owners):
            if (src / sub / owner).is_dir():
                shutil.copytree(src / sub / owner, out / sub / owner, symlinks=True)
    for path in out.glob(".courses/*/*/course.json"):
        _clean_course(path, owners)
    for path in out.glob(".repos/*/*/repo.json"):
        _clean_repo(path)
    for name in ("catalog.json", "config.json"):
        if (args.snapshot / name).is_file():
            shutil.copy2(args.snapshot / name, args.out / name)
    if (args.out / "catalog.json").is_file():
        _clean_catalog(args.out / "catalog.json", owners)
    config = _json(args.out / "config.json") if (args.out / "config.json").is_file() else {}
    config["registration_open"] = True        # the student signs up on their own machine
    _write(args.out / "config.json", config)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
