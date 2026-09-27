"""Blob (tar) pack/unpack for HTTP transfer: images (meta + layer/) and tasks (bundle/hp/meta)."""
import contextlib
import io
import json
import stat
import subprocess
import tarfile
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from hashpass.imagestore.store import ImageStore, StoredImage


@dataclass(frozen=True)
class ImageBlobInfo:
    """What a blob declares (meta.json) and whether extracting it faithfully needs root."""

    name: str
    version: str
    parents: tuple[str, ...]
    needs_root: bool


def _member_is_unsafe(name: str) -> bool:
    parts = name.split("/")
    return name.startswith("/") or ".." in parts


def _norm(name: str) -> str:
    """Canonical member path: drop empty and `.` segments (`layer/./d/` == `layer/d`)."""
    return "/".join(p for p in name.split("/") if p not in ("", "."))


def _under_link(name: str, links: set[str]) -> bool:
    """Whether `name` itself, or any of its ancestors, is an already-seen symlink/hardlink member."""
    parts = name.split("/")
    return any("/".join(parts[:i]) in links for i in range(1, len(parts) + 1))


def _check_member(m: tarfile.TarInfo, name: str, links: set[str]) -> None:
    """
    Reject a member that would write outside the extraction root or create a device node.

    Names alone are not enough: a symlink `layer/d -> /home/student` followed by
    `layer/d/.bashrc` makes the extractor write THROUGH the link. So any member at or below a
    previously seen symlink/hardlink is refused; a hardlink must point inside `layer/` (and not
    at/through a link, since os.link follows symlinks). Absolute symlink TARGETS stay allowed
    -- dpkg ships `/etc/alternatives/*` -- they are never followed during extraction once
    nothing is written beneath them. Devices/FIFOs are refused: as root the sudo path would
    create real device nodes. The one exception is a 0:0 character device -- the overlayfs
    whiteout a layer (an overlay upperdir) uses to record a deleted file; it is inert.
    """
    if _under_link(name, links):
        msg = f"image blob: member under a symlink ancestor {m.name!r}"
        raise ValueError(msg)
    whiteout = m.ischr() and m.devmajor == 0 and m.devminor == 0     # overlay deletion marker
    if (m.ischr() and not whiteout) or m.isblk() or m.isfifo():
        msg = f"image blob: device/fifo member {m.name!r}"
        raise ValueError(msg)
    if m.islnk():
        target = _norm(m.linkname)
        if (not m.linkname.startswith("layer/") or _member_is_unsafe(m.linkname)
                or _under_link(target, links)):
            msg = f"image blob: hardlink {m.name!r} -> {m.linkname!r} escapes layer/"
            raise ValueError(msg)


def _check_in_layer(m: tarfile.TarInfo) -> None:
    """Every non-meta member is the `layer` directory itself or lives under `layer/`."""
    if m.name == "layer":
        if not m.isdir():
            msg = "image blob: no layer/ member (layer is not a directory)"
            raise ValueError(msg)
    elif not m.name.startswith("layer/"):
        msg = f"image blob: member outside layer/: {m.name!r}"
        raise ValueError(msg)


def _check_parents(parents: object) -> tuple[str, ...]:
    """Validate the declared parent refs (`name[:version]`, default `latest`) as safe refs."""
    if not isinstance(parents, list | tuple):
        msg = f"unsafe image parents: {parents!r}"
        raise ValueError(msg)                           # noqa: TRY004  one error type for callers
    out: list[str] = []
    for p in parents:
        name, sep, version = str(p).partition(":")
        ImageStore.validate_ref(name, version if sep else "latest")   # "unsafe image …"
        out.append(str(p))
    return tuple(out)


def _layer_has_unreadable(layer: Path) -> bool:
    """Return True if any file under `layer` is unreadable by the current user (root-owned 0640, …)."""
    try:
        for p in Path(layer).rglob("*"):
            if p.is_file() and not p.is_symlink():
                try:
                    with p.open("rb"):
                        pass
                except (PermissionError, OSError):
                    return True
    except (PermissionError, OSError):
        return True
    return False


