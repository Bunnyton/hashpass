"""Local image store: images/<name>/<version>/{layer/,meta.json}."""
import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_VERSION = "latest"
# A version, and each "/"-separated segment of a name, must be ONE safe path component: no "\",
# no "..", no leading ".", no NUL, not absolute. This blocks a traversal write when name/version
# come from an untrusted blob (registry push on the server, or anonymous pull on the client). A
# NAME may be multi-segment (`ns/app`) for namespacing -- every segment is checked, so the joined
# path still cannot escape the images root. See §5.
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_BLOB_PREFIX = "blob-"
_BLOB_SUFFIX = ".tar.gz"


def _check_component(kind: str, value: str) -> None:
    """Reject a version that is not a single safe path component (traversal guard)."""
    if not _COMPONENT.fullmatch(value):
        msg = f"unsafe image {kind}: {value!r}"
        raise ValueError(msg)


def _check_name(name: str) -> None:
    """Reject a name whose "/"-segments are not each a safe path component (traversal guard)."""
    segments = name.split("/")
    if not all(_COMPONENT.fullmatch(seg) for seg in segments):
        msg = f"unsafe image name: {name!r}"
        raise ValueError(msg)


def _is_blob_name(name: str) -> bool:
    """Check if a filename is a blob (blob-<digest>.tar.gz)."""
    return name.startswith(_BLOB_PREFIX) and name.endswith(_BLOB_SUFFIX)


