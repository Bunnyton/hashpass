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
from hashpass.lab.mask import masked
from hashpass.machines import machine_name
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
    owner = "" if step.owner == "root" else "\0owner\0" + step.owner
    return "copy\0" + step.dst + "\0" + _hash_source(step.src) + owner


def _owner_ids(rootfs: Path, user: str) -> str:
    """
    Return `uid:gid` of `user` as the IMAGE knows it (its /etc/passwd), for `rsync --chown`.

    A name would resolve against the host's passwd, where `student` does not exist (and uid 1000
    is the author) -- so the ids come from the image itself.

    Raises:
        ValueError: the image has no such user.

    """
    if user == "root":
        return "0:0"
    for line in (rootfs / "etc" / "passwd").read_text(encoding="utf-8").splitlines():
        fields = line.split(":")
        if len(fields) > 3 and fields[0] == user:   # noqa: PLR2004 -- name:x:uid:gid
            return f"{fields[2]}:{fields[3]}"
    msg = f"user {user!r}: no such user in the image (create it with `run useradd` first)"
    raise ValueError(msg)


def _copy(step: CopyStep, rootfs: Path) -> None:
    """
    Copy a host file or directory into the image, owned by `step.owner`, without group/other write.

    A directory source lands as its CONTENTS at dst (docker COPY semantics), so
    `copy data/tree /home/student/tree` never nests a second `tree/` inside. Its entries are
    copied one by one: an existing dst directory keeps its own owner and mode (`copy data/home
    /home/student` must not hand the student's home to root, `copy data/bin /usr/local/bin` must
    not hand /usr/local/bin to anyone); a missing one is created by root.
    """
    dst = rootfs / step.dst.lstrip("/")
    rsync = ["sudo", "rsync", "-a", "--mkpath", f"--chown={_owner_ids(rootfs, step.owner)}",
             "--chmod=go-w"]
    src = Path(step.src)
    if not src.is_dir():
        subprocess.run([*rsync, str(src), str(dst)], check=True)
        return
    entries = sorted(str(p) for p in src.iterdir())
    if not entries:
        subprocess.run([*rsync, "--dirs", str(src) + "/", str(dst) + "/"], check=True)
        return
    subprocess.run([*rsync, *entries, str(dst) + "/"], check=True)


def _base_stamp(base: Path) -> str:
    """Return a stable identity for the base layer (its runtime version stamp, else its path)."""
    try:
        return (Path(base) / "etc" / "hp-base-version").read_text(encoding="utf-8").strip()
    except OSError:
        return str(base)


def _parent_ids(store: ImageStore, parents: tuple[str, ...]) -> tuple[str, ...]:
    """
    Identify each parent by ref AND content (`ref@build_key`), so a rebuilt parent invalidates its children.

    A parent without a build key (pulled from a pool, committed from a console) is identified by
    its ref plus its pool digest when it has one -- there is nothing better to hash short of the
    whole layer.
    """
    out = []
    for ref in parents:
        img = store.get(ref)
        out.append(f"{ref}@{img.build_key or img.pool_digest or ''}")
    return tuple(out)


def _lay_extra(extra: tuple[Path, str] | None, upper: Path) -> None:
    """Lay a build's extra files (a lab's `/.hp-nodes`, root-owned) into its layer."""
    if extra is not None:
        subprocess.run(["sudo", "rsync", "-a", f"{extra[0]}/", f"{upper}/"], check=True)


def _build_key(base: Path, parents: tuple[str, ...], steps: Sequence[_Step], *,
               extra: str | None = None) -> str:
    """
    Fold base identity + parents + every step (COPY by source content) into one cache key.

    `parents` are the ids from `_parent_ids` (ref@content), never bare refs: a child built on
    an older generation of its parent must not be served from the cache once the parent changed.
    """
    h = hashlib.sha256()
    h.update(("base\0" + _base_stamp(base) + "\0parents\0" + ",".join(parents)).encode())
    for step in steps:
        h.update(b"\0")
        h.update(_step_repr(step).encode())
    if extra is not None:
        h.update(b"\0extra\0" + extra.encode())
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
    extra: tuple[Path, str] | None = None,
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
        base: Prebuilt base rootfs layer -- the base image (`bunnyton/debian:trixie`,
            see `cli.base_ref`); when given it is used directly and `base_tar` is ignored
            (built once in the store, reused).
        workdir: Scratch directory for base/upper/work/mnt.
        sudo: Whether overlay mounts use sudo (True for real nspawn).
        progress: Optional sink for per-step build-progress lines.
        extra: (directory, key): files laid into the layer after the steps (a lab's `/.hp-nodes`),
            and their identity for the build cache.

    Returns:
        The StoredImage for the newly built layer.

    """
    workdir = Path(workdir)
    ref = f"{recipe.name}:{recipe.version}"
    lowers = masked(resolve_lowers(recipe.parents, store), store.root)   # `from <lab>`: no /.hp-nodes
    base = base or build_base(workdir / "base", from_tar=base_tar)
    key = _build_key(base, _parent_ids(store, recipe.parents), recipe.steps,
                     extra=extra[1] if extra else None)
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
                _copy(step, mnt)
            else:
                if progress is not None:
                    progress(f"{label}: выполняю: {step.cmd}")
                subprocess.run(["sudo", "systemd-nspawn", "-q", "--register=no", "-M", machine_name(),
                                "-D", str(mnt), "sh", "-c", step.cmd], check=True)
    finally:
        overlay_umount(mnt, sudo=sudo)
    _lay_extra(extra, upper)
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
        base: Prebuilt base rootfs layer -- the base image (`bunnyton/debian:trixie`,
            see `cli.base_ref`); when given it is used directly and `base_tar` is ignored
            (built once in the store, reused).

    Returns:
        A prepared NspawnRunner (mounted image; the caller foreground-boots it).

    """
    workdir = Path(workdir)
    lowers = masked(resolve_lowers((ref,), store), store.root)  # KeyError if ref is absent
    base = base or build_base(workdir / "base", from_tar=base_tar)
    runner = NspawnRunner(workdir / "run", base_dir=base)
    runner.prepare(lowers)
    return runner
