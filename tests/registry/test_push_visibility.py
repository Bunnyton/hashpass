"""
Tier2: a push asks who sees the image on the pool -- everyone, or only its people.

User 2026-10-25: «при пуше пускай спрашивает — приватный или публичный образ». Enter keeps what
the pool has; `--public` / `--private` answer without the question (scripts); someone else's
image goes as a proposal and is not asked about.
"""
import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.registry.revisions import RepoIndex
from tests.registry.test_cli_revisions import _login, _seed


def _io(answers: list[str | None], asked: list[str]) -> cli.Io:
    def read(prompt: str) -> str | None:
        asked.append(prompt)
        return answers.pop(0) if answers else None
    return cli.Io(read=read, write=lambda _s: None, clock=lambda: "")


def _visibility(registry, name: str) -> str:
    return RepoIndex(registry.store.root / ".repos", name).visibility


@pytest.mark.tier2
@pytest.mark.parametrize(("answer", "want"), [("2", "private"), ("приватный", "private"),
                                              ("", "public"), (None, "public")])
def test_the_push_asks_and_sets_the_visibility(registry, tmp_path, monkeypatch, answer, want) -> None:
    env = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    _seed(ImageStore(env.images), tmp_path, "bob/lab", "one")
    asked: list[str] = []
    assert cli.cmd_push(env, "bob/lab:1", registry.base_url, io=_io([answer], asked)) == 0
    assert len(asked) == 1 and "приватный" in asked[0] and "публичный" in asked[0]
    assert _visibility(registry, "bob/lab") == want


@pytest.mark.tier2
def test_enter_keeps_a_private_image_private(registry, tmp_path, monkeypatch) -> None:
    env = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    local = ImageStore(env.images)
    _seed(local, tmp_path, "bob/lab", "one")
    cli.cmd_push(env, "bob/lab:1", registry.base_url, visibility="private")
    _seed(local, tmp_path, "bob/lab", "two")
    asked: list[str] = []
    cli.cmd_push(env, "bob/lab:1", registry.base_url, io=_io([""], asked))
    assert "сейчас: приватный" in asked[0]
    assert _visibility(registry, "bob/lab") == "private"


@pytest.mark.tier2
def test_a_flag_answers_without_the_question(registry, tmp_path, monkeypatch) -> None:
    env = _login(registry, tmp_path, monkeypatch, "bob", "bob")
    _seed(ImageStore(env.images), tmp_path, "bob/lab", "one")
    asked: list[str] = []
    cli.cmd_push(env, "bob/lab:1", registry.base_url, io=_io([], asked), visibility="private")
    assert asked == []
    assert _visibility(registry, "bob/lab") == "private"
