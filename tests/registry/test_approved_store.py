"""Tier1: the copy of a task's approved version that students keep while an update waits."""
import hashlib
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.approved import ApprovedStore
from hashpass.registry.blob import pack_image_to_file


def _published(tmp_path: Path, text: str) -> tuple[ImageStore, Path]:
    """Publish a server-side image with a blob + a task/ dir (as PUT /image + PUT /task leave it)."""
    local = ImageStore(tmp_path / "local")
    src = tmp_path / f"src-{text}"
    src.mkdir()
    (src / "f.txt").write_text(text, encoding="utf-8")
    local.save("bob/lab", "1", src, ())
    blob = tmp_path / f"{text}.blob"
    pack_image_to_file(local.get("bob/lab:1"), blob)
    srv = ImageStore(tmp_path / "srv")
    digest = hashlib.sha256(blob.read_bytes()).hexdigest()
    img = srv.publish_blob("bob/lab", "1", blob, parents=(), digest=digest)
    task = img.layer.parent / "task"
    task.mkdir(exist_ok=True)
    (task / "task-meta.json").write_text(text, encoding="utf-8")
    return srv, task


@pytest.mark.tier1
def test_take_copies_the_blob_and_the_task(tmp_path):
    srv, task = _published(tmp_path, "v1")
    approved = ApprovedStore(tmp_path / "approved")
    img = srv.get("bob/lab:1")
    assert approved.take("bob/lab:1", img, task, srv) == img.digest
    assert approved.digest("bob/lab:1") == img.digest
    assert approved.blob("bob/lab:1").read_bytes() == srv.blob_path_of(img).read_bytes()
    assert (approved.task_dir("bob/lab:1") / "task-meta.json").read_text(encoding="utf-8") == "v1"


@pytest.mark.tier1
def test_a_new_take_replaces_the_copy(tmp_path):
    srv, task = _published(tmp_path, "v1")
    approved = ApprovedStore(tmp_path / "approved")
    approved.take("bob/lab:1", srv.get("bob/lab:1"), task, srv)
    (task / "task-meta.json").write_text("v2", encoding="utf-8")
    approved.take("bob/lab:1", srv.get("bob/lab:1"), task, srv)
    assert (approved.task_dir("bob/lab:1") / "task-meta.json").read_text(encoding="utf-8") == "v2"


@pytest.mark.tier1
def test_a_legacy_image_without_a_blob_is_packed(tmp_path):
    srv = ImageStore(tmp_path / "srv")
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("old", encoding="utf-8")
    srv.save("bob/lab", "1", src, ())
    task = srv.get("bob/lab:1").layer.parent / "task"
    task.mkdir()
    approved = ApprovedStore(tmp_path / "approved")
    digest = approved.take("bob/lab:1", srv.get("bob/lab:1"), task, srv)
    assert digest and approved.blob("bob/lab:1").stat().st_size > 0


@pytest.mark.tier1
def test_nothing_and_removed(tmp_path):
    approved = ApprovedStore(tmp_path / "approved")
    assert (approved.blob("x/y:1"), approved.task_dir("x/y:1"), approved.digest("x/y:1")) == (None, None, None)
    srv, task = _published(tmp_path, "v1")
    approved.take("bob/lab:1", srv.get("bob/lab:1"), task, srv)
    approved.remove("bob/lab:1")
    assert approved.digest("bob/lab:1") is None
