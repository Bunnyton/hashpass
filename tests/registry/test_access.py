"""Tier1: the course permission matrix (spec 2026-10-21 §5)."""
import pytest

from hashpass.registry.access import ACTIONS, can
from hashpass.registry.courses import Course

#         peek view play propose add moderate admin
_EXPECT = {
    ("public", None): "1100000",          # anonymous
    ("public", "outsider"): "1111000",
    ("public", "member"): "1111000",
    ("public", "author"): "1111100",
    ("public", "maintainer"): "1111110",
    ("public", "owner"): "1111111",
    ("private", None): "1000000",
    ("private", "outsider"): "1000000",
    ("private", "member"): "1111000",
    ("private", "author"): "1111100",
    ("private", "maintainer"): "1111110",
    ("private", "owner"): "1111111",
}


@pytest.mark.tier1
@pytest.mark.parametrize(("visibility", "who"), list(_EXPECT))
def test_matrix(visibility: str, who: str | None) -> None:
    course = Course(id="c", owner="own", name="x", visibility=visibility,
                    members={"mem": "member", "aut": "author", "mai": "maintainer"})
    user = {None: None, "outsider": "eve", "member": "mem", "author": "aut",
            "maintainer": "mai", "owner": "own"}[who]
    got = "".join("1" if can(user, "user", course, a) else "0" for a in ACTIONS)
    assert got == _EXPECT[(visibility, who)]


@pytest.mark.tier1
def test_server_admin_may_do_everything() -> None:
    course = Course(id="c", owner="own", name="x", visibility="private")
    assert all(can("root", "admin", course, a) for a in ACTIONS)


@pytest.mark.tier1
def test_unknown_action_is_a_bug() -> None:
    with pytest.raises(ValueError, match="unknown action"):
        can("a", "user", Course(id="c", owner="o", name="x"), "fly")
