import pytest

from hashpass.recipe.model import (
    CmdCond,
    CopyStep,
    ExecAction,
    IdleCond,
    OutputCond,
    Recipe,
    RunStep,
    SayAction,
    Settings,
    ShowFileAction,
    StageSpec,
    TriesCond,
    Voice,
    image_ref,
)
from hashpass.recipe.parse import load_recipe, parse_recipe

_EXPECTED_TWO_STAGES = 2
_RECIPE = """\
# a phase-1 image recipe

image log-archive:1
from  base, coreutils-lab:1
copy  assets/ /home/student/
run   mkdir -p /var/log/app
run   touch /var/log/app/app.log
"""


@pytest.mark.tier1
def test_parse_full_recipe():
    recipe = parse_recipe(_RECIPE)
    assert recipe == Recipe(
        name="log-archive",
        version="1",
        parents=("base", "coreutils-lab:1"),
        steps=(
            CopyStep("assets/", "/home/student/"),
            RunStep("mkdir -p /var/log/app"),
            RunStep("touch /var/log/app/app.log"),
        ),
    )
    assert image_ref(recipe) == "log-archive:1"


@pytest.mark.tier1
def test_run_before_copy_keeps_source_order():
    recipe = parse_recipe("image t:1\nrun mkdir -p /opt/app\ncopy f /opt/app/\n")
    assert recipe.steps == (RunStep("mkdir -p /opt/app"), CopyStep("f", "/opt/app/"))


@pytest.mark.tier1
def test_missing_image_raises():
    with pytest.raises(ValueError, match="missing a required 'image"):
        parse_recipe("run echo hi\n")


@pytest.mark.tier1
def test_unknown_directive_raises():
    with pytest.raises(ValueError, match="unknown directive"):
        parse_recipe("image t:1\nfrobnicate stuff\n")


@pytest.mark.tier1
def test_load_recipe_from_disk(tmp_path):
    path = tmp_path / "Imagefile"
    path.write_text("image solo:2\n", encoding="utf-8")
    recipe = load_recipe(path)
    assert recipe.name == "solo"
    assert recipe.version == "2"
    assert recipe.parents == ()


_TASK = """\
image  log-archive:1
from   base, coreutils-lab
readme readme.txt
copy   assets/ /home/student/
run    mkdir -p /var/log/app
hidden grade/

stage "Collect ERROR lines into errors.txt"
  solve   grep -rh ERROR /var/log/app > errors.txt
  observe errors.txt
  exclude .cache *.log
  neutral ls cd cat pwd
  on enter exec seed.sh
  on pass  exec cheer.sh
  check    exec verify.sh
"""


@pytest.mark.tier1
def test_parse_task_recipe_full_stage():
    r = parse_recipe(_TASK)
    assert r.name == "log-archive"
    assert r.parents == ("base", "coreutils-lab")
    assert r.readme == "readme.txt"
    assert r.hidden == "grade/"
    assert r.steps == (CopyStep("assets/", "/home/student/"), RunStep("mkdir -p /var/log/app"))
    assert len(r.stages) == 1
    s = r.stages[0]
    assert s == StageSpec(
        message="Collect ERROR lines into errors.txt",
        solve=("grep -rh ERROR /var/log/app > errors.txt",),
        observe=("errors.txt",),
        exclude=(".cache", "*.log"),
        neutral=("ls", "cd", "cat", "pwd"),
        check=ExecAction("verify.sh"),
        on_enter=(ExecAction("seed.sh"),),
        on_pass=(ExecAction("cheer.sh"),),
    )


@pytest.mark.tier1
def test_parse_solve_block_and_multiple_stages():
    text = (
        "image pipe:1\n\n"
        'stage "one"\n'
        "  solve:\n"
        "    sort f > s\n"
        "    uniq s > u\n"
        "  observe u\n"
        "  on pass exec a.sh\n"
        "  on pass exec b.sh\n\n"
        'stage "two"\n'
        "  solve wc -l < u > n\n"
        "  observe n\n"
    )
    r = parse_recipe(text)
    assert len(r.stages) == _EXPECTED_TWO_STAGES
    assert r.stages[0].solve == ("sort f > s", "uniq s > u")
    assert r.stages[0].on_pass == (ExecAction("a.sh"), ExecAction("b.sh"))
    assert r.stages[1].solve == ("wc -l < u > n",)


@pytest.mark.tier1
def test_plain_image_recipe_has_no_stages():
    r = parse_recipe("image solo:2\nrun echo hi\n")
    assert r.stages == ()
    assert r.hidden is None


@pytest.mark.tier1
@pytest.mark.parametrize(
    ("text", "match"),
    [
        ('image t:1\nstage "x"\n  observe f\n', "no 'solve'"),
        ('image t:1\nstage "x"\n  solve echo hi\n  check verify.sh\n', "expected an 'exec"),
        ("image t:1\n  solve echo hi\n", "unexpected indentation"),
        ('image t:1\nstage "x"\n  solve:\n  observe f\n', "empty 'solve:' block"),
        ('image t:1\nstage "x"\n  solve: echo hi\n    echo bye\n', "no inline content"),
        ('image t:1\nstage "x"\n  solve: echo hi\n', "no inline content"),
        ('image t:1\nstage "x"\n  solve echo hi\n  on exit exec x.sh\n', "unknown stage event"),
        ("image t:1\nhidden a/\nhidden b/\n", "duplicate 'hidden'"),
        ("image t:1\nreadme a.txt\nreadme b.txt\n", "duplicate 'readme'"),
        ('image t:1\nstage "x"\n  solve echo hi\n  check exec a.sh\n  check exec b.sh\n', "duplicate 'check'"),
        ("image t:1\nhidden a/ b/\n", "single <src>"),
        ("image t:1\nreadme a b\n", "single <file>"),
    ],
)
def test_task_parse_errors(text, match):
    with pytest.raises(ValueError, match=match):
        parse_recipe(text)


