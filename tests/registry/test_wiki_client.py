"""Tier1: `hashpass push` sends the wiki on the side; `hashpass clone` pulls its changes into a folder."""
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from hashpass import cli
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry
from hashpass.registry.wiki_store import pack
from tests.registry.test_push_commit import _http, _Pool


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Pool:
    p = _Pool(registry, tmp_path)
    p.push("bob/lab", "1", image="one", task="t1")
    return p


def _env(tmp_path: Path, user: str = "bob") -> cli.Home:
    return cli.build_env({"HASHPASS_HOME": str(tmp_path / f"h-{user}")}, default_home=tmp_path)


def _client(pool: _Pool, env: cli.Home, user: str = "bob") -> RemoteRegistry:
    client = RemoteRegistry(pool.url, cache=CredentialCache(env.creds))
    client.login(user, "pw-correct1")
    return client


def _folder(tmp_path: Path, name: str = "lab", main: str = "# Lab\n") -> Path:
    d = tmp_path / name
    (d / "wiki").mkdir(parents=True)
    (d / "Taskfile").write_text("stage\n", encoding="utf-8")
    (d / "wiki.md").write_text(main, encoding="utf-8")
    (d / "wiki" / "more.md").write_text("# More\n", encoding="utf-8")
    return d


def _io() -> tuple[cli.Io, list[str]]:
    out: list[str] = []
    return cli.Io(read=lambda _p: None, write=out.append, clock=lambda: ""), out


def _head(pool: _Pool) -> int:
    return RemoteRegistry(pool.url).wiki_get("bob/lab", token=pool.tok["bob"])[0]


@pytest.mark.tier1
def test_the_task_sources_leave_the_wiki_out(tmp_path: Path) -> None:
    d = _folder(tmp_path)
    (d / ".hashpass.json").write_text('{"origin": "bob/lab", "wiki": 3}', encoding="utf-8")
    with tarfile.open(fileobj=BytesIO(cli.pack_task_source(d)), mode="r:gz") as tar:
        assert sorted(tar.getnames()) == ["Taskfile"]


@pytest.mark.tier1
def test_push_sends_the_wiki_once_and_remembers_its_version(pool: _Pool, tmp_path: Path) -> None:
    env, d = _env(tmp_path), _folder(tmp_path)
    client = _client(pool, env)
    io, out = _io()
    cli._push_wiki(client, "bob/lab", d, io, "первая")           # noqa: SLF001
    assert _head(pool) == 1 and cli._wiki_base(d, pool.url) == 1            # noqa: SLF001
    assert "wiki: версия 1" in "".join(out)
    cli._push_wiki(client, "bob/lab", d, io, "")                  # noqa: SLF001
    assert _head(pool) == 1 and "wiki без изменений" in "".join(out)


@pytest.mark.tier1
def test_a_folder_without_a_wiki_stays_silent(pool: _Pool, tmp_path: Path) -> None:
    env = _env(tmp_path)
    d = tmp_path / "bare"
    d.mkdir()
    io, out = _io()
    cli._push_wiki(_client(pool, env), "bob/lab", d, io, "")    # noqa: SLF001
    assert out == [] and RemoteRegistry(pool.url).wiki_get("bob/lab", token=pool.tok["bob"]) is None


@pytest.mark.tier1
def test_a_browser_edit_of_the_same_page_stops_the_wiki_not_the_task(pool: _Pool, tmp_path: Path) -> None:
    env, d = _env(tmp_path), _folder(tmp_path)
    client = _client(pool, env)
    io, out = _io()
    cli._push_wiki(client, "bob/lab", d, io, "")                  # noqa: SLF001
    _http("POST", f"{pool.url}/wiki/bob/lab?base=1", token=pool.tok["bob"],
          data=pack({"wiki.md": b"# Lab from the site\n", "wiki/more.md": b"# More\n"}))
    (d / "wiki.md").write_text("# Lab, local edit\n", encoding="utf-8")
    cli._push_wiki(client, "bob/lab", d, io, "")                  # noqa: SLF001
    said = "".join(out)
    assert "правили после твоей версии" in said and "wiki.md" in said and "hashpass clone bob/lab" in said
    assert _head(pool) == 2 and cli._wiki_base(d, pool.url) == 1  # noqa: PLR2004, SLF001


