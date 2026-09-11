"""Tier2: image cards over the live server — attachments, description, and catalog management."""
import json
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from pathlib import Path

import pytest

from hashpass.registry.catalog import Catalog
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.server import _parse_multipart


@pytest.mark.tier2
def test_history_and_antibot_recorded_and_shown(registry):
    Catalog(registry.catalog_path).add_task("lab:1", "d1")
    student = RemoteRegistry(registry.base_url)
    stok = student.register("stud", "pass123!", group="G")
    history = [{"command": "echo pasted solution here", "ts": "T", "typing": 0.02, "pasted": True}]
    auth = {"verdict": "pasted", "typed": 0, "pasted": 1}
    result = student.submit("lab:1", "d1", passed=True, history=history, authenticity=auth, token=stok)
    assert result["status"] == "passed"
    opener, cookie = _author_cookie(registry)
    url = f"{registry.base_url}/web/history?user=stud&ref={urllib.parse.quote('lab:1')}"
    _, _, body = _req(opener, "GET", url, cookie=cookie)
    assert "echo pasted solution here" in body      # the student's command is visible
    assert "вставка" in body                        # per-command paste flag shown


@pytest.mark.tier1
def test_parse_multipart_text_and_binary():
    body = (b'--B\r\nContent-Disposition: form-data; name="ref"\r\n\r\nlab:1\r\n'
            b'--B\r\nContent-Disposition: form-data; name="file"; filename="a.bin"\r\n'
            b'Content-Type: application/octet-stream\r\n\r\n\x00\r\n\xff\r\n--B--\r\n')
    fields, files = _parse_multipart(body, "multipart/form-data; boundary=B")
    assert fields == {"ref": "lab:1"}
    assert files["file"][0] == "a.bin"
    assert files["file"][1] == b"\x00\r\n\xff"   # binary content preserved exactly


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_k) -> None:  # noqa: ANN002, ANN003
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def _req(opener, method, url, *, cookie=None, data=None) -> tuple:
    headers = {"Cookie": cookie} if cookie else {}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310
    try:
        resp = opener.open(req, timeout=10)
        return resp.status, resp.headers, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode("utf-8", "replace")


def _author_cookie(registry) -> tuple:
    registry.users.add("teacher", "pass123!", role="admin", group="")
    opener = _opener()
    _, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login",
                         data={"user": "teacher", "password": "pass123!"})
    return opener, headers["Set-Cookie"].split(";")[0]


def _seed(registry, ref: str, tmp_path: Path, *, task: bool = False) -> str:
    name, _, version = ref.partition(":")
    src = tmp_path / f"src-{name.replace('/', '_')}-{version}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "f.txt").write_text("x", encoding="utf-8")
    registry.store.save(name, version, src, ())
    if task:
        tdir = registry.store.get(ref).layer.parent / "task"
        tdir.mkdir()
        (tdir / "task-meta.json").write_text(f'{{"image_ref":"{ref}"}}', encoding="utf-8")
    return ref


@pytest.mark.tier2
def test_push_attachment_and_web_download(registry, tmp_path):
    registry.users.add("dev", "pass123!", role="author", group="")
    _seed(registry, "lab:1", tmp_path)
    c = RemoteRegistry(registry.base_url)
    tok = c.login("dev", "pass123!")
    c.push_attachment("lab", "1", "Taskfile", b"stage one\nsolve: ls\n", taskfile=True, token=tok)
    opener, cookie = _author_cookie(registry)
    # ref is listed on the catalog page; per-image files live on the card page
    _, _, cat_body = _req(opener, "GET", f"{registry.base_url}/web/images", cookie=cookie)
    assert "lab:1" in cat_body
    _, _, body = _req(opener, "GET", f"{registry.base_url}/web/image/lab:1", cookie=cookie)
    assert "Taskfile" in body
    dl = f"{registry.base_url}/web/images/file?ref={urllib.parse.quote('lab:1')}&name=Taskfile"
    status, _, content = _req(opener, "GET", dl, cookie=cookie)
    assert status == HTTPStatus.OK
    assert "solve: ls" in content


@pytest.mark.tier2
def test_attachment_upload_requires_author(registry, tmp_path):
    _seed(registry, "lab:1", tmp_path)
    student = RemoteRegistry(registry.base_url).register("stud", "pass123!", group="G")
    with pytest.raises(urllib.error.HTTPError) as exc:
        RemoteRegistry(registry.base_url).push_attachment("lab", "1", "x", b"y", token=student)
    assert exc.value.code == HTTPStatus.FORBIDDEN


