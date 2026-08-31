import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe
from hashpass.taskbuild import build_task
from hashpass.taskrun import run_task

_DERIVED = """\
image logtask:1
run mkdir -p /var/log/app
run printf 'ERROR one\\nok\\nERROR two\\n' > /var/log/app/a.log

stage "collect ERROR lines"
  solve grep -rh ERROR /var/log/app > /errors.txt
  observe /errors.txt
"""


@pytest.mark.tier3
def test_e2e_derived_stage_accepts_and_rejects(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_DERIVED), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    ts = "2026-08-31T00:00:00"
    session = run_task("logtask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        wrong = session.feed("echo nope > /errors.txt", ts=ts)
        assert wrong.advanced is False
        assert wrong.local_key is None
        right = session.feed("grep -rh ERROR /var/log/app > /errors.txt", ts=ts)
        assert right.advanced is True
        assert right.local_key is not None
    finally:
        session.teardown()


_CHECK = """\
image verifytask:1
hidden {hidden}

stage "create the flag"
  solve touch /done
  check exec verify.sh
"""


@pytest.mark.tier3
def test_e2e_check_exec_stage(tmp_path, base_tar):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    v = hidden / "verify.sh"
    v.write_text("#!/bin/sh\n[ -f /done ]\n", encoding="utf-8")
    v.chmod(0o755)
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_CHECK.format(hidden=hidden)), store, base_tar=base_tar,
               workdir=tmp_path / "bt")
    session = run_task("verifytask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        assert session.feed("ls /", ts="t").advanced is False       # /done absent -> verify exit 1
        assert session.feed("touch /done", ts="t").advanced is True  # now verify exit 0
    finally:
        session.teardown()


_SIDE = """\
image sidetask:1
hidden {hidden}

stage "write the marker"
  solve echo done > /marker
  observe /marker
  on enter exec seed.sh
  on pass  exec cheer.sh
"""


@pytest.mark.tier3
def test_e2e_on_enter_and_on_pass_fire(tmp_path, base_tar):
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    for name, body in (("seed.sh", '#!/bin/sh\necho Welcome\necho enter >> "$HP_STATE"\n'),
                       ("cheer.sh", '#!/bin/sh\necho pass >> "$HP_STATE"\n')):
        p = hidden / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    store = ImageStore(tmp_path / "images")
    build_task(parse_recipe(_SIDE.format(hidden=hidden)), store, base_tar=base_tar,
               workdir=tmp_path / "bt", passes=2)
    session = run_task("sidetask:1", store, tmp_path / "run", base_tar=base_tar,
                       student_id="s1", nonce="n1")
    try:
        greeting = session.enter()
        assert any("Welcome" in g for g in greeting)                 # on_enter stdout rendered
        state = (session.hp_dir / "state.json").read_text(encoding="utf-8")
        assert "enter" in state                                      # on_enter wrote rw /hp
        res = session.feed("echo done > /marker", ts="t")
        assert res.advanced is True
        state2 = (session.hp_dir / "state.json").read_text(encoding="utf-8")
        assert "pass" in state2                                      # on_pass fired after accept
    finally:
        session.teardown()
