"""Build reusable images from recipes (overlay + nspawn) and run bare images."""
import subprocess
from pathlib import Path

from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore, StoredImage
from hashpass.overlay import overlay_mount, overlay_umount
from hashpass.recipe.model import Recipe


def build(
    recipe: Recipe,
    store: ImageStore,
    *,
    base_tar: Path,
    workdir: Path,
    sudo: bool = True,
) -> StoredImage:
    """
    Build a recipe into a stored image layer (the overlay delta).

    Mounts the resolved parent lowers over a fresh base, applies `copy` and
    `run` steps, then stores the upperdir as the image's own layer (delta).

    Args:
        recipe: The parsed recipe to build.
        store: Image store to resolve parents from and save the result into.
        base_tar: Rootfs tarball for the bottom base layer.
        workdir: Scratch directory for base/upper/work/mnt.
        sudo: Whether overlay mounts use sudo (True for real nspawn).

    Returns:
        The StoredImage for the newly built layer.

    """
    workdir = Path(workdir)
    lowers = resolve_lowers(recipe.parents, store)
    base = build_base(workdir / "base", from_tar=base_tar)
    upper = workdir / "upper"
    work = workdir / "work"
    mnt = workdir / "mnt"
    for d in (upper, work, mnt):
        d.mkdir(parents=True, exist_ok=True)
    overlay_mount([*lowers, base], upper, work, mnt, sudo=sudo)
    try:
        for step in recipe.copies:
            dst = mnt / step.dst.lstrip("/")
            subprocess.run(["sudo", "rsync", "-a", step.src, str(dst)], check=True)
        for cmd in recipe.runs:
            subprocess.run(
                ["sudo", "systemd-nspawn", "-q", "--register=no",
                 "-D", str(mnt), "sh", "-c", cmd],
                check=True,
            )
    finally:
        overlay_umount(mnt, sudo=sudo)
    return store.save(recipe.name, recipe.version, upper, recipe.parents, sudo=sudo)
