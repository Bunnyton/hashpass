"""Tier1: web dashboard HTML rendering (pure functions)."""
import shutil
import subprocess

import pytest

from hashpass.registry.web import (
    render_dashboard,
    render_engine_install_script,
    render_front,
    render_install_script,
    render_login,
    render_password_form,
    render_reset_form,
    render_reset_link,
    render_users,
)


@pytest.mark.tier1
def test_front_shows_install_command():
    html = render_front("http://pool.example/")
    assert "http://pool.example/install.sh" in html
    assert "curl -fsSL http://pool.example/install.sh" in html   # plain http: no -k
    assert "curl -fsSLk https://pool.example/install.sh" in render_front("https://pool.example/")  # self-signed


@pytest.mark.tier1
def test_front_has_one_install_command_and_no_manual_preparation():
    """One link (user 2026-10-23): the script itself checks and installs the dependencies."""
    html = render_front("http://pool.example/")
    assert html.count("/install.sh | bash") == 1
    assert "sudo apt install" not in html
    assert "pacman" not in html
    assert "hpcopy(this)" in html                                  # one-click copy


@pytest.mark.tier1
def test_install_script_brings_an_x86_emulator_on_other_architectures():
    """Tasks are x86_64 Debian: on arm64 the script installs qemu-user unless Rosetta is there."""
    script = render_install_script("http://pool.example/")
    assert 'ARCH="$(uname -m)"' in script
    assert "/proc/sys/fs/binfmt_misc/rosetta" in script
    assert "/proc/sys/fs/binfmt_misc/qemu-x86_64" in script
    assert 'P_QEMU="qemu-user-static binfmt-support"' in script            # Debian/Ubuntu
    assert 'P_QEMU="qemu-user-static qemu-user-static-binfmt"' in script   # Arch
    assert script.index('ARCH="$(uname -m)"') < script.index("ставлю недостающие пакеты")


@pytest.mark.tier1
def test_install_script_stops_on_macos_with_a_pointer_to_a_linux_vm():
    script = render_install_script("http://pool.example/")
    assert '"$(uname -s)" = Darwin' in script
    assert "UTM" in script


@pytest.mark.tier1
def test_login_form_and_error():
    assert "type='password'" in render_login()
    assert "class='err'" not in render_login()
    assert "плохо" in render_login("плохо")


@pytest.mark.tier1
def test_dashboard_rows_cells_and_group_filter():
    profiles = [
        {"user": "s1", "role": "student", "group": "ИУ7-31", "comment": "Иван"},
        {"user": "s2", "role": "student", "group": "ИУ7-32", "comment": "Пётр"},
        {"user": "author1", "role": "author", "group": "", "comment": "Автор"},
        {"user": "adm", "role": "admin", "group": "", "comment": "Админ"},
    ]
    entries = [{"number": 1, "ref": "lab:1", "title": "T1"},
               {"number": 2, "ref": "lab:2", "title": "T2"}]
    progress = {"s1": {"lab:1": {"status": "passed"}}, "s2": {"lab:1": {"status": "failed"}},
                "author1": {"lab:1": {"status": "passed"}}}
    html = render_dashboard(profiles, entries, progress)
    assert "Иван" in html
    assert "Пётр" in html
    assert "Автор" in html           # authors appear too (own `authors` group)
    assert "Админ" in html           # admins share the `authors` group
    assert "authors" in html         # synthetic group listed in dropdown
    assert "✓" in html
    assert "◐" in html               # a failed (digest-mismatch) record is still «выполняется»
    only31 = render_dashboard(profiles, entries, progress, group="ИУ7-31")
    assert "Иван" in only31
    assert "Пётр" not in only31
    assert "Автор" not in only31
    only_authors = render_dashboard(profiles, entries, progress, group="authors")
    assert "Автор" in only_authors
    assert "Админ" in only_authors
    assert "Иван" not in only_authors


@pytest.mark.tier1
def test_users_toggle_and_inline_controls():
    profiles = [{"user": "s1", "role": "student", "group": "G", "comment": ""}]
    html = render_users(profiles, registration_open=True, boxes=frozenset({"admins", "people"}))
    assert "Закрыть регистрацию" in html
    assert "Открыть регистрацию" in render_users(profiles, registration_open=False, boxes=frozenset({"people"}))
    assert "/web/users/role" in html          # «Сделать админом» (the `admins` box, 2026-10-25)
    assert "/web/users/reset" in html         # per-user reset link
    assert "ссылка сброса" in html


