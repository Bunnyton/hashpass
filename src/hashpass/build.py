"""Build reusable images from recipes (overlay + nspawn) and run bare images."""
import subprocess
from pathlib import Path

from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore, StoredImage
from hashpass.overlay import overlay_mount, overlay_umount
from hashpass.recipe.model import CopyStep, Recipe, RunStep
from hashpass.runner.nspawn import NspawnRunner


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
        for step in recipe.steps:
            if isinstance(step, CopyStep):
                dst = mnt / step.dst.lstrip("/")
                subprocess.run(
                    ["sudo", "rsync", "-a", "--mkpath", step.src, str(dst)],
                    check=True,
                )
            elif isinstance(step, RunStep):
                subprocess.run(
                    ["sudo", "systemd-nspawn", "-q", "--register=no",
                     "-D", str(mnt), "sh", "-c", step.cmd],
                    check=True,
                )
    finally:
        overlay_umount(mnt, sudo=sudo)
    return store.save(recipe.name, recipe.version, upper, recipe.parents, sudo=sudo)


def run_image(ref: str, store: ImageStore, workdir: Path, *, base_tar: Path) -> NspawnRunner:
    """
    Prepare an NspawnRunner over a stored image's overlay closure (bare env).

    Resolves the image's transitive layer closure (the image itself topmost)
    and mounts it over a fresh base, returning the prepared runner. The caller
    drives it with `.run(...)`/`.rootfs` and must `.teardown()` when done.

    Args:
        ref: Image reference `name` or `name:version` to run.
        store: Image store holding the image and its ancestors.
        workdir: Scratch directory for base and the runner tree.
        base_tar: Rootfs tarball for the bottom base layer.

    Returns:
        A prepared NspawnRunner (no task; a bare image environment).

    """
    workdir = Path(workdir)
    lowers = resolve_lowers((ref,), store)  # raises KeyError if ref is absent
    base = build_base(workdir / "base", from_tar=base_tar)
    runner = NspawnRunner(workdir / "run", base_dir=base)
    runner.prepare(lowers)
    return runner
