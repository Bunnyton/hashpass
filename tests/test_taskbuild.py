from dataclasses import replace

import pytest

import hashpass.taskbuild as tb
from hashpass.canon.capture import FileState
from hashpass.imagestore.store import ImageStore
from hashpass.recipe.model import (
    ExecAction,
    Recipe,
    SayAction,
    Settings,
    ShowFileAction,
    TriesCond,
    Voice,
)
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import _build_meta, build_task
from hashpass.taskcode.bundle import load_bundle
from hashpass.taskcode.derive import StageChecks
from hashpass.taskstore import load_task, meta_from_dict, meta_to_dict

_DERIVED = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt

stage "count them"
  solve wc -l < /errors.txt > /count.txt
  observe /count.txt
"""


@pytest.mark.tier3
def test_build_task_derives_and_stores_artifacts(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    stored = build_task(parse_recipe(_DERIVED), store, base_tar=base_tar,
                        workdir=tmp_path / "bt", passes=2)
    # image built + stored
    assert store.exists("logtask:1")
    # bundle: two derived stages, each canonical carries a real signal
    assert (stored.bundle_dir / "checks.json").exists()
    checks = load_bundle(stored.bundle_dir).checks
    assert checks.task_id == "logtask"
    assert len(checks.stages) == 2  # noqa: PLR2004
    assert any(k != "<output>" for k in checks.stages[0].canonical)
    # hidden /hp staged with the bundle under task/
    assert (stored.hp_src_dir / "task" / "checks.json").exists()
    assert (stored.hp_src_dir / "state.json").read_text(encoding="utf-8") == "{}"
    # meta records derived acceptance for both stages
    meta = load_task("logtask:1", store).meta
    assert [s.acceptance for s in meta.stages] == ["derived", "derived"]
    assert meta.image_ref == "logtask:1"


@pytest.mark.tier1
def test_build_task_rejects_passes_below_two(tmp_path):
    store = ImageStore(tmp_path / "images")
    recipe = parse_recipe('image t:1\nstage "x"\n  solve echo hi\n  observe o\n')
    # guard fires before any build/nspawn, so the (absent) base_tar is never read
    with pytest.raises(ValueError, match="passes must be >= 2"):
        build_task(recipe, store, base_tar=tmp_path / "none.tar", workdir=tmp_path / "b", passes=1)


_RECIPE = (
    'image demo:1\n'
    'settings\n  type-mode dramatic\n  type-speed 30\n'
    'voice\n  hello say "hi"\n  bye exec bye.sh\n'
    'react on command exec watch.sh\n'
    'stage "one"\n'
    '  solve echo hi\n  observe o\n'
    '  on enter exec seed.sh\n'
    '  on pass say "nice"\n'
    '  on pass show file art/ok.txt\n'
    '  hint tries 3 say "try -r"\n'
)


@pytest.mark.tier1
def test_build_meta_carries_actions_hints_voice_settings_react():
    meta = _build_meta("demo:1", parse_recipe(_RECIPE), ["derived"])
    s = meta.stages[0]
    assert s.on_enter == (ExecAction("seed.sh"),)
    assert s.on_pass == (SayAction("nice"), ShowFileAction("art/ok.txt"))
    assert s.hints[0].condition == TriesCond(3)
    assert s.hints[0].action == SayAction("try -r")
    assert meta.voice == Voice(hello=(SayAction("hi"),), bye=(ExecAction("bye.sh"),))
    assert meta.settings == Settings(type_mode="dramatic", type_speed=30)
    assert meta.react == (ExecAction("watch.sh"),)
    # and the whole thing survives the JSON round-trip
    assert meta_from_dict(meta_to_dict(meta)) == meta


# --- per-stage derivation cache: only stages whose inputs changed re-run their solve -----------
# Stage i is derived from the image + solve of stages 0..i-1 + its own grading fields, so editing
# the LAST stage re-derives only it, and a hint/message edit re-derives nothing.

_CACHED = """\
image ctask:1
hidden hid

stage "first"
  solve echo a > /a.txt
  observe /a.txt
  hint tries 2 say "look around"

stage "second"
  solve echo b > /b.txt
  observe /b.txt
