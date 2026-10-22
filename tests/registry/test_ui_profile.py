"""
Tier1: the web after user 2026-10-23.

Profile home, tasks apart from images, where-used with blocks, progress inside a course, no
global «Прогресс»/«Образы и каталог»/groups, the home page as a showcase.
"""
import pytest

from hashpass.registry.remote import RemoteRegistry, use_course
from hashpass.registry.revisions import RepoIndex
from tests.registry.test_course_api import _Courses
from tests.registry.test_course_web import _browser, _page
from tests.registry.test_course_web import pool as pool  # noqa: PLC0414  (fixture)


@pytest.fixture
def world(pool: _Courses) -> _Courses:
    """bob: task git-init (course bob/linux, block Git) + plain image bob/base; eve's private course uses git-init."""
    pool.push("bob/base", "1", image="plain")
    pool.call("POST", "/courses", "eve", {"name": "hush", "title": "Тайный", "visibility": "private"})
    pool.call("POST", "/courses/eve/hush/tasks", "eve", {"repo": "bob/git-init", "tag": "1"})
    pool.call("POST", "/courses/bob/linux/join", "kid", {})
    digest = RepoIndex(pool.r.store.root / ".repos", "bob/git-init").get("1", 1).task_digest
    client = RemoteRegistry(pool.url, token=pool.tok["kid"])
    use_course(pool.url, "bob/linux")
    try:
        client.submit("bob/git-init:1", digest, passed=True, token=pool.tok["kid"])
    finally:
        use_course(pool.url, None)
    return pool


@pytest.mark.tier1
def test_the_image_card_says_where_it_is_used_course_and_block_not_on_top(world: _Courses) -> None:
    html = _page(_browser(world, "bob"), f"{world.url}/web/image/bob/git-init:1")[1]
    hero = html.split("<h2", 1)[0]
    assert "блок «" not in hero                                           # not on top any more
    assert "/c/bob/linux" in html and "Git" in html.split("id='courses'", 1)[1]
    assert "/c/eve/hush" in html                                          # its owner sees every course
    other = _page(_browser(world, "kid"), f"{world.url}/web/image/bob/git-init:1")[1]
    assert "/c/eve/hush" not in other                                     # others: only what they may see


@pytest.mark.tier1
def test_profile_lists_tasks_apart_from_images_and_all_courses_using_them(world: _Courses) -> None:
    html = _page(_browser(world, "bob"), f"{world.url}/u/bob")[1]
    tasks, images = html.split("id='tasks'", 1)[1].split("id='images'", 1)
    assert "bob/git-init" in tasks and "bob/base" not in tasks
    assert "bob/base" in images.split("id='used'", 1)[0]
    used = html.split("id='used'", 1)[1]
    assert "/c/bob/linux" in used and "/c/eve/hush" in used               # own and (his own view) private


@pytest.mark.tier1
def test_ones_own_profile_is_home_with_the_courses_one_takes(world: _Courses) -> None:
    status, html = _page(_browser(world, "kid"), f"{world.url}/u/kid")
    assert status == 200 and "Прохожу" in html and "/c/bob/linux" in html  # noqa: PLR2004
    assert "1 / 1" in html
    assert "Прохожу" not in _page(_browser(world, "eve"), f"{world.url}/u/kid")[1]
    assert "href='/u/kid'" in html                                        # the header links home


@pytest.mark.tier1
def test_search_has_tasks_and_images_apart(world: _Courses) -> None:
    html = _page(_browser(world, "kid"), f"{world.url}/search?q=bob&type=tasks")[1]
    assert "data-tab='tasks'" in html and "data-tab='images'" in html
    assert "bob/git-init" in html and "bob/base" not in html


@pytest.mark.tier1
def test_progress_lives_in_the_course(world: _Courses) -> None:
    html = _page(_browser(world, "bob"), f"{world.url}/c/bob/linux")[1]
    students = html.split("id='students'", 1)[1]
    assert "kid" in students and "1 / 1" in students and "type='search'" in students
    status, page = _page(_browser(world, "bob"), f"{world.url}/c/bob/linux/u/kid")
    assert status == 200 and "bob/git-init" in page and "решено" in page  # noqa: PLR2004
    assert _page(_browser(world, "eve"), f"{world.url}/c/bob/linux/u/kid")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_no_global_progress_images_catalog_or_groups(world: _Courses) -> None:
    html = _page(_browser(world, "bunnyton"), f"{world.url}/c")[1]
    nav = html.split("<main", 1)[0]
    assert "Образы и каталог" not in nav and ">Прогресс<" not in nav
    assert _page(_browser(world, "bunnyton"), f"{world.url}/web")[1].count("id='students'") == 0
    users = _page(_browser(world, "bunnyton"), f"{world.url}/web/users")[1]
    assert "Группа" not in users and "delete-group" not in users


@pytest.mark.tier1
def test_the_home_page_is_a_showcase_with_search(world: _Courses) -> None:
    status, html = _page(_browser(world, None), f"{world.url}/")
    assert status == 200 and "action='/search'" in html  # noqa: PLR2004
    assert "/c/bob/linux" in html and "/c/eve/hush" not in html            # what a visitor may see
    assert "bob/git-init" in html and "bob/base" in html and "href='/u/bob'" in html
    assert "install.sh" in html and "Войти" in html
