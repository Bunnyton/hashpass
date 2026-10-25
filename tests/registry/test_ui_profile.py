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
def test_my_courses_show_the_courses_one_takes_with_progress(world: _Courses) -> None:
    status, html = _page(_browser(world, "kid"), f"{world.url}/c")
    assert status == 200 and "Прохожу" in html and "/c/bob/linux" in html  # noqa: PLR2004
    assert "1 / 1" in html
    assert "Прохожу" not in _page(_browser(world, "eve"), f"{world.url}/u/kid")[1]   # private
    assert "href='/u/kid'" in html                                        # the header links one's page
    assert "Веду" in _page(_browser(world, "bob"), f"{world.url}/c")[1]


@pytest.mark.tier1
def test_search_has_tasks_and_images_apart(world: _Courses) -> None:
    html = _page(_browser(world, "kid"), f"{world.url}/search?q=bob&type=tasks")[1]
    assert "data-tab='tasks'" in html and "data-tab='images'" in html
    assert "bob/git-init" in html and "bob/base" not in html


@pytest.mark.tier1
def test_progress_lives_in_the_course(world: _Courses) -> None:
    html = _page(_browser(world, "bunnyton"), f"{world.url}/c/bob/linux")[1]
    students = html.split("id='students'", 1)[1]
    assert "kid" in students and "1 / 1" in students and "type='search'" in students
    status, page = _page(_browser(world, "bunnyton"), f"{world.url}/c/bob/linux/u/kid")
    assert status == 200 and "bob/git-init" in page and "решено" in page  # noqa: PLR2004
    assert _page(_browser(world, "bob"), f"{world.url}/c/bob/linux/u/kid")[0] == 200  # noqa: PLR2004  (its owner)
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
    assert status == 200 and "action='/'" in html and "data-live" in html  # noqa: PLR2004
    assert "/c/bob/linux" in html and "/c/eve/hush" not in html            # what a visitor may see
    assert "bob/git-init" in html and "bob/base" in html and "href='/u/bob'" in html
    assert "install.sh" in html and "Войти" in html


@pytest.mark.tier1
def test_the_home_page_searches_in_place(world: _Courses) -> None:
    """User 2026-10-23: «главная и поиск — одно и то же, при поиске не уезжать никуда»."""
    part = _page(_browser(world, "kid"), f"{world.url}/?q=git&partial=1")[1]
    assert "<html" not in part and "bob/git-init" in part and "data-tab='tasks'" in part
    status, html = _page(_browser(world, "kid"), f"{world.url}/search?q=git")   # old links still land
    assert status == 200 and "value='git'" in html  # noqa: PLR2004


@pytest.mark.tier1
def test_a_profile_photo(world: _Courses) -> None:
    import urllib.request  # noqa: PLC0415
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
    b = "----hp"
    body = (f'--{b}\r\nContent-Disposition: form-data; name="photo"; filename="me.png"\r\n'
            "Content-Type: image/png\r\n\r\n").encode() + png + f"\r\n--{b}--\r\n".encode()
    browser = _browser(world, "kid")
    browser.open(urllib.request.Request(f"{world.url}/web/avatar", data=body,  # noqa: S310
                                        headers={"Content-Type": f"multipart/form-data; boundary={b}"}))
    with urllib.request.urlopen(f"{world.url}/u/kid/avatar") as resp:      # noqa: S310
        assert resp.headers["Content-Type"] == "image/png" and resp.read() == png
    assert "src='/u/kid/avatar'" in _page(_browser(world, "eve"), f"{world.url}/u/kid")[1]
    bad = body.replace(png, b"<svg onload=alert(1)>")
    browser.open(urllib.request.Request(f"{world.url}/web/avatar", data=bad,  # noqa: S310
                                        headers={"Content-Type": f"multipart/form-data; boundary={b}"}))
    with urllib.request.urlopen(f"{world.url}/u/kid/avatar") as resp:      # noqa: S310
        assert resp.read() == png                                           # not an image: refused


@pytest.mark.tier1
def test_ones_profile_has_the_solved_tasks_and_stats(world: _Courses) -> None:
    """User 2026-10-23: «в профиле есть выполненные (статистика и т.д.)» -- one's own, like «Прохожу»."""
    html = _page(_browser(world, "kid"), f"{world.url}/u/kid")[1]
    solved = html.split("id='solved'", 1)[1].split("</section>", 1)[0]
    assert "bob/git-init:1" in solved and "/c/bob/linux" in solved and "версия 1" in solved
    # user 2026-10-23: «не в курсе так себе звучит» -- the courses the task is in, «—» if none;
    # the date sits small beside the name, as in a GitHub repository list
    assert "Используется в курсах" in solved and "не в курсе" not in solved and "Когда" not in solved
    assert "<time class='ts' data-rel datetime=" in solved.split("<tbody>", 1)[1].split("</td>", 1)[0]
    assert "data-tab>" in html and "Решено" in html
    stats = html.split("class='user-stats'", 1)[1].split("</ul>", 1)[0]
    assert "решено" in stats and "<b>1</b>" in stats
    other = _page(_browser(world, "eve"), f"{world.url}/u/kid")[1]
    assert "id='solved'" not in other                                    # progress is private


@pytest.mark.tier1
def test_a_progress_mark_opens_the_solution(world: _Courses) -> None:
    """User 2026-10-25: «после нажатия на прогресс (галочку и остальное) хочу сразу решение»."""
    history = "/web/history?user=kid&amp;ref=bob%2Fgit-init%3A1#solution"
    course = _page(_browser(world, "bunnyton"), f"{world.url}/c/bob/linux")[1]
    cells = course.split("id='student-rows'", 1)[1].split("</tbody>", 1)[0]
    assert f"href='{history}'" in cells
    student = _page(_browser(world, "bunnyton"), f"{world.url}/c/bob/linux/u/kid")[1]
    assert f"href='{history}'" in student
    mine = _page(_browser(world, "kid"), f"{world.url}/u/kid")[1]
    assert f"href='{history}'" in mine                          # one's own solved list
    assert "#solution" not in _page(_browser(world, "eve"), f"{world.url}/u/kid")[1]
    status, _page_html = _page(_browser(world, "kid"), world.url + history.replace("&amp;", "&").split("#")[0])
    assert status == 200  # noqa: PLR2004                       # one's own work: open
    assert _page(_browser(world, "eve"), world.url + history.replace("&amp;", "&").split("#")[0])[0] == 403  # noqa: PLR2004
