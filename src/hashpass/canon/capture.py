"""Post-run snapshot of observed paths → Observation."""
import posixpath
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileState:
    """Snapshot of a file's state: kind and (optionally) text content."""

    kind: str  # "file" | "hardlink" | "link" | "dir" | "perms" | "absent"
    text: str | None


Observation = dict[str, "FileState"]

PERMS = "perms:"   # `observe perms <path>` rides on observe as `perms:<path>`


def read_perms(p: Path) -> FileState:
    """Mode bits + numeric owner:group of a path (not following a symlink) -- `chmod`/`chgrp` results."""
    try:
        st = p.lstat()
    except OSError:
        return FileState("absent", None)
    return FileState("perms", f"{st.st_mode & 0o7777:04o} {st.st_uid}:{st.st_gid}")


def read_state(p: Path, inside: str | None = None) -> FileState:
    """
    Snapshot one path; `inside` is where `p` lives in the student's system (`/home/student/l`).

    A symlink is a `link` whose text is the absolute path it points to inside that system --
    `d/f`, `./d/f` and `/home/student/d/f` read the same, and a copy is never a link (the links
    task, 2026-10-14). A file with more than one name is a `hardlink` (content compared as for a
    file), so `ln notes backup` differs from `cp notes backup`.
    """
    if p.is_symlink():
        target = str(p.readlink())
        if inside is not None:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(inside), target))
        return FileState("link", target)
    if p.is_dir():
        return FileState("dir", None)
    if p.is_file():
        kind = "hardlink" if p.stat().st_nlink > 1 else "file"
        try:
            return FileState(kind, p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            return FileState(kind, None)
    return FileState("absent", None)


_MAX_LINKS = 40   # as the kernel's ELOOP limit


def resolve_inside(rootfs: Path, path: str) -> Path | None:
    """
    Resolve `path` of the student's system as that system would: links followed inside `rootfs`.

    A target from the root (`/home/student/logs/a.log`) and `..` above `/` stay inside, as under
    chroot. None for a link loop. The result may not exist (a dangling link).
    """
    parts = [p for p in path.split("/") if p not in ("", ".")]
    done: list[str] = []
    hops = 0
    while parts:
        part = parts.pop(0)
        if part == "..":
            if done:
                done.pop()
            continue
        here = rootfs.joinpath(*done, part)
        if not here.is_symlink():
            done.append(part)
            continue
        hops += 1
        if hops > _MAX_LINKS:
            return None
        target = str(here.readlink())
        if target.startswith("/"):
            done = []
        parts = [p for p in target.split("/") if p not in ("", ".")] + parts
    return rootfs.joinpath(*done)


def capture(rootfs: Path, observe: list[str], *, output_path: str | None = None,
            bool_observe: list[str] | None = None) -> Observation:
    rootfs = Path(rootfs)
    obs: Observation = {}
    for rel in observe:
        if rel.startswith(PERMS):
            path = rel[len(PERMS):].lstrip("/")
            obs[PERMS + path] = read_perms(rootfs / path)
            continue
        base = rootfs / rel.lstrip("/")
        if base.is_dir() and not base.is_symlink():
            for f in sorted(base.rglob("*")):
                if f.is_symlink() or f.is_file():
                    key = str(f.relative_to(rootfs))
                    obs[key] = read_state(f, "/" + key)
        else:
            obs[rel.lstrip("/")] = read_state(base, "/" + rel.lstrip("/"))
    for rel in bool_observe or []:                       # existence/kind only -- no content, no recursion
        obs[rel.lstrip("/")] = FileState(read_state(rootfs / rel.lstrip("/")).kind, None)
    if output_path is not None:
        obs["<output>"] = read_state(rootfs / output_path.lstrip("/"))
    return obs