@pytest.mark.tier1
def test_users_self_row_has_no_role_or_delete():
    profiles = [{"user": "admin", "role": "admin", "group": "", "comment": ""},
                {"user": "s1", "role": "student", "group": "G", "comment": ""}]
    html = render_users(profiles, registration_open=True, current_user="admin", boxes=frozenset({"people"}))
    assert "/web/users/delete" in html   # a delete control exists (for s1)
    assert "вы" in html                  # the admin's own row shows "вы", not controls


@pytest.mark.tier1
def test_password_and_reset_forms():
    assert "Текущий пароль" in render_password_form()
    assert "спецсимвол" in render_password_form()          # the password-policy hint
    assert "class='err'" in render_password_form("плохо")
    assert "Пароль изменён" in render_password_form(done=True)
    assert "TOK" in render_reset_form("TOK")
    assert "спецсимвол" in render_reset_form("TOK")
    assert "http://p/web/reset" in render_reset_link("bob", "http://p/web/reset?token=x")


@pytest.mark.tier1
def test_install_script_targets_pool_and_pip():
    script = render_install_script("http://pool.example/")
    assert script.startswith("#!/usr/bin/env bash")
    assert 'POOL="http://pool.example"' in script
    assert "pip install --user" in script
    assert "git+https://" not in script                         # a full clone of the history is slow
    assert "https://github.com/Bunnyton/hashpass/archive/$SHA.tar.gz" in script
    assert "pool.json" in script
    # preflight installs every missing tool before the download; the pip line comes after
    for tool in ("python3", "python3 -m pip --version", "command -v git", "command -v curl",
                 "command -v machinectl"):
        assert tool in script
    assert script.index("ставлю недостающие пакеты") < script.index("pip install --user")


@pytest.mark.tier1
def test_engine_install_script_is_the_one_install_script():
    """One link everywhere: the old author link serves the same installer."""
    assert render_engine_install_script("http://p") == render_install_script("http://p")


