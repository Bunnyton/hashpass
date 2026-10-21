"""Tier2: task moderation on a live pool -- approve, update, reject, delete, auto-approval, purge."""
import json
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.catalog import REJECT_TTL, Catalog
from hashpass.registry.pool_settings import PoolSettings
from hashpass.registry.remote import RemoteRegistry


def _http(method: str, url: str, *, token: str | None = None,
          body: dict | None = None) -> tuple[int, dict, bytes]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


class _Pool:
    def __init__(self, registry, tmp_path: Path) -> None:
        self.r, self.tmp = registry, tmp_path
        PoolSettings(registry.catalog_path.parent / "pool-settings.json").set_auto_approve(on=False)
        for user, role in (("bob", "author"), ("alice", "author"), ("root", "admin"),
                           ("kid", "student")):
            registry.users.add(user, "pw-correct1", role=role)
        self.tok = {u: RemoteRegistry(registry.base_url).login(u, "pw-correct1")
                    for u in ("bob", "alice", "root", "kid")}

    def push(self, name: str, marker: str) -> None:
        local = ImageStore(self.tmp / f"loc-{marker}")
        src = self.tmp / f"src-{marker}"
        src.mkdir(exist_ok=True)
        (src / "f").write_text(marker, encoding="utf-8")
        local.save(name, "1", src, ())
        c = RemoteRegistry(self.r.base_url)
        c.push(local, f"{name}:1", token=self.tok["bob"], force=True)
        td = self.tmp / f"task-{marker}"
        (td / "bundle").mkdir(parents=True)
        (td / "bundle" / "c.json").write_text(marker, encoding="utf-8")
        (td / "task-meta.json").write_text('{"image_ref":"x"}', encoding="utf-8")
        c.push_task(td, name, "1", publish=True, block="Б", token=self.tok["bob"])
        Catalog(self.r.catalog_path).set_task_hidden(f"{name}:1", hidden=False)

    def catalog(self, user: str) -> list[dict]:
        return json.loads(_http("GET", f"{self.r.base_url}/catalog", token=self.tok[user])[2])["catalog"]

    def digest(self, ref: str, user: str | None) -> str | None:
        name, _, ver = ref.partition(":")
        status, headers, _ = _http("HEAD", f"{self.r.base_url}/image/{name}/{ver}",
                                   token=self.tok[user] if user else None)
        return headers.get("X-Image-Digest") if status == HTTPStatus.OK else None

    def task_marker(self, ref: str, user: str) -> str | None:
        from hashpass.registry.blob import unpack_task  # noqa: PLC0415
        name, _, ver = ref.partition(":")
        status, _, body = _http("GET", f"{self.r.base_url}/task/{name}/{ver}", token=self.tok[user])
        if status != HTTPStatus.OK:
            return None
        out = self.tmp / f"got-{user}-{len(list(self.tmp.iterdir()))}"
        unpack_task(body, out)
        return (out / "bundle" / "c.json").read_text(encoding="utf-8")

    def post(self, path: str, user: str, body: dict) -> int:
        return _http("POST", f"{self.r.base_url}{path}", token=self.tok[user], body=body)[0]


