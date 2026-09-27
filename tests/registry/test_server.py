"""Tier2: drive the localhost registry server's HTTP contract directly via urllib."""
import hashlib
import io
import json
import tarfile
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

import pytest
from werkzeug.exceptions import ClientDisconnected

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image, pack_image_to_file, unpack_image
from hashpass.registry.passwords import UserStore
from hashpass.registry.server import make_server

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
    registry.users.add("alice", "pw-correct", role="admin")   # pushes un-namespaced refs
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
    registry.users.add("alice", "pw-correct", role="admin")   # pushes an un-namespaced ref
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


@pytest.mark.tier2
def test_put_rejects_missing_layer_directory(registry):
    """Server must reject blobs where 'layer' is a file instead of a directory."""
    registry.users.add("alice", "pw-correct", role="admin")   # pushes an un-namespaced ref
    token = json.loads(_login(registry.base_url, "alice", "pw-correct")[1])["token"]
    auth = {"Authorization": f"Bearer {token}"}
    # Build a blob where "layer" is a FILE not a directory
    buf = io.BytesIO()
    meta = json.dumps({"name": "badimg", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
        # "layer" as a file instead of directory
        layer_info = tarfile.TarInfo("layer")
        layer_info.size = 4
        tar.addfile(layer_info, io.BytesIO(b"test"))
    # Should get 400 BAD_REQUEST (not 500 or 201)
    status, _body = _http("PUT", f"{registry.base_url}/image/badimg/1", data=buf.getvalue(), headers=auth)
    assert status == HTTPStatus.BAD_REQUEST


@pytest.mark.tier2
def test_put_accepts_root_owned_blob(registry):
    """Server accepts blobs with uid=0 members when sudo=False (doesn't preserve ownership, but stores)."""
    registry.users.add("alice", "pw-correct", role="admin")   # pushes an un-namespaced ref
    token = json.loads(_login(registry.base_url, "alice", "pw-correct")[1])["token"]
    auth = {"Authorization": f"Bearer {token}"}
    # Build a gzip blob with uid=0 members (following _raw_tar pattern)
    buf = io.BytesIO()
    meta = json.dumps({"name": "rooty", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
        # Layer directory with uid=0
        layer_info = tarfile.TarInfo("layer")
        layer_info.type = tarfile.DIRTYPE
        layer_info.uid = 0
        layer_info.mode = 0o755
        tar.addfile(layer_info)
        # File member with uid=0 and readable mode
        file_info = tarfile.TarInfo("layer/f")
        file_info.size = 4
        file_info.uid = 0
        file_info.mode = 0o644
        tar.addfile(file_info, io.BytesIO(b"test"))
    # PUT should succeed (201) — sudo=False prevents NotImplementedError on uid=0 members
    status, _body = _http("PUT", f"{registry.base_url}/image/rooty/1", data=buf.getvalue(), headers=auth)
    assert status == HTTPStatus.CREATED
    # Verify the image was stored (even without root ownership preservation)
    assert registry.store.exists("rooty:1")


def _author_token(registry) -> dict[str, str]:
    registry.users.add("alice", "pw-correct", role="admin")   # pushes un-namespaced refs
    _status, body = _login(registry.base_url, "alice", "pw-correct")
    return {"Authorization": f"Bearer {json.loads(body)['token']}"}


def _head(url: str) -> tuple[int, dict[str, str]]:
    req = urllib.request.Request(url, method="HEAD")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers)


@pytest.mark.tier2
def test_put_stores_blob_verbatim_and_serves_digest(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "img", ())
    blob = pack_image_to_file(local.get("img:1"), tmp_path / "img.tar.gz").read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    auth = _author_token(registry)
    url = f"{registry.base_url}/image/img/1"
    status, _ = _http("PUT", url, data=blob, headers=auth)
    assert status == HTTPStatus.CREATED
    assert registry.store.blob_path("img:1").read_bytes() == blob          # verbatim, not repacked
    assert not (registry.store.dir("img", "1") / "layer").exists()         # never unpacked
    status, headers = _head(url)
    assert status == HTTPStatus.OK and headers["X-Image-Digest"] == digest
    req = urllib.request.Request(url)  # noqa: S310
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        assert resp.headers["X-Image-Digest"] == digest
        assert resp.read() == blob                                          # same bytes back


@pytest.mark.tier2
def test_put_malformed_blob_keeps_previous_generation(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "img", ())
    good = pack_image_to_file(local.get("img:1"), tmp_path / "good.tar.gz").read_bytes()
    auth = _author_token(registry)
    url = f"{registry.base_url}/image/img/1"
    assert _http("PUT", url, data=good, headers=auth)[0] == HTTPStatus.CREATED
    old_digest = _head(url)[1]["X-Image-Digest"]
    # meta.json only, no layer/  -> refused; the old generation is still served
    buf = io.BytesIO()
    meta = json.dumps({"name": "img", "version": "1", "parents": []}).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("meta.json")
        info.size = len(meta)
        tar.addfile(info, io.BytesIO(meta))
    assert _http("PUT", url, data=buf.getvalue(), headers=auth)[0] == HTTPStatus.BAD_REQUEST
    # name in meta != URL -> refused too
    wrong = pack_image_to_file(local.get("img:1"), tmp_path / "wrong.tar.gz").read_bytes()
    assert _http("PUT", f"{registry.base_url}/image/other/1", data=wrong, headers=auth)[0] == HTTPStatus.BAD_REQUEST
    assert _head(url)[1]["X-Image-Digest"] == old_digest
    assert registry.store.blob_path("img:1").read_bytes() == good
    assert not list(registry.store.dir("img", "1").glob("incoming-*.tmp"))  # temp files cleaned
    assert not list((registry.store.root / ".incoming").glob("*"))
    # a rejected PUT to a brand-new ref leaves no directory behind for it
    assert _http("PUT", f"{registry.base_url}/image/fresh/1", data=buf.getvalue(),
                 headers=auth)[0] == HTTPStatus.BAD_REQUEST
    assert not (registry.store.root / "fresh").exists()
    assert not (registry.store.root / "other").exists()


@pytest.mark.tier2
def test_legacy_layer_record_is_served_without_digest(registry, tmp_path):
    _seed(registry.store, tmp_path, "old", ())          # a layer/-only record, as pre-change servers made
    url = f"{registry.base_url}/image/old/1"
    status, headers = _head(url)
    assert status == HTTPStatus.OK and "X-Image-Digest" not in headers
    with urllib.request.urlopen(urllib.request.Request(url), timeout=_TIMEOUT) as resp:  # noqa: S310
        status, body = resp.status, resp.read()
        assert "X-Image-Digest" not in resp.headers            # never an empty digest header
    assert status == HTTPStatus.OK
    dst = ImageStore(tmp_path / "dst")
    assert unpack_image(body, dst) == "old:1"
    assert (dst.get("old:1").layer / "old.txt").read_text(encoding="utf-8") == "old"


@pytest.mark.tier2
def test_images_rows_carry_digest(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "img", ())
    auth = _author_token(registry)
    blob = pack_image_to_file(local.get("img:1"), tmp_path / "img.tar.gz").read_bytes()
    _http("PUT", f"{registry.base_url}/image/img/1", data=blob, headers=auth)
    _seed(registry.store, tmp_path, "old", ())
    _status, body = _http("GET", f"{registry.base_url}/images", headers=auth)
    rows = {r["ref"]: r for r in json.loads(body)["images"]}
    assert rows["img:1"]["digest"] == hashlib.sha256(blob).hexdigest()
    assert rows["old:1"]["digest"] is None


@pytest.mark.tier2
def test_receive_image_sweeps_tmp_on_client_disconnect(tmp_path):
    """
    A client that declares a Content-Length and then stops sending must not leak a tmp file.

    That trips werkzeug's ClientDisconnected (an HTTPException, not an OSError) mid-stream;
    `incoming-*.tmp` must still be swept, and a previous generation must still be served.
    """
    store = ImageStore(tmp_path / "srv")
    users = UserStore(tmp_path / "users.json")
    server = make_server(store, users, b"0" * 32, catalog_path=tmp_path / "catalog.json")
    pool = server.pool
    try:
        local = ImageStore(tmp_path / "local")
        _seed(local, tmp_path, "img", ())
        good = pack_image_to_file(local.get("img:1"), tmp_path / "good.tar.gz").read_bytes()
        good_digest = hashlib.sha256(good).hexdigest()
        seed_tmp = tmp_path / "seed.tmp"
        seed_tmp.write_bytes(good)
        store.publish_blob("img", "1", seed_tmp, parents=(), digest=good_digest)

        partial = good[:16]     # far shorter than the Content-Length the client declared
        with pool.app.test_request_context(
            "/image/img/1", method="PUT", input_stream=io.BytesIO(partial),
            environ_overrides={"CONTENT_LENGTH": str(len(good) * 2)},
        ), pytest.raises(ClientDisconnected):
            pool._receive_image("img", "1")  # noqa: SLF001  (exercising the private method directly)

        assert not list(store.dir("img", "1").glob("incoming-*.tmp"))   # swept, not leaked
        assert not list((store.root / ".incoming").glob("*"))
        assert store.get("img:1").digest == good_digest                 # previous generation intact
        assert store.blob_path("img:1").read_bytes() == good
    finally:
        server.server_close()


def _get(url: str) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=_TIMEOUT) as resp:  # noqa: S310
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


@pytest.mark.tier2
def test_get_digest_header_names_the_served_bytes_after_republish(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "img", ())
    auth = _author_token(registry)
    url = f"{registry.base_url}/image/img/1"
    first = pack_image_to_file(local.get("img:1"), tmp_path / "g1.tar.gz").read_bytes()
    assert _http("PUT", url, data=first, headers=auth)[0] == HTTPStatus.CREATED
    (tmp_path / "src-img" / "more.txt").write_text("gen2", encoding="utf-8")
    local.save("img", "1", tmp_path / "src-img", ())
    second = pack_image_to_file(local.get("img:1"), tmp_path / "g2.tar.gz").read_bytes()
    assert second != first
    assert _http("PUT", url, data=second, headers=auth)[0] == HTTPStatus.CREATED
    status, headers, body = _get(url)
    assert status == HTTPStatus.OK
    assert headers["X-Image-Digest"] == hashlib.sha256(body).hexdigest()
    assert body == second
    assert headers["Content-Length"] == str(len(second))       # streamed from an fd, size still sent


@pytest.mark.tier2
def test_get_whose_blob_file_vanished_is_404(registry, tmp_path):
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "img", ())
    auth = _author_token(registry)
    url = f"{registry.base_url}/image/img/1"
    blob = pack_image_to_file(local.get("img:1"), tmp_path / "img.tar.gz").read_bytes()
    assert _http("PUT", url, data=blob, headers=auth)[0] == HTTPStatus.CREATED
    registry.store.blob_path("img:1").unlink()              # meta still names it
    status, headers, _body = _get(url)
    assert status == HTTPStatus.NOT_FOUND
    assert "X-Image-Digest" not in headers


# -- ownership: an author may only write under their own namespace -----------

def _seed_ns(store: ImageStore, tmp_path: Path, name: str) -> None:
    """Seed a local image whose name may itself carry a namespace segment (`alice/app`)."""
    src = tmp_path / "src" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "f.txt").write_text(name, encoding="utf-8")
    store.save(name, "1", src, ())


