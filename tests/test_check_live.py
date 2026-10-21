"""Tier1: `check live` — a stage accepted by a command run inside the student's live machine."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import build_task
from hashpass.taskcode.bundle import Bundle, dump_bundle
from hashpass.taskcode.derive import DerivedChecks, StageChecks
from hashpass.taskrun import TaskSession
from hashpass.taskstore import StageMeta, StoredTask, TaskMeta
from tests.test_taskbuild import (
    fake_build,  # noqa: F401 -- fixture (stubbed image build + derive)
)

_LIVE = """\
image livetask:1

stage
  say "Запусти сайт"
  solve docker run -d -p 8080:80 web
  check live docker ps | grep -q web
"""


@pytest.mark.tier1
def test_live_stage_is_not_derived_and_carries_its_command(tmp_path, fake_build):  # noqa: F811
    task = build_task(parse_recipe(_LIVE), ImageStore(tmp_path / "images"), base=tmp_path / "base",
                      workdir=tmp_path / "bt", sudo=False)
    assert fake_build["derived"] == []          # a container cannot be derived on a throwaway run
    sm = task.meta.stages[0]
    assert sm.acceptance == "live"
    assert sm.check == "docker ps | grep -q web"


def _session(tmp_path: Path, rcs: list[int], *, accept_cmds: tuple[str, ...] = ()) -> tuple:
    bundle = tmp_path / "bundle"
    dump_bundle(Bundle(checks=DerivedChecks(task_id="t", stages=(StageChecks(canonical={}),)),
                       conditions={}, hints={}), bundle)
    stage = StageMeta(message="go", neutral=(), check="docker ps | grep -q web", on_enter=(),
                      on_pass=(), acceptance="live", accept_cmds=accept_cmds)
    stored = StoredTask(ref="t:1", image=None, bundle_dir=bundle, hp_src_dir=tmp_path / "src",
                        meta=TaskMeta(image_ref="t:1", stages=(stage,)))
    hp = tmp_path / "hp"
    hp.mkdir()
    sent: list[str] = []
    runner = SimpleNamespace(rootfs=tmp_path / "rootfs",
                             check_live=lambda script: sent.append(script) or rcs.pop(0))
    return TaskSession(stored, runner, hp, student_id="s", nonce="n",
                       sink=lambda _s: None, sleep=lambda _s: None), sent


@pytest.mark.tier1
def test_live_stage_passes_only_when_the_live_command_succeeds(tmp_path):
    s, sent = _session(tmp_path, [1, 0])
    assert s.observe("docker run web", ts="2026-10-21T10:00:00").advanced is False
    assert s.observe("docker run -d -p 8080:80 web", ts="2026-10-21T10:00:05").advanced is True
    assert sent == ["docker ps | grep -q web"] * 2


@pytest.mark.tier1
def test_live_check_adds_up_with_accept_cmd(tmp_path):
    s, sent = _session(tmp_path, [0], accept_cmds=("docker ps",))
    assert s.observe("ls", ts="2026-10-21T10:00:00").advanced is False
    assert sent == []                               # the command gate failed first: no live call
    assert s.observe("docker ps", ts="2026-10-21T10:00:05").advanced is True
