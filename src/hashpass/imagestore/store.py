"""Local image store: images/<name>/<version>/{layer/,meta.json}."""
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_VERSION = "latest"


@dataclass(frozen=True)
class StoredImage:
    """A stored image: its name/version, on-disk layer dir, and parent refs."""

    name: str
    version: str
    layer: Path
    parents: tuple[str, ...]


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

    def _dir(self, name: str, version: str) -> Path:
        return self._root / name / version

    def save(
        self,
        name: str,
        version: str,
        layer_dir: Path,
        parents: tuple[str, ...],
        *,
        sudo: bool = False,
    ) -> StoredImage:
        """
        Copy a layer directory into the store and record its parents.

        Args:
            name: Image name.
            version: Image version.
            layer_dir: Source rootfs-delta directory copied in as the layer.
            parents: Direct `from` refs, in declaration order.
            sudo: Whether to use sudo rsync for copying (handles root-owned files).

        Returns:
            The StoredImage describing the saved entry.

        """
        dest = self._dir(name, version)
        layer = dest / "layer"
        if layer.exists():
            shutil.rmtree(layer)
        dest.mkdir(parents=True, exist_ok=True)
        if sudo:
            layer.mkdir()
            # rsync as root: copies root-owned files AND preserves ownership/perms.
            subprocess.run(
                ["sudo", "rsync", "-a", str(layer_dir) + "/", str(layer) + "/"],
                check=True,
            )
        else:
            shutil.copytree(layer_dir, layer)
        meta = {"name": name, "version": version, "parents": list(parents)}
        (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return StoredImage(name, version, layer, parents)

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
        return StoredImage(name, version, dest / "layer", tuple(meta["parents"]))

    def exists(self, ref: str) -> bool:
        """Return whether an image is stored under the reference."""
        name, version = _split_ref(ref)
        return (self._dir(name, version) / "meta.json").exists()