def _push_blob(base_url: str, ref: str, blob: bytes, token: str) -> tuple[int, bytes]:
    name, version = ref.rsplit(":", 1)
    return _http("PUT", f"{base_url}/image/{name}/{version}", data=blob,
                 headers={"Authorization": f"Bearer {token}"})


@pytest.mark.tier2
def test_author_push_is_scoped_to_own_namespace(registry, tmp_path):
    registry.users.add("alice", "pw-correct", role="author")
    token = json.loads(_login(registry.base_url, "alice", "pw-correct")[1])["token"]
    local = ImageStore(tmp_path / "local")

    _seed_ns(local, tmp_path, "alice/app")
    own = pack_image(local.get("alice/app:1"))
    status, _ = _push_blob(registry.base_url, "alice/app:1", own, token)
    assert status == HTTPStatus.CREATED

    _seed_ns(local, tmp_path, "bob/app")
    others = pack_image(local.get("bob/app:1"))
    status, body = _push_blob(registry.base_url, "bob/app:1", others, token)
    assert status == HTTPStatus.FORBIDDEN
    assert "bob" in json.loads(body)["error"]

    _seed_ns(local, tmp_path, "app")
    bare = pack_image(local.get("app:1"))
    status, body = _push_blob(registry.base_url, "app:1", bare, token)
    assert status == HTTPStatus.FORBIDDEN
    assert "администратор" in json.loads(body)["error"]


