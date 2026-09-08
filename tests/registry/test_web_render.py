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
def test_login_form_and_error():
    assert "type='password'" in render_login()
    assert "class='err'" not in render_login()
    assert "плохо" in render_login("плохо")


@pytest.mark.tier1
def test_dashboard_rows_cells_and_group_filter():
    profiles = [
        {"user": "s1", "role": "student", "group": "ИУ7-31", "comment": "Иван"},
        {"user": "s2", "role": "student", "group": "ИУ7-32", "comment": "Пётр"},
        {"user": "adm", "role": "admin", "group": "", "comment": "Админ"},
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
def test_users_toggle_and_inline_controls():
    profiles = [{"user": "s1", "role": "student", "group": "G", "comment": ""}]
    html = render_users(profiles, registration_open=True)
    assert "Закрыть регистрацию" in html
    assert "Открыть регистрацию" in render_users(profiles, registration_open=False)
    assert "/web/users/role" in html          # inline per-user role change
    assert "/web/users/reset" in html         # per-user reset link
    assert "ссылка сброса" in html
    assert "/web/users/delete-group" in html  # delete a whole group


@pytest.mark.tier1
def test_users_self_row_has_no_role_or_delete():
    profiles = [{"user": "admin", "role": "admin", "group": "", "comment": ""},
                {"user": "s1", "role": "student", "group": "G", "comment": ""}]
    html = render_users(profiles, registration_open=True, current_user="admin")
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
    assert "git+https://github.com/Bunnyton/hashpass@main" in script
    assert "pool.json" in script
    # preflight checks all tools before the download; the install line comes after them
    for tool in ("python3", "python3 -m pip --version", "git"):
        assert tool in script
    assert script.index("не хватает зависимостей") < script.index("pip install --user")


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