@pytest.mark.tier1
@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_install_script_passes_shellcheck():
    script = render_install_script("http://pool.example")
    proc = subprocess.run(["shellcheck", "-s", "bash", "-"], input=script,
                          text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stdout


@pytest.mark.tier1
def test_install_script_puts_user_bin_on_path():
    """Ubuntu: ~/.local/bin is not on PATH after a first `pip --user` install -> persist it."""
    script = render_install_script("http://pool.example/")
    assert 'BIN="$("$PY" -m site --user-base)/bin"' in script
    assert 'add_line "$HOME/.bashrc" "$PATH_LINE"' in script
    assert 'add_line "$HOME/.profile" "$PATH_LINE"' in script
    assert 'add_line "$HOME/.zshrc" "$PATH_LINE"' in script        # zsh (Arch, macOS-style setups)
    assert "fish/conf.d/hashpass.fish" in script                       # fish has its own syntax
    assert "contains -- '$BIN' \\$PATH; or set -gx PATH '$BIN' \\$PATH" in script
    assert 'RC_HINT="source ~/.bashrc"' in script
    assert 'grep -q -- --break-system-packages && BSP="--break-system-packages"' in script


@pytest.mark.tier1
def test_install_script_names_packages_for_the_hosts_package_manager():
    """Arch: pacman + python-pip; Debian/Ubuntu: apt + python3-pip; systemd-nspawn is checked."""
    script = render_install_script("http://pool.example/")
    assert 'PKG_INSTALL="sudo pacman -Syu --needed --noconfirm"' in script   # no partial upgrade
    assert "P_PY=python; P_PIP=python-pip; P_NSPAWN=systemd" in script
    assert 'if ! $PKG_INSTALL$missing <"$TTY"; then' in script          # installs, not just hints
    assert 'PKG_INSTALL="sudo env DEBIAN_FRONTEND=noninteractive apt install -y"' in script
    assert "command -v systemd-nspawn" in script


@pytest.mark.tier1
def test_install_script_refreshes_apt_lists_before_install():
    """A fresh Debian/Ubuntu has stale lists -> `apt install` fails with «Unable to locate package»."""
    script = render_install_script("http://pool.example/")
    assert 'PKG_INSTALL="sudo apt update && sudo apt install -y"' not in script   # eval-free form
    assert 'PKG_REFRESH="sudo apt update"' in script
    assert script.index("$PKG_REFRESH") < script.index("$PKG_INSTALL$missing")


@pytest.mark.tier1
def test_install_script_retries_pip_trusting_hosts_on_self_signed():
    script = render_install_script("http://pool.example/")
    assert "PIP_TRUSTED_HOST=" in script
    for host in ("github.com", "codeload.github.com", "pypi.org", "files.pythonhosted.org"):
        assert host in script
    assert "http.sslVerify=false" in script          # git ls-remote behind the same proxy


@pytest.mark.tier1
def test_install_script_brings_python_313_when_the_system_one_is_older():
    """The package needs >=3.13; Ubuntu 22.04/24.04 and Debian 12 ship older -> the script fetches it."""
    script = render_install_script("http://pool.example/")
    assert "sys.version_info < (3, 13)" in script
    assert "ppa:deadsnakes/ppa" in script                  # Ubuntu
    assert "python3.13 python3.13-venv" in script
    assert "sudo dnf install -y python3.13" in script      # Fedora
    assert "python install 3.13" in script                 # anything else: uv's standalone CPython
    assert "ensurepip" in script
    assert "bootstrap.pypa.io/get-pip.py" in script
    # every pip/site call after the probe goes through the chosen interpreter
    tail = script[script.index('PY=""'):]
    assert "python3 -m" not in tail
    assert '"$PY" -m pip install --user' in tail
    assert 'BIN="$("$PY" -m site --user-base)/bin"' in tail


@pytest.mark.tier1
def test_front_page_does_not_mention_python_313():
    """Python 3.13 is the script's business only (user's call): the page lists plain packages."""
    assert "3.13" not in render_front("http://pool.example/")
    assert "deadsnakes" not in render_front("http://pool.example/")


@pytest.mark.tier1
def test_install_script_works_without_a_controlling_tty():
    """`ssh host 'curl … | bash'`, su -, CI: no /dev/tty -> `</dev/tty` must not abort the install."""
    script = render_install_script("http://pool.example/")
    assert script.count("</dev/tty") == 1                  # only the probe itself
    assert "TTY=/dev/tty; ( : </dev/tty ) 2>/dev/null || TTY=/dev/null" in script
    assert 'PKG_INSTALL="sudo env DEBIAN_FRONTEND=noninteractive apt install -y"' in script


@pytest.mark.tier1
def test_install_script_adds_a_course_given_as_its_argument():
    """`curl …/install.sh | bash -s -- <course link>`: install, then `hashpass add <link>`."""
    script = render_install_script("http://pool:8080")
    assert 'COURSE="${1:-}"' in script
    assert '"$BIN/hashpass" --no-update add "$COURSE"' in script


@pytest.mark.tier1
def test_install_script_gives_the_new_python_its_own_pip():
    """
    Ubuntu 22.04: python3.13 imports the system pip 22.0 (for 3.10) and dies on `distutils`.

    `ensurepip --user` then says «Requirement already satisfied … dist-packages» and installs
    nothing (checked in ubuntu:22.04 + deadsnakes, 2026-10-24); `--upgrade` puts a pip into
    ~/.local. If pip still does not run, the script stops with a clear message.
    """
    script = render_install_script("http://pool.example/")
    assert "ensurepip --user --upgrade" in script
    boot = script[script.index("ensurepip"):script.index("SHA=")]
    assert boot.count("-m pip --version") >= 2 and "exit 1" in boot  # noqa: PLR2004


@pytest.mark.tier1
def test_install_script_raises_the_inotify_limit_for_many_consoles():
    """
    Each console's systemd takes ~4 of root's inotify instances (128 by default).

    2026-10-24: the 31st console on one machine died «Failed to create control group inotify
    object: Too many open files». The install raises it for good in /etc/sysctl.d.
    """
    script = render_install_script("http://pool.example/")
    assert "/etc/sysctl.d/60-hashpass.conf" in script
    assert "fs.inotify.max_user_instances = 8192" in script
    assert "fs.inotify.max_user_watches = 1048576" in script


@pytest.mark.tier1
def test_install_script_puts_its_own_deps_over_the_system_ones():
    """
    The deps go into ~/.local even when the system has a copy.

    Ubuntu 24.04: deadsnakes python3.13 sees /usr/lib/python3/dist-packages, where apt's
    typing_extensions 4.10 «satisfies» textual -- pip installs nothing, and 4.10 dies on 3.13
    («'__default__' of 'typing.ParamSpec' objects is not writable»).
    """
    script = render_install_script("http://pool.example/")
    deps = next(line for line in script.splitlines() if '"textual>=1.0"' in line)
    assert "--ignore-installed" in deps


@pytest.mark.tier1
def test_install_script_refuses_root():
    """
    User 2026-10-25: installing as root breaks a lot (~root/.local, a root-owned ~/.hashpass).

    The check comes before anything is installed.
    """
    script = render_install_script("http://pool.example/")
    check = script.index('if [ "$(id -u)" = 0 ]')
    assert check < script.index("missing=")
    assert "без sudo" in script[check:check + 400]


@pytest.mark.tier1
def test_install_block_shows_the_uninstall_command():
    from hashpass.registry.web import render_front  # noqa: PLC0415
    page = render_front("http://pool.example/")
    assert "http://pool.example/uninstall.sh | bash" in page
