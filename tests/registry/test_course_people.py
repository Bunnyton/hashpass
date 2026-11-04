"""Tier1: the private profile comment moves into the course notes once, writing over nothing."""
from pathlib import Path

import pytest

from hashpass.registry.course_people import CourseInvites, CourseNotes, migrate_profile_comments


@pytest.mark.tier1
def test_the_profile_comment_becomes_the_note_of_every_course_the_student_is_in(tmp_path: Path) -> None:
    notes = CourseNotes(tmp_path / "notes")
    notes.set("c2", "kid", "сам написал при вступлении")
    comments = {"kid": "Иванов И., ИУ7-31", "max": "", "ann": "Анна"}
    members = [("c1", ["kid", "max"]), ("c2", ["kid", "ann"])]
    marker = tmp_path / "notes" / ".migrated"
    assert migrate_profile_comments(notes, iter(members), comments.get, marker) == 2  # noqa: PLR2004
    assert notes.of_course("c1") == {"kid": "Иванов И., ИУ7-31"}                     # max had none
    assert notes.of_course("c2") == {"kid": "сам написал при вступлении", "ann": "Анна"}
    notes.set("c1", "kid", "")                                                      # removed later
    assert migrate_profile_comments(notes, iter(members), comments.get, marker) == 0  # once
    assert notes.of_course("c1") == {}


@pytest.mark.tier1
def test_invitations_wait_per_user_and_go_away_once(tmp_path: Path) -> None:
    inv = CourseInvites(tmp_path / "inv")
    assert inv.add("kid", "c1", by="bob") and not inv.add("kid", "c1", by="eve")
    inv.add("max", "c1", by="bob")
    inv.add("kid", "c2", by="bob")
    assert sorted(inv.to_course("c1")) == ["kid", "max"] and set(inv.of("kid")) == {"c1", "c2"}
    assert inv.drop("kid", "c1") and not inv.drop("kid", "c1")
    assert sorted(inv.to_course("c1")) == ["max"]


@pytest.mark.tier1
def test_a_pool_starting_on_old_data_moves_the_comments(tmp_path: Path) -> None:
    from hashpass.imagestore.store import ImageStore  # noqa: PLC0415
    from hashpass.registry.course_api import Enrollments  # noqa: PLC0415
    from hashpass.registry.courses import CourseStore  # noqa: PLC0415
    from hashpass.registry.passwords import UserStore  # noqa: PLC0415
    from hashpass.registry.server import make_server  # noqa: PLC0415
    store = ImageStore(tmp_path / "srv")
    users = UserStore(tmp_path / "users.json")
    users.add("bob", "pw-correct1", role="admin")
    users.add("kid", "pw-correct1", comment="Иванов И., ИУ7-31")
    course = CourseStore(Path(store.root) / ".courses").create("bob", "linux")
    Enrollments(Path(store.root) / ".enrollments").enroll("kid", course.id)
    server = make_server(store, users, b"s" * 32, catalog_path=tmp_path / "catalog.json")
    server.server_close()
    assert CourseNotes(Path(store.root) / ".course-notes").of_course(course.id) == {"kid": "Иванов И., ИУ7-31"}
    assert users.get("kid")["comment"] == "Иванов И., ИУ7-31"                       # the profile keeps it