def inspect_image_blob(path: Path) -> ImageBlobInfo:
    """
    Validate a blob's structure WITHOUT extracting it; return its declared identity.

    Accepted shape: a `meta.json` member plus a `layer` directory tree (every other member
    lives under `layer/`); no absolute or `..` paths; nothing at or below a symlink/hardlink
    member; hardlinks only inside `layer/`; no devices/FIFOs (bar overlay whiteouts); a safe
    name/version and safe parent refs. `needs_root` is True when any member is root-owned or
    setuid/setgid -- extracting such a layer as an unprivileged user would silently drop
    ownership (fatal for a base image).
    """
    with tarfile.open(path, mode="r") as tar:           # auto-detects gzip / plain
        meta_member: tarfile.TarInfo | None = None
        has_layer = False
        needs_root = False
        links: set[str] = set()                         # normalized names of symlink/hardlink members
        for m in tar:
            if m.name == "meta.json":
                meta_member = m
                continue
            if _member_is_unsafe(m.name):
                msg = f"image blob: unsafe member path {m.name!r}"
                raise ValueError(msg)
            _check_in_layer(m)
            has_layer = True
            name = _norm(m.name)
            _check_member(m, name, links)
            if m.issym() or m.islnk():
                links.add(name)
            if m.uid == 0 or m.mode & (stat.S_ISUID | stat.S_ISGID):
                needs_root = True
        if meta_member is None:
            msg = "image blob: no meta.json member"
            raise ValueError(msg)
        if not has_layer:
            msg = "image blob: no layer/ member"
            raise ValueError(msg)
        f = tar.extractfile(meta_member)
        meta = json.loads((f.read() if f else b"{}").decode("utf-8"))
    if not isinstance(meta, dict):
        msg = "image blob: meta.json is not an object"
        raise ValueError(msg)                           # noqa: TRY004  one error type for callers
    name, version = str(meta.get("name", "")), str(meta.get("version", ""))
    ImageStore.validate_ref(name, version)               # "unsafe image name/version"
    return ImageBlobInfo(name, version, _check_parents(meta.get("parents", [])), needs_root)


def blob_needs_root(path: Path) -> bool:
    """Whether faithful extraction of this blob needs root (see inspect_image_blob)."""
    return inspect_image_blob(path).needs_root


def pack_image_to_file(img: StoredImage, dest: Path) -> Path:
    """Pack a stored image (meta.json + layer/) into a gzip tar file at `dest`; return dest."""
    meta = json.dumps(
        {"name": img.name, "version": img.version, "parents": list(img.parents)},
    ).encode("utf-8")
    if _layer_has_unreadable(img.layer):
        _pack_via_sudo_tar(img.layer, meta, dest)
        return dest
    with tarfile.open(dest, mode="w:gz") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
        tar.add(img.layer, arcname="layer")
    return dest


def pack_image(img: StoredImage) -> bytes:
    """Pack a stored image into gzip tar bytes (thin wrapper over pack_image_to_file)."""
    with tempfile.TemporaryDirectory() as td:
        return pack_image_to_file(img, Path(td) / "image.tar.gz").read_bytes()


def _pack_via_sudo_tar(layer: Path, meta: bytes, dest: Path) -> None:
    """Build the gzip blob with `sudo tar` (root-only files in the layer), streaming into `dest`."""
    with tempfile.TemporaryDirectory() as td:
        staging = Path(td)
        (staging / "meta.json").write_bytes(meta)
        with dest.open("wb") as out:
            subprocess.run(
                ["sudo", "tar", "-czf", "-",
                 "-C", str(staging), "meta.json",
                 "--transform", f"s|^{str(layer).lstrip('/')}|layer|",
                 "-C", "/", str(layer).lstrip("/")],
                check=True, stdout=out, stderr=subprocess.PIPE,
            )


