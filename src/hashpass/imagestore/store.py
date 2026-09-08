"""Local image store: images/<name>/<version>/{layer/,meta.json}."""
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_VERSION = "latest"
# A version, and each "/"-separated segment of a name, must be ONE safe path component: no "\",
# no "..", no leading ".", no NUL, not absolute. This blocks a traversal write when name/version
# come from an untrusted blob (registry push on the server, or anonymous pull on the client). A
# NAME may be multi-segment (`ns/app`) for namespacing -- every segment is checked, so the joined
# path still cannot escape the images root. See §5.
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


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


@dataclass(frozen=True)
class StoredImage:
    """A stored image: its name/version, on-disk layer dir, parent refs, and build-cache key."""

    name: str
    version: str
    layer: Path
    parents: tuple[str, ...]
    build_key: str | None = None


def _split_ref(ref: str) -> tuple[str, str]:
    name, sep, version = ref.partition(":")
    return name, (version if sep else _DEFAULT_VERSION)


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
            if layer.exists():
                shutil.rmtree(layer)
            shutil.copytree(layer_dir, layer)
        meta = {"name": name, "version": version, "parents": list(parents),
                "build_key": build_key}
        (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return StoredImage(name, version, layer, parents, build_key)

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
        name, version = _split_ref(ref)
        dest = self._dir(name, version)
        meta_path = dest / "meta.json"
        if not meta_path.exists():
            raise KeyError(ref)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return StoredImage(name, version, dest / "layer", tuple(meta["parents"]),
                           meta.get("build_key"))

    def exists(self, ref: str) -> bool:
        """Return whether an image is stored under the reference."""
        name, version = _split_ref(ref)
        return (self._dir(name, version) / "meta.json").exists()

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
            if "meta.json" in filenames and "layer" in dirnames:
                ver_dir = Path(dirpath)
                name = ver_dir.parent.relative_to(self._root).as_posix()
                refs.append(f"{name}:{ver_dir.name}")
                dirnames[:] = []  # prune: don't descend into this image's layer/ (or below)
        return sorted(refs)
