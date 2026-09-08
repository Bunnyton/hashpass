"""
Playground: build a Taskfile and auto-solve every stage with the reference solution.

Usage:  TMPDIR=/var/tmp/hp-pytest python3 docs/examples/author_playground.py <Taskfile>

Needs systemd-nspawn and scoped passwordless sudo (tier3), plus a prepared base rootfs tarball
(hashpass never builds it): set HASHPASS_BASE_TAR, else it reuses ~/.hashpass/base/rootfs.tar.
Prints ADVANCED/key or REJECTED per stage. Edit the `command = ...` line to feed your OWN commands
per stage instead of the reference `solve`.
"""
# Standalone example (not a package); /var/tmp is the intended scratch dir.
# ruff: noqa: INP001, S108
import os
import sys
from pathlib import Path

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import load_recipe
from hashpass.taskbuild import build_task
from hashpass.taskrun import run_task

_WORK = Path("/var/tmp/hp-playground")
_PASSES = 2
_ARGC = 2
_MSG_WIDTH = 60


def _base_tar() -> Path:
    """Locate a prepared Debian rootfs tarball (HASHPASS_BASE_TAR, else ~/.hashpass/base/rootfs.tar)."""
    explicit = os.environ.get("HASHPASS_BASE_TAR")
    candidates = ([Path(explicit)] if explicit else []) + [Path.home() / ".hashpass" / "base" / "rootfs.tar"]
    for tar in candidates:
        if tar.exists():
            return tar
    msg = ("нет базового rootfs: задайте HASHPASS_BASE_TAR или положите ~/.hashpass/base/rootfs.tar "
           "(готовится один раз вручную, напр. `docker export debian:trixie-slim -o rootfs.tar`)")
    raise SystemExit(msg)


def main() -> int:
    if len(sys.argv) != _ARGC:
        print("usage: author_playground.py <Taskfile>")
        return 2
    recipe = load_recipe(sys.argv[1])
    ref = f"{recipe.name}:{recipe.version}"
    base = _base_tar()
    store = ImageStore(_WORK / "images")

    print(f"building task {ref} ({len(recipe.stages)} stage(s)) — reference-solving each...")
    build_task(recipe, store, base_tar=base, workdir=_WORK / "build", passes=_PASSES)

    session = run_task(ref, store, _WORK / "run", base_tar=base, student_id="me", nonce="n1")
    all_ok = True
    try:
        session.enter()
        for i, stage in enumerate(recipe.stages):
            command = "\n".join(stage.solve)  # <-- reference solution; swap in your own command(s)
            res = session.feed(command, ts=f"2026-01-01T00:00:{i:02d}")
            status = f"ADVANCED {res.local_key}" if res.advanced else "REJECTED"
            print(f"  stage {i}: {status}   ({stage.message[:_MSG_WIDTH]})")
            all_ok = all_ok and res.advanced
    finally:
        session.teardown()
    print("OK — every stage was solved by its reference." if all_ok
          else "A stage did NOT advance — check the Taskfile / determinism.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
