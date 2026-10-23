"""Tier1: a pre-courses pool moves to revisions + a default course, once (spec 2026-10-21 §13)."""
import hashlib
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.approved import ApprovedStore
from hashpass.registry.blob import pack_image_to_file
from hashpass.registry.catalog import Catalog
from hashpass.registry.migrate import migrate_to_courses
from hashpass.registry.passwords import UserStore
from hashpass.registry.progress_store import ProgressStore
from hashpass.registry.server import PoolServer
from hashpass.taskdigest import task_digest


def _image(tmp: Path, srv: ImageStore, name: str, version: str, text: str,  # noqa: PLR0913, PLR0917
           parents: tuple[str, ...] = (), *, task: str | None = None) -> str:
    local = ImageStore(tmp / f"loc-{name.replace('/', '_')}-{text}")
    src = tmp / f"src-{name.replace('/', '_')}-{text}"
    src.mkdir(parents=True)
    (src / "f").write_text(text, encoding="utf-8")
    local.save(name, version, src, parents)
    blob = tmp / f"{name.replace('/', '_')}-{text}.tar.gz"
    pack_image_to_file(local.get(f"{name}:{version}"), blob)
    img = srv.publish_blob(name, version, blob, parents=parents,
                           digest=hashlib.sha256(blob.read_bytes()).hexdigest())
    if task is not None:
        tdir = img.layer.parent / "task"
        tdir.mkdir(exist_ok=True)
        (tdir / "task-meta.json").write_text(task, encoding="utf-8")
    return f"{name}:{version}"


@pytest.fixture
def legacy(tmp_path: Path) -> PoolServer:
    root = tmp_path / "pool"
    srv = ImageStore(root / "store")
    users = UserStore(root / "users.json")
    users.add("bunnyton", "pw-correct1", role="admin")
    users.add("bob", "pw-correct1", role="author")
    users.add("kid", "pw-correct1", role="student", group="ИТ-21")
    server = PoolServer(store=srv, users=users, secret=b"s" * 32, catalog_path=root / "catalog.json",
                        config_path=root / "config.json", progress_path=root / "progress")
    catalog = Catalog(root / "catalog.json")
    _image(tmp_path, srv, "bunnyton/debian", "trixie", "base")
    # bob/lab:1 -- approved "old", then updated to "new" (pending; students keep the copy)
    lab = _image(tmp_path, srv, "bob/lab", "1", "old", task="lab-old")
    catalog.add_task(lab, task_digest(srv.get(lab).layer.parent / "task"), block_name="Git",
                     hidden=False, auto=True, image=srv.get(lab).digest)
    ApprovedStore(srv.root / "approved").take(lab, srv.get(lab), srv.get(lab).layer.parent / "task",
                                             srv, task_digest=catalog.find(lab).approved_digest)
    _image(tmp_path / "v2", srv, "bob/lab", "1", "new", task="lab-new")
    catalog.add_task(lab, task_digest(srv.get(lab).layer.parent / "task"), auto=False,
                     image=srv.get(lab).digest)
    ok = _image(tmp_path, srv, "bob/ok", "1", "ok", task="ok")
    catalog.add_task(ok, task_digest(srv.get(ok).layer.parent / "task"), block_name="Git",
                     hidden=True, auto=True, image=srv.get(ok).digest)
    new = _image(tmp_path, srv, "bob/new", "1", "fresh", task="new")
    catalog.add_task(new, task_digest(srv.get(new).layer.parent / "task"), block_name="Docker")
    ProgressStore(root / "progress").record("kid", ok, status="passed", ts="t")
    return server


@pytest.mark.tier1
def test_images_become_revisions(legacy: PoolServer) -> None:
    report = migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    assert report["images"] == 4  # noqa: PLR2004
    store = legacy.store
    assert sorted(store.list()) == ["bob/lab:1_v1", "bob/lab:1_v2", "bob/new:1_v1", "bob/ok:1_v1",
                                    "bunnyton/debian:trixie_v1"]
    assert (store.get("bob/lab:1_v1").layer.parent / "task" / "task-meta.json").read_text(
        encoding="utf-8") == "lab-old"
    assert store.get("bob/ok:1_v1").base == "bunnyton/debian:trixie_v1"
    assert [r.n for r in legacy.repo("bob/lab").revisions("1")] == [1, 2]


