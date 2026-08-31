"""FROM-DAG resolver: transitive parent closure -> deterministic deduped overlay lowers."""
from pathlib import Path

from hashpass.imagestore.store import ImageStore


def resolve_lowers(parents: tuple[str, ...], store: ImageStore) -> list[Path]:
    """
    Resolve a recipe's direct parents to an ordered, deduped overlay lowers list.

    Topmost-first: a later-declared parent has higher priority (sits higher /
    earlier); each parent's own ancestors sit below it; a shared ancestor
    appears exactly once at its lowest required position. This is a topological
    sort (a node precedes all of its ancestors) with declaration order as the
    tie-break, realized as a post-order DFS (a node emitted after its parents)
    that is reversed at the end.

    Args:
        parents: Direct `from` refs, in declaration order.
        store: Image store used to look up each ref's own parents.

    Returns:
        Layer directories, topmost first (bottommost last).

    """
    visited: set[str] = set()
    post: list[Path] = []

    def visit(ref: str) -> None:
        if ref in visited:
            return
        visited.add(ref)
        img = store.get(ref)
        for parent in img.parents:
            visit(parent)
        post.append(img.layer)

    for ref in parents:
        visit(ref)
    post.reverse()
    return post
