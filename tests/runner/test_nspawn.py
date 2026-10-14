import pytest

from hashpass.runner.nspawn import NspawnRunner


@pytest.mark.tier3
def test_nspawn_run_and_persist(tmp_path, base_tar):
    r = NspawnRunner(tmp_path, base_tar=base_tar)
    r.prepare([])
    try:
        res = r.run(["sh", "-c", ". /etc/os-release; echo $ID; id -u"])
        assert res.exit_code == 0
        assert "debian" in res.stdout and "0" in res.stdout
        # /var/tmp is 1777 and root's default umask makes the new file 644,
        # so it's world-readable -- read it back directly from the host-side
        # upperdir. This proves the write actually landed in the overlay
        # upperdir specifically (a wrongly-wired upper= could still pass an
        # in-container-only check like `cat` through the mount).
        #
        # NOTE: this must be /var/tmp, not /tmp -- systemd-nspawn mounts a
        # private, ephemeral tmpfs over /tmp by default (confirmed via
        # `cat /proc/mounts` inside the container: `tmpfs /tmp tmpfs rw,...`),
        # so anything written to /tmp never reaches the overlay at all and
        # the direct upperdir read fails with FileNotFoundError. /var/tmp is
        # not on nspawn's private-mount list, so it round-trips through the
        # overlay like any other ordinary path (verified manually).
        r.run(["sh", "-c", "echo persisted > /var/tmp/p.txt"])
        assert (r.rootfs_upper / "var/tmp/p.txt").read_text(encoding="utf-8").strip() == "persisted"
    finally:
        r.teardown()


@pytest.mark.tier3
def test_nspawn_bind_and_setenv_are_per_run(tmp_path, base_tar):
    hp = tmp_path / "hp"
    hp.mkdir()
    (hp / "token.txt").write_text("SECRET", encoding="utf-8")
    r = NspawnRunner(tmp_path / "run", base_tar=base_tar)
    r.prepare([])
    try:
        # A run WITH the bind + env sees the file and the variable.
        res = r.run(
            ["sh", "-c", "cat /hp/token.txt; printf ':'; printf '%s' \"$HP_TRIES\""],
            binds=[(str(hp), "/hp")],
            setenv={"HP_TRIES": "3"},
        )
        assert res.exit_code == 0
        assert res.stdout.strip() == "SECRET:3"
        # A plain run right after does NOT see /hp (fresh mount-ns, no bind).
        res2 = r.run(["sh", "-c", "test -e /hp; echo $?"])
        assert res2.stdout.strip() == "1"
    finally:
        r.teardown()


@pytest.mark.tier1
def test_run_live_goes_through_the_booted_console_machine(tmp_path, monkeypatch):
    """The live console holds the student mount; `apply` must run INSIDE that machine."""
    import subprocess  # noqa: PLC0415

    from hashpass.runner import nspawn  # noqa: PLC0415
    calls: list[list[str]] = []
    monkeypatch.setattr(nspawn.subprocess, "run",
                        lambda argv, **_kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    r = NspawnRunner(tmp_path)
    r.live_machine = "hp-abc"
    assert r.run_live(["sh", "-c", "echo x > /home/student/f"]).exit_code == 0
    assert calls[-1][:6] == ["sudo", "machinectl", "shell", "hp-abc", "/bin/sh", "-c"]
    r.live_machine = None                                  # no console (build): plain run
    r.run_live(["true"])
    assert calls[-1][:2] == ["sudo", "systemd-nspawn"]


@pytest.mark.tier1
def test_run_live_script_survives_systemd_expansion(tmp_path, monkeypatch):
    """
    A live script reaches the machine with no `$` and still runs verbatim.

    `machinectl shell` lets systemd expand `${VAR}` in its arguments: `${at}a` reached the mc
    task's hide script as `a` (2026-10-14) and sed appended the password after EVERY line.
    """
    import subprocess  # noqa: PLC0415

    from hashpass.runner import nspawn  # noqa: PLC0415
    real_run = subprocess.run
    calls: list[list[str]] = []
    monkeypatch.setattr(nspawn.subprocess, "run",
                        lambda argv, **_kw: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    r = NspawnRunner(tmp_path)
    r.live_machine = "hp-abc"
    script = 'at=3; f="x y"; echo "${at}a $f $((at + 1))" > ' + str(tmp_path / "out")
    r.run_live(["sh", "-c", script])
    sent = calls[-1][4:]
    assert sent[:2] == ["/bin/sh", "-c"]
    assert not any("$" in a or "{" in a for a in sent)
    real_run(sent, check=True)                             # what the machine's /bin/sh would do
    assert (tmp_path / "out").read_text() == "3a x y 4\n"