"""


@pytest.fixture
def fake_build(tmp_path, monkeypatch):
    """Stub the image build + per-stage derivation; record which stages actually derive."""
    calls = {"derived": [], "image_key": "img-key-1"}

    def build(recipe, store, **_kw: object) -> object:
        layer = tmp_path / "layer"
        layer.mkdir(exist_ok=True)
        return store.save(recipe.name, recipe.version, layer, recipe.parents,
                          build_key=calls["image_key"])

    def derive_stage(_factory, task, i, *_a: object, **_kw: object) -> StageChecks:
        calls["derived"].append(i)
        return StageChecks(canonical={f"s{i}": FileState("file", task.stages[i].commands[0])})

    monkeypatch.setattr(tb, "build", build)
    monkeypatch.setattr(tb, "_derive_stage", derive_stage)
    monkeypatch.setattr(tb, "resolve_lowers", lambda *_a, **_k: [])
    (tmp_path / "hid").mkdir()
    (tmp_path / "hid" / "grade").write_text("v1", encoding="utf-8")
    return calls


def _cached_recipe(tmp_path, text=_CACHED) -> Recipe:
    r = parse_recipe(text)
    return replace(r, hidden=str(tmp_path / "hid"))


def _build(tmp_path, recipe, store, progress=None) -> object:
    return build_task(recipe, store, base=tmp_path / "base", workdir=tmp_path / "bt",
                      sudo=False, progress=progress)


def _rebuild(tmp_path, fake_build, text=_CACHED) -> tuple:
    """Build once, reset the call log, build again with `text`; return (rebuilt-stages, task)."""
    store = ImageStore(tmp_path / "images")
    _build(tmp_path, _cached_recipe(tmp_path), store)
    fake_build["derived"].clear()
    task = _build(tmp_path, _cached_recipe(tmp_path, text), store)
    return fake_build["derived"], task


@pytest.mark.tier1
def test_unchanged_task_rebuild_derives_nothing(tmp_path, fake_build):
    derived, task = _rebuild(tmp_path, fake_build)
    assert derived == []
    checks = load_bundle(task.bundle_dir).checks
    assert [st.canonical for st in checks.stages] == [
        {"s0": FileState("file", "echo a > /a.txt")}, {"s1": FileState("file", "echo b > /b.txt")}]


@pytest.mark.tier1
def test_changed_last_stage_rederives_only_it(tmp_path, fake_build):
    derived, task = _rebuild(tmp_path, fake_build, _CACHED.replace("echo b", "echo B"))
    assert derived == [1]
    assert load_bundle(task.bundle_dir).checks.stages[1].canonical == {
        "s1": FileState("file", "echo B > /b.txt")}


@pytest.mark.tier1
def test_changed_first_stage_solve_rederives_later_stages_too(tmp_path, fake_build):
    derived, _ = _rebuild(tmp_path, fake_build, _CACHED.replace("echo a", "echo A"))
    assert derived == [0, 1]


@pytest.mark.tier1
def test_hint_and_message_edit_rederives_nothing_but_updates_meta(tmp_path, fake_build):
    text = _CACHED.replace("look around", "try ls").replace('"second"', '"второй"')
    derived, task = _rebuild(tmp_path, fake_build, text)
    assert derived == []
    assert task.meta.stages[1].message == "второй"


@pytest.mark.tier1
def test_hidden_edit_rederives_nothing_but_restages_hp(tmp_path, fake_build):
    store = ImageStore(tmp_path / "images")
    _build(tmp_path, _cached_recipe(tmp_path), store)
    fake_build["derived"].clear()
    (tmp_path / "hid" / "grade").write_text("v2", encoding="utf-8")
    task = _build(tmp_path, _cached_recipe(tmp_path), store)
    assert fake_build["derived"] == []
    assert (task.hp_src_dir / "work" / "grade").read_text(encoding="utf-8") == "v2"


@pytest.mark.tier1
def test_rebuilt_image_rederives_every_stage(tmp_path, fake_build):
    store = ImageStore(tmp_path / "images")
    _build(tmp_path, _cached_recipe(tmp_path), store)
    fake_build["derived"].clear()
    fake_build["image_key"] = "img-key-2"
    _build(tmp_path, _cached_recipe(tmp_path), store)
    assert fake_build["derived"] == [0, 1]
