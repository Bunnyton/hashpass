"""Tier2: `hashengine catalog layout` -- blocks by theme drive the pool's numbering."""
import io
import json
import urllib.error
import urllib.request
from http import HTTPStatus
from typing import Never

import pytest

from hashpass import cli
from hashpass.registry.catalog import Catalog
from hashpass.registry.remote import RemoteRegistry


def _seed(registry, ref: str, tmp_path) -> None:
    name, _, version = ref.partition(":")
    src = tmp_path / f"src-{name.replace('/', '_')}-{version}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "f.txt").write_text("x", encoding="utf-8")
    registry.store.save(name, version, src, ())
    Catalog(registry.catalog_path).add_task(ref, "d", auto=True)


def _put(base_url: str, token: str | None, payload: dict) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{base_url}/catalog/layout", method="PUT",  # noqa: S310
                                 data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body) if body else {}


@pytest.mark.tier1
def test_parse_layout_specs_namespaces_bare_refs():
    blocks = cli.parse_layout_specs(["Знакомство: intro-hello:1 alice/x:2", "Поиск: grep-search:1"],
                                    "bunnyton")
    assert [b["name"] for b in blocks] == ["Знакомство", "Поиск"]
    assert blocks[0]["tasks"] == ["bunnyton/intro-hello:1", "alice/x:2"]
    with pytest.raises(ValueError, match="Название"):
        cli.parse_layout_specs(["no colon here"], "bunnyton")


@pytest.mark.tier2
def test_layout_api_is_admin_only_and_renumbers(registry, tmp_path):
    for ref in ("b/a:1", "b/c:1", "b/d:1", "b/old:1"):
        _seed(registry, ref, tmp_path)                     # appended in this order: 1..4
    registry.users.add("admin", "pw-correct", role="admin")
    registry.users.add("alice", "pw-correct", role="author")
    admin = RemoteRegistry(registry.base_url).login("admin", "pw-correct")
    alice = RemoteRegistry(registry.base_url).login("alice", "pw-correct")
    payload = {"blocks": [{"name": "Поиск", "tasks": ["b/d:1", "b/c:1"]},
                          {"name": "Знакомство", "tasks": ["b/a:1", "b/ghost:1"]}]}
    assert _put(registry.base_url, None, payload)[0] == HTTPStatus.UNAUTHORIZED
    status, body = _put(registry.base_url, alice, payload)
    assert status == HTTPStatus.FORBIDDEN and "администратор" in body["error"]
    assert _put(registry.base_url, admin, {"blocks": "nope"})[0] == HTTPStatus.BAD_REQUEST
    status, body = _put(registry.base_url, admin, payload)
    assert status == HTTPStatus.OK
    rows = [(r["number"], r["ref"], r["block_name"]) for r in body["catalog"]]
    assert rows == [(1, "b/d:1", "Поиск"), (2, "b/c:1", "Поиск"), (3, "b/a:1", "Знакомство")]
    assert body["removed"] == ["b/old:1"]   # same namespace, not in the layout -> de-listed, reported
    # b/ghost:1 is not on the pool -> dropped


@pytest.mark.tier2
def test_layout_keeps_other_authors_tasks_and_block_state(registry, tmp_path):
    # A deploy lists only its own namespace: another author's tasks stay published (after the
    # requested blocks), and a block already in the catalog keeps its id and collapsed state.
    for ref in ("b/a:1", "alice/x:1", "b/c:1"):
        _seed(registry, ref, tmp_path)
    cat = Catalog(registry.catalog_path)
    first = cat.blocks()[0]
    cat.rename_block(first.id, "Знакомство")
    cat.set_block_open(first.id, open_=False)
    registry.users.add("admin", "pw-correct", role="admin")
    admin = RemoteRegistry(registry.base_url).login("admin", "pw-correct")
    status, body = _put(registry.base_url, admin, {"blocks": [{"name": "Знакомство", "tasks": ["b/c:1", "b/a:1"]}]})
    assert status == HTTPStatus.OK
    rows = [(r["number"], r["ref"], r["block_name"]) for r in body["catalog"]]
    assert rows[:2] == [(1, "b/c:1", "Знакомство"), (2, "b/a:1", "Знакомство")]
    assert rows[2] == (3, "alice/x:1", "Знакомство")      # kept, in the same-named block
    assert body["removed"] == []
    blocks = cat.blocks()
    assert blocks[0].id == first.id and blocks[0].open is False   # id + collapsed state preserved
    assert len(blocks) == 1                              # not a second «Знакомство» with the same id


@pytest.mark.tier2
def test_layout_appends_other_authors_blocks_with_unique_ids(registry, tmp_path):
    # A foreign task in a block the deploy does not name keeps its own block; block ids stay unique.
    for ref in ("b/a:1", "alice/x:1"):
        _seed(registry, ref, tmp_path)
    cat = Catalog(registry.catalog_path)
    first = cat.blocks()[0]
    cat.rename_block(first.id, "Чужое")
    registry.users.add("admin", "pw-correct", role="admin")
    admin = RemoteRegistry(registry.base_url).login("admin", "pw-correct")
    status, body = _put(registry.base_url, admin, {"blocks": [{"name": "Моё", "tasks": ["b/a:1"]}]})
    assert status == HTTPStatus.OK
    assert [(r["ref"], r["block_name"]) for r in body["catalog"]] == [("b/a:1", "Моё"), ("alice/x:1", "Чужое")]
    blocks = cat.blocks()
    assert [b.name for b in blocks] == ["Моё", "Чужое"]
    assert len({b.id for b in blocks}) == len(blocks)


