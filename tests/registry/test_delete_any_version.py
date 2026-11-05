"""
Tier1: any version can be deleted once no live image stands on it; its number is never reused.

User 2026-11-05: «разрешай удалять версии в принципе. Вернуть их нельзя, просто можно сделать
недоступными — удалить, номер версии остаётся неизменным… конкретные хочу посносить».
A version a live image stands on (one's own too) stays until that image goes: clients pull it with
the image. Someone else's image standing on it says so.
"""
import pytest

from tests.registry.test_push_commit import _http, _Pool
from tests.registry.test_push_commit import pool as pool  # noqa: PLC0414  (fixture)

BASE = ("bunnyton/debian:trixie",)


def _versions(pool: _Pool, name: str, tag: str = "1") -> list[int]:
    return [r["n"] for r in _http("GET", f"{pool.url}/revisions/{name}", token=pool.tok["bunnyton"])[1]["tags"][tag]]


def _delete(pool: _Pool, ref: str, n: int, user: str = "bunnyton") -> tuple[int, dict]:
    return _http("DELETE", f"{pool.url}/revisions/{ref}/{n}", token=pool.tok[user])


@pytest.mark.tier1
def test_a_version_a_live_image_stands_on_stays_until_that_image_goes(pool: _Pool) -> None:
    """
    A version any live image (one's own too) stands on stays until that image goes.

    2026-11-05: base trixie_v3 left the index while 66 live task versions stood on it -- every
    client pulling them got 404.
    """
    pool.push("bob/lab", "1", image="one", task="t1", parents=BASE)          # lab v1 on base v1
    pool.push("bob/kit", "1", image="k1", task="k1", parents=("bob/lab:1",))  # kit v1 stands on lab v1
    pool.push("bob/lab", "1", image="two", task="t2", parents=BASE)          # lab v2
    code, body = _delete(pool, "bob/lab/1", 1)
    assert code == 409 and "bob/kit:1_v1" in body["error"], body  # noqa: PLR2004
    assert _versions(pool, "bob/lab") == [1, 2]                              # still listed, still pulled
    assert _delete(pool, "bob/kit/1", 1)[0] == 200  # noqa: PLR2004
    assert _delete(pool, "bob/lab/1", 1)[0] == 200  # noqa: PLR2004        # nothing stands on it now
    assert not pool.r.store.exists("bob/lab:1_v1")
    assert pool.push("bob/lab", "1", image="three", task="t3", parents=BASE)[1]["n"] == 3  # never reused  # noqa: PLR2004


@pytest.mark.tier1
def test_someone_elses_image_standing_on_it_blocks_the_deletion(pool: _Pool) -> None:
    """User 2026-11-05: «если зависит от моего образа чужой — пусть блокируется удаление»."""
    pool.push("bob/lab", "1", image="one", task="t1", parents=BASE)          # bob's lab on base v1
    pool.push("bunnyton/debian", "trixie", image="base2", user="bunnyton")  # base v2
    code, body = _delete(pool, "bunnyton/debian/trixie", 1)
    assert code == 409 and "bob/lab:1_v1" in body["error"]  # noqa: PLR2004
    assert _versions(pool, "bunnyton/debian", "trixie") == [1, 2]


@pytest.mark.tier1
def test_only_who_maintains_the_image_deletes(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1", parents=BASE)
    pool.push("bob/lab", "1", image="two", task="t2", parents=BASE)
    assert _delete(pool, "bob/lab/1", 1, user="eve")[0] == 403  # noqa: PLR2004


@pytest.mark.tier1
def test_the_versions_page_warns_before_deleting_one_someones_course_shows(pool: _Pool) -> None:
    """User 2026-11-05: «предупреждай, что она стоит в чужих курсах перед попыткой удаления»."""
    import http.cookiejar  # noqa: PLC0415
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    pool.push("bob/lab", "1", image="one", task="t1", parents=BASE)
    pool.push("bob/lab", "1", image="two", task="t2", parents=BASE)
    _http("POST", f"{pool.url}/courses", token=pool.tok["eve"], body={"name": "evecourse"})
    _http("POST", f"{pool.url}/courses/eve/evecourse/tasks", token=pool.tok["eve"],
          body={"repo": "bob/lab", "tag": "1", "n": 1})
    _http("PUT", f"{pool.url}/courses/eve/evecourse/tasks/bob/lab:1", token=pool.tok["eve"], body={"pinned": True})
    pool.push("eve/kit", "1", image="k", task="k", parents=("bob/lab:1",), user="eve")   # eve: an image on lab v2
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.open(urllib.request.Request(f"{pool.url}/web/login", data=urllib.parse.urlencode(  # noqa: S310
        {"user": "bob", "password": "pw-correct1"}).encode()), timeout=10)
    html = opener.open(f"{pool.url}/web/versions/bob/lab", timeout=10).read().decode()
    at1, at2 = html.index(">1_v1<"), html.index(">1_v2<")                        # newest first
    v1 = html[at1:]
    assert "в чужих курсах" in v1 and "eve/evecourse" in v1                     # said before deleting
    v2 = html[at2:at1]
    assert "чужие образы" in v2 and "DELETE /revisions/bob/lab/1/2" not in v2   # blocked: no button
