"""Tier1: `accept output|file "<ERE>"` and `observe perms` -- checks written in the Taskfile, no script."""
import pytest

from hashpass.recipe.model import StageSpec
from hashpass.recipe.parse import parse_recipe


def _stage(body: str) -> StageSpec:
    return parse_recipe('image t:1\nstage\n  say "goal"\n' + body).stages[0]


@pytest.mark.tier1
def test_accept_output_and_file_regexes_parse_without_a_solve():
    st = _stage('  accept output "Терпение должны"\n'
                '  accept file /home/student/.vimrc "^\\s*n?(nore)?map\\s"\n')
    assert st.accept_texts == (("output", "Терпение должны"),
                               ("/home/student/.vimrc", "^\\s*n?(nore)?map\\s"))


@pytest.mark.tier1
def test_accept_output_empty_is_a_keyword():
    assert _stage("  solve ./x > /dev/null 2>&1\n  accept output empty\n").accept_texts == (("output", None),)


@pytest.mark.tier1
def test_accept_cmd_combines_with_observe():
    st = _stage('  solve rm -f /f || true\n  accept cmd "rm"\n  observe bool /f\n')
    assert st.accept_cmds == ("rm",) and st.observe_bool == ("/f",)


@pytest.mark.tier1
def test_observe_perms_rides_on_observe_with_a_marker():
    st = _stage("  solve chmod 741 /home/student/d\n  observe perms /home/student/d /home/student/f\n")
    assert st.observe == ("perms:/home/student/d", "perms:/home/student/f")


@pytest.mark.tier1
@pytest.mark.parametrize("bad", ["  accept output\n", "  accept file /x\n", '  accept output "a" "b"\n',
                                 '  accept output "("\n'])
def test_malformed_accept_texts_are_rejected(bad):
    with pytest.raises(ValueError, match="accept"):
        _stage(bad)
