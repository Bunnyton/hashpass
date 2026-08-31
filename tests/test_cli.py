from pathlib import Path

import pytest

from hashpass import cli
from hashpass.imagestore.store import ImageStore
from hashpass.progress import current_stage, mark_passed_local, new_progress
from hashpass.taskrun import FeedResult


@pytest.mark.tier1
def test_resolve_root_prefers_env_then_default_home(tmp_path):
    assert cli.resolve_root({"HASHPASS_HOME": "/x/y"},
                            default_home=tmp_path) == __import__("pathlib").Path("/x/y")
    assert cli.resolve_root({}, default_home=tmp_path) == tmp_path / ".hashpass"


@pytest.mark.tier1
def test_home_sub_paths():
    h = cli.Home(Path("/home/u/.hashpass"))
    assert h.images == Path("/home/u/.hashpass/images")
    assert h.base_tar == Path("/home/u/.hashpass/base/rootfs.tar")
    assert h.creds == Path("/home/u/.hashpass/creds.json")
    assert h.work == Path("/home/u/.hashpass/work")


@pytest.mark.tier1
def test_build_env_creates_images_dir(tmp_path):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    assert env.images.is_dir()


class _Completed:
    stdout = "cid123\n"


@pytest.mark.tier1
def test_ensure_base_tar_shortcircuits_when_present(tmp_path):
    dest = tmp_path / "rootfs.tar"
    dest.write_text("x", encoding="utf-8")
    calls = []
    cli.ensure_base_tar(dest, run=lambda *a, **_k: calls.append(a), which=lambda _n: "docker")
    assert calls == []


@pytest.mark.tier1
def test_ensure_base_tar_requires_docker(tmp_path):
    with pytest.raises(RuntimeError, match="docker is required"):
        cli.ensure_base_tar(tmp_path / "base" / "rootfs.tar",
                            run=lambda *_a, **_k: _Completed(), which=lambda _n: None)


@pytest.mark.tier1
def test_ensure_base_tar_export_argv(tmp_path):
    dest = tmp_path / "base" / "rootfs.tar"
    calls = []

    def fake_run(argv: list, **_kwargs: object) -> _Completed:
        calls.append(argv)
        return _Completed()

    cli.ensure_base_tar(dest, run=fake_run, which=lambda _n: "/usr/bin/docker")
    assert calls[0] == ["docker", "create", "debian:trixie-slim"]
    assert calls[1] == ["docker", "export", "cid123", "-o", str(dest)]
    assert calls[2] == ["docker", "rm", "cid123"]
    assert dest.parent.exists()


def _seed_image(store: ImageStore, tmp_path, name: str, *, task: bool = False) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, "1", src, ())
    if task:
        (store.get(f"{name}:1").layer.parent / "task").mkdir()


@pytest.mark.tier1
def test_format_image_rows_empty_is_header_only():
    assert cli.format_image_rows([]) == "REF  KIND\n"


@pytest.mark.tier1
def test_format_image_rows_aligns_columns():
    out = cli.format_image_rows([("log-archive:1", "task"), ("base:latest", "image")])
    assert out == ("REF            KIND\n"
                   "log-archive:1  task\n"
                   "base:latest    image\n")


@pytest.mark.tier1
def test_kind_detects_task_vs_image(tmp_path):
    store = ImageStore(tmp_path / "images")
    _seed_image(store, tmp_path, "base")
    _seed_image(store, tmp_path, "lab", task=True)
    assert cli._kind(store, "lab:1") == "task"  # noqa: SLF001
    assert cli._kind(store, "base:1") == "image"  # noqa: SLF001


@pytest.mark.tier1
def test_cmd_images_prints_table(tmp_path, capsys):
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    store = ImageStore(env.images)
    _seed_image(store, tmp_path, "base")
    _seed_image(store, tmp_path, "lab", task=True)
    assert cli.cmd_images(env) == 0
    out = capsys.readouterr().out
    assert out == cli.format_image_rows([("base:1", "image"), ("lab:1", "task")])


@pytest.mark.tier1
@pytest.mark.parametrize(
    ("text", "expected"),
    [("1", 0), ("3", 2), ("  2 ", 1), ("0", None), ("4", None),
     ("", None), (None, None), ("x", None)],
)
def test_select_index(text, expected):
    assert cli.select_index(text, 3) == expected


class _FakeSession:
    """A container-free stand-in for TaskSession: real progress, scripted outcomes, a sink."""

    def __init__(self, task_id: str, n_stages: int, script: dict, sink) -> None:
        self.task_id = task_id
        self.progress = new_progress(task_id, n_stages)
        self._script = script            # command -> "advance" | ("hint", text)
        self._sink = sink
        self.entered = 0

    def enter(self) -> list:
        self.entered += 1
        self._sink("<hello>\n")
        return []

    def feed(self, command: str, *, ts: str) -> FeedResult:  # noqa: ARG002
        stage = current_stage(self.progress)
        outcome = self._script.get(command)
        if outcome == "advance":
            mark_passed_local(self.progress, stage)
            return FeedResult(advanced=True, stage=stage, local_key=f"key{stage}")
        if isinstance(outcome, tuple):
            self._sink(outcome[1] + "\n")   # the real Renderer types the hint here
            return FeedResult(advanced=False, stage=stage, local_key=None, hint=outcome[1])
        return FeedResult(advanced=False, stage=stage, local_key=None)


@pytest.mark.tier1
def test_interact_solves_with_hint_and_completion():
    writes, sinks, prompts = [], [], []
    session = _FakeSession("demo", 2,
                           {"solve0": "advance", "solve1": "advance", "bad": ("hint", "try grep")},
                           sinks.append)
    lines = iter(["bad", "solve0", "solve1"])
    cli.interact(session, read=lambda p: prompts.append(p) or next(lines),
                 write=writes.append, clock=lambda: "2026-01-01T00:00:00")
    assert session.entered == 1
    assert prompts == ["hashpass:demo [stage 1/2]$ ",
                       "hashpass:demo [stage 1/2]$ ",
                       "hashpass:demo [stage 2/2]$ "]
    assert "<hello>\n" in sinks
    assert "try grep\n" in sinks                       # hint reached the sink, not double-printed
    assert writes == ["✓ stage passed  key0\n",
                      "✓ stage passed  key1\n",
                      "✓ all stages passed — task complete\n"]


@pytest.mark.tier1
@pytest.mark.parametrize("stopper", ["exit", None])
def test_interact_stops_on_stop_word_and_eof(stopper):
    writes = []
    session = _FakeSession("t", 1, {}, lambda _s: None)
    cli.interact(session, read=lambda _p: stopper, write=writes.append, clock=lambda: "t")
    assert session.entered == 1
    assert writes == []