@pytest.mark.tier2
def test_moderation_lifecycle(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    ref = "bob/lab:1"
    pool.push("bob/lab", "v1")
    assert pool.catalog("kid") == []                                   # pending: not for students
    assert pool.task_marker(ref, "kid") is None
    assert pool.digest(ref, None) is None
    row = next(r for r in pool.catalog("bob") if r["ref"] == ref)
    assert row["state"] == "pending"
    assert pool.post("/catalog/approve", "bob", {"ref": ref}) == HTTPStatus.FORBIDDEN
    assert pool.post("/catalog/approve", "root", {"ref": ref}) == HTTPStatus.OK
    assert [r["ref"] for r in pool.catalog("kid")] == [ref]
    v1 = pool.digest(ref, "kid")
    assert pool.task_marker(ref, "kid") == "v1"

    pool.push("bob/lab", "v2")                                         # an update: pending again
    assert pool.digest(ref, "kid") == v1 and pool.digest(ref, None) == v1   # students keep v1
    assert pool.task_marker(ref, "kid") == "v1"
    assert pool.digest(ref, "bob") != v1 and pool.task_marker(ref, "bob") == "v2"   # the author: v2
    assert pool.task_marker(ref, "root") == "v2"                       # the admin reviews v2
    assert pool.task_marker(ref, "alice") == "v1"                      # another author: approved
    row = next(r for r in pool.catalog("bob") if r["ref"] == ref)
    assert (row["state"], row["pending_update"]) == ("pending", True)

    assert pool.post("/catalog/reject", "root", {"ref": ref, "reason": "нет финала"}) == HTTPStatus.OK
    assert pool.task_marker(ref, "kid") == "v1"                        # still the approved one
    rejected = [r for r in pool.catalog("bob") if r.get("rejected")]
    assert [(r["ref"], r["reason"], r["block_name"]) for r in rejected] == [(ref, "нет финала", "Отклонённые")]
    assert not [r for r in pool.catalog("alice") if r.get("rejected")]   # not alice's task

    pool.push("bob/lab", "v3")
    assert pool.post("/catalog/approve", "root", {"ref": ref}) == HTTPStatus.OK
    assert pool.task_marker(ref, "kid") == "v3"                        # approved update reaches students

    name, _, ver = ref.partition(":")
    assert _http("DELETE", f"{registry.base_url}/task/{name}/{ver}", token=pool.tok["alice"])[0] == HTTPStatus.FORBIDDEN
    assert _http("DELETE", f"{registry.base_url}/task/{name}/{ver}", token=pool.tok["bob"])[0] == HTTPStatus.OK
    assert pool.catalog("root") == []
    assert not registry.store.exists(ref)


@pytest.mark.tier2
def test_auto_approval_by_author_flag_and_pool_switch(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    base = registry.base_url
    assert _http("PUT", f"{base}/users/bob/auto-approve", token=pool.tok["bob"], body={"on": True})[0] == HTTPStatus.FORBIDDEN
    assert _http("PUT", f"{base}/users/bob/auto-approve", token=pool.tok["root"], body={"on": True})[0] == HTTPStatus.OK
    pool.push("bob/auto", "a1")
    assert [r["ref"] for r in pool.catalog("kid")] == ["bob/auto:1"]
    assert _http("PUT", f"{base}/users/bob/auto-approve", token=pool.tok["root"], body={"on": False})[0] == HTTPStatus.OK
    assert json.loads(_http("GET", f"{base}/pool/settings", token=pool.tok["root"])[2]) == {"auto_approve": False}
    assert _http("PUT", f"{base}/pool/settings", token=pool.tok["alice"], body={"auto_approve": True})[0] == HTTPStatus.FORBIDDEN
    assert _http("PUT", f"{base}/pool/settings", token=pool.tok["root"], body={"auto_approve": True})[0] == HTTPStatus.OK
    pool.push("bob/pool", "p1")
    assert "bob/pool:1" in [r["ref"] for r in pool.catalog("kid")]


@pytest.mark.tier2
def test_rejected_tasks_are_purged_after_a_week(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    pool.push("bob/old", "o1")
    Catalog(registry.catalog_path).reject("bob/old:1", "", now=0.0)   # rejected long ago
    assert pool.catalog("root") == []                                 # the next look purges it
    assert not registry.store.exists("bob/old:1")
    assert REJECT_TTL == 7 * 24 * 3600


def _push_image_only(pool: _Pool, name: str, marker: str) -> None:
    """`hashengine push ref` without --task: a new image, the same task/."""
    local = ImageStore(pool.tmp / f"loc-img-{marker}")
    src = pool.tmp / f"src-img-{marker}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text(marker, encoding="utf-8")
    local.save(name, "1", src, ())
    RemoteRegistry(pool.r.base_url).push(local, f"{name}:1", token=pool.tok["bob"], force=True)


@pytest.mark.tier2
def test_a_new_image_alone_waits_for_approval_too(registry, tmp_path):
    """Review 2026-10-14: an image-only update reached students without approval."""
    pool = _Pool(registry, tmp_path)
    ref = "bob/lab:1"
    pool.push("bob/lab", "v1")
    pool.post("/catalog/approve", "root", {"ref": ref})
    v1 = pool.digest(ref, "kid")
    _push_image_only(pool, "bob/lab", "img2")                  # data changed, task/ the same
    assert pool.digest(ref, "kid") == v1                       # students keep the approved image
    assert pool.digest(ref, "bob") != v1
    row = next(r for r in pool.catalog("bob") if r["ref"] == ref)
    assert (row["state"], row["pending_update"]) == ("pending", True)
    assert pool.post("/catalog/approve", "root", {"ref": ref}) == HTTPStatus.OK
    assert pool.digest(ref, "kid") == pool.digest(ref, "bob")  # approved: everyone gets it


@pytest.mark.tier2
def test_a_rejected_update_falls_back_to_the_approved_version_after_a_week(registry, tmp_path):
    """Review 2026-10-14: the purge deleted an approved course task whose UPDATE was rejected."""
    pool = _Pool(registry, tmp_path)
    ref = "bob/lab:1"
    pool.push("bob/lab", "v1")
    pool.post("/catalog/approve", "root", {"ref": ref})
    pool.push("bob/lab", "v2")
    Catalog(registry.catalog_path).reject(ref, "не то", now=0.0)          # a week ago
    assert [r["ref"] for r in pool.catalog("kid")] == [ref]               # the purge keeps it
    row = next(r for r in pool.catalog("bob") if r["ref"] == ref)
    assert (row["state"], row.get("rejected", False)) == ("approved", False)
    assert pool.task_marker(ref, "kid") == "v1"                           # students: the approved
    assert pool.task_marker(ref, "bob") == "v2"     # revisions are immutable: the author keeps v2


@pytest.mark.tier2
def test_students_do_not_get_moderation_details(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    pool.push("bob/lab", "v1")
    pool.post("/catalog/approve", "root", {"ref": "bob/lab:1"})
    pool.push("bob/lab", "v2")
    pool.post("/catalog/reject", "root", {"ref": "bob/lab:1", "reason": "грейдер принимает ls"})
    row = pool.catalog("kid")[0]
    assert not {"reason", "state", "owner", "pending_update", "rejected_at", "approved_digest"} & set(row)
