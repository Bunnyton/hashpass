import base64
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashengine import cli as engine_cli
from hashpass import cli, student_cli
from hashpass.imagestore.store import ImageStore
from hashpass.progress import current_stage, mark_passed_local, new_progress
from hashpass.recipe.model import Recipe
from hashpass.recipe.parse import parse_recipe
from hashpass.taskrun import FeedResult

_FAKE_RUN_EXIT = 7


@pytest.mark.tier1
def test_rebase_paths_resolves_relative_to_taskfile_dir():
    r = parse_recipe("image t:1\ncopy welcome.txt /opt/w\nhidden hp\nreadme README.md\nrun echo hi\n")
    out = cli._rebase_paths(r, Path("/task/dir"))  # noqa: SLF001
    assert [s.src for s in out.steps if hasattr(s, "src")] == ["/task/dir/welcome.txt"]
    assert out.hidden == "/task/dir/hp"
    assert out.readme == "/task/dir/README.md"
    assert cli._rebase_paths(replace(r, hidden="/abs/hp"), Path("/task/dir")).hidden == "/abs/hp"  # noqa: SLF001


@pytest.mark.tier1
def test_strip_terminal_cleans_ansi_and_cr():
    raw = "\x1b[32mERROR\x1b[0m one\r\nok\r\n\x1b[1mtwo\x1b[0m"
    assert cli._strip_terminal(raw) == "ERROR one\nok\ntwo"  # noqa: SLF001


@pytest.mark.tier1
def test_strip_terminal_drops_charset_escapes_and_lone_cr():
    # A REAL fish output fragment: charset-designation `ESC ( B` around colors, and `\r3\r\n`
    # (cursor-return + CRLF). Both used to leak -- `(B` garbage and a spurious leading newline --
    # and broke strict output grading. Cleaned it is exactly "3\n".
    raw = "\x1b[30m\x1b(B\x1b[m\r3\r\n"
    assert cli._strip_terminal(raw) == "3\n"  # noqa: SLF001


@pytest.mark.tier1
def test_extract_output_isolates_stdout_via_osc133():
    # fish wraps a command's output in OSC 133 ;C (output starts) .. ;D (done); extraction returns
    # just that stdout -- prompt + echoed command excluded -- so output grading is strict. This
    # sample mirrors real fish 4.x: `;C;cmdline_url=...`, a title OSC, `\x1b(B`, and `\r3\r\n`.
    d = ("\x1b]133;A;special_key=1\x07\x1b[94m~ \x1b[92m❯ \x1b(B\x1b[mgrep -c ERROR f\r\n"
         "\x1b]133;C;cmdline_url=grep\x07\x1b[?2004l\x1b]0;grep ~\x07"
         "\x1b[30m\x1b(B\x1b[m\r3\r\n\x1b]133;D;0\x07~ ❯ ")
    assert cli._extract_output(d) == "3\n"  # noqa: SLF001
    assert cli._extract_output("plain out\n") == "plain out\n"  # no marks -> cleaned whole  # noqa: SLF001


@pytest.mark.tier1
def test_parse_cmd_request_decodes_command_and_cleans_output():
    cmd = base64.b64encode("grep ERROR log".encode()).decode()
    out = base64.b64encode("\x1b[31mERROR here\x1b[0m\r\n".encode()).decode()
    command, output = cli._parse_cmd_request(f"cmd {cmd} {out}")  # noqa: SLF001
    assert command == "grep ERROR log"
    assert "ERROR here" in output
    assert "\x1b" not in output                                # ANSI stripped for matching
    assert cli._parse_cmd_request(f"cmd {cmd}") == ("grep ERROR log", "")  # noqa: SLF001


@pytest.mark.tier1
def test_resolve_root_prefers_env_then_default_home(tmp_path):
    assert cli.resolve_root({"HASHPASS_HOME": "/x/y"},
                            default_home=tmp_path) == __import__("pathlib").Path("/x/y")
    assert cli.resolve_root({}, default_home=tmp_path) == tmp_path / ".hashpass"


@pytest.mark.tier1
def test_home_sub_paths():
    h = cli.Home(Path("/home/u/.hashpass"))
    assert h.images == Path("/home/u/.hashpass/images")
    assert h.base_tar == Path("/home/u/.hashpass/base/rootfs.tar")
    assert h.creds == Path("/home/u/.hashpass/creds.json")
    assert h.work == Path("/home/u/.hashpass/work")


@pytest.mark.tier1
def test_build_env_creates_images_dir(tmp_path):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    assert env.images.is_dir()


