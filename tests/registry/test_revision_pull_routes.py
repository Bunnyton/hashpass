"""Tier1: reads follow revisions -- pinned closure, `X-Image-Ref`, students get the approved one."""
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from hashpass.registry.catalog import Catalog
from hashpass.registry.pool_settings import PoolSettings
from hashpass.registry.remote import RemoteRegistry
from tests.registry.test_push_commit import _http, _Pool


def _get(url: str, token: str | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


@pytest.fixture
def pool(registry, tmp_path: Path) -> _Pool:
    PoolSettings(registry.catalog_path.parent / "pool-settings.json").set_auto_approve(on=False)
    p = _Pool(registry, tmp_path)
    registry.users.add("kid", "pw-correct1", role="student")
    p.tok["kid"] = RemoteRegistry(p.url).login("kid", "pw-correct1")
    p.push("bunnyton/debian", "trixie", image="base", user="bunnyton")
    return p


@pytest.mark.tier1
def test_closure_with_revisions_names_pinned_parents(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1", parents=("bunnyton/debian:trixie",))
    pool.push("bunnyton/debian", "trixie", image="base2", user="bunnyton")
    code, body = _http("GET", f"{pool.url}/closure/bob/lab/1?revisions=1", token=pool.tok["bob"])
    assert code == 200  # noqa: PLR2004
    assert body["refs"] == ["bunnyton/debian:trixie_v1", "bob/lab:1_v1"]
    assert body["parents"]["bob/lab:1_v1"] == ["bunnyton/debian:trixie_v1"]
    legacy = _http("GET", f"{pool.url}/closure/bob/lab/1", token=pool.tok["bob"])[1]
    assert legacy == {"refs": ["bunnyton/debian:trixie", "bob/lab:1"]}      # an old client


@pytest.mark.tier1
def test_get_names_the_served_revision(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1")
    pool.push("bob/lab", "1", image="two", task="t2")
    status, headers, _ = _get(f"{pool.url}/image/bob/lab/1", pool.tok["bob"])
    assert (status, headers["X-Image-Ref"]) == (200, "bob/lab:1_v2")
    status, headers, _ = _get(f"{pool.url}/image/bob/lab/1_v1", pool.tok["bob"])
    assert (status, headers["X-Image-Ref"]) == (200, "bob/lab:1_v1")


@pytest.mark.tier1
def test_students_get_the_approved_revision_authors_the_newest(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one", task="t1", query="&publish=1")
    assert _http("POST", f"{pool.url}/catalog/approve", token=pool.tok["bunnyton"],
                 body={"ref": "bob/lab:1"})[0] == 200  # noqa: PLR2004
    Catalog(pool.r.catalog_path).set_task_hidden("bob/lab:1", hidden=False)
    pool.push("bob/lab", "1", task="t2")                           # pending update
    kid = _get(f"{pool.url}/task/bob/lab/1", pool.tok["kid"])
    bob = _get(f"{pool.url}/task/bob/lab/1", pool.tok["bob"])
    assert (kid[0], kid[1]["X-Image-Ref"]) == (200, "bob/lab:1_v1")
    assert (bob[0], bob[1]["X-Image-Ref"]) == (200, "bob/lab:1_v2")
    assert _get(f"{pool.url}/task/bob/lab/1_v2", pool.tok["kid"])[0] == 404  # noqa: PLR2004
    rows = json.loads(_get(f"{pool.url}/images", pool.tok["kid"])[2])["images"]
    assert [r["ref"] for r in rows if r["repo"] == "bob/lab"] == ["bob/lab:1_v1"]


@pytest.mark.tier1
def test_images_mark_the_newest_revision(pool: _Pool) -> None:
    pool.push("bob/lab", "1", image="one")
    pool.push("bob/lab", "1", image="two")
    rows = json.loads(_get(f"{pool.url}/images", pool.tok["bob"])[2])["images"]
    mine = {r["ref"]: r["latest"] for r in rows if r["repo"] == "bob/lab"}
    assert mine == {"bob/lab:1_v1": False, "bob/lab:1_v2": True}
