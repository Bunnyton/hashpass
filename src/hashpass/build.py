"""Build reusable images from recipes (overlay + nspawn) and run bare images."""
# Build cache (Docker-style, coarse): a build's inputs -- base identity, parents, and every
# `run`/`copy` step (a COPY hashed by its source content) -- fold into one `build_key` stored in
# the image meta. A rebuild whose key matches the stored image reuses it and does NOT re-run any
# step. (Per-step layer reuse was tried but each nspawn step's delta carries container side effects
# -- /dev nodes, machine-id, /run -- that overlayfs refuses to stack, so this whole-build key is
# the robust form; change any step and the whole image rebuilds, same as `docker build` from that
# point with no matching prefix cache.)
import hashlib
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore, StoredImage
from hashpass.overlay import overlay_mount, overlay_umount
from hashpass.recipe.model import CopyStep, Recipe, RunStep
from hashpass.runner.nspawn import NspawnRunner

_Step = CopyStep | RunStep


def _hash_source(path: Path) -> str:
    """Hash a COPY source so editing the copied file(s) busts the cache (like Docker's checksum)."""
    p = Path(path)
    h = hashlib.sha256()
    if p.is_dir():
        for f in sorted(p.rglob("*")):
            h.update(str(f.relative_to(p)).encode())
            h.update(b"\0")
            if f.is_file():
                h.update(f.read_bytes())
            h.update(b"\0")
    elif p.is_file():
        h.update(p.read_bytes())
    else:
        h.update(b"<missing>")
    return h.hexdigest()


def _step_repr(step: _Step) -> str:
    """Canonical cache-relevant text for a step (RUN command; COPY dest + source content hash)."""
    if isinstance(step, RunStep):
        return "run\0" + step.cmd
    return "copy\0" + step.dst + "\0" + _hash_source(step.src)


def _base_stamp(base: Path) -> str:
    """Return a stable identity for the base layer (its runtime version stamp, else its path)."""
    try:
        return (Path(base) / "etc" / "hp-base-version").read_text(encoding="utf-8").strip()
    except OSError:
        return str(base)


def _build_key(base: Path, parents: tuple[str, ...], steps: Sequence[_Step]) -> str:
    """Fold base identity + parents + every step (COPY by source content) into one cache key."""
    h = hashlib.sha256()
    h.update(("base\0" + _base_stamp(base) + "\0parents\0" + ",".join(parents)).encode())
    for step in steps:
        h.update(b"\0")
        h.update(_step_repr(step).encode())
    return h.hexdigest()


def build(  # noqa: PLR0913
    recipe: Recipe,
    store: ImageStore,
    *,
    base_tar: Path | None = None,
    base: Path | None = None,
    workdir: Path,
    sudo: bool = True,
    progress: Callable[[str], None] | None = None,
) -> StoredImage:
    """
    Build a recipe into a stored image layer (the overlay delta), with a build cache.

    If a stored image with the same `build_key` (base + parents + all steps) already exists, it
    is reused verbatim -- no step re-runs. Otherwise: mount the resolved parent lowers over a
    fresh base, apply `copy`/`run` steps into one upperdir, and store it as the image layer.

    Args:
        recipe: The parsed recipe to build.
        store: Image store to resolve parents from and save the result into.
        base_tar: Rootfs tarball for the bottom base layer (fallback when `base` is None).
        base: Prebuilt base rootfs layer (the `debian:trixie` image); when given it is
            used directly and `base_tar` is ignored (built once in the store, reused).
        workdir: Scratch directory for base/upper/work/mnt.
        sudo: Whether overlay mounts use sudo (True for real nspawn).
        progress: Optional sink for per-step build-progress lines.

    Returns:
        The StoredImage for the newly built layer.

    """
    workdir = Path(workdir)
    ref = f"{recipe.name}:{recipe.version}"
    lowers = resolve_lowers(recipe.parents, store)
    base = base or build_base(workdir / "base", from_tar=base_tar)
    key = _build_key(base, recipe.parents, recipe.steps)
    if store.exists(ref):
        cached = store.get(ref)
        if cached.build_key == key:                   # identical inputs -> reuse, run nothing
            if progress is not None:
                progress(f"образ {ref} не изменился — беру из кэша (сборка пропущена)")
            return cached
    upper = workdir / "upper"
    work = workdir / "work"
    mnt = workdir / "mnt"
    for d in (upper, work, mnt):
        d.mkdir(parents=True, exist_ok=True)
    overlay_mount([*lowers, base], upper, work, mnt, sudo=sudo)
    try:
        for i, step in enumerate(recipe.steps):
            label = f"шаг {i + 1}/{len(recipe.steps)}"
            if isinstance(step, CopyStep):
                if progress is not None:
                    progress(f"{label}: копирую {step.src} → {step.dst}")
                subprocess.run(["sudo", "rsync", "-a", "--mkpath", step.src,
                                str(mnt / step.dst.lstrip("/"))], check=True)
            else:
                if progress is not None:
                    progress(f"{label}: выполняю: {step.cmd}")
                subprocess.run(["sudo", "systemd-nspawn", "-q", "--register=no",
                                "-D", str(mnt), "sh", "-c", step.cmd], check=True)
    finally:
        overlay_umount(mnt, sudo=sudo)
    return store.save(recipe.name, recipe.version, upper, recipe.parents, sudo=sudo, build_key=key)


def run_image(ref: str, store: ImageStore, workdir: Path, *,
              base_tar: Path | None = None, base: Path | None = None) -> NspawnRunner:
    """
    Prepare a booted runner over a stored image's overlay closure (booted env).

    Resolves the image's transitive layer closure (the image itself topmost)
    and mounts it over a fresh base, returning the prepared runner. The caller
    drives it with `.run(...)`/`.rootfs` and must `.teardown()` when done.

    Args:
        ref: Image reference `name` or `name:version` to run.
        store: Image store holding the image and its ancestors.
        workdir: Scratch directory for base and the runner tree.
        base_tar: Rootfs tarball for the bottom base layer (fallback when `base` is None).
        base: Prebuilt base rootfs layer (the `debian:trixie` image); when given it is
            used directly and `base_tar` is ignored (built once in the store, reused).

    Returns:
        A prepared NspawnRunner (mounted image; the caller foreground-boots it).

    """
    workdir = Path(workdir)
    lowers = resolve_lowers((ref,), store)  # raises KeyError if ref is absent
    base = base or build_base(workdir / "base", from_tar=base_tar)
    runner = NspawnRunner(workdir / "run", base_dir=base)
    runner.prepare(lowers)
    return runner
