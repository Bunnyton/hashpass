"""Tier1: drive the real console rc in a pty with a fake hp-io -- what the host actually receives."""
import base64
import contextlib
import os
import stat
import threading
from pathlib import Path

import pytest

pexpect = pytest.importorskip("pexpect")

_RC = Path(__file__).resolve().parents[2] / "src" / "hashpass" / "runtime" / "etc" / "hp-bashrc"


def _fake_hp_io(tmp_path: Path) -> Path:
    """Write a stand-in for /usr/local/bin/hp-io that logs every request line and replies nothing."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "hp-io"
    shim.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$HP_IO_LOG"\n', encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return bindir


def _requests(log: Path) -> list[str]:
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        kind, _, rest = line.partition(" ")
        if kind == "cmd":
            out.append("cmd " + base64.b64decode(rest.split(" ")[0]).decode())
        else:
            out.append(kind)
    return out


@pytest.mark.tier1
def test_console_ships_only_the_students_commands(tmp_path):
    # The rc is sourced early (from /etc/bash.bashrc in the image); its DEBUG trap must not turn
    # the rest of the startup files into a phantom first command (an extra «try»), and the host
    # is greeted exactly once.
    log = tmp_path / "hp-io.log"
    log.touch()
    env = {**os.environ, "PATH": f"{_fake_hp_io(tmp_path)}:{os.environ['PATH']}",
           "HP_PORT": "1", "HP_IO_LOG": str(log), "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    _drive_and_check(str(_RC), env, log)


@pytest.mark.tier1
def test_startup_lines_after_the_rc_are_not_a_try(tmp_path):
    # In the image /etc/bash.bashrc sources the rc FIRST and the rest of the startup files
    # (skel ~/.bashrc: aliases, PS1 tweaks, command substitutions) run with the DEBUG trap already
    # installed. None of that may reach the host as a command.
    log = tmp_path / "hp-io.log"
    log.touch()
    rc = tmp_path / "bashrc"
    rc.write_text(f". {_RC}\nalias ls='ls --color=auto'\nHOSTTAG=$(hostname)\n"
                  "[ -f /nonexistent ] && . /nonexistent\ntrue\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{_fake_hp_io(tmp_path)}:{os.environ['PATH']}",
           "HP_PORT": "1", "HP_IO_LOG": str(log), "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    _drive_and_check(str(rc), env, log)


def _drive_and_check(rcfile: str, env: dict, log: Path) -> None:
    child = pexpect.spawn("bash", ["--rcfile", rcfile, "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 100))
    child.expect("❯")
    child.sendline("echo hi")
    child.expect("❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)
    reqs = _requests(log)
    assert reqs[0] == "hello"
    cmds = [r for r in reqs if r.startswith("cmd ")]
    assert cmds == ["cmd echo hi"], reqs                    # no `return`/startup-line phantom
    assert reqs.count("hello") == 1


@pytest.mark.tier1
def test_prompt_gets_a_solved_label_once_the_host_says_so(tmp_path):
    # User (2026-10-04): «в конце когда решили добавь в командную строку label [Решено]».
    log = tmp_path / "hp-io.log"
    log.touch()
    flag = tmp_path / "solved"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "hp-io"
    shim.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$HP_IO_LOG"\n'
                    '[ "$1" = state ] && [ -f "$HP_SOLVED" ] && echo solved\nexit 0\n',
                    encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "HP_PORT": "1",
           "HP_IO_LOG": str(log), "HP_SOLVED": str(flag), "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    child = pexpect.spawn("bash", ["--rcfile", str(_RC), "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 100))
    child.expect("❯")
    child.sendline("echo one")
    child.expect("❯")
    assert "Решено" not in child.before
    flag.touch()                                   # the host now reports the task as done
    child.sendline("echo two")
    child.expect(r"\[Решено\][^\n]*❯")
    child.sendline("echo three")                    # it stays
    child.expect(r"\[Решено\][^\n]*❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)
    assert [r for r in _requests(log) if r.startswith("cmd ")] == [
        "cmd echo one", "cmd echo two", "cmd echo three"]


def _policy_shim(tmp_path: Path, policy: str) -> Path:
    """Write an hp-io that answers `policy` with the given line (and logs everything else)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (tmp_path / "policy").write_text(policy + "\n", encoding="utf-8")
    shim = bindir / "hp-io"
    shim.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$HP_IO_LOG"\n'
                    '[ "$1" = policy ] && cat "$HP_POLICY"\nexit 0\n', encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return bindir