@pytest.mark.tier1
def test_solve_block_still_parses_after_inline_guard():
    r = parse_recipe('image t:1\nstage "x"\n  solve:\n    echo one\n    echo two\n  observe o\n')
    assert r.stages[0].solve == ("echo one", "echo two")


@pytest.mark.tier1
def test_hint_conditions_and_actions():
    text = (
        'image t:1\nstage "x"\n  solve echo hi\n'
        '  hint tries 5 say "look in /var/log 👀"\n'
        '  hint cmd grep missing -i say "add -i"\n'
        "  hint idle 90 exec idle.sh\n"
        '  hint output "ERROR" show file art/hit.txt\n'
    )
    hints = parse_recipe(text).stages[0].hints
    assert hints[0].condition == TriesCond(5)
    assert hints[0].action == SayAction("look in /var/log 👀")
    assert hints[1].condition == CmdCond("grep", (), ("-i",))
    assert hints[1].action == SayAction("add -i")
    assert hints[2].condition == IdleCond(90.0)
    assert hints[2].action == ExecAction("idle.sh")
    assert hints[3].condition == OutputCond("ERROR")
    assert hints[3].action == ShowFileAction("art/hit.txt")


@pytest.mark.tier1
def test_cmd_condition_has_and_missing():
    text = ('image t:1\nstage "x"\n  solve echo hi\n'
            "  hint cmd grep has -r missing -i exec f.sh\n")
    cond = parse_recipe(text).stages[0].hints[0].condition
    assert cond == CmdCond("grep", ("-r",), ("-i",))


@pytest.mark.tier1
def test_on_enter_pass_say_show_and_dramatic():
    text = (
        'image t:1\nstage "x"\n  solve echo hi\n'
        "  on enter exec seed.sh\n"
        '  on pass say "first!"\n'
        '  on pass say dramatic "the end."\n'
        "  on pass show file art/ok.txt\n"
    )
    s = parse_recipe(text).stages[0]
    assert s.on_enter == (ExecAction("seed.sh"),)
    assert s.on_pass == (SayAction("first!"), SayAction("the end.", dramatic=True),
                         ShowFileAction("art/ok.txt"))


@pytest.mark.tier1
def test_voice_settings_react_top_level():
    text = (
        "image t:1\n"
        "settings\n"
        "  type-mode dramatic\n"
        "  type-speed 60\n"
        "  pager on\n"
        "voice\n"
        '  hello say "yo"\n'
        "  hello exec greet.sh\n"
        '  bye say "gg"\n'
        "react on command exec watch.sh\n"
        'stage "x"\n  solve echo hi\n'
    )
    r = parse_recipe(text)
    assert r.settings == Settings(type_mode="dramatic", type_speed=60, pager=True)
    assert r.voice == Voice(hello=(SayAction("yo"), ExecAction("greet.sh")), bye=(SayAction("gg"),))
    assert r.react == (ExecAction("watch.sh"),)


@pytest.mark.tier1
def test_backcompat_pure_image_unchanged():
    r = parse_recipe("image solo:2\nrun echo hi\n")
    assert r == Recipe("solo", "2", (), (r.steps[0],))
    assert r.voice == Voice()
    assert r.settings == Settings()
    assert r.react == ()


@pytest.mark.tier1
def test_backcompat_flipped_reserved_cases_now_parse():
    # was: parse_recipe("image t:1\nvoice\n") raised "phase 3"
    r = parse_recipe('image t:1\nvoice\n  hello say "hi"\n')
    assert r.voice.hello == (SayAction("hi"),)
    # was: 'hint tries 3 say hi' raised "phase 3"
    r1 = parse_recipe('image t:1\nstage "x"\n  solve echo hi\n  hint tries 3 say "hi"\n')
    assert r1.stages[0].hints[0].condition == TriesCond(3)
    # was: 'on pass say "yo"' raised "phase 3"
    r2 = parse_recipe('image t:1\nstage "x"\n  solve echo hi\n  on pass say "yo"\n')
    assert r2.stages[0].on_pass == (SayAction("yo"),)


@pytest.mark.tier1
@pytest.mark.parametrize(
    ("text", "match"),
    [
        ('image t:1\nstage "x"\n  solve echo hi\n  hint bogus 3 say "hi"\n', "unknown hint condition"),
        ('image t:1\nstage "x"\n  solve echo hi\n  hint tries 3\n', "requires an action"),
        ('image t:1\nstage "x"\n  solve echo hi\n  hint tries x say "h"\n', "needs an integer"),
        ('image t:1\nstage "x"\n  solve echo hi\n  hint output "ERR\n', "unterminated"),
        ('image t:1\nstage "x"\n  solve echo hi\n  check say "no"\n', "requires an 'exec"),
        ('image t:1\nstage "x"\n  solve echo hi\n  on pass show art.txt\n', "show file"),
        ("image t:1\nsettings\n  type-mode turbo\n", "type-mode must be"),
        ("image t:1\nsettings\n  pager on\nsettings\n  pager off\n", "duplicate 'settings'"),
        ('image t:1\nvoice\n  yo say "hi"\n', "unknown voice directive"),
        ("image t:1\nreact do exec f.sh\n", "react must be"),
        ('image t:1\nstage "x"\n  solve echo hi\n  say "loose"\n', "unknown directive"),
    ],
)
def test_parse_errors(text, match):
    with pytest.raises(ValueError, match=match):
        parse_recipe(text)
