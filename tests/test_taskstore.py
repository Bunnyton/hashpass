"""Validate rich StageMeta/TaskMeta JSON round-trip (actions, hints, voice, settings, react)."""
import json

import pytest

from hashpass.recipe.model import (
    CmdCond,
    ExecAction,
    HintRule,
    IdleCond,
    OutputCond,
    SayAction,
    Settings,
    ShowFileAction,
    TriesCond,
    Voice,
)
from hashpass.taskstore import (
    StageMeta,
    TaskMeta,
    meta_from_dict,
    meta_to_dict,
)


def _meta() -> TaskMeta:
    return TaskMeta(
        image_ref="log-archive:1",
        stages=(
            StageMeta(
                message="collect", neutral=("ls", "cd"), check=None,
                on_enter=(ExecAction("seed.sh"),),
                on_pass=(SayAction("first!"), ShowFileAction("art/ok.txt")),
                acceptance="derived",
                hints=(
                    HintRule(TriesCond(5), SayAction("look", dramatic=True)),
                    HintRule(CmdCond("grep", ("-r",), ("-i",)), ExecAction("h.sh")),
                    HintRule(IdleCond(90.0), ExecAction("idle.sh")),
                    HintRule(OutputCond("ERROR"), ShowFileAction("art/hit.txt")),
                ),
            ),
            StageMeta(message="verify", neutral=(), check="verify.sh",
                      on_enter=(), on_pass=(), acceptance="handler"),
            StageMeta(message="run it", neutral=(), check=None, on_enter=(), on_pass=(),
                      acceptance="command", accept_cmds=("grep -r ERROR", "rg ERROR")),
        ),
        readme="readme.txt",
        voice=Voice(hello=(SayAction("yo"), ExecAction("greet.sh")), bye=(SayAction("gg"),)),
        settings=Settings(type_mode="dramatic", type_speed=60, pager=True, similarity=80),
        react=(ExecAction("watch.sh"),),
    )


@pytest.mark.tier1
def test_meta_dict_round_trip():
    meta = _meta()
    assert meta_from_dict(meta_to_dict(meta)) == meta


@pytest.mark.tier1
def test_meta_json_string_round_trip():
    meta = _meta()
    assert meta_from_dict(json.loads(json.dumps(meta_to_dict(meta)))) == meta


@pytest.mark.tier1
def test_backcompat_missing_new_keys_default():
    m = meta_from_dict({"image_ref": "x:1", "stages": []})
    assert m.readme is None
    assert m.voice == Voice()
    assert m.settings == Settings()
    assert m.react == ()
