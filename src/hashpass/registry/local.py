"""Filesystem registry (no auth): same on-disk layout as the local ImageStore."""
from dataclasses import dataclass
from pathlib import Path

from hashpass.imagestore.store import ImageStore
from hashpass.registry.refs import closure_refs


def _transfer_closure(refs: list[str], *, src: ImageStore, dest: ImageStore,
                      sudo: bool) -> list[str]:
    """Copy each ref (already bottom-up) from src to dest, skipping ones dest already has."""
    copied: list[str] = []
    for ref in refs:
        if dest.exists(ref):
            continue
        img = src.get(ref)
        dest.save(img.name, img.version, img.layer, img.parents, sudo=sudo)
        copied.append(ref)
    return copied


@dataclass
class LocalRegistry:
    """A filesystem registry with NO auth; same <name>/<ver>/{layer,meta.json} layout."""

    root: Path
    sudo: bool = False

    def _backing(self) -> ImageStore:
        return ImageStore(self.root)

    def push(self, store: ImageStore, ref: str, *, token: str | None = None) -> list[str]:
        """
        Copy ref + its `from` closure from a local store into the registry (bottom-up).

        No auth: `token` is accepted for Registry-protocol parity and ignored. Refs the
        registry already holds are skipped (idempotent); returns the refs newly copied.
        """
        _ = token
        return _transfer_closure(
            closure_refs(ref, store), src=store, dest=self._backing(), sudo=self.sudo,
        )

    def pull(self, ref: str, store: ImageStore) -> list[str]:
        """Copy ref + its `from` closure from the registry into a local store (bottom-up)."""
        src = self._backing()
        return _transfer_closure(closure_refs(ref, src), src=src, dest=store, sudo=self.sudo)
