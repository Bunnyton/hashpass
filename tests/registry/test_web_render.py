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
    render_users,
)


@pytest.mark.tier1
def test_front_shows_install_command():
    html = render_front("http://pool.example/")
    assert "http://pool.example/install.sh" in html
    assert "curl" in html


@pytest.mark.tier1
def test_login_form_and_error():
    assert "type='password'" in render_login()
    assert "class='err'" not in render_login()
    assert "плохо" in render_login("плохо")


@pytest.mark.tier1
def test_dashboard_rows_cells_and_group_filter():
    profiles = [
        {"user": "s1", "role": "student", "full_name": "Иван", "group": "ИУ7-31", "comment": ""},
        {"user": "s2", "role": "student", "full_name": "Пётр", "group": "ИУ7-32", "comment": ""},
        {"user": "adm", "role": "admin", "full_name": "Админ", "group": "", "comment": ""},
    ]
    entries = [{"number": 1, "ref": "lab:1", "title": "T1"},
               {"number": 2, "ref": "lab:2", "title": "T2"}]
    progress = {"s1": {"lab:1": {"status": "passed"}}, "s2": {"lab:1": {"status": "failed"}}}
    html = render_dashboard(profiles, entries, progress)
    assert "Иван" in html
    assert "Пётр" in html
    assert "Админ" not in html          # admins are not tracked as students
    assert "✓" in html
    assert "✗" in html
    only31 = render_dashboard(profiles, entries, progress, group="ИУ7-31")
    assert "Иван" in only31
    assert "Пётр" not in only31


@pytest.mark.tier1
def test_users_toggle_label_flips():
    profiles = [{"user": "a", "role": "admin", "full_name": "Adm", "group": "", "comment": "c"}]
    assert "Закрыть регистрацию" in render_users(profiles, registration_open=True)
    assert "Открыть регистрацию" in render_users(profiles, registration_open=False)


@pytest.mark.tier1
def test_install_script_targets_pool_and_pip():
    script = render_install_script("http://pool.example/")
    assert script.startswith("#!/usr/bin/env bash")
    assert 'POOL="http://pool.example"' in script
    assert "pip install --user" in script
    assert "git+https://github.com/Bunnyton/hashpass@main" in script
    assert "pool.json" in script


@pytest.mark.tier1
def test_engine_install_script_mentions_engine():
    script = render_engine_install_script("http://p")
    assert "engine" in script
    assert "pip install" in script


@pytest.mark.tier1
@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_install_script_passes_shellcheck():
    script = render_install_script("http://pool.example")
    proc = subprocess.run(["shellcheck", "-s", "bash", "-"], input=script,
                          text=True, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stdout