@pytest.mark.tier1
def test_ensure_base_tar_returns_existing(tmp_path):
    dest = tmp_path / "rootfs.tar"
    dest.write_text("x", encoding="utf-8")
    assert cli.ensure_base_tar(dest) == dest       # present -> returned, no build


@pytest.mark.tier1
def test_ensure_base_tar_missing_raises_with_hint(tmp_path):
    dest = tmp_path / "base" / "rootfs.tar"
    with pytest.raises(RuntimeError, match="базовый rootfs не найден"):
        cli.ensure_base_tar(dest)                  # absent -> clear error (hashpass never builds it)


def _seed_image(store: ImageStore, tmp_path, name: str, *, task: bool = False) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, "1", src, ())
    if task:
        (store.get(f"{name}:1").layer.parent / "task").mkdir()


@pytest.mark.tier1
def test_format_image_rows_empty_is_header_only():
    assert cli.format_image_rows([]) == "REF  KIND\n"


@pytest.mark.tier1
def test_format_image_rows_aligns_columns():
    out = cli.format_image_rows([("log-archive:1", "task"), ("base:latest", "image")])
    assert out == ("REF            KIND\n"
                   "log-archive:1  task\n"
                   "base:latest    image\n")


@pytest.mark.tier1
def test_kind_detects_task_vs_image(tmp_path):
    store = ImageStore(tmp_path / "images")
    _seed_image(store, tmp_path, "base")
    _seed_image(store, tmp_path, "lab", task=True)
    assert cli._kind(store, "lab:1") == "task"  # noqa: SLF001
    assert cli._kind(store, "base:1") == "image"  # noqa: SLF001


@pytest.mark.tier1
def test_cmd_images_prints_table(tmp_path, capsys):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    store = ImageStore(env.images)
    _seed_image(store, tmp_path, "base")
    _seed_image(store, tmp_path, "lab", task=True)
    assert cli.cmd_images(env) == 0
    out = capsys.readouterr().out
    assert out == cli.format_image_rows([("base:1", "image"), ("lab:1", "task")])


@pytest.mark.tier1
@pytest.mark.parametrize(
    ("text", "expected"),
    [("1", 0), ("3", 2), ("  2 ", 1), ("0", None), ("4", None),
     ("", None), (None, None), ("x", None)],
)
def test_select_index(text, expected):
    assert cli.select_index(text, 3) == expected


class _FakeSession:
    """A container-free stand-in for TaskSession: real progress, scripted outcomes, a sink."""

    def __init__(self, task_id: str, n_stages: int, script: dict, sink) -> None:
        self.task_id = task_id
        self.progress = new_progress(task_id, n_stages)
        self._script = script            # command -> "advance" | ("hint", text)
        self._sink = sink
        self.entered = 0

    def enter(self) -> list:
        self.entered += 1
        self._sink("<hello>\n")
        return []

    def feed(self, command: str, *, ts: str) -> FeedResult:  # noqa: ARG002
        stage = current_stage(self.progress)
        outcome = self._script.get(command)
        if outcome == "advance":
            mark_passed_local(self.progress, stage)
            return FeedResult(advanced=True, stage=stage, local_key=f"key{stage}")
        if isinstance(outcome, tuple):
            self._sink(outcome[1] + "\n")   # the real Renderer types the hint here
            return FeedResult(advanced=False, stage=stage, local_key=None, hint=outcome[1])
        return FeedResult(advanced=False, stage=stage, local_key=None)


@pytest.mark.tier1
def test_interact_solves_with_hint_and_completion():
    writes, sinks, prompts = [], [], []
    session = _FakeSession("demo", 2,
                           {"solve0": "advance", "solve1": "advance", "bad": ("hint", "try grep")},
                           sinks.append)
    lines = iter(["bad", "solve0", "solve1"])
    cli.interact(session, read=lambda p: prompts.append(p) or next(lines),
                 write=writes.append, clock=lambda: "2026-01-01T00:00:00")
    assert session.entered == 1
    assert prompts == ["hashpass:demo [stage 1/2]$ ",
                       "hashpass:demo [stage 1/2]$ ",
                       "hashpass:demo [stage 2/2]$ "]
    assert "<hello>\n" in sinks
    assert "try grep\n" in sinks                       # hint reached the sink, not double-printed
    assert writes == []                                # no forced pass/complete phrase; progress shows in the prompt


@pytest.mark.tier1
@pytest.mark.parametrize("stopper", ["exit", None])
def test_interact_stops_on_stop_word_and_eof(stopper):
    writes = []
    session = _FakeSession("t", 1, {}, lambda _s: None)
    cli.interact(session, read=lambda _p: stopper, write=writes.append, clock=lambda: "t")
    assert session.entered == 1
    assert writes == []