@pytest.mark.tier2
def test_admin_push_is_unrestricted(registry, tmp_path):
    registry.users.add("root", "pw-correct", role="admin")
    token = json.loads(_login(registry.base_url, "root", "pw-correct")[1])["token"]
    local = ImageStore(tmp_path / "local")

    src = tmp_path / "src-debian"
    src.mkdir()
    (src / "f.txt").write_text("base", encoding="utf-8")
    local.save("debian", "trixie-18", src, ())
    base_blob = pack_image(local.get("debian:trixie-18"))
    status, _ = _push_blob(registry.base_url, "debian:trixie-18", base_blob, token)
    assert status == HTTPStatus.CREATED

    _seed_ns(local, tmp_path, "alice/app")
    app_blob = pack_image(local.get("alice/app:1"))
    status, _ = _push_blob(registry.base_url, "alice/app:1", app_blob, token)
    assert status == HTTPStatus.CREATED


@pytest.mark.tier2
def test_author_cannot_push_task_or_attachment_for_others_namespace(registry, tmp_path):
    _seed_ns(registry.store, tmp_path, "bob/app")           # the ref exists, owned by "bob"
    registry.users.add("alice", "pw-correct", role="author")
    token = json.loads(_login(registry.base_url, "alice", "pw-correct")[1])["token"]
    auth = {"Authorization": f"Bearer {token}"}
    status, _ = _http("PUT", f"{registry.base_url}/task/bob/app/1", data=b"junk", headers=auth)
    assert status == HTTPStatus.FORBIDDEN
    status, _ = _http("PUT", f"{registry.base_url}/attachment/bob/app/1?name=Taskfile",
                      data=b"stage x\n", headers=auth)
    assert status == HTTPStatus.FORBIDDEN


