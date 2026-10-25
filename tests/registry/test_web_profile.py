"""Web: user profile page, task links, per-viewer time zone, sortable tables, lossless autosave."""
import re
from http import HTTPStatus

import pytest

from hashpass.registry.passwords import UserStore
from hashpass.registry.web import (
    render_dashboard,
    render_history,
    render_profile,
    render_users,
    ts_html,
)

from .test_web_flow import _admin_cookie, _req

_ENTRIES = [{"number": 1, "ref": "lab/one:1"}, {"number": 2, "ref": "lab/two:1"}]


@pytest.mark.tier1
def test_ts_html_is_utc_iso_for_the_browser_to_localise():
    html = str(ts_html(0))
    assert "datetime='1970-01-01T00:00:00Z'" in html
    assert "class='ts'" in html
    assert str(ts_html("2026-10-21T10:00:00Z")).count("2026-10-21T10:00:00Z") == 1
    assert str(ts_html(None)) == "—"


@pytest.mark.tier1
def test_users_page_links_logins_to_profiles_and_is_sortable():
    html = render_users([{"user": "s 1", "role": "student", "group": "G", "comment": "c",
                          "created_at": 0.0}], registration_open=True)
    assert "href='/u/s%201'" in html
    assert "class='wide sortable'" in html
    assert "<thead>" in html
    assert "/static/sort.js" in html


@pytest.mark.tier1
def test_dashboard_links_logins_and_task_names_and_shows_staff_group():
    profiles = [{"user": "s1", "role": "student", "group": "G1", "comment": ""},
                {"user": "adm", "role": "admin", "group": "Кафедра", "comment": ""},
                {"user": "au", "role": "author", "group": "", "comment": ""}]
    html = render_dashboard(profiles, _ENTRIES, {})
    assert "href='/web/user/s1'" in html
    assert "href='/web/image/lab/one:1'" in html       # task name in the header -> its card
    assert "Кафедра" in html                           # a staff member's own group is shown
    assert re.search(r"/web/user/au'>au</a></td><td>authors<", html)   # no group -> authors
    assert "sortable" in html


@pytest.mark.tier1
def test_history_links_task_and_user_and_localises_times():
    sess = [{"session_id": "a", "started": 1_700_000_000, "updated": 1_700_000_600,
             "final": "passed", "entries": []}]
    html = render_history("s1", "lab/one:1", {}, sessions=sess)
    assert "href='/web/image/lab/one:1'" in html
    assert "href='/web/user/s1'" in html
    assert "datetime='2023-11-14T22:13:20Z'" in html


@pytest.mark.tier1
def test_profile_lists_every_catalog_task_with_status_attempts_and_times():
    profile = {"user": "s1", "role": "student", "group": "G1", "comment": "Иван", "created_at": 0}
    progress = {"lab/one:1": {"status": "passed", "ts": "2026-10-21T10:00:00Z"},
                "old/gone:1": {"status": "failed", "ts": "2026-10-01T10:00:00Z"}}
    sessions = {"lab/one:1": [{"started": 1_700_000_000, "updated": 1_700_000_600,
                               "final": "passed"},
                              {"started": 1_699_000_000, "updated": 1_699_000_060,
                               "final": "abandoned"}]}
    html = render_profile(profile, _ENTRIES, progress, sessions)
    assert "Иван" in html                                   # the private comment, to staff
    assert "1 / 2" in html                                     # passed / catalog tasks
    assert "href='/web/image/lab/one:1'" in html             # task name -> card
    assert "href='/web/history?user=s1&amp;ref=lab%2Fone%3A1#solution'" in html
    assert "datetime='2026-10-21T10:00:00Z'" in html         # credited at
    assert "lab/two:1" in html                               # untouched task is listed too
    assert "old/gone:1" in html                              # off-catalog progress is not lost
    assert "sortable" in html


@pytest.mark.tier1
def test_user_store_keeps_a_time_zone(tmp_path):
    users = UserStore(tmp_path / "u.json")
    users.add("a", "pw", role="admin")
    assert users.get("a")["tz"] == ""
    users.set_tz("a", "Europe/Moscow")
    assert users.get("a")["tz"] == "Europe/Moscow"


@pytest.mark.tier2
def test_profile_route_for_staff_only(registry):
    registry.users.add("stud", "pw", role="student", group="G", comment="Вася")
    opener, cookie = _admin_cookie(registry)
    status, _, body = _req(opener, "GET", f"{registry.base_url}/web/user/stud", cookie=cookie)
    assert status == HTTPStatus.OK
    assert "Вася" in body
    status, _, _ = _req(opener, "GET", f"{registry.base_url}/web/user/nobody", cookie=cookie)
    assert status == HTTPStatus.NOT_FOUND
    status, _, _ = _req(opener, "GET", f"{registry.base_url}/web/user/stud")
    assert status == HTTPStatus.SEE_OTHER


@pytest.mark.tier2
def test_settings_time_zone_is_per_viewer_and_reaches_every_page(registry):
    opener, cookie = _admin_cookie(registry)
    status, _, body = _req(opener, "GET", f"{registry.base_url}/web/settings", cookie=cookie)
    assert status == HTTPStatus.OK
    assert "Europe/Moscow" in body                            # the zone list
    assert "data-tz=''" in body                               # default: the browser's zone
    _req(opener, "POST", f"{registry.base_url}/web/settings/tz", cookie=cookie,
         data={"tz": "Asia/Tokyo"})
    _, _, body = _req(opener, "GET", f"{registry.base_url}/c", cookie=cookie)
    assert "data-tz='Asia/Tokyo'" in body
    _req(opener, "POST", f"{registry.base_url}/web/settings/tz", cookie=cookie,
         data={"tz": "Not/AZone"})                            # junk is refused, setting kept
    _, _, body = _req(opener, "GET", f"{registry.base_url}/c", cookie=cookie)
    assert "data-tz='Asia/Tokyo'" in body


@pytest.mark.tier2
def test_inline_edit_by_fetch_answers_204_and_saves(registry):
    """The autosave posts in the background (survives a click on a link) -> 204, no redirect."""
    registry.users.add("stud", "pw", role="student", group="OLD", comment="old")
    opener, cookie = _admin_cookie(registry)
    status, _, _ = _req(opener, "POST", f"{registry.base_url}/web/users/comment?bg=1",
                        cookie=cookie, data={"user": "stud", "comment": "новый"})
    assert status == HTTPStatus.NO_CONTENT
    assert registry.users.get("stud")["comment"] == "новый"