@pytest.mark.tier1
def test_cmd_run_unknown_ref_reports_and_exits_1(tmp_path):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    out = []
    io = cli.Io(read=lambda _p: None, write=out.append, clock=lambda: "t")
    assert cli.cmd_run(env, "ghost:1", io) == 1
    assert out == ["no such image: ghost:1\n"]


@pytest.mark.tier1
def test_engine_parser_args():
    p = engine_cli.build_parser()
    assert p.parse_args(["build", "T"]).taskfile == "T"
    assert p.parse_args(["build", "T", "-t", "n:1"]).tag == "n:1"
    assert p.parse_args(["build", "T"]).tag is None
    assert p.parse_args(["images"]).command == "images"
    assert p.parse_args(["login", "http://h"]).registry == "http://h"
    assert p.parse_args(["login"]).registry is None      # registry optional (uses the saved one)
    assert p.parse_args(["remote"]).command == "remote"
    assert p.parse_args(["pull", "x:1"]).ref == "x:1"
    a = p.parse_args(["push", "x:1", "http://h"])
    assert (a.ref, a.registry) == ("x:1", "http://h")
    assert p.parse_args(["push", "x:1"]).registry is None
    serve_port = 9000
    s = p.parse_args(["serve", "--host", "0.0.0.0", "--port", str(serve_port)])  # noqa: S104
    assert (s.host, s.port) == ("0.0.0.0", serve_port)  # noqa: S104
    assert p.parse_args(["serve"]).host is None    # defaults resolved in cmd_serve
    assert p.parse_args(["serve", "--reset-admin"]).reset_admin is True
    assert p.parse_args([]).command is None


@pytest.mark.tier1
def test_student_parser_args():
    p = student_cli.build_parser()
    assert p.parse_args(["run", "3"]).task == "3"
    assert p.parse_args(["run", "lab:1"]).task == "lab:1"
    assert p.parse_args(["register", "--pool", "http://p"]).pool == "http://p"
    assert p.parse_args(["login"]).pool is None
    assert p.parse_args(["pull"]).command == "pull"
    assert p.parse_args([]).command is None