@pytest.mark.tier2
def test_unknown_ref_404_suggests_the_same_name_under_another_namespace(registry, tmp_path):
    _seed_ns(registry.store, tmp_path, "bunnyton/debian")            # -> bunnyton/debian:1
    base = registry.base_url
    status, body = _http("GET", f"{base}/image/debian/1")
    assert status == HTTPStatus.NOT_FOUND
    payload = json.loads(body)
    assert payload["suggestions"] == ["bunnyton/debian:1"]
    assert "быть может, вы искали bunnyton/debian:1?" in payload["error"]
    status, body = _http("GET", f"{base}/closure/debian/1")
    assert status == HTTPStatus.NOT_FOUND
    assert json.loads(body)["suggestions"] == ["bunnyton/debian:1"]
    # HEAD carries no body: the hint travels in a header
    req = urllib.request.Request(f"{base}/image/debian/1", method="HEAD")  # noqa: S310
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=_TIMEOUT)  # noqa: S310
    assert exc.value.code == HTTPStatus.NOT_FOUND
    assert exc.value.headers["X-Image-Suggest"] == "bunnyton/debian:1"
    # a name nobody published stays a plain 404 (no suggestions)
    status, body = _http("GET", f"{base}/image/ghost/1")
    assert status == HTTPStatus.NOT_FOUND
    assert json.loads(body)["suggestions"] == []


@pytest.mark.tier2
def test_forbidden_push_hints_the_namespaced_twin(registry, tmp_path):
    _seed_ns(registry.store, tmp_path, "bunnyton/debian")
    registry.users.add("alice", "pw-correct", role="author")
    token = json.loads(_login(registry.base_url, "alice", "pw-correct")[1])["token"]
    local = ImageStore(tmp_path / "local")
    _seed(local, tmp_path, "debian", ())
    status, body = _push_blob(registry.base_url, "debian:1", pack_image(local.get("debian:1")), token)
    assert status == HTTPStatus.FORBIDDEN
    assert "быть может, вы искали bunnyton/debian:1?" in json.loads(body)["error"]


@pytest.mark.tier2
def test_closure_404_names_the_missing_parent_not_the_requested_image(registry, tmp_path):
    src = tmp_path / "src-orphan"
    src.mkdir()
    (src / "f.txt").write_text("x", encoding="utf-8")
    registry.store.save("app", "1", src, ("base:1",))          # its parent was never pushed
    status, body = _http("GET", f"{registry.base_url}/closure/app/1")
    assert status == HTTPStatus.NOT_FOUND
    assert "«base:1»" in json.loads(body)["error"]
