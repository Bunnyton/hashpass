"""Tier1: the source viewer in hashpass -- a task's files from the pool, one by one."""
from __future__ import annotations

import asyncio
import urllib.error
from typing import TYPE_CHECKING

import pytest

from hashpass.viewer import SourceViewer, listing_or_taskfile
from tests.test_tui import _env
from tests.test_tui_moderation import ENTRIES, _ModClient

if TYPE_CHECKING:
    from pathlib import Path

FILES = {"Taskfile": b'stage\n  say "\xd1\x86\xd0\xb5\xd0\xbb\xd1\x8c"\n', "hp/check": b"#!/bin/sh\nexit 0\n",
         "data/blob.bin": b"\x00\xff\x00\xfe"}


class _SourceClient(_ModClient):
    def source_listing(self, ref: str, *, token: str | None = None) -> list[dict]:  # noqa: ARG002
        return [{"path": "Taskfile", "size": 20, "dir": False},
                {"path": "data", "size": 0, "dir": True},
                {"path": "data/blob.bin", "size": 4, "dir": False},
                {"path": "hp", "size": 0, "dir": True},
                {"path": "hp/check", "size": 17, "dir": False}]

    def source_file(self, ref: str, path: str, *, token: str | None = None) -> bytes:  # noqa: ARG002
        return FILES[path]


class _OldPool(_ModClient):
    def source_listing(self, ref: str, *, token: str | None = None) -> list[dict]:  # noqa: ARG002
        url = "/source"
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    def get_attachment(self, name: str, version: str, filename: str, *, token: str | None = None) -> bytes:  # noqa: ARG002
        return b"stage old\n" if filename == "Taskfile" else b""


@pytest.mark.tier1
def test_an_old_pool_shows_just_the_taskfile():
    files, fetch = listing_or_taskfile(_OldPool([], "author"), "bob/lab:1", "tok")
    assert [f["path"] for f in files] == ["Taskfile"]
    assert fetch("Taskfile") == b"stage old\n"


@pytest.mark.tier1
def test_v_opens_the_viewer_with_the_tree_and_a_file(tmp_path: Path):
    from hashpass.tui import PoolTUI  # noqa: PLC0415
    client = _SourceClient(ENTRIES, "author")

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", "bob", "tok")
        app.client = client
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import Tree  # noqa: PLC0415
            app.query_one("#tasks", Tree).move_cursor(app._leaf_nodes["bob/new:1"])  # noqa: SLF001
            await pilot.pause()
            await pilot.press("v")
            await pilot.pause()
            viewer = app.screen
            assert isinstance(viewer, SourceViewer)
            assert viewer.shown_paths() == ["Taskfile", "data", "data/blob.bin", "hp", "hp/check"]
            viewer.open_path("hp/check")
            await pilot.pause()
            assert "exit 0" in viewer.shown_text()
            viewer.open_path("Taskfile")
            await pilot.pause()
            assert 'say "цель"' in viewer.shown_text()
            viewer.open_path("data/blob.bin")
            await pilot.pause()
            assert "двоичный файл, 4 байт" in viewer.shown_text()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, SourceViewer)
            await pilot.press("q")

    asyncio.run(_drive())


@pytest.mark.tier1
def test_a_student_cannot_open_the_viewer(tmp_path: Path):
    from hashpass.tui import PoolTUI  # noqa: PLC0415

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", "kid", "tok")
        app.client = _SourceClient(ENTRIES, "student")
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause()
            assert app.check_action("view", ()) is False
            await pilot.press("q")

    asyncio.run(_drive())
