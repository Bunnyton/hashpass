"""
Tier2: the pool hands out the offline installer next to the online one.

User 2026-10-25: «Добавь его на репозиторий и на сайт (онлайн установщик) и оффлайн». `/offline`
serves the bundle the operator put in `<registry>/offline/`; a pool without one sends the browser
to the latest GitHub release, so the link on the page always works.
"""
import urllib.error
import urllib.request
from http import HTTPStatus

import pytest

from hashpass.registry import era

_NAME = "hashpass-offline-x86_64.run"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        return None


def _get(url: str) -> tuple[int, object, bytes]:
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
    try:
        resp = opener.open(url, timeout=10)
        return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


@pytest.mark.tier2
def test_the_pool_serves_its_own_offline_bundle(registry) -> None:
    bundle = registry.catalog_path.parent / "offline" / _NAME
    bundle.parent.mkdir()
    bundle.write_bytes(b"#!/bin/bash\npayload")
    status, headers, body = _get(f"{registry.base_url}/offline")
    assert status == HTTPStatus.OK
    assert body == b"#!/bin/bash\npayload"
    assert _NAME in headers["Content-Disposition"]


@pytest.mark.tier2
def test_a_pool_without_a_bundle_sends_to_the_release(registry) -> None:
    status, headers, _ = _get(f"{registry.base_url}/offline")
    assert status == HTTPStatus.FOUND
    assert headers["Location"] == f"https://github.com/Bunnyton/hashpass/releases/latest/download/{_NAME}"


@pytest.mark.tier2
@pytest.mark.parametrize("courses", [False, True])
def test_the_install_block_links_the_offline_bundle(registry, monkeypatch, courses) -> None:
    monkeypatch.setattr(era, "COURSES", courses)
    status, _, body = _get(f"{registry.base_url}/")
    assert status == HTTPStatus.OK
    page = body.decode("utf-8")
    assert "/install.sh" in page
    assert "href='/offline'" in page


@pytest.mark.tier2
def test_the_pool_serves_the_uninstaller(registry) -> None:
    status, _, body = _get(f"{registry.base_url}/uninstall.sh")
    assert status == HTTPStatus.OK
    assert body.startswith(b"#!/usr/bin/env bash") and "hashpass удалён".encode() in body
