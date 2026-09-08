"""Tier2: drive the localhost registry server's HTTP contract directly via urllib."""
import io
import json
import tarfile
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image

_TIMEOUT = 10


def _seed(store: ImageStore, tmp_path: Path, name: str, parents: tuple[str, ...]) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / f"{name}.txt").write_text(name, encoding="utf-8")
    store.save(name, "1", src, parents)


def _http(method: str, url: str, *, data: bytes | None = None,
          headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(  # noqa: S310  (localhost test URL)
        url, data=data, method=method, headers=headers or {},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310  (localhost test)
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _login(base_url: str, user: str, password: str) -> tuple[int, bytes]:
    body = json.dumps({"user": user, "password": password}).encode("utf-8")
    return _http("POST", f"{base_url}/login", data=body,
                 headers={"Content-Type": "application/json"})


@pytest.mark.tier2
def test_login_ok_and_bad_password(registry):
    registry.users.add("alice", "pw-correct")
    status, body = _login(registry.base_url, "alice", "pw-correct")
    assert status == HTTPStatus.OK
    assert json.loads(body)["token"]
    assert _login(registry.base_url, "alice", "wrong")[0] == HTTPStatus.UNAUTHORIZED
    assert _login(registry.base_url, "ghost", "any")[0] == HTTPStatus.UNAUTHORIZED


@pytest.mark.tier2
def test_put_requires_valid_token(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "img", ())
    blob = pack_image(local.get("img:1"))
    url = f"{registry.base_url}/image/img/1"
    assert _http("PUT", url, data=blob)[0] == HTTPStatus.UNAUTHORIZED  # no token
    bad = {"Authorization": "Bearer forged.token"}
    assert _http("PUT", url, data=blob, headers=bad)[0] == HTTPStatus.UNAUTHORIZED


@pytest.mark.tier2
def test_put_then_get_and_closure(registry, tmp_path):
    registry.users.add("alice", "pw-correct", role="author")
    token = json.loads(_login(registry.base_url, "alice", "pw-correct")[1])["token"]
    auth = {"Authorization": f"Bearer {token}"}
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "base", ())
    _seed(local, tmp_path, "app", ("base:1",))
    for ref in ("base/1", "app/1"):
        name, version = ref.split("/")
        blob = pack_image(local.get(f"{name}:{version}"))
        created = _http("PUT", f"{registry.base_url}/image/{ref}", data=blob, headers=auth)
        assert created[0] == HTTPStatus.CREATED

    assert _http("HEAD", f"{registry.base_url}/image/app/1")[0] == HTTPStatus.OK
    assert _http("HEAD", f"{registry.base_url}/image/nope/1")[0] == HTTPStatus.NOT_FOUND
    status, body = _http("GET", f"{registry.base_url}/closure/app/1")
    assert status == HTTPStatus.OK
    assert json.loads(body)["refs"] == ["base:1", "app:1"]
    assert _http("GET", f"{registry.base_url}/image/app/1")[0] == HTTPStatus.OK
    assert _http("GET", f"{registry.base_url}/closure/ghost/1")[0] == HTTPStatus.NOT_FOUND


@pytest.mark.tier2
def test_put_rejects_traversing_blob(registry, tmp_path):
    registry.users.add("alice", "pw-correct", role="author")
    token = json.loads(_login(registry.base_url, "alice", "pw-correct")[1])["token"]
    auth = {"Authorization": f"Bearer {token}"}
    layer = tmp_path / "layer"
    layer.mkdir()
    (layer / "f").write_text("x", encoding="utf-8")
    buf = io.BytesIO()
    meta = json.dumps({"name": "../evil", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
        tar.add(layer, arcname="layer")
    # a VALID token, but the blob's traversing name is rejected cleanly (400, not 500 or 201)
    status = _http("PUT", f"{registry.base_url}/image/evil/1", data=buf.getvalue(), headers=auth)[0]
    assert status == HTTPStatus.BAD_REQUEST
