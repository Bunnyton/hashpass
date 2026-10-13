"""Tier1: on an ARM machine hashpass makes the kernel run x86 programs (qemu) before a task boots."""
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
