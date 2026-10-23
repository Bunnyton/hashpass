"""Tier1: on an ARM machine hashpass makes the kernel run x86 programs (qemu) before a task boots."""
from pathlib import Path

import pytest

from hashpass.emulation import binfmt_ready, ensure_x86_emulation


def _say() -> tuple[list[str], object]:
    said: list[str] = []
    return said, said.append


@pytest.mark.tier1
def test_an_x86_machine_needs_nothing() -> None:
    said, write = _say()
    calls: list[list[str]] = []
    assert ensure_x86_emulation(write, machine=lambda: "x86_64", ready=lambda: False,
                                run=lambda a, **_k: calls.append(a)) is True
    assert calls == [] and said == []


@pytest.mark.tier1
def test_arm_installs_qemu_when_missing_and_checks_again() -> None:
    # User (2026-10-13): a student on ARM got «execv(/usr/lib/systemd/systemd…) failed: Exec format
    # error» -- the base is x86_64. «hashpass пусть устанавливает при запуске, если нужно».
    said, write = _say()
    calls: list[list[str]] = []
    state = {"ready": False}

    def run(argv: list[str], **_k: object) -> object:
        calls.append(argv)
        if "apt-get" in argv:
            state["ready"] = True
        return type("R", (), {"returncode": 0})()

    assert ensure_x86_emulation(write, machine=lambda: "aarch64", ready=lambda: state["ready"],
                                run=run, has_apt=lambda: True) is True
    assert any("apt-get" in c and "qemu-user-static" in c for c in calls)
    assert "aarch64" in "".join(said)


@pytest.mark.tier1
def test_arm_without_apt_says_what_to_do() -> None:
    said, write = _say()
    assert ensure_x86_emulation(write, machine=lambda: "aarch64", ready=lambda: False,
                                run=lambda _a, **_k: None, has_apt=lambda: False) is False
    assert "qemu-user-static" in "".join(said)


@pytest.mark.tier1
def test_binfmt_ready_wants_an_enabled_entry_with_the_fix_binary_flag(tmp_path) -> None:
    # In a container the interpreter must be opened in advance (flag F), or nspawn cannot use it.
    entry = tmp_path / "qemu-x86_64"
    assert binfmt_ready(entry) is False
    entry.write_text("enabled\ninterpreter /usr/libexec/qemu-binfmt/x86_64-binfmt-P\nflags: POCF\n")
    assert binfmt_ready(entry) is True
    entry.write_text("disabled\nflags: POCF\n")
    assert binfmt_ready(entry) is False
    entry.write_text("enabled\nflags: PO\n")
    assert binfmt_ready(entry) is False


def _policy(available: set[str]):  # noqa: ANN202
    """Fake `apt-cache policy` for a system where only `available` can be installed."""
    def out(pkgs: list[str]) -> str:
        return "".join(f"{p}:\n  Installed: (none)\n  Candidate: {'1.0' if p in available else '(none)'}\n"
                       for p in pkgs)
    return out


@pytest.mark.tier1
@pytest.mark.parametrize(("available", "want"), [
    ({"qemu-user", "qemu-user-binfmt"}, ["qemu-user", "qemu-user-binfmt"]),       # Debian 13, new Ubuntu
    ({"qemu-user-static", "binfmt-support"}, ["qemu-user-static", "binfmt-support"]),  # older
])
def test_arm_installs_the_package_set_this_system_has(available: set[str], want: list[str]) -> None:
    # A student: «E: Для пакета «qemu-user-static» не найден кандидат на установку» -- newer
    # releases split it into qemu-user + qemu-user-binfmt.
    _said, write = _say()
    calls: list[list[str]] = []
    state = {"ready": False}
    policy = _policy(available)

    def run(argv: list[str], **_k: object) -> object:
        calls.append(argv)
        if argv[:2] == ["apt-cache", "policy"]:
            return type("R", (), {"returncode": 0, "stdout": policy(argv[2:])})()
        if "install" in argv:
            state["ready"] = True
        return type("R", (), {"returncode": 0, "stdout": ""})()

    assert ensure_x86_emulation(write, machine=lambda: "aarch64", ready=lambda: state["ready"],
                                run=run, has_apt=lambda: True) is True
    installs = [c for c in calls if "install" in c]
    assert installs == [["sudo", "apt-get", "install", "-y", *want]]


@pytest.mark.tier1
def test_arm_refreshes_package_lists_when_nothing_is_found() -> None:
    _said, write = _say()
    calls: list[list[str]] = []
    state = {"updated": False, "ready": False}

    def run(argv: list[str], **_k: object) -> object:
        calls.append(argv)
        if argv[:2] == ["apt-cache", "policy"]:
            avail = {"qemu-user", "qemu-user-binfmt"} if state["updated"] else set()
            return type("R", (), {"returncode": 0, "stdout": _policy(avail)(argv[2:])})()
        if argv[-1] == "update":
            state["updated"] = True
        if "install" in argv:
            state["ready"] = True
        return type("R", (), {"returncode": 0, "stdout": ""})()

    assert ensure_x86_emulation(write, machine=lambda: "aarch64", ready=lambda: state["ready"],
                                run=run, has_apt=lambda: True) is True
    assert ["sudo", "apt-get", "update"] in calls


@pytest.mark.tier1
def test_an_emulated_console_gets_no_seccomp_and_a_relaxed_sandbox_for_every_service() -> None:
    """ARM MacBook, 2026-10-23: «запускается, но часть сервисов failed» -- qemu-user vs sandboxes."""
    from hashpass.emulation import nspawn_emulation_args  # noqa: PLC0415
    assert nspawn_emulation_args(machine=lambda: "x86_64") == []
    args = nspawn_emulation_args(machine=lambda: "aarch64")
    assert "--setenv=SYSTEMD_SECCOMP=0" in args
    binds = {a.split(":", 1)[1]: a.split("=", 1)[1].split(":", 1)[0] for a in args if a.startswith("--bind-ro=")}
    assert "/etc/systemd/system/service.d/hp-emulated.conf" in binds
    assert "/etc/systemd/system/multi-user.target.d/hp-emulated-report.conf" in binds   # not .wants
    for src in binds.values():
        assert Path(src).is_file()


@pytest.mark.tier1
def test_the_failed_services_report_is_read_back(tmp_path) -> None:
    from hashpass.emulation import failed_units  # noqa: PLC0415
    log = tmp_path / "var" / "log"
    log.mkdir(parents=True)
    (log / "hp-emulated-report.txt").write_text(
        "## failed units\nsystemd-journald.service loaded failed failed Journal\n"
        "foo.service loaded failed failed Foo\n## errors\nsomething\n", encoding="utf-8")
    assert failed_units(tmp_path) == ["systemd-journald.service", "foo.service"]
    assert failed_units(tmp_path / "nope") == []
