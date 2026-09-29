"""Tier2: `hashengine catalog layout` -- blocks by theme drive the pool's numbering."""
import json
import urllib.error
import urllib.request
from http import HTTPStatus

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
    Catalog(registry.catalog_path).add_task(ref, "d")


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
    assert rows[2][1] == "alice/x:1"                     # kept, after the requested blocks
    assert body["removed"] == []
    blocks = cat.blocks()
    assert blocks[0].id == first.id and blocks[0].open is False   # id + collapsed state preserved


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
    assert "№1  bunnyton/c:1   [Первый]" in text and "№2  bunnyton/a:1   [Первый]" in text
    assert "пропущен: bunnyton/ghost:1" in text
    assert [e["ref"] for e in RemoteRegistry(registry.base_url).catalog(token=cli._pool_token(env, registry.base_url))] == ["bunnyton/c:1", "bunnyton/a:1"]  # noqa: SLF001
