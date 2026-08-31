"""Registry port + ref parsing + transitive `from`-closure over the local image store."""
from typing import Protocol

from hashpass.imagestore.store import ImageStore

_DEFAULT_VERSION = "latest"


def split_ref(ref: str) -> tuple[str, str]:
    """Split `name:version` into parts; a bare name defaults to 'latest'."""
    name, sep, version = ref.partition(":")
    return name, (version if sep else _DEFAULT_VERSION)


def normalize_ref(ref: str) -> str:
    """Canonicalize a ref to `name:version` (a bare name becomes `name:latest`)."""
    name, version = split_ref(ref)
    return f"{name}:{version}"


def closure_refs(ref: str, store: ImageStore) -> list[str]:
    """
    Return ref plus its transitive `from` parents, dependencies-first and deduplicated.

    Bottom-up: every ref is emitted after all of its ancestors, exactly once, with the
    target ref last. This is a post-order DFS over each image's stored parents (a node
    emitted after its parents), with declaration order as the tie-break — the same walk
    as `imagestore.resolve.resolve_lowers`, minus the final reverse (push/pull want
    parents transferred before the children that reference them).

    Args:
        ref: The target image reference.
        store: Image store used to look up each ref's own parents.

    Returns:
        Canonical `name:version` refs, ancestors first, target last.

    """
    visited: set[str] = set()
    order: list[str] = []

    def visit(current: str) -> None:
        canon = normalize_ref(current)
        if canon in visited:
            return
        visited.add(canon)
        for parent in store.get(current).parents:
            visit(parent)
        order.append(canon)

    visit(ref)
    return order


class Registry(Protocol):
    """A place images are pushed to / pulled from by name, with their `from` closure."""

    def push(self, store: ImageStore, ref: str, *, token: str | None = None) -> list[str]: ...
    def pull(self, ref: str, store: ImageStore) -> list[str]: ...