@pytest.mark.tier2
def test_web_describe_and_delete(registry, tmp_path):
    _seed(registry, "lab:1", tmp_path)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    _req(opener, "POST", f"{base}/web/images/describe", cookie=cookie,
         data={"ref": "lab:1", "description": "Описание образа"})
    _req(opener, "POST", f"{base}/web/images/attach-delete", cookie=cookie,
         data={"ref": "lab:1", "name": "nope"})   # deleting a missing file is harmless
    _, _, body = _req(opener, "GET", f"{base}/web/image/lab:1", cookie=cookie)
    assert "Описание образа" in body


@pytest.mark.tier2
def test_web_blocks_add_task_toggle_remove(registry, tmp_path):
    _seed(registry, "lab:1", tmp_path, task=True)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    student = RemoteRegistry(registry.base_url).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(registry.base_url)

    # add a task to the catalog: it auto-numbers into a (default) open block
    _req(opener, "POST", f"{base}/web/catalog/add", cookie=cookie, data={"ref": "lab:1"})
    cat = sc.catalog(token=student)
    assert [(e["number"], e["available"]) for e in cat] == [(1, True)]
    block_id = cat[0]["block_id"]

    # closing the whole block locks its tasks (still visible), and /submit is refused
    _req(opener, "POST", f"{base}/web/blocks/toggle", cookie=cookie,
         data={"block_id": block_id, "open": "0"})
    assert [(e["number"], e["available"]) for e in sc.catalog(token=student)] == [(1, False)]
    assert sc.submit("lab:1", "any", passed=True, token=student)["status"] == "unavailable"

    _req(opener, "POST", f"{base}/web/blocks/toggle", cookie=cookie,
         data={"block_id": block_id, "open": "1"})
    assert [(e["number"], e["available"]) for e in sc.catalog(token=student)] == [(1, True)]

    _req(opener, "POST", f"{base}/web/catalog/remove", cookie=cookie, data={"ref": "lab:1"})
    assert sc.catalog(token=student) == []


@pytest.mark.tier2
def test_web_catalog_layout_reorders(registry, tmp_path):
    for name in ("a", "b"):
        _seed(registry, f"{name}:1", tmp_path, task=True)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    student = RemoteRegistry(registry.base_url).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(registry.base_url)
    _req(opener, "POST", f"{base}/web/catalog/add", cookie=cookie, data={"ref": "a:1"})
    _req(opener, "POST", f"{base}/web/catalog/add", cookie=cookie, data={"ref": "b:1"})
    block_id = sc.catalog(token=student)[0]["block_id"]
    # drag: JS posts the new order as JSON (id + task refs)
    req = urllib.request.Request(  # noqa: S310
        f"{base}/web/catalog/layout", method="POST",
        data=json.dumps({"blocks": [{"id": block_id, "tasks": ["b:1", "a:1"]}]}).encode(),
        headers={"Cookie": cookie, "Content-Type": "application/json"})
    opener.open(req, timeout=10)
    assert [e["ref"] for e in sc.catalog(token=student)] == ["b:1", "a:1"]


@pytest.mark.tier2
def test_web_multipart_upload_and_list(registry, tmp_path):
    _seed(registry, "lab:1", tmp_path)
    opener, cookie = _author_cookie(registry)
    b = "----hpTEST"
    body = "".join([
        f'--{b}\r\nContent-Disposition: form-data; name="ref"\r\n\r\nlab:1\r\n',
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="notes.txt"\r\n\r\n',
        "privet\r\n",
        f"--{b}--\r\n",
    ]).encode()
    req = urllib.request.Request(  # noqa: S310
        f"{registry.base_url}/web/images/attach", data=body, method="POST",
        headers={"Cookie": cookie, "Content-Type": f"multipart/form-data; boundary={b}"})
    follow = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    follow.open(req, timeout=10).read()   # 303 -> follows the redirect back to the card page
    _, _, page = _req(opener, "GET", f"{registry.base_url}/web/image/lab:1", cookie=cookie)
    assert "notes.txt" in page
    dl = f"{registry.base_url}/web/images/file?ref={urllib.parse.quote('lab:1')}&name=notes.txt"
    assert _req(opener, "GET", dl, cookie=cookie)[2] == "privet"


@pytest.mark.tier2
def test_web_images_is_author_only(registry):
    status, headers, _ = _req(_opener(), "GET", f"{registry.base_url}/web/images")
    assert status == HTTPStatus.SEE_OTHER
    assert headers["Location"] == "/web/login"