@pytest.mark.tier1
def test_the_catalog_becomes_the_default_course(legacy: PoolServer) -> None:
    migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    course = legacy.course_api.courses.get("bunnyton/linux")
    assert legacy.config.default_course == "bunnyton/linux"
    assert [b["name"] for b in course.blocks] == ["Git", "Docker"]
    lab = course.find_task("bob/lab", "1")
    assert (lab["n"], lab["pinned"]) == (1, True)                  # the approved one, kept
    assert course.find_task("bob/ok", "1")["hidden"] is True
    assert course.find_task("bob/new", "1") is None                # never approved ...
    kinds = sorted((p["kind"], p["repo"], p["n"], p["state"]) for p in course.proposals)
    assert kinds == [("add", "bob/new", 1, "open"), ("update", "bob/lab", 2, "open")]
    assert course.members == {"bob": "author"}


@pytest.mark.tier1
def test_users_and_enrollment(legacy: PoolServer) -> None:
    migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    assert str(legacy.users.get("kid")["comment"]).startswith("ИТ-21")
    course = legacy.course_api.courses.get("bunnyton/linux")
    assert legacy.course_api.enrollments.users_of(course.id) == ["kid"]


@pytest.mark.tier1
def test_runs_once_and_keeps_a_backup(legacy: PoolServer) -> None:
    assert migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    assert migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie") == {}
    backups = list(Path(legacy.store.root).glob(".backup-courses-*"))
    assert [p.name for p in sorted(backups[0].iterdir())] == ["catalog.json", "users.json"]


@pytest.mark.tier1
def test_old_clients_work_in_the_default_course(legacy: PoolServer) -> None:
    migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    client = legacy.app.test_client()
    tok = client.post("/login", json={"user": "kid", "password": "pw-correct1"}).get_json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    rows = client.get("/catalog", headers=auth).get_json()["catalog"]
    assert [(r["ref"], r["number"]) for r in rows] == [("bob/lab:1", 1)]   # ok hidden, new a proposal
    assert client.get("/task/bob/lab/1", headers=auth).headers["X-Image-Ref"] == "bob/lab:1_v1"
    digest = legacy.repo("bob/lab").get("1", 1).task_digest
    got = client.post("/submit", headers=auth, json={"task_ref": "bob/lab:1", "digest": digest,
                                                     "passed": True}).get_json()
    assert got["status"] == "passed"
    admin = client.post("/login", json={"user": "bunnyton", "password": "pw-correct1"}).get_json()["token"]
    gone = client.put("/catalog/layout", headers={"Authorization": f"Bearer {admin}"}, json={"blocks": []})
    assert gone.status_code == 410  # noqa: PLR2004


@pytest.mark.tier1
def test_anonymous_pulls_of_a_public_course_still_work(legacy: PoolServer) -> None:
    """Before the move anyone pulled a catalogued task (installer, a client without a token)."""
    client = legacy.app.test_client()
    assert client.get("/closure/bob/lab/1?revisions=1").status_code == 200  # noqa: PLR2004
    migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    closure = client.get("/closure/bob/lab/1?revisions=1")
    assert closure.status_code == 200 and closure.get_json()["refs"][-1] == "bob/lab:1_v1"  # noqa: PLR2004
    assert client.get("/image/bob/lab/1").status_code == 200  # noqa: PLR2004
    # a public image outside any course is public too (user 2026-10-23: search and run any)
    assert client.get("/closure/bob/new/1?revisions=1").status_code == 200  # noqa: PLR2004


