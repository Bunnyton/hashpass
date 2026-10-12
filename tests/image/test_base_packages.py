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
