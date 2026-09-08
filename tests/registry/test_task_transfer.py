"""Task blob transport: pack/unpack round-trip + /task PUT (author) / GET (token) over the pool."""
import urllib.error
from http import HTTPStatus

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_task, unpack_task
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest


def _make_task_dir(root) -> None:
    (root / "bundle").mkdir(parents=True)
    (root / "bundle" / "checks.json").write_text('{"stages":[]}', encoding="utf-8")
    (root / "hp").mkdir()
    (root / "hp" / "grade").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (root / "task-meta.json").write_text('{"image_ref":"lab:1"}', encoding="utf-8")


def _seed_image(store, tmp_path, name) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, "1", src, ())


@pytest.mark.tier1
def test_pack_unpack_preserves_digest(tmp_path):
    src = tmp_path / "task"
    src.mkdir()
    _make_task_dir(src)
    dest = tmp_path / "out"
    unpack_task(pack_task(src), dest)
    assert task_digest(dest) == task_digest(src)
    assert (dest / "bundle" / "checks.json").exists()
    assert (dest / "hp" / "grade").exists()
    assert (dest / "task-meta.json").exists()


@pytest.mark.tier2
def test_push_task_author_gated_then_pull(registry, tmp_path):
    registry.users.add("author1", "pw", role="author")
    student_c = RemoteRegistry(registry.base_url)
    student_tok = student_c.register("stud", "pw", group="G")
    author_c = RemoteRegistry(registry.base_url)
    author_tok = author_c.login("author1", "pw")

    local = ImageStore(tmp_path / "local")
    _seed_image(local, tmp_path, "lab")

    # a student cannot push the image
    with pytest.raises(urllib.error.HTTPError) as exc:
        student_c.push(local, "lab:1", token=student_tok)
    assert exc.value.code == HTTPStatus.FORBIDDEN

    # the author pushes image + task
    author_c.push(local, "lab:1", token=author_tok)
    task_src = tmp_path / "task"
    task_src.mkdir()
    _make_task_dir(task_src)
    author_c.push_task(task_src, "lab", "1", token=author_tok)

    # a logged-in student pulls the task, and the digest survives transport
    dest = tmp_path / "pulled"
    student_c.pull_task("lab:1", dest, token=student_tok)
    assert task_digest(dest) == task_digest(task_src)


@pytest.mark.tier2
def test_put_task_before_image_is_404(registry, tmp_path):
    registry.users.add("author1", "pw", role="author")
    c = RemoteRegistry(registry.base_url)
    tok = c.login("author1", "pw")
    task_src = tmp_path / "task"
    task_src.mkdir()
    _make_task_dir(task_src)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.push_task(task_src, "ghost", "1", token=tok)
    assert exc.value.code == HTTPStatus.NOT_FOUND