@pytest.mark.tier1
def test_before_the_move_students_still_get_the_approved_copy(legacy: PoolServer) -> None:
    """Prod 2026-10-22: tasks with a waiting update must keep serving the approved copy (no 404)."""
    Catalog(legacy.catalog_path).set_task_hidden("bob/lab:1", hidden=False)
    client = legacy.app.test_client()
    tok = client.post("/login", json={"user": "kid", "password": "pw-correct1"}).get_json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    task = client.get("/task/bob/lab/1", headers=auth)
    assert task.status_code == 200  # noqa: PLR2004
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415
    with tarfile.open(fileobj=io.BytesIO(task.data)) as tar:
        assert tar.extractfile("task-meta.json").read() == b"lab-old"
    image = client.get("/image/bob/lab/1", headers=auth)
    assert image.status_code == 200  # noqa: PLR2004
    assert image.headers["X-Image-Digest"] == ApprovedStore(legacy.store.root / "approved").digest("bob/lab:1")
    assert client.get("/closure/bob/lab/1", headers=auth).get_json() == {"refs": ["bob/lab:1"]}
    bob = client.post("/login", json={"user": "bob", "password": "pw-correct1"}).get_json()["token"]
    with tarfile.open(fileobj=io.BytesIO(client.get("/task/bob/lab/1", headers={
            "Authorization": f"Bearer {bob}"}).data)) as tar:
        assert tar.extractfile("task-meta.json").read() == b"lab-new"      # the author: the latest


@pytest.mark.tier1
def test_the_command_runs_once_on_the_pool_home(tmp_path: Path) -> None:
    from hashpass import cli  # noqa: PLC0415
    env = cli.build_env({"HASHPASS_HOME": str(tmp_path / "home")}, default_home=tmp_path)
    users = UserStore(env.registry / "users.json")
    users.add("bunnyton", "pw-correct1", role="admin")
    users.add("bob", "pw-correct1", role="author")
    said: list[str] = []
    io = cli.Io(read=lambda _p: None, write=said.append, clock=lambda: "")
    with pytest.raises(RuntimeError, match="администратором"):
        cli.cmd_migrate_courses(env, "bob", io)
    assert cli.cmd_migrate_courses(env, "bunnyton", io) == 0
    assert "курс по умолчанию bunnyton/linux" in said[-1]
    assert cli.cmd_migrate_courses(env, "bunnyton", io) == 0
    assert "уже переведён" in said[-1]


@pytest.mark.tier1
def test_a_tag_collision_stops_before_any_change(legacy: PoolServer, tmp_path: Path) -> None:
    _image(tmp_path / "c1", legacy.store, "bob/x", "1_v1", "a")
    _image(tmp_path / "c2", legacy.store, "bob/x", "1-v1", "b")
    before = sorted(legacy.store.list())
    with pytest.raises(RuntimeError, match="один тег"):
        migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    assert sorted(legacy.store.list()) == before
    assert not (Path(legacy.store.root) / ".migrated-courses").exists()


@pytest.mark.tier1
def test_an_interrupted_move_finishes_on_the_next_run(legacy: PoolServer, monkeypatch: pytest.MonkeyPatch) -> None:
    from hashpass.registry import migrate  # noqa: PLC0415
    real = migrate.cm.add_block

    def crash(*_a: object, **_k: object) -> str:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(migrate.cm, "add_block", crash)
    with pytest.raises(OSError, match="disk full"):
        migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    monkeypatch.setattr(migrate.cm, "add_block", real)
    report = migrate_to_courses(legacy, owner="bunnyton", base_ref="bunnyton/debian:trixie")
    assert report["images"] == 4  # noqa: PLR2004
    assert sorted(legacy.store.list()) == ["bob/lab:1_v1", "bob/lab:1_v2", "bob/new:1_v1", "bob/ok:1_v1",
                                           "bunnyton/debian:trixie_v1"]
    course = legacy.course_api.courses.get("bunnyton/linux")
    assert [b["name"] for b in course.blocks] == ["Git", "Docker"]
    assert [r.n for r in legacy.repo("bob/lab").revisions("1")] == [1, 2]
