"""Tier2: image cards over the live server — attachments, description, and catalog management."""
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.attachments import AttachmentStore
from hashpass.registry.blob import pack_image_to_file
from hashpass.registry.catalog import Catalog
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.server import _parse_multipart


@pytest.fixture(autouse=True)
def _pool_without_courses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run on a pool not on courses: its global progress page, catalog editor and moderation."""
    monkeypatch.delenv("HASHPASS_COURSES", raising=False)



@pytest.mark.tier2
def test_history_and_antibot_recorded_and_shown(registry):
    Catalog(registry.catalog_path).add_task("lab:1", "d1", hidden=False, auto=True)
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


def _login_cookie(registry, user: str, password: str, *, role: str = "author") -> tuple:
    """Register (role=author by default) and log in via /web/login; return (opener, cookie)."""
    registry.users.add(user, password, role=role, group="")
    opener = _opener()
    _, headers, _ = _req(opener, "POST", f"{registry.base_url}/web/login",
                         data={"user": user, "password": password})
    return opener, headers["Set-Cookie"].split(";")[0]


def _add_shown(opener, base: str, cookie: str, ref: str) -> None:
    """Add a task to the catalog via the web (it lands hidden) and show it to students."""
    _req(opener, "POST", f"{base}/web/catalog/add", cookie=cookie, data={"ref": ref})
    _req(opener, "POST", f"{base}/web/tasks/toggle", cookie=cookie, data={"ref": ref, "hidden": "0"})


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
    registry.users.add("dev", "pass123!", role="admin", group="")   # attaches to an un-namespaced ref
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


def _about(registry, ref: str, text: str) -> None:
    """Attach a task's about.md to its card, as `hashengine push` does."""
    AttachmentStore(Path(registry.store.root) / "attachments").put_file(ref, "about.md", text.encode())


@pytest.mark.tier2
def test_web_card_shows_about_md_read_only(registry, tmp_path):
    _seed(registry, "lab:1", tmp_path)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    _about(registry, "lab:1", "# Лаборатория\n\nОписание образа")
    _req(opener, "POST", f"{base}/web/images/attach-delete", cookie=cookie,
         data={"ref": "lab:1", "name": "nope"})   # deleting a missing file is harmless
    _, _, body = _req(opener, "GET", f"{base}/web/image/lab:1", cookie=cookie)
    assert "<h3>Лаборатория</h3>" in body and "<p>Описание образа</p>" in body   # like a README
    assert "about.md" in body and "<textarea" not in body       # read-only: edited in the task
    status, _, _ = _req(opener, "POST", f"{base}/web/images/describe", cookie=cookie,
                        data={"ref": "lab:1", "description": "x"})
    assert status in (HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED)


@pytest.mark.tier2
def test_web_blocks_add_task_toggle_remove(registry, tmp_path):
    _seed(registry, "lab:1", tmp_path, task=True)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    student = RemoteRegistry(registry.base_url).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(registry.base_url)

    # add a task to the catalog: it auto-numbers into a (default) open block
    _add_shown(opener, base, cookie, "lab:1")
    cat = sc.catalog(token=student)
    assert [(e["number"], e["available"]) for e in cat] == [(1, True)]
    block_id = cat[0]["block_id"]

    # closing the whole block locks its tasks (still visible), and /submit is refused
    _req(opener, "POST", f"{base}/web/blocks/toggle", cookie=cookie,
         data={"block_id": block_id, "open": "0"})
    assert sc.catalog(token=student) == []          # a closed block is not shown to students
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
    _add_shown(opener, base, cookie, "a:1")
    _add_shown(opener, base, cookie, "b:1")
    block_id = sc.catalog(token=student)[0]["block_id"]
    # drag: JS posts the new order as JSON (id + task refs)
    req = urllib.request.Request(  # noqa: S310
        f"{base}/web/catalog/layout", method="POST",
        data=json.dumps({"blocks": [{"id": block_id, "tasks": ["b:1", "a:1"]}]}).encode(),
        headers={"Cookie": cookie, "Content-Type": "application/json"})
    opener.open(req, timeout=10)
    assert [e["ref"] for e in sc.catalog(token=student)] == ["b:1", "a:1"]