def unpack_image_file(path: Path, dest: ImageStore, *, sudo: bool | None = None) -> str:
    """
    Unpack a blob FILE into the store; return the stored `name:version` ref.

    `sudo=None` decides by the archive: root-owned/setuid members are extracted with
    `sudo tar` so ownership survives (Task 5); otherwise plain tarfile extraction as today.
    """
    info = inspect_image_blob(path)
    use_sudo = info.needs_root if sudo is None else sudo
    if use_sudo:
        return _unpack_root_owned(path, dest, info)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        with tarfile.open(path, mode="r") as tar:
            tar.extractall(tmp, filter="fully_trusted")   # noqa: S202  validated by inspect_image_blob
        img = dest.save(info.name, info.version, tmp / "layer", info.parents)
    return f"{img.name}:{img.version}"


def _cleanup_old_layers(image_dir: Path) -> None:
    """Remove every `layer.old-*` (root-owned) tree with granted-sudo rsync; ignore failures."""
    for old in sorted(image_dir.glob("layer.old-*")):
        empty = image_dir / f".empty-{old.name}"
        try:
            empty.mkdir(exist_ok=True)
            subprocess.run(["sudo", "rsync", "-a", "--delete", str(empty) + "/", str(old) + "/"],
                           check=True, capture_output=True)
            old.rmdir()
        except (subprocess.CalledProcessError, OSError):
            continue                                   # next pull retries; the live layer is fine
        finally:
            with contextlib.suppress(OSError):
                empty.rmdir()


def _unpack_root_owned(path: Path, dest: ImageStore, info: ImageBlobInfo) -> str:
    """
    Extract a root-owned blob with `sudo tar` and swap it in as the ref's layer atomically.

    The archive's `layer/…` members are extracted (owners and setuid preserved, since tar
    runs as root) into a user-created `layer.incoming-<uuid>` directory; two same-parent
    renames then publish it -- both allowed to the owner of the image directory. The
    previous layer is removed with `sudo rsync --delete` from an empty dir (the only
    granted way to delete root-owned trees); if that fails, the new layer is already live
    and the next pull sweeps `layer.old-*`.
    """
    image_dir = dest.dir(info.name, info.version)
    image_dir.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex
    incoming = image_dir / f"layer.incoming-{tag}"
    incoming.mkdir()
    try:
        subprocess.run(
            ["sudo", "tar", "-xpf", str(path), "--same-owner", "--strip-components=1",
             "-C", str(incoming), "layer"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError:
        with contextlib.suppress(OSError):
            incoming.rmdir()                            # only if tar left it empty
        raise
    layer = image_dir / "layer"
    if layer.exists():
        layer.rename(image_dir / f"layer.old-{tag}")
    incoming.rename(layer)
    dest.write_meta(info.name, info.version, parents=info.parents)
    _cleanup_old_layers(image_dir)
    return f"{info.name}:{info.version}"


def unpack_image(blob: bytes, dest: ImageStore, *, sudo: bool | None = None) -> str:
    """Unpack tar bytes into dest (wrapper: writes a temp file, then unpack_image_file)."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "image.blob"
        p.write_bytes(blob)
        return unpack_image_file(p, dest, sudo=sudo)


def pack_task(task_dir: Path) -> bytes:
    """Pack a task's artifacts dir (bundle/, hp/, task-meta.json) into a tar byte blob."""
    src = Path(task_dir)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for child in sorted(src.iterdir()):
            tar.add(child, arcname=child.name)
    return buf.getvalue()


def unpack_task(blob: bytes, dest_task_dir: Path) -> None:
    """Extract a task blob into dest_task_dir (creating it); mirrors `pack_task`."""
    dest = Path(dest_task_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r") as tar:
        tar.extractall(dest, filter="data")
