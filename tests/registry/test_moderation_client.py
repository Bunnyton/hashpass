"""Tier2: the client side of moderation -- approve/reject/delete, and the author's own latest image."""
import urllib.error
from http import HTTPStatus

import pytest

from hashpass.registry.remote import RemoteRegistry
from tests.registry.test_moderation_routes import _Pool


@pytest.mark.tier2
def test_client_moderates_and_the_author_reads_the_latest_image(registry, tmp_path):
    pool = _Pool(registry, tmp_path)
    ref = "bob/lab:1"
    pool.push("bob/lab", "v1")
    admin = RemoteRegistry(registry.base_url, token=pool.tok["root"])
    admin.approve(ref, token=pool.tok["root"])
    v1 = RemoteRegistry(registry.base_url).image_digest(ref)           # anonymous: approved
    pool.push("bob/lab", "v2")
    assert RemoteRegistry(registry.base_url).image_digest(ref) == v1
    author = RemoteRegistry(registry.base_url, token=pool.tok["bob"])
    assert author.image_digest(ref) not in (None, v1)                  # the author: own latest
    admin.reject(ref, "поправь подсказки", token=pool.tok["root"])
    row = next(r for r in author.catalog(token=pool.tok["bob"]) if r["ref"] == ref)
    assert (row["state"], row["reason"]) == ("rejected", "поправь подсказки")
    with pytest.raises(urllib.error.HTTPError) as exc:
        RemoteRegistry(registry.base_url).delete_task(ref, token=pool.tok["alice"])
    assert exc.value.code == HTTPStatus.FORBIDDEN
    author.delete_task(ref, token=pool.tok["bob"])
    assert author.catalog(token=pool.tok["bob"]) == []


@pytest.mark.tier2
def test_hashengine_pull_gives_the_author_their_own_pending_task(registry, tmp_path):
    """Review 2026-10-14: `hashengine pull` read images anonymously -- 404 on the author's own push."""
    from hashpass import cli  # noqa: PLC0415
    from hashpass.imagestore.store import ImageStore  # noqa: PLC0415
    from hashpass.registry.creds import CredentialCache  # noqa: PLC0415
    pool = _Pool(registry, tmp_path)
    pool.push("bob/lab", "v1")                                        # pending: never approved
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "bob-home")}, default_home=tmp_path)
    RemoteRegistry(registry.base_url, cache=CredentialCache(env.creds)).login("bob", "pw-correct1")
    assert cli.cmd_pull(env, "bob/lab:1", registry.base_url) == 0
    assert ImageStore(env.images).exists("bob/lab:1")