@pytest.mark.tier1
def test_clone_into_the_working_folder_merges_and_the_next_push_goes(pool: _Pool, tmp_path: Path) -> None:
    env, d = _env(tmp_path), _folder(tmp_path)
    client = _client(pool, env)
    io, out = _io()
    cli._push_wiki(client, "bob/lab", d, io, "")                  # noqa: SLF001
    _http("POST", f"{pool.url}/wiki/bob/lab?base=1", token=pool.tok["bob"],
          data=pack({"wiki.md": b"# Lab from the site\n", "wiki/more.md": b"# More\n"}))
    (d / "wiki" / "more.md").write_text("# More, local\n", encoding="utf-8")
    assert cli.cmd_source(env, "bob/lab:1", str(d), pool.url, io=io) == 0
    assert (d / "wiki.md").read_text(encoding="utf-8") == "# Lab from the site\n"
    assert (d / "wiki" / "more.md").read_text(encoding="utf-8") == "# More, local\n"
    assert (d / "Taskfile").read_text(encoding="utf-8") == "stage\n" and cli._wiki_base(d, pool.url) == 2  # noqa: PLR2004, SLF001
    assert "wiki обновлена до версии 2" in "".join(out)
    cli._push_wiki(client, "bob/lab", d, io, "")                  # noqa: SLF001
    assert _head(pool) == 3  # noqa: PLR2004


@pytest.mark.tier1
def test_clone_puts_the_pool_page_aside_when_both_sides_edited_it(pool: _Pool, tmp_path: Path) -> None:
    env, d = _env(tmp_path), _folder(tmp_path)
    client = _client(pool, env)
    io, _out = _io()
    cli._push_wiki(client, "bob/lab", d, io, "")                  # noqa: SLF001
    _http("POST", f"{pool.url}/wiki/bob/lab?base=1", token=pool.tok["bob"],
          data=pack({"wiki.md": b"# site\n", "wiki/more.md": b"# More\n"}))
    (d / "wiki.md").write_text("# mine\n", encoding="utf-8")
    # review 2026-11-03: the clone must lead out of the conflict -- mine stays, the pool's lies aside,
    # the base moves on, so the next push goes
    assert cli.cmd_source(env, "bob/lab:1", str(d), pool.url, io=io) == 0
    said = "".join(_out)
    assert "wiki.md" in said and ".hashpass-wiki-pool" in said
    assert (d / "wiki.md").read_text(encoding="utf-8") == "# mine\n"
    assert (d / ".hashpass-wiki-pool" / "wiki.md").read_text(encoding="utf-8") == "# site\n"
    assert cli._wiki_base(d, pool.url) == 2  # noqa: PLR2004, SLF001
    with tarfile.open(fileobj=BytesIO(cli.pack_task_source(d)), mode="r:gz") as tar:
        assert not any(n.startswith(".hashpass-wiki-pool") for n in tar.getnames())
    cli._push_wiki(client, "bob/lab", d, io, "")                  # noqa: SLF001
    assert _head(pool) == 3  # noqa: PLR2004


@pytest.mark.tier1
def test_a_never_cloned_folder_cannot_overwrite_a_pool_wiki(pool: _Pool, tmp_path: Path) -> None:
    env = _env(tmp_path)
    client = _client(pool, env)
    io, out = _io()
    cli._push_wiki(client, "bob/lab", _folder(tmp_path, "first"), io, "")              # noqa: SLF001
    cli._push_wiki(client, "bob/lab", _folder(tmp_path, "other", main="# other\n"), io, "")  # noqa: SLF001
    assert _head(pool) == 1 and "скачай изменения" in "".join(out)


@pytest.mark.tier1
def test_a_proposal_push_does_not_send_the_wiki(pool: _Pool, tmp_path: Path) -> None:
    env, d = _env(tmp_path, "eve"), _folder(tmp_path)
    io, out = _io()
    cli._push_wiki(_client(pool, env, "eve"), "bob/lab", d, io, "", proposal=True)  # noqa: SLF001
    assert "wiki не отправлена" in "".join(out)
    assert RemoteRegistry(pool.url).wiki_get("bob/lab", token=pool.tok["bob"]) is None


@pytest.mark.tier1
def test_each_pool_keeps_its_own_wiki_version_in_the_folder(pool: _Pool, tmp_path: Path) -> None:
    # pushing the same folder to two pools: the version one pool gave says nothing about the other
    d = _folder(tmp_path)
    cli._set_wiki_base(d, "https://other.example:8080", 7)       # noqa: SLF001
    io, _out = _io()
    cli._push_wiki(_client(pool, _env(tmp_path)), "bob/lab", d, io, "")  # noqa: SLF001
    assert cli._wiki_base(d, pool.url) == 1                       # noqa: SLF001
    assert cli._wiki_base(d, "https://other.example:8080") == 7  # noqa: PLR2004, SLF001
