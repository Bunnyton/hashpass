import pytest

from hashpass.build import build, run_image
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe


@pytest.mark.tier3
def test_build_stores_delta_layer(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")

    demo = build(
        parse_recipe("image demo:1\nrun touch /marker\n"),
        store,
        base_tar=base_tar,
        workdir=tmp_path / "b-demo",
    )
    assert (demo.layer / "marker").exists()

    child = build(
        parse_recipe("image child:1\nfrom demo:1\nrun touch /child-marker\n"),
        store,
        base_tar=base_tar,
        workdir=tmp_path / "b-child",
    )
    # the child's stored layer holds ONLY its own delta (marker came from demo)
    assert (child.layer / "child-marker").exists()
    assert not (child.layer / "marker").exists()
    # child's closure is topmost-first: child over demo
    assert resolve_lowers(("child:1",), store) == [child.layer, demo.layer]


@pytest.mark.tier3
def test_copy_interleave_and_resave(tmp_path, base_tar):
    src = tmp_path / "hostfile.txt"
    src.write_text("payload", encoding="utf-8")
    store = ImageStore(tmp_path / "images")
    recipe = parse_recipe(f"image demo:1\nrun mkdir -p /opt/app\ncopy {src} /opt/app/f.txt\n")
    demo = build(recipe, store, base_tar=base_tar, workdir=tmp_path / "b1")
    # copy landed (interleave: run made /opt/app first) — the stored delta has the file
    assert (demo.layer / "opt/app/f.txt").read_text(encoding="utf-8") == "payload"
    # re-save the same tag must NOT crash (root-owned layer cleared via rsync --delete)
    build(recipe, store, base_tar=base_tar, workdir=tmp_path / "b2")


@pytest.mark.tier3
def test_copy_directory_puts_its_contents_at_dst(tmp_path, base_tar):
    # `copy data/tree /home/student/tree` lands data/tree/* under /home/student/tree (docker COPY
    # semantics), whatever the trailing slash -- authors ship real fixture trees next to the Taskfile.
    src = tmp_path / "data" / "tree"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("A", encoding="utf-8")
    (src / "sub" / "b.txt").write_text("B", encoding="utf-8")
    store = ImageStore(tmp_path / "images")
    recipe = parse_recipe(f"image demo:1\ncopy {src} /home/student/tree\n")
    demo = build(recipe, store, base_tar=base_tar, workdir=tmp_path / "b1")
    assert (demo.layer / "home/student/tree/a.txt").read_text(encoding="utf-8") == "A"
    assert (demo.layer / "home/student/tree/sub/b.txt").read_text(encoding="utf-8") == "B"
    assert not (demo.layer / "home/student/tree/tree").exists()


@pytest.mark.tier3
def test_build_then_run_image_roundtrips(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    build(
        parse_recipe("image demo:1\nrun touch /marker\n"),
        store,
        base_tar=base_tar,
        workdir=tmp_path / "build",
    )
    runner = run_image("demo:1", store, tmp_path / "run", base_tar=base_tar)
    try:
        res = runner.run(["sh", "-c", "test -f /marker && echo OK"])
        assert res.stdout.strip() == "OK"
    finally:
        runner.teardown()


@pytest.mark.tier3
def test_build_cache_skips_unchanged_rebuild(tmp_path, base_tar):
    # A cold build runs the steps and records a build_key; an identical rebuild matches the key
    # and reuses the stored image WITHOUT running any step; changing a step busts the key -> rebuild.
    store = ImageStore(tmp_path / "images")
    recipe = parse_recipe("image demo:1\nrun mkdir -p /a\nrun touch /a/one\n")

    cold: list[str] = []
    img = build(recipe, store, base_tar=base_tar, workdir=tmp_path / "b1", progress=cold.append)
    assert sum("выполняю" in m for m in cold) == 2          # cold: both steps run  # noqa: PLR2004
    assert img.build_key and (img.layer / "a/one").exists()

    warm: list[str] = []
    img2 = build(recipe, store, base_tar=base_tar, workdir=tmp_path / "b2", progress=warm.append)
    assert not any("выполняю" in m for m in warm)           # warm: NOTHING re-runs
    assert any("не изменился" in m for m in warm)
    assert img2.build_key == img.build_key

    changed = parse_recipe("image demo:1\nrun mkdir -p /a\nrun touch /a/two\n")
    hot: list[str] = []
    img3 = build(changed, store, base_tar=base_tar, workdir=tmp_path / "b3", progress=hot.append)
    assert sum("выполняю" in m for m in hot) == 2           # changed key -> full rebuild  # noqa: PLR2004
    assert img3.build_key != img.build_key
    assert (img3.layer / "a/two").exists() and not (img3.layer / "a/one").exists()


@pytest.mark.tier3
def test_copy_owner_is_root_unless_user_directive(tmp_path, base_tar):
    # Без `user` всё, что кладёт copy, принадлежит root (как COPY в Docker), а владелец
    # существующего каталога назначения не меняется: /home/student остаётся студенту.
    # После `user student` файлы ложатся от имени студента.
    src = tmp_path / "data" / "home"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("A", encoding="utf-8")
    (src / "sub" / "b.txt").write_text("B", encoding="utf-8")
    bin_src = tmp_path / "data" / "bin"
    bin_src.mkdir()
    (bin_src / "tool").write_text("#!/bin/sh\n", encoding="utf-8")
    (bin_src / "tool").chmod(0o775)
    mine = tmp_path / "data" / "mine.txt"
    mine.write_text("M", encoding="utf-8")
    store = ImageStore(tmp_path / "images")
    recipe = parse_recipe(f"image demo:1\ncopy {src} /home/student\ncopy {bin_src} /usr/local/bin\n"
                          f"user student\ncopy {mine} /home/student/mine.txt\n")
    demo = build(recipe, store, base_tar=base_tar, workdir=tmp_path / "b1")
    runner = run_image("demo:1", store, tmp_path / "r", base_tar=base_tar)
    try:
        paths = ("/home/student /home/student/a.txt /home/student/sub /usr/local/bin "
                 "/usr/local/bin/tool /home/student/mine.txt")
        res = runner.run(["sh", "-c", f"stat -c '%U %a %n' {paths}"])
    finally:
        runner.teardown()
    assert demo.layer.exists()
    lines = res.stdout.split("\n")
    assert lines[0].startswith("student ")
    assert lines[1].startswith("root ") and lines[1].endswith(" /home/student/a.txt")
    assert lines[2].startswith("root ")
    assert lines[3] == "root 755 /usr/local/bin"
    assert lines[4] == "root 755 /usr/local/bin/tool"
    assert lines[5].startswith("student ")