def _write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON via a temp file + Path.replace so readers never see a torn meta.json."""
    fd, tmp = tempfile.mkstemp(prefix=".meta-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        Path(tmp).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


@dataclass(frozen=True)
class StoredImage:
    """A stored image: its name/version, on-disk layer dir, parent refs, and build-cache key."""

    name: str
    version: str
    layer: Path
    parents: tuple[str, ...]
    build_key: str | None = None
    taskfile_path: str | None = None   # absolute path of the Taskfile this was built from (author side)
    digest: str | None = None          # server: sha256 of the blob this generation serves
    blob: str | None = None            # server: file name of that blob inside the image dir
    pool_digest: str | None = None     # client: digest of the blob this copy was pulled from
    pool_digests: dict[str, str] = field(default_factory=dict)   # client: per registry_key(url)
    base: str | None = None            # server: the pinned base revision it was built on


def _split_ref(ref: str) -> tuple[str, str]:
    name, sep, version = ref.partition(":")
    return name, (version if sep else _DEFAULT_VERSION)


_MAX_SUGGESTIONS = 3


def _remove_tree(tree: Path) -> None:
    """
    Delete `tree`; when the user may not (files of another uid), empty it with `sudo rsync`.

    Best effort: a tree that still cannot go stays as a `layer.old-*` leftover -- the live layer
    is already in place, and the next root-owned unpack sweeps leftovers.
    """
    with contextlib.suppress(OSError):
        shutil.rmtree(tree)
    if not tree.exists():
        return
    empty = tree.parent / f".empty-{tree.name}"
    try:
        empty.mkdir(exist_ok=True)
        subprocess.run(["sudo", "rsync", "-a", "--delete", str(empty) + "/", str(tree) + "/"],
                       check=True, capture_output=True)
        tree.rmdir()
    except (subprocess.CalledProcessError, OSError):
        pass
    finally:
        with contextlib.suppress(OSError):
            empty.rmdir()


def registry_key(url: str) -> str:
    """Normalize a pool URL to its `host[:port]` key (scheme, trailing slash and case dropped)."""
    return url.strip().partition("://")[2].rstrip("/").lower() if "://" in url \
        else url.strip().rstrip("/").lower()


def similar_refs(refs: Iterable[str], ref: str) -> list[str]:
    """
    Return up to three stored refs sharing `ref`'s short name (last `/` segment), the ref excluded.

    `debian:trixie` against a store holding `bunnyton/debian:trixie` yields exactly that. Twins
    with the same version (other namespaces) come first, then other versions of the same short
    name (any namespace, including none -- e.g. a legacy `debian:trixie-18`), each group sorted.
    """
    name, version = _split_ref(ref)
    short = name.rpartition("/")[2]
    exact, others = [], []
    for candidate in sorted(set(refs)):
        c_name, c_version = _split_ref(candidate)
        if c_name.rpartition("/")[2] != short or (c_name, c_version) == (name, version):
            continue
        (exact if c_version == version else others).append(f"{c_name}:{c_version}")
    return (exact + others)[:_MAX_SUGGESTIONS]


def did_you_mean(suggestions: list[str]) -> str:
    """Russian hint for `similar_refs` output («быть может, вы искали X или Y?»); '' if none."""
    if not suggestions:
        return ""
    return f"быть может, вы искали {' или '.join(suggestions)}?"


class ImageStore:
    """A local filesystem image store rooted at an images/ directory."""

    def __init__(self, root: Path) -> None:
        """
        Initialize the store at the given images/ root (created on demand).

        Args:
            root: Directory that holds per-image <name>/<version>/ trees.

        """
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """The store's images/ root directory."""
        return self._root

    def _dir(self, name: str, version: str) -> Path:
        return self._root / name / version

    # -- aliases: a tag pointing at a pulled revision (`x:1` -> `x:1_v2`), like `docker pull` ----

    def _aliases_path(self) -> Path:
        return self._root / ".aliases.json"

    def _aliases(self) -> dict[str, str]:
        try:
            data = json.loads(self._aliases_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _write_aliases(self, data: dict[str, str]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self._aliases_path(), data)

    def set_alias(self, ref: str, target: str) -> None:
        """Point `ref` at the stored `target` (a later build or save of `ref` takes it back)."""
        data = self._aliases()
        data[ref] = target
        self._write_aliases(data)

    def alias_of(self, ref: str) -> str | None:
        """Return the revision `ref` points at, or None when it is not an alias."""
        return self._aliases().get(ref)

    def _drop_alias(self, name: str, version: str) -> None:
        data = self._aliases()
        if data.pop(f"{name}:{version}", None) is not None:
            self._write_aliases(data)

    def _resolve(self, name: str, version: str) -> tuple[str, str]:
        """
        Return the stored (name, version) a ref means: its alias target, else itself.

        The last action wins: a pull sets the alias (over a local build of the same tag), a
        build or save of the tag drops it again.
        """
        target = self._aliases().get(f"{name}:{version}")
        if target:
            t_name, t_version = _split_ref(target)
            if (self._dir(t_name, t_version) / "meta.json").exists():
                return t_name, t_version
        return name, version

    def save(  # noqa: PLR0913
        self,
        name: str,
        version: str,
        layer_dir: Path,
        parents: tuple[str, ...],
        *,
        sudo: bool = False,
        build_key: str | None = None,
    ) -> StoredImage:
        """
        Copy a layer directory into the store and record its parents + build key.

        Args:
            name: Image name.
            version: Image version.
            layer_dir: Source rootfs-delta directory copied in as the layer.
            parents: Direct `from` refs, in declaration order.
            sudo: Whether to use sudo rsync for copying (handles root-owned files).
            build_key: Content hash of the build inputs (base+parents+steps); reused to skip
                an unchanged rebuild. None for layers with no recipe (e.g. the base image).

        Returns:
            The StoredImage describing the saved entry.

        """
        _check_name(name)
        _check_component("version", version)
        self._drop_alias(name, version)
        dest = self._dir(name, version)
        layer = dest / "layer"
        dest.mkdir(parents=True, exist_ok=True)
        if sudo:
            layer.mkdir(exist_ok=True)
            # rsync as root: copies + preserves ownership AND deletes stale (root-owned) files.
            subprocess.run(
                ["sudo", "rsync", "-a", "--delete", str(layer_dir) + "/", str(layer) + "/"],
                check=True,
            )
        else:
            # The old layer may hold files of ANOTHER uid (the container's student is 1000, the
            # host user may not be): a plain rmtree of it failed with «Permission denied …/layer/
            # home» and the new layer never landed (find-2, 2026-10-13). Move it aside (a rename
            # in our own directory always works), put the new one live, then remove the old one.
            old = None
            if layer.exists():
                old = dest / f"layer.old-{uuid.uuid4().hex}"
                layer.rename(old)
            # symlinks=True: an image layer routinely holds symlinks whose targets live in the
            # BASE image (a dpkg drop), so following them (the shutil default) trips on the
            # dangling absolute path and blows up unpack.  Keep them as-is.
            shutil.copytree(layer_dir, layer, symlinks=True)
            if old is not None:
                _remove_tree(old)
        meta = {"name": name, "version": version, "parents": list(parents),
                "build_key": build_key}
        _write_json_atomic(dest / "meta.json", meta)
        return StoredImage(name, version, layer, parents, build_key)

    def _read_meta(self, name: str, version: str) -> dict:
        meta_path = self._dir(name, version) / "meta.json"
        if not meta_path.exists():
            ref = f"{name}:{version}"
            raise KeyError(ref)
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def get(self, ref: str) -> StoredImage:
        """
        Look up a stored image by `name:version` (a bare name uses 'latest').

        Args:
            ref: Image reference, `name` or `name:version`.

        Returns:
            The StoredImage for the reference.

        Raises:
            KeyError: If no image is stored under the reference.

        """
        name, version = self._resolve(*_split_ref(ref))
        meta = self._read_meta(name, version)
        dest = self._dir(name, version)
        return StoredImage(name, version, dest / "layer", tuple(meta["parents"]),
                           meta.get("build_key"), meta.get("taskfile_path"),
                           digest=meta.get("digest"), blob=meta.get("blob"),
                           pool_digest=meta.get("pool_digest"),
                           pool_digests=dict(meta.get("pool_digests") or {}),
                           base=meta.get("base"))

    def set_taskfile_path(self, ref: str, taskfile_path: str) -> None:
        """Record (in meta.json) the Taskfile an image was built from, for push to attach later."""
        name, version = self._resolve(*_split_ref(ref))
        meta_path = self._dir(name, version) / "meta.json"
        if not meta_path.exists():
            raise KeyError(ref)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["taskfile_path"] = taskfile_path
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def similar(self, ref: str) -> list[str]:
        """Return stored refs with `ref`'s short name under another namespace (see `similar_refs`)."""
        return similar_refs(self.list(), ref)

    def exists(self, ref: str) -> bool:
        """Return whether an image is stored under the reference (or under the revision it aliases)."""
        name, version = self._resolve(*_split_ref(ref))
        return (self._dir(name, version) / "meta.json").exists()

    @staticmethod
    def validate_ref(name: str, version: str) -> None:
        """Reject names/versions that are not safe path components (traversal guard)."""
        _check_name(name)
        _check_component("version", version)

    def dir(self, name: str, version: str) -> Path:
        """Return the image directory for name/version (validated; may not exist yet)."""
        self.validate_ref(name, version)
        return self._dir(name, version)

    def publish_blob(self, name: str, version: str, tmp_blob: Path, *,
                     parents: tuple[str, ...], digest: str) -> StoredImage:
        """
        Publish an uploaded blob as this ref's current generation (server side).

        The blob is moved to `blob-<digest>.tar.gz` (immutable, content-named), then meta.json
        naming it is replaced atomically — a reader sees either the old (blob, digest) pair or
        the new one, never a mix. Older generations' blobs are removed best-effort afterwards.
        """
        self.validate_ref(name, version)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            msg = f"unsafe image digest: {digest!r}"
            raise ValueError(msg)
        dest = self._dir(name, version)
        dest.mkdir(parents=True, exist_ok=True)
        final = dest / f"{_BLOB_PREFIX}{digest}{_BLOB_SUFFIX}"
        tmp_blob.replace(final)
        meta = {"name": name, "version": version, "parents": list(parents),
                "build_key": None, "digest": digest, "blob": final.name}
        _write_json_atomic(dest / "meta.json", meta)
        for stale in dest.glob(f"{_BLOB_PREFIX}*{_BLOB_SUFFIX}"):
            if stale.name != final.name:
                with contextlib.suppress(OSError):
                    stale.unlink()
        return self.get(f"{name}:{version}")

    def list(self) -> list[str]:
        """
        Return sorted `name:version` refs for every stored image (walks the images root).

        A name may be multi-segment (`ns/app`), so an image dir sits at a variable depth: the
        version dir is the one holding both `meta.json` and `layer/`, and the name is its path
        relative to the root minus the trailing version. Descent is pruned at each such dir so
        an image's own `layer/` tree (arbitrary files) is never scanned for more images.
        """
        if not self._root.exists():
            return []
        refs: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            # dot-dirs are the pool's own bookkeeping (`.staging/`, `.repos/`, `.commit-*`, `.incoming/`)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            has_blob = any(_is_blob_name(f) for f in filenames)
            if "meta.json" in filenames and ("layer" in dirnames or has_blob):
                ver_dir = Path(dirpath)
                name = ver_dir.parent.relative_to(self._root).as_posix()
                refs.append(f"{name}:{ver_dir.name}")
                dirnames[:] = []  # prune: don't descend into this image's layer/ (or below)
        return sorted(refs)

    def blob_path(self, ref: str) -> Path | None:
        """Path of the blob file this ref's current generation serves; None for layer-only records."""
        path = self.blob_path_of(self.get(ref))
        return path if path is not None and path.exists() else None

    def blob_path_of(self, img: StoredImage) -> Path | None:
        """
        Path of the blob an ALREADY-READ record names (no second meta.json read, no exists check).

        Use this when the digest and the file must come from one meta read (a concurrent publish
        swaps both); None when the record names no blob or a name that is not `blob-*.tar.gz`.
        """
        if not img.blob or not _is_blob_name(img.blob) or "/" in img.blob:
            return None
        return self._dir(img.name, img.version) / img.blob

    def remove(self, ref: str) -> None:
        """Delete a stored image (an alias: just the alias), root-owned layers included."""
        name, version = _split_ref(ref)
        target = self._aliases().get(f"{name}:{version}")
        if target is not None:
            self._drop_alias(name, version)
            return
        dest = self.dir(name, version)
        if dest.is_dir():
            _remove_tree(dest)

    def set_meta_field(self, ref: str, key: str, value: str) -> None:
        """Record one extra field in a stored image's meta.json (e.g. the base it was built on)."""
        name, version = self._resolve(*_split_ref(ref))
        meta = self._read_meta(name, version)
        meta[key] = value
        _write_json_atomic(self._dir(name, version) / "meta.json", meta)

    def link_revision(self, src_ref: str, dst_name: str, dst_version: str, *,
                      parents: tuple[str, ...]) -> StoredImage:
        """
        Publish `src_ref`'s blob + `task/` under another name/version, sharing the blob (server side).

        The blob is hard-linked (same content, same digest, no copy); across filesystems it is
        copied. `task/` is copied (small). The new record names its own pinned `parents`.
        """
        src = self.get(src_ref)
        src_blob = self.blob_path_of(src)
        if src_blob is None or not src.digest:
            msg = f"{src_ref}: no blob to link"
            raise ValueError(msg)
        self.validate_ref(dst_name, dst_version)
        dest = self._dir(dst_name, dst_version)
        dest.mkdir(parents=True, exist_ok=True)
        final = dest / src_blob.name
        try:
            os.link(src_blob, final)
        except FileExistsError:
            pass
        except OSError:
            shutil.copyfile(src_blob, final)
        task = src.layer.parent / "task"
        if task.is_dir():
            shutil.copytree(task, dest / "task", symlinks=True, dirs_exist_ok=True)
        meta = {"name": dst_name, "version": dst_version, "parents": list(parents),
                "build_key": None, "digest": src.digest, "blob": final.name}
        _write_json_atomic(dest / "meta.json", meta)
        return self.get(f"{dst_name}:{dst_version}")

    def write_meta(self, name: str, version: str, *, parents: tuple[str, ...],
                   build_key: str | None = None) -> None:
        """(Re)write a layer record's meta.json, keeping a previously recorded pool_digest."""
        self.validate_ref(name, version)
        self._drop_alias(name, version)
        dest = self._dir(name, version)
        dest.mkdir(parents=True, exist_ok=True)
        old: dict = {}
        with contextlib.suppress(KeyError):
            old = self._read_meta(name, version)
        meta = {"name": name, "version": version, "parents": list(parents), "build_key": build_key}
        if old.get("pool_digest"):
            meta["pool_digest"] = old["pool_digest"]
        if old.get("pool_digests"):
            meta["pool_digests"] = old["pool_digests"]
        if old.get("taskfile_path"):
            meta["taskfile_path"] = old["taskfile_path"]
        _write_json_atomic(dest / "meta.json", meta)

    def set_pool_digest(self, ref: str, digest: str, *, registry: str | None = None) -> None:
        """
        Record the pool digest this local copy was pulled from / pushed as (staleness reference).

        `pool_digest` is the last digest seen from any pool (what `pull --refresh` compares);
        with `registry`, the digest is also remembered per pool under `registry_key(registry)`,
        so a push to the local registry never masquerades as the state of prod.
        """
        name, version = self._resolve(*_split_ref(ref))
        meta = self._read_meta(name, version)          # KeyError if absent
        meta["pool_digest"] = digest
        if registry is not None:
            per_pool = dict(meta.get("pool_digests") or {})
            per_pool[registry_key(registry)] = digest
            meta["pool_digests"] = per_pool
        _write_json_atomic(self._dir(name, version) / "meta.json", meta)
