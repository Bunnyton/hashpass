"""Tier1: moderation in hashpass -- badges, approve/reject (admin), delete own, «Отклонённые»."""
from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import pytest

from hashpass.tui import PoolTUI, TaskRow
from tests.test_tui import _env, _leaves, _StubClient

if TYPE_CHECKING:
    from pathlib import Path


class _ModClient(_StubClient):
    """A stub pool that records moderation calls and answers /me with a role."""

    def __init__(self, entries: list[dict], role: str) -> None:
        super().__init__(entries)
        self.role = role
        self.calls: list[tuple] = []

    def me(self, *, token: str) -> dict:  # noqa: ARG002
        return {"role": self.role}

    def approve(self, ref: str, *, digest: str | None = None, token: str | None = None) -> None:  # noqa: ARG002
        self.calls.append(("approve", ref))
        self.approved_digest = digest

    def set_block_open(self, block_id: str, *, open_: bool, token: str | None = None) -> None:  # noqa: ARG002
        self.calls.append(("block", block_id))

    def reject(self, ref: str, reason: str = "", *, token: str | None = None) -> None:  # noqa: ARG002
        self.calls.append(("reject", ref, reason))

    def delete_task(self, ref: str, *, token: str | None = None) -> None:  # noqa: ARG002
        self.calls.append(("delete", ref))


def _row(ref: str, **kw: object) -> dict:
    return {"number": 1, "ref": ref, "block_name": "Б", "available": True, "digest": "",
            "owner": ref.split("/", 1)[0], **kw}


ENTRIES = [
    _row("bob/new:1", state="pending", available=False, preview=True, digest="d-new"),
    _row("bob/upd:1", state="pending", pending_update=True),
    _row("bob/bad:1", state="rejected", reason="нет финала", rejected=True, preview=True,
         available=False, block_name="Отклонённые", block_id="rejected",
         expires_at=time.time() + 3 * 86400 - 60),
    _row("alice/her:1", state="approved"),
]


def _run(tmp_path: Path, user: str, role: str, steps) -> _ModClient:
    client = _ModClient(ENTRIES, role)

    async def _drive() -> None:
        app = PoolTUI(_env(tmp_path), "http://pool.example", user, "tok")
        app.client = client
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.pause()
            await steps(app, pilot)
            await pilot.press("q")

    asyncio.run(_drive())
    return client


async def _goto(app: PoolTUI, pilot, ref: str) -> None:
    from textual.widgets import Tree  # noqa: PLC0415
    tree = app.query_one("#tasks", Tree)
    tree.move_cursor(app._leaf_nodes[ref])  # noqa: SLF001
    await pilot.pause()


@pytest.mark.tier1
def test_badges_tell_the_moderation_state():
    pending = TaskRow(ref="b/x:1", number=1, block="Б", available=False, digest="",
                      preview=True, moderation="pending")
    assert "на проверке" in pending.tree_label()
    upd = TaskRow(ref="b/x:1", number=1, block="Б", available=True, digest="",
                  moderation="pending", pending_update=True)
    assert "обновление на проверке" in upd.tree_label()
    bad = TaskRow(ref="b/x:1", number=1, block="Отклонённые", available=False, digest="",
                  preview=True, moderation="rejected", reason="нет финала",
                  expires_at=time.time() + 3 * 86400 - 60)
    assert "отклонено: нет финала" in bad.tree_label() and "удалится через 3 дн." in bad.tree_label()


@pytest.mark.tier1
def test_admin_approves_and_rejects_with_a_reason(tmp_path):
    async def steps(app, pilot) -> None:
        await _goto(app, pilot, "bob/new:1")
        await pilot.press("a")
        await pilot.pause()
        await _goto(app, pilot, "bob/upd:1")
        await pilot.press("n")
        await pilot.pause()
        for ch in "поправь подсказки":
            await pilot.press("space" if ch == " " else ch)
        await pilot.press("enter")
        await pilot.pause()

    client = _run(tmp_path, "root", "admin", steps)
    assert ("approve", "bob/new:1") in client.calls
    assert ("reject", "bob/upd:1", "поправь подсказки") in client.calls


@pytest.mark.tier1
def test_author_deletes_own_task_only_after_confirming(tmp_path):
    async def steps(app, pilot) -> None:
        await _goto(app, pilot, "alice/her:1")
        await pilot.press("delete")                    # not bob's: refused, nothing asked
        await pilot.pause()
        await _goto(app, pilot, "bob/new:1")
        await pilot.press("delete")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

    client = _run(tmp_path, "bob", "author", steps)
    assert client.calls == [("delete", "bob/new:1")]


@pytest.mark.tier1
def test_rejected_block_toggles_and_is_remembered(tmp_path):
    async def steps(app, pilot) -> None:
        assert any("bob/bad:1" in s for s in _leaves(app))         # shown by default
        await pilot.press("z")
        await pilot.pause()
        assert not any("bob/bad:1" in s for s in _leaves(app))

    _run(tmp_path, "bob", "author", steps)
    saved = json.loads((tmp_path / "root" / "tui.json").read_text(encoding="utf-8"))
    assert saved["show_rejected"] is False


@pytest.mark.tier1
def test_a_student_has_no_moderation_keys(tmp_path):
    async def steps(app, _pilot) -> None:
        for action in ("approve", "reject", "delete_task", "toggle_rejected"):
            assert app.check_action(action, ()) is False

    client = _run(tmp_path, "kid", "student", steps)
    assert client.calls == []


@pytest.mark.tier1
def test_approve_sends_the_digest_the_admin_saw(tmp_path):
    async def steps(app, pilot) -> None:
        await _goto(app, pilot, "bob/new:1")
        await pilot.press("a")
        await pilot.pause()

    client = _run(tmp_path, "root", "admin", steps)
    assert client.approved_digest == "d-new"


@pytest.mark.tier1
def test_o_on_the_rejected_block_explains_instead_of_failing(tmp_path):
    async def steps(app, pilot) -> None:
        await _goto(app, pilot, "bob/bad:1")
        await pilot.press("o")
        await pilot.pause()

    client = _run(tmp_path, "root", "admin", steps)
    assert ("block", "rejected") not in client.calls