def _rule(base: str, mode: str, pattern: str, message: str) -> str:
    return base64.b64encode(f"{base}\x1f{mode}\x1f{pattern}\x1f{message}".encode()).decode()


@pytest.mark.tier1
def test_block_rules_refuse_commands_by_their_arguments(tmp_path):
    """`block` (cd only absolute, rm only with *, no sudo cat): refused commands do NOT run."""
    log = tmp_path / "hp-io.log"
    log.touch()
    work = tmp_path / "w"
    (work / "sub").mkdir(parents=True)
    (work / "keep.txt").write_text("x", encoding="utf-8")
    rules = ",".join([_rule("cd", "unless", "^cd +/", "no no no, mister fish!"),
                      _rule("rm", "unless", r"\*", "А где же звёздочка?"),
                      _rule("cat", "match", "^sudo ", "Сначала без sudo")])
    bindir = _policy_shim(tmp_path, f";;ls;{rules}")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "HP_PORT": "1",
           "HP_IO_LOG": str(log), "HP_POLICY": str(tmp_path / "policy"),
           "HOME": str(work), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    child = pexpect.spawn("bash", ["--rcfile", str(_RC), "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 120), cwd=str(work))
    child.expect("❯")
    child.sendline("cd sub")                              # relative -> refused, stays put
    child.expect("no no no, mister fish!")
    child.expect("❯")
    child.sendline("pwd")
    child.expect(str(work) + r"\r?\n")
    child.expect("❯")
    child.sendline(f"cd {work}/sub && pwd")               # absolute -> runs
    child.expect(str(work / "sub"))
    child.expect("❯")
    child.sendline(f"rm {work}/keep.txt")                 # no star -> refused, file survives
    child.expect("А где же звёздочка")
    child.expect("❯")
    assert (work / "keep.txt").exists()
    child.sendline("sudo cat /etc/hostname")              # sudo cat -> refused before sudo runs
    child.expect("Сначала без sudo")
    child.expect("❯")
    child.sendline(f"rm {work}/kee*")                     # with a star -> runs
    child.expect("❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)
    assert not (work / "keep.txt").exists()


_MARK = r"(?:\x01\x1b\]133;C\x07\x02)?"     # invisible «command output starts» marker


@pytest.mark.tier1
def test_refusal_looks_like_the_systems_talk(tmp_path):
    # User (2026-10-12), after «no no no, mister fish!» came out as plain command output: the
    # refusal is the system talking, so it gets the same blank line and cyan bar as hints.
    log = tmp_path / "hp-io.log"
    log.touch()
    rules = ",".join([_rule("cd", "unless", "^cd +/", "no no no, mister fish!")])
    bindir = _policy_shim(tmp_path, f";rm;;{rules}")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "HP_PORT": "1",
           "HP_IO_LOG": str(log), "HP_POLICY": str(tmp_path / "policy"),
           "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    child = pexpect.spawn("bash", ["--rcfile", str(_RC), "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 120), cwd=str(tmp_path))
    child.expect("❯")
    child.sendline("cd sub")
    child.expect(r"cd sub\r?\n" + _MARK + r"\r?\n\x1b\[36m│\x1b\[0m no no no, mister fish!\r?\n")
    child.expect("❯")
    child.sendline("rm nothing")                          # plain `deny` speaks the same way
    child.expect(r"rm nothing\r?\n" + _MARK + r"\r?\n\x1b\[36m│\x1b\[0m Команда «rm» запрещена\.\r?\n")
    child.expect("❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)


_HP_IO = Path(__file__).resolve().parents[2] / "src" / "hashpass" / "runtime" / "usr" / "local" / "bin" / "hp-io"


def _pager_host(answers: list[bytes]) -> tuple[int, threading.Thread]:
    """Run a one-shot fake host: reply with three pages split by 0x01 and record each pager answer."""
    import socket  # noqa: PLC0415
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(64)                                   # the request line
            for page in (b"page-one\n", b"page-two\n"):
                conn.sendall(page + b"\x01")
                answers.append(conn.recv(16))
                if answers[-1] == b"q":                     # skipped: the rest without pauses
                    break
            conn.sendall(b"page-three\n")
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return srv.getsockname()[1], t


@pytest.mark.tier1
def test_pager_answers_q_to_skip_the_rest():
    """hp-io: «q» at a page break tells the host to print the rest at once (no more pauses)."""
    answers: list[bytes] = []
    port, t = _pager_host(answers)
    child = pexpect.spawn("bash", [str(_HP_IO), "hello"], env={**os.environ, "HP_PORT": str(port)},
                          encoding="utf-8", timeout=10)
    child.expect("пропустить: q")
    child.sendline("q")
    child.expect("page-three")
    child.expect(pexpect.EOF)
    t.join(5)
    assert answers == [b"q"]


@pytest.mark.tier1
def test_pager_enter_goes_on_page_by_page():
    answers: list[bytes] = []
    port, t = _pager_host(answers)
    child = pexpect.spawn("bash", [str(_HP_IO), "hello"], env={**os.environ, "HP_PORT": str(port)},
                          encoding="utf-8", timeout=10)
    child.expect("пропустить: q")
    child.sendline("")
    child.expect("page-two")
    child.expect("пропустить: q")
    child.sendcontrol("c")                                 # Ctrl+C = skip, and hp-io survives it
    child.expect("page-three")
    child.expect(pexpect.EOF)
    t.join(5)
    assert answers == [b"x", b"q"]


@pytest.mark.tier1
def test_ctrl_c_while_typing_asks_the_host_to_skip():
    # User (2026-10-12): «пропуск теории — на Ctrl+C». While the host is still typing (no page
    # break yet), Ctrl+C sends «q» once; hp-io survives it, and a later page break the host may
    # still send is not waited on (the host already has its answer).
    import socket  # noqa: PLC0415
    import time  # noqa: PLC0415
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got: list[bytes] = []

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(64)
            conn.settimeout(0.05)
            for ch in "typing-slowly-" * 40:            # ~3 s of typing unless skipped
                conn.sendall(ch.encode())
                try:
                    data = conn.recv(16)
                except TimeoutError:
                    continue
                got.append(data)
                break
            conn.sendall(b"\x01" + b"the-rest\n")
            conn.settimeout(1)
            with contextlib.suppress(TimeoutError):
                got.append(conn.recv(16))                # must stay silent: nothing more to say
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    child = pexpect.spawn("bash", [str(_HP_IO), "hello"],
                          env={**os.environ, "HP_PORT": str(srv.getsockname()[1])},
                          encoding="utf-8", timeout=10)
    child.expect("typing-slowly-typing")
    time.sleep(0.2)
    child.sendcontrol("c")
    child.expect(pexpect.EOF)
    t.join(5)
    assert "the-rest" in child.before
    assert got == [b"q"]                                  # once, and nothing at the page break
    assert "пропустить" not in child.before
    assert "^C" not in child.before                       # the tty's ^C echo stays out of the text


@pytest.mark.tier1
def test_bash_inside_a_root_shell_does_not_replay_the_intro(tmp_path):
    # User (2026-10-12): `sudo su` (or `sudo su - root`), then /bin/bash -- the whole intro, theory
    # and goal came again. The root shell recovers the port from the port file (sudo scrubs the
    # env) and stays quiet, but its child bash inherited the port without HP_GREETED and greeted.
    log = tmp_path / "hp-io.log"
    log.touch()
    (tmp_path / "port").write_text("1\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{_fake_hp_io(tmp_path)}:{os.environ['PATH']}",
           "HP_IO_LOG": str(log), "HP_PORT_FILE": str(tmp_path / "port"),
           "HOME": str(tmp_path), "TERM": "dumb"}
    for k in ("HP_PORT", "HP_GREETED"):
        env.pop(k, None)                                  # what `sudo su` leaves of the env
    child = pexpect.spawn("bash", ["--rcfile", str(_RC), "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 100))
    child.expect("❯")
    child.sendline(f"bash --rcfile {_RC} -i")             # the student's /bin/bash in there
    child.expect("❯")
    child.sendline("exit")
    child.expect("❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)
    assert "hello" not in _requests(log)


@pytest.mark.tier1
def test_hp_io_passes_a_big_reply_byte_for_byte():
    # User (2026-10-12, a screenshot): the colour meme sometimes came out torn -- shifted rows,
    # bits of escape codes and Cyrillic in the middle. hp-io drained the stream with
    # `read -t 0.005 -N 65536`: a timed read can lose the byte in flight when its timer fires,
    # and a big reply arriving in uneven pieces hits that again and again.
    import random  # noqa: PLC0415
    import socket  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import time  # noqa: PLC0415
    rng = random.Random(7)
    cols = 80
    art = "".join(f"\x1b[38;2;{rng.randrange(256)};{rng.randrange(256)};{rng.randrange(256)}m▀"
                  + ("\n" if i % cols == cols - 1 else "") for i in range(6000)).encode()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(64)
            pos = 0
            while pos < len(art):
                step = rng.choice((1, 7, 300, 4096, 20000))
                conn.sendall(art[pos:pos + step])
                pos += step
                time.sleep(rng.choice((0, 0, 0.001, 0.004, 0.006)))
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    out = subprocess.run(["bash", str(_HP_IO), "hello"], capture_output=True, timeout=60, check=False,
                         env={**os.environ, "HP_PORT": str(srv.getsockname()[1])}).stdout
    t.join(5)
    assert out == art, f"{len(out)} bytes out of {len(art)}"


@pytest.mark.tier1
def test_keys_typed_during_a_reply_do_not_land_inside_it():
    # The torn meme (2026-10-12): keys pressed while ~80 KB of colour art streams were echoed by
    # the tty into the middle of escape codes -- rows shifted, garbage after. hp-io silences the
    # echo for the reply (the keys stay queued for the next prompt).
    import socket  # noqa: PLC0415
    import time  # noqa: PLC0415
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(64)
            for _ in range(30):
                conn.sendall(b"[ART]")
                time.sleep(0.03)
            conn.sendall(b"END\n")
        srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    child = pexpect.spawn("bash", [str(_HP_IO), "hello"],
                          env={**os.environ, "HP_PORT": str(srv.getsockname()[1])},
                          encoding="utf-8", timeout=10)
    child.expect(r"\[ART\]")
    child.send("zzz\r")                                     # impatient typing mid-reply
    child.expect("END")
    t.join(5)
    assert "zzz" not in child.before


@pytest.mark.tier1
def test_readme_asks_for_the_theory_and_is_not_a_try(tmp_path):
    # User (2026-10-13): «добавь команду readme, чтобы можно было вызвать теорию ещё раз». It asks
    # the host for the theory, is never shipped as a student command (no try, no hint) and works
    # even where only a few commands are allowed (ls-mv-cp).
    log = tmp_path / "hp-io.log"
    log.touch()
    bindir = _policy_shim(tmp_path, "cat;;;")                # allow: cat only
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "HP_PORT": "1",
           "HP_IO_LOG": str(log), "HP_POLICY": str(tmp_path / "policy"),
           "HOME": str(tmp_path), "TERM": "dumb"}
    env.pop("HP_GREETED", None)
    child = pexpect.spawn("bash", ["--rcfile", str(_RC), "-i"], env=env, encoding="utf-8",
                          timeout=10, dimensions=(24, 100), cwd=str(tmp_path))
    child.expect("❯")
    child.sendline("readme")
    child.expect("❯")
    child.sendline("exit")
    child.expect(pexpect.EOF)
    reqs = _requests(log)
    assert "readme" in reqs
    assert not [r for r in reqs if r.startswith("cmd ")], reqs
    assert "запрещена" not in child.before
