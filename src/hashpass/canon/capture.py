"""Post-run snapshot of observed paths → Observation."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileState:
    """Snapshot of a file's state: kind and (optionally) text content."""

    kind: str  # "file" | "dir" | "absent"
    text: str | None


Observation = dict[str, "FileState"]


def read_state(p: Path) -> FileState:
    if p.is_dir():
        return FileState("dir", None)
    if p.is_file():
        try:
            return FileState("file", p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            return FileState("file", None)
    return FileState("absent", None)


def capture(rootfs: Path, observe: list[str], *, output_path: str | None = None,
            bool_observe: list[str] | None = None) -> Observation:
    rootfs = Path(rootfs)
    obs: Observation = {}
    for rel in observe:
        base = rootfs / rel.lstrip("/")
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    obs[str(f.relative_to(rootfs))] = read_state(f)
        else:
            obs[rel.lstrip("/")] = read_state(base)
    for rel in bool_observe or []:                       # existence/kind only -- no content, no recursion
        obs[rel.lstrip("/")] = FileState(read_state(rootfs / rel.lstrip("/")).kind, None)
    if output_path is not None:
        obs["<output>"] = read_state(rootfs / output_path.lstrip("/"))
    return obs