@pytest.mark.tier2
def test_web_catalog_layout_is_admin_only(registry, tmp_path):
    """The whole-catalog drag-reorder is an administrative op; an author gets 403, admin succeeds."""
    for name in ("a", "b"):
        _seed(registry, f"{name}:1", tmp_path, task=True)
    admin_opener, admin_cookie = _author_cookie(registry)   # "teacher", admin
    base = registry.base_url
    _add_shown(admin_opener, base, admin_cookie, "a:1")
    _add_shown(admin_opener, base, admin_cookie, "b:1")
    student = RemoteRegistry(registry.base_url).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(registry.base_url)
    block_id = sc.catalog(token=student)[0]["block_id"]
    before = [e["ref"] for e in sc.catalog(token=student)]

    author_opener, author_cookie = _login_cookie(registry, "alice", "pass123!")
    payload = json.dumps({"blocks": [{"id": block_id, "tasks": ["b:1", "a:1"]}]}).encode()
    req = urllib.request.Request(  # noqa: S310
        f"{base}/web/catalog/layout", method="POST", data=payload,
        headers={"Cookie": author_cookie, "Content-Type": "application/json"})
    try:
        status = author_opener.open(req, timeout=10).status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == HTTPStatus.FORBIDDEN
    assert [e["ref"] for e in sc.catalog(token=student)] == before   # layout untouched

    req2 = urllib.request.Request(  # noqa: S310
        f"{base}/web/catalog/layout", method="POST", data=payload,
        headers={"Cookie": admin_cookie, "Content-Type": "application/json"})
    admin_opener.open(req2, timeout=10)
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


def _seed_blob(registry, ref: str, tmp_path: Path, *, parents: tuple[str, ...] = ()) -> str:
    """Seed the SERVER store the way a new-client push does: a blob generation, no layer/."""
    name, _, version = ref.partition(":")
    slug = f"{name.replace('/', '_')}-{version}"
    local = ImageStore(tmp_path / f"local-{slug}")
    src = tmp_path / f"src-{slug}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "f.txt").write_text("x", encoding="utf-8")
    img = local.save(name, version, src, parents)
    blob_bytes = pack_image_to_file(img, tmp_path / f"{slug}.tar.gz").read_bytes()
    tmp = tmp_path / f"incoming-{slug}.tmp"
    tmp.write_bytes(blob_bytes)
    digest = hashlib.sha256(blob_bytes).hexdigest()
    registry.store.publish_blob(name, version, tmp, parents=parents, digest=digest)
    return ref


@pytest.mark.tier2
def test_blob_only_record_works_in_web_card_task_and_closure(registry, tmp_path):
    opener, cookie = _author_cookie(registry)              # registers + logs in the author "teacher"
    _seed_blob(registry, "base:1", tmp_path)
    _seed_blob(registry, "lab:1", tmp_path, parents=("base:1",))
    client = RemoteRegistry(registry.base_url)
    atok = client.login("teacher", "pass123!")
    assert client.closure("lab:1") == ["base:1", "lab:1"]  # parents come from meta.json alone
    tdir = tmp_path / "task"
    (tdir / "bundle").mkdir(parents=True)
    (tdir / "task-meta.json").write_text('{"image_ref":"lab:1"}', encoding="utf-8")
    client.push_task(tdir, "lab", "1", publish=True, token=atok)          # task next to a blob-only image
    assert any(e["ref"] == "lab:1" for e in client.catalog(token=atok))
    client.push_attachment("lab", "1", "Taskfile", b"image lab:1\n", taskfile=True, token=atok)
    status, _headers, body = _req(opener, "GET", f"{registry.base_url}/web/image/lab:1", cookie=cookie)
    assert status == HTTPStatus.OK
    assert "lab:1" in body and "Taskfile" in body
    # /images is a bearer-token JSON API (like /catalog, /progress) -- not a cookie-session route
    assert any("digest" in row for row in client.pool_images(token=atok))


