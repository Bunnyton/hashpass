"""Student TUI menu + self-check: local-solved vs server-credited status, and push auto-attach."""
import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.catalog import Catalog, CatalogEntry
from hashpass.registry.creds import CredentialCache
from hashpass.registry.remote import RemoteRegistry


def _env(tmp_path) -> cli.Home:
    return cli.build_env({"HASHPASS_HOME": str(tmp_path / "h")}, default_home=tmp_path)


@pytest.mark.tier1
def test_solved_store_roundtrip(tmp_path):
    env = _env(tmp_path)
    assert cli.load_solved(env) == {}
    cli.mark_solved(env, "lab:1")
    assert "lab:1" in cli.load_solved(env)
    assert "lab:1" in cli.load_solved(env)   # persisted across reads


@pytest.mark.tier1
def test_status_badge_and_menu_render():
    assert "зачтено" in cli._status_badge({"server": "passed"})            # noqa: SLF001
    assert "решено" in cli._status_badge({"server": None, "local": True})  # noqa: SLF001
    assert "не начато" in cli._status_badge({"server": None, "local": False})  # noqa: SLF001
    assert "недоступно" in cli._status_badge({"available": False, "server": "passed"})  # noqa: SLF001
    rows = [{"number": 1, "title": "Первое", "local": True, "server": None},
            {"number": 2, "title": "Второе", "local": False, "server": "passed"}]
    menu = cli._render_pool_menu(rows, "stud")   # noqa: SLF001
    assert "Первое" in menu
    assert "Второе" in menu
    assert "stud" in menu


@pytest.mark.tier1
def test_next_number_prefers_uncredited_ahead():
    rows = [{"number": 1, "server": "passed"}, {"number": 2, "server": None},
            {"number": 3, "server": None}]
    # after 1 -> first uncredited ahead (2); after 2 -> 3; after 3 -> wrap to first uncredited (2)
    assert [cli._next_number(rows, after=a) for a in (1, 2, 3)] == [2, 3, 2]  # noqa: SLF001
    assert cli._next_number([{"number": 1, "server": "passed"}], after=1) is None  # noqa: SLF001


@pytest.mark.tier1
def test_set_taskfile_path_roundtrip(tmp_path):
    store = ImageStore(tmp_path / "img")
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("x", encoding="utf-8")
    store.save("u/lab", "1", src, ())
    assert store.get("u/lab:1").taskfile_path is None
    store.set_taskfile_path("u/lab:1", "/home/a/Taskfile")
    assert store.get("u/lab:1").taskfile_path == "/home/a/Taskfile"


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list = []

    def push_attachment(self, name, version, filename, blob, *, taskfile=False, token=None) -> None:  # noqa: PLR0913, ARG002
        self.calls.append((name, version, filename, blob, taskfile))


@pytest.mark.tier1
def test_attach_taskfile_uploads_when_present(tmp_path):
    env = _env(tmp_path)
    store = ImageStore(env.images)
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("x", encoding="utf-8")
    store.save("u/lab", "1", src, ())
    tf = tmp_path / "Taskfile"
    tf.write_text("stage one\n", encoding="utf-8")
    store.set_taskfile_path("u/lab:1", str(tf))
    client = _FakeClient()
    out: list[str] = []
    io = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    cli._attach_taskfile(client, store, "u/lab:1", io)   # noqa: SLF001
    assert client.calls == [("u/lab", "1", "Taskfile", b"stage one\n", True)]
    assert "прикреплён Taskfile" in "".join(out)


@pytest.mark.tier1
def test_attach_taskfile_reports_absence(tmp_path):
    env = _env(tmp_path)
    store = ImageStore(env.images)
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("x", encoding="utf-8")
    store.save("u/lab", "1", src, ())
    store.set_taskfile_path("u/lab:1", str(tmp_path / "gone" / "Taskfile"))
    client = _FakeClient()
    out: list[str] = []
    io = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "")
    cli._attach_taskfile(client, store, "u/lab:1", io)   # noqa: SLF001
    assert client.calls == []
    assert "можете приложить файлы" in "".join(out)


@pytest.mark.tier2
def test_pool_status_local_vs_server(registry, tmp_path):
    env = _env(tmp_path)
    c = RemoteRegistry(registry.base_url, cache=CredentialCache(env.creds))
    tok = c.register("stud", "pass123!", group="G")
    Catalog(registry.catalog_path).put(CatalogEntry(1, "lab", "1", "One", "d1"))
    Catalog(registry.catalog_path).put(CatalogEntry(2, "lab2", "1", "Two", "d2"))
    cli.mark_solved(env, "lab:1")                          # solved locally only
    c.submit("lab2:1", "d2", passed=True, token=tok)       # credited on the server only
    rows = {r["number"]: r for r in cli.pool_status(env, registry.base_url, tok, "stud")}
    assert rows[1]["local"] is True and rows[1]["server"] is None
    assert rows[2]["local"] is False and rows[2]["server"] == "passed"


@pytest.mark.tier1
def test_run_from_menu_offers_next_until_done(tmp_path, monkeypatch):
    env = _env(tmp_path)
    ran: list[str] = []
    monkeypatch.setattr(cli, "cmd_pool_run", lambda _env, arg, _io=None: ran.append(arg) or 0)
    statuses = iter([
        [{"number": 1, "server": None}, {"number": 2, "server": None}],   # after task 1 -> next 2
        [{"number": 1, "server": "passed"}, {"number": 2, "server": "passed"}],  # after 2 -> done
    ])
    monkeypatch.setattr(cli, "pool_status", lambda *_a, **_k: next(statuses))
    out: list[str] = []
    answers = iter([""])   # Enter = accept the offered next task
    io = cli.Io(read=lambda _p: next(answers), write=out.append, clock=lambda: "")
    cli._run_from_menu(env, "http://p", "stud", "tok", 1, io)   # noqa: SLF001
    assert ran == ["1", "2"]
    assert "зачтены" in "".join(out)


@pytest.mark.tier1
def test_menu_loop_rejects_bad_number_then_quits(tmp_path, monkeypatch):
    env = _env(tmp_path)
    monkeypatch.setattr(cli, "_require_pool_identity", lambda _e, _io: ("http://p", "stud"))
    monkeypatch.setattr(cli, "_pool_token", lambda _e, _u: "tok")
    monkeypatch.setattr(cli, "pull_new", lambda *_a, **_k: (0, 0))
    monkeypatch.setattr(cli, "pool_status",
                        lambda *_a, **_k: [{"number": 1, "title": "T", "local": False, "server": None}])
    ran: list[str] = []
    monkeypatch.setattr(cli, "cmd_pool_run", lambda *_a, **_k: ran.append("x") or 0)
    out: list[str] = []
    answers = iter(["7", "q"])   # 7 is not a listed number -> rejected, then quit
    io = cli.Io(read=lambda _p: next(answers), write=out.append, clock=lambda: "")
    assert cli.cmd_pool_home(env, io) == 0
    assert ran == []
    assert "нет такого номера" in "".join(out)
