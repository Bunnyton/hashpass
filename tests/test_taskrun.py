"""Validate taskrun: neutral tries, idle/action helpers (tier1), and live sessions (tier3 e2e)."""
import pytest

from hashpass.handler import HandlerContext
from hashpass.imagestore.store import ImageStore
from hashpass.recipe.model import ExecAction, SayAction, Settings, ShowFileAction
from hashpass.recipe.parse import parse_recipe
from hashpass.render import Renderer
from hashpass.runner.nspawn import RunResult
from hashpass.taskbuild import build_task
from hashpass.taskrun import _elapsed, _is_neutral, perform_action, run_task

_DERIVED = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt
"""


@pytest.mark.tier3
def test_e2e_derived_stage_accepts_and_rejects(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_DERIVED), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    ts = "2026-08-31T00:00:00"
    session = run_task("logtask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        wrong = session.feed("echo nope > /errors.txt", ts=ts)
        assert wrong.advanced is False
        assert wrong.local_key is None
        right = session.feed("grep -rh ERROR /var/log/app > /errors.txt", ts=ts)
        assert right.advanced is True
        assert right.local_key is not None
    finally:
        session.teardown()


_CHECK = """\
image verifytask:1
hidden {hidden}

stage "create the flag"
  solve touch /done
  check exec verify.sh
"""


@pytest.mark.tier3
def test_e2e_check_exec_stage(tmp_path, base_tar):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    v = hidden / "verify.sh"
    v.write_text("#!/bin/sh\n[ -f /done ]\n", encoding="utf-8")
    v.chmod(0o755)
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_CHECK.format(hidden=hidden)), store, base_tar=base_tar,
               workdir=tmp_path / "bt")
    session = run_task("verifytask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        assert session.feed("ls /", ts="t").advanced is False       # /done absent -> verify exit 1
        assert session.feed("touch /done", ts="t").advanced is True  # now verify exit 0
    finally:
        session.teardown()


_SIDE = """\
image sidetask:1
hidden {hidden}

stage "write the marker"
  solve echo done > /marker
  observe /marker
  on enter exec seed.sh
  on pass  exec cheer.sh
"""


@pytest.mark.tier3
def test_e2e_on_enter_and_on_pass_fire(tmp_path, base_tar):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    for name, body in (("seed.sh", '#!/bin/sh\necho Welcome\necho enter >> "$HP_STATE"\n'),
                       ("cheer.sh", '#!/bin/sh\necho pass >> "$HP_STATE"\n')):
        p = hidden / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_SIDE.format(hidden=hidden)), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    session = run_task("sidetask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        greeting = session.enter()
        assert any("Welcome" in g for g in greeting)                 # on_enter stdout rendered
        state = (session.hp_dir / "state.json").read_text(encoding="utf-8")
        assert "enter" in state                                      # on_enter wrote rw /hp
        res = session.feed("echo done > /marker", ts="t")
        assert res.advanced is True
        state2 = (session.hp_dir / "state.json").read_text(encoding="utf-8")
        assert "pass" in state2                                      # on_pass fired after accept
    finally:
        session.teardown()


@pytest.mark.tier1
def test_is_neutral_and_unparseable_command_counts_as_try():
    assert _is_neutral("ls -la", ("ls", "cd")) is True
    assert _is_neutral("grep x f", ("ls", "cd")) is False
    # unbalanced quote makes shlex raise -> treated as a real try, never crashes feed
    assert _is_neutral('echo "oops', ("ls", "cd")) is False


class _FakeRunner:
    def __init__(self, out: str) -> None:
        self._out = out
        self.calls: list = []

    def run(self, argv: list[str], *, binds: object = None,
            setenv: object = None) -> RunResult:
        self.calls.append((argv, binds, setenv))
        return RunResult(self._out, "", 0)


_CTX = HandlerContext(student_cmd="grep x f", tries=1, last_out="", stage=0)


@pytest.mark.tier1
def test_elapsed_seconds_and_bad_ts():
    assert _elapsed("2026-08-31T00:00:00", "2026-08-31T00:01:30") == 90.0  # noqa: PLR2004
    # mixed tz-aware/naive would raise TypeError on subtraction -> idle stays neutral (0.0)
    assert _elapsed("2026-08-31T00:00:00", "2026-08-31T00:00:30+00:00") == 0.0
    assert _elapsed("not-a-ts", "2026-08-31T00:00:00") == 0.0


@pytest.mark.tier1
def test_perform_say_renders_and_returns(tmp_path):
    chunks: list[str] = []
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=lambda _s: None)
    out = perform_action(SayAction("hello there"), _CTX, render=r,
                         runner=_FakeRunner(""), hp_dir=tmp_path)
    assert out == "hello there"
    assert chunks == ["hello there"]


@pytest.mark.tier1
def test_perform_show_file_reads_hp_work(tmp_path):
    work = tmp_path / "work" / "art"
    work.mkdir(parents=True)
    (work / "ok.txt").write_text("nice job", encoding="utf-8")
    chunks: list[str] = []
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=lambda _s: None)
    out = perform_action(ShowFileAction("art/ok.txt"), _CTX, render=r,
                         runner=_FakeRunner(""), hp_dir=tmp_path)
    assert out == "nice job"
    assert chunks == ["nice job"]


@pytest.mark.tier1
def test_perform_exec_runs_handler_and_renders(tmp_path):
    chunks: list[str] = []
    r = Renderer(Settings(type_mode="instant"), sink=chunks.append, sleep=lambda _s: None)
    runner = _FakeRunner("HINT-OUT\n")
    out = perform_action(ExecAction("echo hi"), _CTX, render=r, runner=runner, hp_dir=tmp_path)
    assert out == "HINT-OUT\n"
    assert chunks == ["HINT-OUT\n"]
    argv, binds, _ = runner.calls[0]
    assert argv == ["sh", "-c", "echo hi"]        # command action -> sh -c
    assert binds == [(str(tmp_path), "/hp")]        # /hp bound for the handler run


_HINT_TASK = """\
image hinttask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

settings
  type-mode normal
  type-speed 2000

stage "collect ERROR lines (case-insensitive)"
  solve grep -rih ERROR /var/log/app > /errors.txt
  observe /errors.txt
  hint cmd grep missing -i say "add -i for case-insensitive 🔎"
  hint tries 2 say "peek in /var/log/app 👀"
"""


@pytest.mark.tier3
def test_e2e_dsl_hint_fires_and_renders(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_HINT_TASK), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    chunks: list[str] = []
    session = run_task("hinttask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1",
                       sink=chunks.append, sleep=lambda _s: None)
    try:
        # a case-sensitive grep (missing -i) does not match ERROR/error -> rejected, and the
        # first-match `cmd grep missing -i` hint fires and is rendered through the injected sink.
        res = session.feed("grep -rh error /var/log/app > /errors.txt",
                           ts="2026-08-31T00:00:00")
        assert res.advanced is False
        assert res.hint is not None
        assert "add -i" in res.hint
        # type-mode normal types char-by-char, so the hint spans many sink chunks;
        # the rendered STREAM (joined) carries it.
        assert "add -i" in "".join(chunks)
        # the reference solution (case-insensitive) is accepted
        ok = session.feed("grep -rih ERROR /var/log/app > /errors.txt",
                          ts="2026-08-31T00:00:05")
        assert ok.advanced is True
        assert ok.local_key is not None
    finally:
        session.teardown()
