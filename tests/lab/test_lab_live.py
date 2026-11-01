"""
Tier3: a real lab -- build a Labfile, raise the network, check across machines (spec 2026-11-02).

Needs the scoped sudo and a built base image (the store copy under ~/.hashpass). Run with
TMPDIR=/var/tmp/hp-pytest: every console copies the base.
"""
from __future__ import annotations

import subprocess
import threading
import uuid
from pathlib import Path

import pytest

from hashpass import cli, machines
from hashpass.imagestore.store import ImageStore
from hashpass.taskrun import run_task

_LABFILE = """\
lab netlab:1

machine pc
  console
  build pc
  net lan 10.77.0.10/24
  gw 10.77.0.1

machine web
  build web
  net lan 10.77.0.20/24

machine router
  build router
  net lan 10.77.0.1/24
  net wan 192.168.77.1/24

machine db
  build web
  net wan 192.168.77.30/24
  gw 192.168.77.1

say "Сеть"

stage
  solve true
  check live on web grep -q pc /etc/hosts
"""


def _base() -> Path:
    root = Path.home() / ".hashpass" / "images" / "bunnyton" / "debian"
    layers = sorted((p / "layer" for p in root.glob("trixie*") if (p / "layer" / "usr/bin/systemd-socket-activate").exists()),
                    key=lambda p: p.stat().st_mtime)
    if not layers:
        pytest.skip("no built base image in ~/.hashpass")
    return layers[-1]


@pytest.fixture
def lab_ref(tmp_path, monkeypatch) -> tuple[cli.Home, str, Path]:
    base = _base()
    monkeypatch.setattr(cli, "ensure_base_image", lambda _env, _store, **_kw: base)
    monkeypatch.setattr(cli, "_author_identity", lambda _env, _io: "dev")
    monkeypatch.setenv("HASHPASS_POOL", "http://127.0.0.1:9")       # never the local service
    src = tmp_path / "src"
    for m, line in (("pc", "echo pc > /etc/hp-who"), ("web", "echo web > /etc/hp-who"),
                    ("router", "echo router > /etc/hp-who")):
        (src / m).mkdir(parents=True)
        (src / m / "Taskfile").write_text(f"run {line}\n", encoding="utf-8")
    (src / "Labfile").write_text(_LABFILE, encoding="utf-8")
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    assert cli.cmd_build(env, str(src)) == 0
    return env, "dev/netlab:1", base


def _alive() -> list[str]:
    out = subprocess.run(["machinectl", "list", "--no-legend"], capture_output=True, text=True,
                         check=False).stdout
    pid = str(__import__("os").getpid())
    return [line.split()[0] for line in out.splitlines() if f"-{pid}-" in line.split()[0]]


def _open(env: cli.Home, ref: str, base: Path, tmp_path: Path) -> tuple:
    store = ImageStore(env.images)
    session = run_task(ref, store, tmp_path / f"run-{uuid.uuid4().hex[:6]}", base=base,
                       student_id="s", nonce="n", sink=lambda _s: None, sleep=lambda _s: None)
    stop = threading.Event()
    port, thread = cli._grade_server(session, cli._Router(lambda _s: None), lambda: "t", stop,  # noqa: SLF001
                                     None, [], sockets=session.lab.sockets)
    thread.start()
    session.lab.start(port)
    console = machines.machine_name()
    session.student.boot(console, session.lab.console_args())
    session.student.live_machine = console
    return session, port, stop


@pytest.mark.tier3
def test_a_lab_builds_boots_wires_and_checks(lab_ref, tmp_path):
    env, ref, base = lab_ref
    store = ImageStore(env.images)
    layer = store.get(ref).layer
    assert store.get(ref).parents == ("dev/netlab.pc:1",)
    assert sorted(p.name for p in (layer / ".hp-nodes").iterdir()) == ["db", "lab.json", "router", "web"]
    session, port, stop = _open(env, ref, base, tmp_path)
    try:
        pc, web, router = session.student, session.nodes["web"], session.nodes["router"]
        assert pc.check_live("test ! -e /.hp-nodes && grep -qx pc /etc/hp-who") == 0
        assert web.check_live('grep -qx web /etc/hp-who && test "$(hostname)" = web') == 0
        assert session.nodes["db"].check_live("grep -qx web /etc/hp-who") == 0      # db reuses web/
        assert pc.check_live("ping -c1 -W3 web") == 0
        assert pc.check_live("ping -c1 -W3 10.77.0.20") == 0
        assert web.check_live(f"grep -qx {port} /run/hp/port") == 0
        # the relay: a machine's hooks reach the host over its own 127.0.0.1:$HP_PORT
        assert web.check_live(f"bash -c 'exec 3<>/dev/tcp/127.0.0.1/{port} && echo state >&3 && read -r -t 3 x <&3'") == 0
        assert pc.check_live(f"bash -c 'exec 3<>/dev/tcp/127.0.0.1/{port} && echo state >&3 && read -r -t 3 x <&3'") == 0
        # a router: two subnets, forwarding switched on by the student, NET_ADMIN inside
        assert router.check_live("ip link set eth1 down && ip link set eth1 up") == 0
        assert router.check_live("sysctl -w net.ipv4.ip_forward=1") == 0
        assert pc.check_live("ping -c1 -W3 192.168.77.30") == 0
        # the stage: `check live on web`
        assert session.observe("true", ts="2026-11-02T10:00:00").advanced is True
    finally:
        stop.set()
        session.teardown()
    assert _alive() == []


@pytest.mark.tier3
def test_two_labs_at_once_do_not_meet(lab_ref, tmp_path):
    env, ref, base = lab_ref
    a, _, stop_a = _open(env, ref, base, tmp_path)
    b, _, stop_b = _open(env, ref, base, tmp_path)
    try:
        assert a.student.check_live("ping -c1 -W3 web") == 0
        assert b.student.check_live("ping -c1 -W3 web") == 0
        assert a.nodes["web"].check_live("ip -br link | grep -c '^eth' | grep -qx 1") == 0
    finally:
        stop_a.set()
        stop_b.set()
        a.teardown()
        b.teardown()
    assert _alive() == []