@pytest.mark.tier2
def test_cmd_catalog_layout_prints_numbering_and_warns_about_missing(registry, tmp_path, monkeypatch):
    for ref in ("bunnyton/a:1", "bunnyton/c:1"):
        _seed(registry, ref, tmp_path)
    registry.users.add("bunnyton", "pw-correct", role="admin")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr("getpass.getpass", lambda _p="": "pw-correct")
    io = cli.Io(read=lambda _p: "bunnyton", write=lambda _s: None, clock=lambda: "")
    assert cli.cmd_login(env, registry.base_url, io) == 0
    out: list[str] = []
    quiet = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    assert cli.cmd_catalog_layout(env, ["Первый: c:1 a:1", "Второй: ghost:1"], registry.base_url,
                                  quiet) == 0
    text = "".join(out)
    assert text.index("bunnyton/c:1   [Первый]") < text.index("bunnyton/a:1   [Первый]")   # order, no numbers
    assert "пропущен: bunnyton/ghost:1" in text
    assert [e["ref"] for e in RemoteRegistry(registry.base_url).catalog(token=cli._pool_token(env, registry.base_url))] == ["bunnyton/c:1", "bunnyton/a:1"]  # noqa: SLF001


@pytest.mark.tier1
def test_cmd_catalog_layout_explains_a_pool_without_the_route(tmp_path, monkeypatch):
    # A pool running an older hashengine answers 404 to PUT /catalog/layout: say what to do.
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    monkeypatch.setattr(cli, "_ensure_registry_login", lambda _e, _r, _i: "http://pool.test")
    monkeypatch.setattr(cli, "_pool_token", lambda _e, _u: "tok")
    monkeypatch.setattr(cli, "token_user", lambda _t: "bunnyton")

    def _gone(self, blocks, *, token=None) -> Never:  # noqa: ARG001
        url = "http://pool.test/catalog/layout"
        raise urllib.error.HTTPError(url, HTTPStatus.NOT_FOUND, "NOT FOUND", {}, io.BytesIO(b""))
    monkeypatch.setattr(cli.RemoteRegistry, "set_catalog_layout", _gone)
    quiet = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "")
    with pytest.raises(RuntimeError, match="обновите hashpass на сервере"):
        cli.cmd_catalog_layout(env, ["Первый: a:1"], "http://pool.test", quiet)


@pytest.mark.tier1
def test_parse_layout_specs_leaves_block_open_state_to_the_pool():
    """Deploy must not re-open a block the teacher closed: specs carry no `open`."""
    blocks = cli.parse_layout_specs(["Знакомство: a:1"], "bunnyton")
    assert "open" not in blocks[0]


@pytest.mark.tier2
def test_hide_and_move_over_the_api(registry, tmp_path):
    # The hashpass TUI edits the catalog with a bearer token: an author hides/shows only its own
    # tasks (like the web ⋯ menu), moving is admin-only (like web drag-and-drop).
    for ref in ("b/a:1", "b/c:1", "alice/x:1"):
        _seed(registry, ref, tmp_path)
    registry.users.add("admin", "pw-correct", role="admin")
    registry.users.add("alice", "pw-correct", role="author")
    admin = RemoteRegistry(registry.base_url)
    admin_tok = admin.login("admin", "pw-correct")
    alice = RemoteRegistry(registry.base_url)
    alice_tok = alice.login("alice", "pw-correct")
    alice.set_task_hidden("alice/x:1", hidden=True, token=alice_tok)
    assert Catalog(registry.catalog_path).find("alice/x:1").hidden is True
    with pytest.raises(RuntimeError, match="другому автору"):
        alice.set_task_hidden("b/a:1", hidden=True, token=alice_tok)
    with pytest.raises(RuntimeError, match="администратор"):
        alice.move_task("alice/x:1", -1, token=alice_tok)
    admin.move_task("b/c:1", -1, token=admin_tok)
    assert [e.ref for e in Catalog(registry.catalog_path).entries()] == ["b/c:1", "b/a:1", "alice/x:1"]
    admin.set_task_hidden("b/a:1", hidden=True, token=admin_tok)
    assert Catalog(registry.catalog_path).find("b/a:1").hidden is True


@pytest.mark.tier2
def test_open_and_close_a_block_over_the_api(registry, tmp_path):
    # User (2026-10-13): «блоки открывать для студентов тоже через hashpass». Same right as the
    # web's block toggle: an author or the admin; a student may not.
    _seed(registry, "b/a:1", tmp_path)
    registry.users.add("alice", "pw-correct", role="author")
    registry.users.add("stud", "pw-correct", role="student")
    alice = RemoteRegistry(registry.base_url)
    tok = alice.login("alice", "pw-correct")
    block = alice.catalog(token=tok)[0]
    assert block["block_open"] is True
    alice.set_block_open(str(block["block_id"]), open_=False, token=tok)
    row = alice.catalog(token=tok)[0]
    assert row["block_open"] is False and row["available"] is False
    stud = RemoteRegistry(registry.base_url)
    stok = stud.login("stud", "pw-correct")
    with pytest.raises(RuntimeError):
        stud.set_block_open(str(block["block_id"]), open_=True, token=stok)
