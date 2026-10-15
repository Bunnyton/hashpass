"""What the base image installs: a common admin toolset, minus what tasks teach to install."""
import re

import pytest

from hashpass.image import base


def _installed() -> set[str]:
    words: set[str] = set()
    for m in re.finditer(r"apt-get install -y (?:--reinstall )?([^&]+)", base._SYSTEMD_INSTALL):  # noqa: SLF001
        words.update(w for w in m.group(1).split() if not w.startswith("-"))
    return words


@pytest.mark.tier1
def test_base_has_the_common_toolset():
    # User (2026-10-12): «в базу добавь vim, общий набор, net-tools и т.д.»
    want = {"vim", "nano", "less", "tree", "file", "htop", "lsof", "net-tools", "iproute2",
            "iputils-ping", "dnsutils", "zip", "unzip", "xz-utils"}
    assert want <= _installed()


@pytest.mark.tier1
def test_base_leaves_out_what_tasks_install_themselves():
    # apt-add-repo: «curl: command not found» is the premise; apt-deb: «такой скачивалки нет»;
    # proc-audit installs psmisc; apt-update/apt-remove/showcase -- sl; apt-deb -- cmatrix.
    assert not ({"curl", "wget", "psmisc", "sl", "cmatrix", "telnet"} & _installed())


@pytest.mark.tier1
def test_base_runs_the_vim_and_carbonyl_setup_scripts():
    # User, 2026-10-15: «в базу добавь vim красивый и carbonyl … напиши скрипт для установки,
    # я его тоже поиспользую» -- the base runs the same scripts that ship in the runtime.
    setup = base._RUNTIME / "usr/local/share/hashpass"  # noqa: SLF001
    for name in ("install-vim.sh", "install-carbonyl.sh"):
        script = setup / name
        assert script.is_file() and script.stat().st_mode & 0o111, name
        assert f"/usr/local/share/hashpass/{name}" in base._SETUP  # noqa: SLF001
    assert base.CARBONYL_URL.endswith("carbonyl.linux-amd64.zip")
    sha = re.search(r"^SHA256_amd64=(\w+)", (setup / "install-carbonyl.sh").read_text(), re.MULTILINE)
    assert sha and sha.group(1) == base.CARBONYL_SHA256
