"""Tier1: a push is staged, then committed as one numbered revision (spec 2026-10-21 §2.3)."""
import io
import json
import tarfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import pack_image_to_file, pack_task
from hashpass.registry.catalog import Catalog
from hashpass.registry.remote import RemoteRegistry


def _http(method: str, url: str, *, token: str | None = None, body: dict | None = None,
          data: bytes | None = None) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw[:1] == b"{" else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, (json.loads(raw) if raw[:1] == b"{" else {})


class _Pool:
    def __init__(self, registry, tmp_path: Path) -> None:
        self.r, self.tmp, self.url = registry, tmp_path, registry.base_url
        for user, role in (("bob", "author"), ("eve", "author"), ("bunnyton", "admin")):
            registry.users.add(user, "pw-correct1", role=role)
        self.tok = {u: RemoteRegistry(self.url).login(u, "pw-correct1") for u in ("bob", "eve", "bunnyton")}
        self._n = 0

    def blob(self, name: str, tag: str, text: str, parents: tuple[str, ...] = ()) -> bytes:
        self._n += 1
        local = ImageStore(self.tmp / f"loc{self._n}")
        src = self.tmp / f"src{self._n}"
        src.mkdir()
        (src / "f.txt").write_text(text, encoding="utf-8")
        local.save(name, tag, src, parents)
        out = self.tmp / f"b{self._n}.tar.gz"
        pack_image_to_file(local.get(f"{name}:{tag}"), out)
        return out.read_bytes()

    def task(self, text: str) -> bytes:
        self._n += 1
        td = self.tmp / f"task{self._n}"
        (td / "bundle").mkdir(parents=True)
        (td / "bundle" / "c.json").write_text(text, encoding="utf-8")
        (td / "task-meta.json").write_text('{"image_ref":"x"}', encoding="utf-8")
        return pack_task(td)

    def begin(self, name: str, tag: str, user: str = "bob") -> tuple[int, dict]:
        return _http("POST", f"{self.url}/revisions/{name}/{tag}", token=self.tok[user])

    def put(self, kind: str, name: str, tag: str, sid: str, data: bytes, user: str = "bob",  # noqa: PLR0913, PLR0917
            query: str = "") -> int:
        return _http("PUT", f"{self.url}/{kind}/{name}/{tag}?staging={sid}{query}", token=self.tok[user],
                     data=data)[0]

    def commit(self, name: str, tag: str, sid: str, user: str = "bob") -> tuple[int, dict]:
        return _http("POST", f"{self.url}/revisions/{name}/{tag}/commit", token=self.tok[user],
                     body={"staging": sid})

    def push(self, name: str, tag: str, *, image: str | None = None, task: str | None = None,  # noqa: PLR0913
             parents: tuple[str, ...] = (), user: str = "bob", query: str = "") -> tuple[int, dict]:
        code, body = self.begin(name, tag, user)
        assert code == 201, body  # noqa: PLR2004
        sid = body["staging"]
        if image is not None:
            assert self.put("image", name, tag, sid, self.blob(name, tag, image, parents), user) == 201  # noqa: PLR2004
        if task is not None:
            assert self.put("task", name, tag, sid, self.task(task), user, query) == 201  # noqa: PLR2004
        return self.commit(name, tag, sid, user)


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Pool:
    p = _Pool(registry, tmp_path)
    assert p.push("bunnyton/debian", "trixie", image="base", user="bunnyton")[0] == 201  # noqa: PLR2004
    return p


@pytest.mark.tier1
def test_push_creates_v1_then_v2(pool: _Pool) -> None:
    first = pool.push("bob/lab", "1", image="one", task="t1", parents=("bunnyton/debian:trixie",))
    second = pool.push("bob/lab", "1", image="two", task="t2", parents=("bunnyton/debian:trixie",))
    assert first == (201, {"ref": "bob/lab:1_v1", "n": 1})
    assert second == (201, {"ref": "bob/lab:1_v2", "n": 2})
    assert pool.r.store.exists("bob/lab:1_v1")
    assert pool.r.store.exists("bob/lab:1_v2")


