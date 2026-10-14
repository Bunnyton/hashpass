"""Tier2: the deferred minors of the moderation review (2026-10-14)."""
import json
import urllib.error
from http import HTTPStatus

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.catalog import Catalog
from hashpass.registry.remote import RemoteRegistry
from tests.registry.test_moderation_routes import _http, _Pool


@pytest.mark.tier2
def test_closure_and_images_do_not_reveal_unapproved_tasks(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    pool.push("bob/lab", "v1")                                      # pending
    base = registry.base_url
    assert _http("GET", f"{base}/closure/bob/lab/1")[0] == HTTPStatus.NOT_FOUND
    assert _http("GET", f"{base}/closure/bob/lab/1", token=pool.tok["bob"])[0] == HTTPStatus.OK
    rows = json.loads(_http("GET", f"{base}/images", token=pool.tok["kid"])[2])["images"]
    assert "bob/lab:1" not in [r["ref"] for r in rows]
    rows = json.loads(_http("GET", f"{base}/images", token=pool.tok["bob"])[2])["images"]
    assert "bob/lab:1" in [r["ref"] for r in rows]


@pytest.mark.tier2
def test_a_task_outside_the_catalog_is_not_served_to_others(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    pool.push("bob/lab", "v1")
    pool.post("/catalog/approve", "root", {"ref": "bob/lab:1"})
    Catalog(registry.catalog_path).remove_task("bob/lab:1")          # dropped by a layout
    assert pool.task_marker("bob/lab:1", "kid") is None
    assert pool.task_marker("bob/lab:1", "bob") == "v1"


@pytest.mark.tier2
def test_approve_refuses_a_version_the_admin_did_not_see(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    pool.push("bob/lab", "v1")
    seen = next(r for r in pool.catalog("root") if r["ref"] == "bob/lab:1")["digest"]
    pool.push("bob/lab", "v2")                                       # re-pushed meanwhile
    assert pool.post("/catalog/approve", "root", {"ref": "bob/lab:1", "digest": seen}) == HTTPStatus.CONFLICT
    now = next(r for r in pool.catalog("root") if r["ref"] == "bob/lab:1")["digest"]
    assert pool.post("/catalog/approve", "root", {"ref": "bob/lab:1", "digest": now}) == HTTPStatus.OK


@pytest.mark.tier2
def test_an_image_others_build_on_cannot_be_deleted(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    pool.push("bob/lab", "v1")
    child = ImageStore(tmp_path / "child-src")
    src = tmp_path / "c"
    src.mkdir()
    (src / "f").write_text("c", encoding="utf-8")
    child.save("bob/lab", "1", src, ())                             # the parent, as the author has it
    child.save("bob/next", "1", src, ("bob/lab:1",))
    RemoteRegistry(registry.base_url).push(child, "bob/next:1", token=pool.tok["bob"])
    status, _, body = _http("DELETE", f"{registry.base_url}/task/bob/lab/1", token=pool.tok["bob"])
    assert status == HTTPStatus.CONFLICT and "bob/next:1" in json.loads(body)["error"]


@pytest.mark.tier2
def test_a_failing_copy_of_the_approved_version_is_a_readable_error(registry, tmp_path, monkeypatch):
    from hashpass.registry import approved  # noqa: PLC0415
    pool = _Pool(registry, tmp_path)
    pool.push("bob/lab", "v1")
    pool.post("/catalog/approve", "root", {"ref": "bob/lab:1"})

    def boom(*_a: object, **_k: object) -> str:
        msg = "No space left on device"
        raise OSError(msg)

    monkeypatch.setattr(approved.ApprovedStore, "take", boom)
    with pytest.raises(urllib.error.HTTPError) as exc:
        pool.push("bob/lab", "v2")
    assert exc.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "одобренную версию" in json.loads(exc.value.read())["error"]


@pytest.mark.tier1
def test_hashengine_push_shows_the_pools_reason_for_any_refusal():
    import io  # noqa: PLC0415

    from hashpass import cli  # noqa: PLC0415

    def fails() -> None:
        body = io.BytesIO(json.dumps({"error": "не удалось сохранить одобренную версию: диск"}).encode())
        url = "/image/bob/lab/1"
        raise urllib.error.HTTPError(url, 500, "Internal", None, body)

    with pytest.raises(RuntimeError, match="одобренную версию: диск"):
        cli._push_call(fails)  # noqa: SLF001
