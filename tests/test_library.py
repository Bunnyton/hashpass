"""Tier1: the client's search over every task and image -- here and on the pool (TODO 2026-10-23)."""
import pytest

from hashpass.library import collect


def _pool(name: str, *, task: bool, n: int = 1, about: str = "") -> dict:
    return {"name": name, "task": task, "about": about, "updated": "2026-10-23T10:00:00Z",
            "tags": [{"tag": "1", "n": n, "ref": f"{name}:1_v{n}", "task": task}]}


@pytest.mark.tier1
def test_local_builds_come_first_tasks_apart_from_images_then_the_pool() -> None:
    local = [("bob/lab:1", "task"), ("bob/base:1", "image"), ("bunnyton/links:1_v4", "task")]
    pool = [_pool("bunnyton/links", task=True, n=4, about="Ссылки"), _pool("alice/web", task=False)]
    rows = collect(local, pool, "")
    assert [(r.section, r.ref) for r in rows] == [
        ("Задания на этой машине", "bob/lab:1"),
        ("Задания на этой машине", "bunnyton/links:1_v4"),
        ("Образы на этой машине", "bob/base:1"),
        ("Задания на пуле", "bunnyton/links:1"),
        ("Образы на пуле", "alice/web:1"),
    ]
    links = rows[3]
    assert (links.kind, links.n, links.about, links.local) == ("task", 4, "Ссылки", True)  # downloaded already


@pytest.mark.tier1
def test_the_query_filters_by_name_and_description() -> None:
    pool = [_pool("bunnyton/links", task=True, about="Символьные ссылки"), _pool("alice/web", task=False)]
    assert [r.ref for r in collect([("bob/lab:1", "task")], pool, "СИМВОЛ")] == ["bunnyton/links:1"]
    assert [r.ref for r in collect([("bob/lab:1", "task")], pool, "lab")] == ["bob/lab:1"]