@pytest.mark.tier1
def test_unchanged_push_creates_nothing(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1")
    code, body = pool.push("bob/lab", "1", task="t1")          # same task, image not re-sent
    assert (code, body) == (200, {"ref": "bob/lab:1_v1", "n": 1, "unchanged": True})
    assert not pool.r.store.exists("bob/lab:1_v2")


@pytest.mark.tier1
def test_task_only_change_links_previous_image(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1")
    code, body = pool.push("bob/lab", "1", task="t2")
    assert (code, body["ref"]) == (201, "bob/lab:1_v2")
    store = pool.r.store
    assert store.get("bob/lab:1_v2").digest == store.get("bob/lab:1_v1").digest
    assert store.blob_path("bob/lab:1_v2").stat().st_ino == store.blob_path("bob/lab:1_v1").stat().st_ino
    task = store.get("bob/lab:1_v2").layer.parent / "task" / "bundle" / "c.json"
    assert task.read_text(encoding="utf-8") == "t2"


@pytest.mark.tier1
def test_image_only_change_keeps_previous_task(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1")
    assert pool.push("bob/lab", "1", image="two")[1]["ref"] == "bob/lab:1_v2"
    task = pool.r.store.get("bob/lab:1_v2").layer.parent / "task" / "bundle" / "c.json"
    assert task.read_text(encoding="utf-8") == "t1"


@pytest.mark.tier1
def test_parents_pinned_to_latest_revision(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1", parents=("bunnyton/debian:trixie",))
    assert pool.r.store.get("bob/lab:1_v1").parents == ("bunnyton/debian:trixie_v1",)
    pool.push("bunnyton/debian", "trixie", image="base2", user="bunnyton")
    assert pool.r.store.get("bob/lab:1_v1").parents == ("bunnyton/debian:trixie_v1",)
    pool.push("bob/lab", "1", task="t2")                       # re-pinned only by a new push
    assert pool.r.store.get("bob/lab:1_v2").parents == ("bunnyton/debian:trixie_v1",)


@pytest.mark.tier1
def test_missing_parent_is_409(pool: _Pool) -> None:
    code, body = pool.push("bob/lab", "1", image="one", parents=("bunnyton/nothere:1",))
    assert code == 409  # noqa: PLR2004
    assert "bunnyton/nothere:1" in body["error"]
    assert not pool.r.store.exists("bob/lab:1_v1")


@pytest.mark.tier1
def test_reserved_tag_is_400(pool: _Pool) -> None:
    code, body = pool.begin("bob/lab", "1_v2")
    assert code == 400  # noqa: PLR2004
    assert "зарезервирован" in body["error"]


@pytest.mark.tier1
def test_foreign_namespace_is_403(pool: _Pool) -> None:
    assert pool.begin("eve/lab", "1")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_commit_by_another_user_is_403(pool: _Pool) -> None:
    sid = pool.begin("bob/lab", "1")[1]["staging"]
    assert pool.put("image", "bob/lab", "1", sid, pool.blob("bob/lab", "1", "x")) == 201  # noqa: PLR2004
    assert pool.commit("bob/lab", "1", sid, user="eve")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_empty_first_commit_is_400(pool: _Pool) -> None:
    sid = pool.begin("bob/lab", "1")[1]["staging"]
    assert pool.commit("bob/lab", "1", sid)[0] == 400  # noqa: PLR2004


@pytest.mark.tier1
def test_staged_image_not_listed_before_commit(pool: _Pool) -> None:
    sid = pool.begin("bob/lab", "1")[1]["staging"]
    pool.put("image", "bob/lab", "1", sid, pool.blob("bob/lab", "1", "x"))
    assert all(not r.startswith("bob/lab") for r in pool.r.store.list())


@pytest.mark.tier1
def test_parallel_commits_get_distinct_numbers(pool: _Pool) -> None:
    sids = []
    for text in ("a", "b"):
        sid = pool.begin("bob/lab", "1")[1]["staging"]
        pool.put("image", "bob/lab", "1", sid, pool.blob("bob/lab", "1", text))
        sids.append(sid)
    got: list[dict] = []
    threads = [threading.Thread(target=lambda s=s: got.append(pool.commit("bob/lab", "1", s)[1]))
               for s in sids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(b["n"] for b in got) == [1, 2]


@pytest.mark.tier1
def test_publish_intent_adds_catalog_entry(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1", query="&publish=1&block=Git")
    entry = Catalog(pool.r.catalog_path).find("bob/lab:1")
    assert entry is not None
    assert entry.block_name == "Git"


@pytest.mark.tier1
def test_commit_updates_catalog_entry_without_publish(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1", query="&publish=1")
    before = Catalog(pool.r.catalog_path).find("bob/lab:1").digest
    pool.push("bob/lab", "1", task="t2")
    assert Catalog(pool.r.catalog_path).find("bob/lab:1").digest != before


def _push_with_files(pool: _Pool, taskfile: bytes, readme: bytes) -> tuple[int, dict]:
    sid = pool.begin("bob/lab", "1")[1]["staging"]
    pool.put("task", "bob/lab", "1", sid, pool.task("t1"))
    pool.put("attachment", "bob/lab", "1", sid, taskfile, query="&name=Taskfile&taskfile=1")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("README.md")
        info.size = len(readme)
        tar.addfile(info, io.BytesIO(readme))
    pool.put("source", "bob/lab", "1", sid, buf.getvalue())
    return pool.commit("bob/lab", "1", sid)


@pytest.mark.tier1
def test_same_files_again_is_unchanged_but_an_edit_is_a_revision(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    assert _push_with_files(pool, b"image x:1", b"# hi")[1]["n"] == 2  # noqa: PLR2004
    assert _push_with_files(pool, b"image x:1", b"# hi")[1].get("unchanged") is True
    third = _push_with_files(pool, b"image x:1", b"# hello")[1]
    assert third["n"] == 3  # noqa: PLR2004
    readme = pool.r.store.root / "sources" / "bob" / "lab" / "1_v3" / "README.md"
    assert readme.read_text(encoding="utf-8") == "# hello"


@pytest.mark.tier1
def test_files_carry_over_to_a_task_only_revision(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    _push_with_files(pool, b"image x:1", b"# hi")
    pool.push("bob/lab", "1", task="t2")
    readme = pool.r.store.root / "sources" / "bob" / "lab" / "1_v3" / "README.md"
    assert readme.read_text(encoding="utf-8") == "# hi"