# -- web ownership: an author's card/catalog writes are scoped to their own namespace -------

@pytest.mark.tier2
def test_web_write_routes_denied_for_other_authors_namespace(registry, tmp_path):
    """Alice (author) gets 403 on every card/catalog write route for bob's namespaced image."""
    _seed(registry, "bob/lab:1", tmp_path, task=True)
    opener, cookie = _login_cookie(registry, "alice", "pass123!")
    base = registry.base_url

    status, _, _ = _req(opener, "POST", f"{base}/web/images/attach-delete", cookie=cookie,
                        data={"ref": "bob/lab:1", "name": "nope"})
    assert status == HTTPStatus.FORBIDDEN
    status, _, _ = _req(opener, "POST", f"{base}/web/catalog/add", cookie=cookie,
                        data={"ref": "bob/lab:1"})
    assert status == HTTPStatus.FORBIDDEN
    status, _, _ = _req(opener, "POST", f"{base}/web/catalog/remove", cookie=cookie,
                        data={"ref": "bob/lab:1"})
    assert status == HTTPStatus.FORBIDDEN
    status, _, _ = _req(opener, "POST", f"{base}/web/tasks/toggle", cookie=cookie,
                        data={"ref": "bob/lab:1", "hidden": "1"})
    assert status == HTTPStatus.FORBIDDEN

    # multipart attach (the real upload path)
    b = "----hpTEST"
    body = "".join([
        f'--{b}\r\nContent-Disposition: form-data; name="ref"\r\n\r\nbob/lab:1\r\n',
        f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="notes.txt"\r\n\r\n',
        "privet\r\n",
        f"--{b}--\r\n",
    ]).encode()
    req = urllib.request.Request(  # noqa: S310
        f"{base}/web/images/attach", data=body, method="POST",
        headers={"Cookie": cookie, "Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        resp = opener.open(req, timeout=10)
        status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == HTTPStatus.FORBIDDEN


@pytest.mark.tier2
def test_web_write_routes_allowed_for_own_namespace(registry, tmp_path):
    """Alice (author) can still describe/attach/catalog her own namespaced image."""
    _seed(registry, "alice/lab:1", tmp_path, task=True)
    opener, cookie = _login_cookie(registry, "alice", "pass123!")
    base = registry.base_url
    student = RemoteRegistry(registry.base_url).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(registry.base_url)

    _about(registry, "alice/lab:1", "Описание образа")
    _, _, body = _req(opener, "GET", f"{base}/web/image/{urllib.parse.quote('alice/lab:1')}",
                      cookie=cookie)
    assert "Описание образа" in body

    _add_shown(opener, base, cookie, "alice/lab:1")
    cat = sc.catalog(token=student)
    assert [(e["number"], e["available"]) for e in cat] == [(1, True)]
    block_id = cat[0]["block_id"]

    _req(opener, "POST", f"{base}/web/blocks/toggle", cookie=cookie,
         data={"block_id": block_id, "open": "0"})
    assert sc.catalog(token=student) == []          # a closed block is not shown to students

    _req(opener, "POST", f"{base}/web/catalog/remove", cookie=cookie, data={"ref": "alice/lab:1"})
    assert sc.catalog(token=student) == []


@pytest.mark.tier2
def test_web_write_routes_allowed_for_admin_on_others_namespace(registry, tmp_path):
    """Teacher (admin, via _author_cookie) may still write bob's namespaced image."""
    _seed(registry, "bob/lab:1", tmp_path, task=True)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url

    _about(registry, "bob/lab:1", "Описание образа")
    _, _, body = _req(opener, "GET", f"{base}/web/image/{urllib.parse.quote('bob/lab:1')}",
                      cookie=cookie)
    assert "Описание образа" in body

    status, _, _ = _req(opener, "POST", f"{base}/web/catalog/add", cookie=cookie,
                        data={"ref": "bob/lab:1"})
    assert status in (HTTPStatus.OK, HTTPStatus.SEE_OTHER, HTTPStatus.FOUND)
    _req(opener, "POST", f"{base}/web/tasks/toggle", cookie=cookie, data={"ref": "bob/lab:1", "hidden": "0"})
    student = RemoteRegistry(registry.base_url).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(registry.base_url)
    assert [e["ref"] for e in sc.catalog(token=student)] == ["bob/lab:1"]

    status, _, _ = _req(opener, "POST", f"{base}/web/catalog/remove", cookie=cookie,
                        data={"ref": "bob/lab:1"})
    assert status in (HTTPStatus.OK, HTTPStatus.SEE_OTHER, HTTPStatus.FOUND)
    assert sc.catalog(token=student) == []


@pytest.mark.tier2
def test_web_card_404_links_the_namespaced_twin(registry, tmp_path):
    _seed(registry, "bunnyton/debian:1", tmp_path)
    opener, cookie = _author_cookie(registry)
    status, _, body = _req(opener, "GET", f"{registry.base_url}/web/image/debian:1", cookie=cookie)
    assert status == HTTPStatus.NOT_FOUND
    assert "быть может, вы искали" in body
    assert 'href="/web/image/bunnyton/debian:1"' in body
    status, _, body = _req(opener, "GET", f"{registry.base_url}/web/image/ghost:1", cookie=cookie)
    assert status == HTTPStatus.NOT_FOUND
    assert "быть может" not in body


@pytest.mark.tier2
def test_web_block_hide_all_tasks_then_open_one_by_one(registry, tmp_path):
    """«Скрыть все задания» hides every task of an OPEN block; the teacher then shows them singly."""
    for ref in ("lab:1", "lab:2", "lab:3"):
        _seed(registry, ref, tmp_path, task=True)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    student = RemoteRegistry(base).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(base)
    for ref in ("lab:1", "lab:2", "lab:3"):
        _add_shown(opener, base, cookie, ref)
    block_id = sc.catalog(token=student)[0]["block_id"]

    _, _, page = _req(opener, "GET", f"{base}/web/images", cookie=cookie)
    assert "Скрыть все задания" in page

    _req(opener, "POST", f"{base}/web/blocks/hide-tasks", cookie=cookie,
         data={"block_id": block_id, "hidden": "1"})
    assert sc.catalog(token=student) == []                      # all hidden → nothing for students
    cat = [e.as_dict() for e in Catalog(registry.catalog_path).entries()]
    assert [(e["available"], e["hidden"]) for e in cat] == [(False, True)] * 3
    _, _, page = _req(opener, "GET", f"{base}/web/images", cookie=cookie)
    assert "Показать все задания" in page

    _req(opener, "POST", f"{base}/web/tasks/toggle", cookie=cookie, data={"ref": "lab:1", "hidden": "0"})
    assert [e["ref"] for e in sc.catalog(token=student)] == ["lab:1"]          # only the shown one

    _req(opener, "POST", f"{base}/web/blocks/hide-tasks", cookie=cookie,
         data={"block_id": block_id, "hidden": "0"})
    assert [e["available"] for e in sc.catalog(token=student)] == [True, True, True]


@pytest.mark.tier2
def test_web_block_hide_all_tasks_touches_only_own_namespace(registry, tmp_path):
    """An author's «скрыть все» hides only the tasks they own; others' tasks in the block stay."""
    _seed(registry, "alice/a:1", tmp_path, task=True)
    _seed(registry, "bob/b:1", tmp_path, task=True)
    admin, acookie = _author_cookie(registry)
    base = registry.base_url
    for ref in ("alice/a:1", "bob/b:1"):
        _add_shown(admin, base, acookie, ref)
    opener, cookie = _login_cookie(registry, "alice", "pass123!")
    student = RemoteRegistry(base).register("stud", "pass123!", group="G")
    sc = RemoteRegistry(base)
    block_id = sc.catalog(token=student)[0]["block_id"]
    _req(opener, "POST", f"{base}/web/blocks/hide-tasks", cookie=cookie,
         data={"block_id": block_id, "hidden": "1"})
    assert [(e["ref"], e["available"]) for e in sc.catalog(token=student)] == [("bob/b:1", True)]


@pytest.mark.tier2
def test_catalog_marks_locked_tasks_as_preview_for_staff_only(registry, tmp_path):
    """Author/admin get `preview: true` on locked tasks (runnable for them); a student does not."""
    _seed(registry, "lab:1", tmp_path, task=True)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    _add_shown(opener, base, cookie, "lab:1")
    _req(opener, "POST", f"{base}/web/tasks/toggle", cookie=cookie, data={"ref": "lab:1", "hidden": "1"})
    student = RemoteRegistry(base).register("stud", "pass123!", group="G")
    teacher = RemoteRegistry(base).login("teacher", "pass123!")
    assert RemoteRegistry(base).catalog(token=student) == []          # hidden: not there at all
    assert [e.get("preview", False) for e in RemoteRegistry(base).catalog(token=teacher)] == [True]


@pytest.mark.tier2
def test_students_never_see_hidden_or_closed_tasks_staff_see_all(registry, tmp_path):
    for ref in ("lab:1", "lab:2"):
        _seed(registry, ref, tmp_path, task=True)
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    for ref in ("lab:1", "lab:2"):
        _req(opener, "POST", f"{base}/web/catalog/add", cookie=cookie, data={"ref": ref})
    student = RemoteRegistry(base).register("stud", "pass123!", group="G")
    teacher = RemoteRegistry(base).login("teacher", "pass123!")
    assert RemoteRegistry(base).catalog(token=student) == []                # added = hidden
    _req(opener, "POST", f"{base}/web/tasks/toggle", cookie=cookie, data={"ref": "lab:2", "hidden": "0"})
    assert [e["ref"] for e in RemoteRegistry(base).catalog(token=student)] == ["lab:2"]
    assert [e["ref"] for e in RemoteRegistry(base).catalog(token=teacher)] == ["lab:1", "lab:2"]


@pytest.mark.tier2
def test_web_card_lists_sources_shows_a_file_and_gives_the_archive(registry, tmp_path):
    from hashpass import cli  # noqa: PLC0415
    from hashpass.registry.sources import SourceStore  # noqa: PLC0415
    _seed(registry, "lab:1", tmp_path, task=True)
    tdir = tmp_path / "lab-src"
    (tdir / "hp").mkdir(parents=True)
    (tdir / "Taskfile").write_text('stage\n  say "цель"\n', encoding="utf-8")
    (tdir / "hp" / "check").write_text("#!/bin/sh\n", encoding="utf-8")
    SourceStore(Path(registry.store.root) / "sources").put_archive("lab:1", cli.pack_task_source(tdir))
    opener, cookie = _author_cookie(registry)
    base = registry.base_url
    _, _, body = _req(opener, "GET", f"{base}/web/image/lab:1", cookie=cookie)
    assert "Исходники" in body and "path=hp'" in body and "source-archive" in body
    _, _, page = _req(opener, "GET", f"{base}/web/images/source?ref=lab%3A1&path=Taskfile", cookie=cookie)
    text = html.unescape(re.sub(r"<[^>]+>", "", page))      # highlighted: tokens are spans
    assert 'say "цель"' in text
    status, _, _ = _req(opener, "GET", f"{base}/web/images/source?ref=lab%3A1&path=..%2F..%2Fx", cookie=cookie)
    assert status == HTTPStatus.NOT_FOUND
    status, headers, _ = _req(opener, "GET", f"{base}/web/images/source-archive?ref=lab%3A1", cookie=cookie)
    assert status == HTTPStatus.OK and "lab-1.tar.gz" in headers.get("Content-Disposition", "")


@pytest.mark.tier2
def test_web_admin_switches_auto_approval_and_the_card_shows_moderation(registry, tmp_path):
    from hashpass.registry.pool_settings import PoolSettings  # noqa: PLC0415
    registry.users.add("bob", "pass123!", role="author")
    opener, cookie = _author_cookie(registry)                    # teacher = admin
    base = registry.base_url
    _, _, page = _req(opener, "GET", f"{base}/web/users", cookie=cookie)
    assert "Авто-одобрение" in page
    _req(opener, "POST", f"{base}/web/users/auto-approve", cookie=cookie, data={"user": "bob", "on": "1"})
    assert registry.users.auto_approve("bob") is True
    _req(opener, "POST", f"{base}/web/pool/auto-approve", cookie=cookie, data={"on": "0"})
    assert PoolSettings(registry.catalog_path.parent / "pool-settings.json").auto_approve is False
    a_op, a_cookie = _login_cookie(registry, "alice", "pass123!")
    _req(a_op, "POST", f"{base}/web/users/auto-approve", cookie=a_cookie, data={"user": "alice", "on": "1"})
    assert registry.users.auto_approve("alice") is False              # only the admin switches it

    _seed(registry, "bob/lab:1", tmp_path, task=True)
    cat = Catalog(registry.catalog_path)
    cat.add_task("bob/lab:1", "d1")
    cat.reject("bob/lab:1", "нет финала", now=0.0)
    _, _, card = _req(opener, "GET", f"{base}/web/image/{urllib.parse.quote('bob/lab:1')}", cookie=cookie)
    assert "отклонено" in card and "нет финала" in card


@pytest.mark.tier1
def test_code_view_numbers_lines_and_highlights():
    from hashpass.registry.codeview import highlight_lines  # noqa: PLC0415
    lines = highlight_lines("check.sh", '#!/bin/sh\necho "a\nb"\n')
    assert len(lines) == 3  # noqa: PLR2004                # a string spanning lines splits per line
    assert "class='c" in str(lines[0])                       # comment / shebang
    assert "&#34;a" in str(lines[1]) or "&quot;a" in str(lines[1]) or '"a' in str(lines[1])
    assert "<script>" not in str(highlight_lines("x.txt", "<script>")[0])


@pytest.mark.tier2
def test_web_sources_browse_folders_raw_download_and_markdown(registry, tmp_path):
    from hashpass import cli  # noqa: PLC0415
    from hashpass.registry.sources import SourceStore  # noqa: PLC0415
    _seed(registry, "lab:1", tmp_path, task=True)
    tdir = tmp_path / "lab-src"
    (tdir / "hp").mkdir(parents=True)
    (tdir / "Taskfile").write_text("stage\n", encoding="utf-8")
    (tdir / "brief.md").write_text("# Заголовок\n\n**жирно**\n", encoding="utf-8")
    (tdir / "hp" / "check").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    SourceStore(Path(registry.store.root) / "sources").put_archive("lab:1", cli.pack_task_source(tdir))
    opener, cookie = _author_cookie(registry)
    src = f"{registry.base_url}/web/images/source?ref=lab%3A1"
    _, _, card = _req(opener, "GET", f"{registry.base_url}/web/image/lab:1", cookie=cookie)
    assert "class='filebox'" in card and "path=hp'" in card   # the root lists the folder, not its files
    assert "path=hp%2Fcheck" not in card
    status, _, folder = _req(opener, "GET", f"{src}&path=hp", cookie=cookie)
    assert status == HTTPStatus.OK and "path=hp%2Fcheck" in folder
    _, _, code = _req(opener, "GET", f"{src}&path=hp%2Fcheck", cookie=cookie)
    assert "id='L2'" in code and "2 строки" in code and "raw=1" in code
    status, headers, raw = _req(opener, "GET", f"{src}&path=hp%2Fcheck&raw=1", cookie=cookie)
    assert raw == "#!/bin/sh\nexit 0\n" and headers["Content-Type"].startswith("text/plain")
    _, headers, _ = _req(opener, "GET", f"{src}&path=hp%2Fcheck&dl=1", cookie=cookie)
    assert 'filename="check"' in headers["Content-Disposition"]
    _, _, md = _req(opener, "GET", f"{src}&path=brief.md", cookie=cookie)
    assert "<strong>жирно</strong>" in md and "<h1>Заголовок</h1>" in md