@pytest.mark.tier1
def test_main_images_dispatch(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HASHPASS_HOME", str(home))
    store = ImageStore(home / "images")
    _seed_image(store, tmp_path, "base")
    _seed_image(store, tmp_path, "lab", task=True)
    assert engine_cli.main(["images"]) == 0
    assert capsys.readouterr().out == cli.format_image_rows([("base:1", "image"), ("lab:1", "task")])


@pytest.mark.tier1
def test_task_mode_empty_message(tmp_path, capsys):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    assert cli.task_mode(env) == 0
    assert "no tasks built yet" in capsys.readouterr().out


@pytest.mark.tier1
def test_task_mode_lists_and_dispatches_pick(tmp_path, monkeypatch):
    home = tmp_path / "home"
    store = ImageStore(home / "images")
    _seed_image(store, tmp_path, "alpha", task=True)
    _seed_image(store, tmp_path, "beta", task=True)
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    chosen = {}

    def fake_run(_env, ref, _io) -> int:
        chosen["ref"] = ref
        return _FAKE_RUN_EXIT

    monkeypatch.setattr(cli, "cmd_run", fake_run)
    listed = []
    io = cli.Io(read=lambda _p: "2", write=listed.append, clock=lambda: "t")
    assert cli.task_mode(env, io) == _FAKE_RUN_EXIT
    assert chosen["ref"] == "beta:1"                 # #2 of sorted [alpha, beta]
    assert listed == ["1. alpha:1\n", "2. beta:1\n"]


@pytest.mark.tier1
def test_main_reports_user_error_without_traceback(tmp_path, monkeypatch, capsys):
    # a missing/broken Taskfile must exit 1 with a clean message, never a traceback.
    monkeypatch.setenv("HASHPASS_HOME", str(tmp_path / "home"))
    assert engine_cli.main(["build", str(tmp_path / "nope.Taskfile")]) == 1
    assert capsys.readouterr().err.startswith("hashengine:")


@pytest.mark.tier1
def test_run_image_ensures_base_image(tmp_path, monkeypatch):
    # `run` must ensure the base IMAGE too (a pull transfers layers, not the base).
    home = tmp_path / "home"
    store = ImageStore(home / "images")
    _seed_image(store, tmp_path, "pulled")
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    seen = {}
    monkeypatch.setattr(cli, "ensure_base_image",
                        lambda _e, _s: seen.setdefault("ensured", True) or tmp_path)
    empty_upper = tmp_path / "empty-upper"
    empty_upper.mkdir()
    monkeypatch.setattr(cli, "run_image",
                        lambda *_a, **_k: SimpleNamespace(rootfs=tmp_path, rootfs_upper=empty_upper,
                                                          teardown=lambda: None))
    monkeypatch.setattr(cli.subprocess, "run", lambda *_a, **_k: None)
    io = cli.Io(read=lambda _p: None, write=lambda _s: None, clock=lambda: "t")
    assert cli._run_image(env, "pulled:1", store, io) == 0  # noqa: SLF001
    assert seen["ensured"]


@pytest.mark.tier1
def test_resolve_ref(tmp_path):
    named = Recipe("foo", "2", (), ())
    unnamed = Recipe("", "latest", (), ())
    tf = tmp_path / "myproj" / "Taskfile"
    tf.parent.mkdir(parents=True)
    tf.write_text("run echo hi\n", encoding="utf-8")
    assert cli.resolve_ref(named, "bar:3", tf) == ("bar", "3")           # -t wins
    assert cli.resolve_ref(named, "bar", tf) == ("bar", "latest")        # -t, default version
    assert cli.resolve_ref(named, None, tf) == ("foo", "2")              # recipe's own image name
    assert cli.resolve_ref(unnamed, None, tf) == ("myproj", "latest")    # else the Taskfile dir


@pytest.mark.tier3
def test_ensure_base_image_stores_debian_trixie(tmp_path, base_tar):
    # The single base image is built once from the provided rootfs, stored as `debian:trixie`, reused.
    home = tmp_path / "home"
    env = cli.build_env({"HASHPASS_HOME": str(home)}, default_home=tmp_path)
    env.base_tar.parent.mkdir(parents=True, exist_ok=True)
    env.base_tar.write_bytes(base_tar.read_bytes())     # rootfs provided out-of-band (no docker)
    store = ImageStore(env.images)
    layer = cli.ensure_base_image(env, store)
    assert "debian:trixie" in store.list()
    assert (layer / "lib/systemd/systemd").exists()
    assert (layer / "usr/bin/fish").exists()
    assert cli.ensure_base_image(env, store) == layer  # second call reuses, no rebuild


@pytest.mark.tier1
def test_render_observe_no_forced_phrase_completion_fires_outro(monkeypatch):
    # No forced "принято"/"завершено" text: completing fires the author's outro, advancing enters
    # the next stage; the host-side key is NEVER written to the console (nothing to copy/fake).
    def run(stage_left: int | None, key: str) -> str:
        writes: list[str] = []
        io = cli.Io(read=lambda _p: None, write=writes.append, clock=lambda: "t")
        session = SimpleNamespace(
            progress=object(),
            meta=SimpleNamespace(stages=[SimpleNamespace(message=f"goal {i}") for i in range(4)]),
            observe=lambda command, *, ts, output: FeedResult(  # noqa: ARG005
                advanced=True, stage=3, local_key=key),
            fire_outro=lambda: writes.append("<outro>"),
            enter=lambda: writes.append("<enter>"),
        )
        monkeypatch.setattr(cli, "current_stage", lambda _p: stage_left)
        cli._render_observe(session, "cmd", "out", io)  # noqa: SLF001
        return "".join(writes)

    done = run(None, "key{secret}")
    assert "принято" not in done and "выполнено" not in done   # no forced phrase
    assert "key{secret}" not in done and "Ключ" not in done    # key stays under the hood
    assert "<outro>" in done and "<enter>" not in done

    mid = run(2, "key{secret}")
    assert "принято" not in mid and "key{secret}" not in mid
    assert "<enter>" in mid and "<outro>" not in mid


@pytest.mark.tier1
def test_policy_reply_serializes_current_stage_policy(monkeypatch):
    session = SimpleNamespace(progress=object(), meta=SimpleNamespace(stages=[
        SimpleNamespace(allow=("grep", "awk", "wc"), deny=(), neutral=("ls", "cat")),
        SimpleNamespace(allow=(), deny=("rm",), neutral=()),
    ]))
    monkeypatch.setattr(cli, "current_stage", lambda _p: 0)
    assert cli._policy_reply(session) == "grep,awk,wc;;ls,cat\n"  # noqa: SLF001
    monkeypatch.setattr(cli, "current_stage", lambda _p: 1)
    assert cli._policy_reply(session) == ";rm;\n"                 # noqa: SLF001
    monkeypatch.setattr(cli, "current_stage", lambda _p: None)
    assert cli._policy_reply(session) == ""                       # noqa: SLF001
