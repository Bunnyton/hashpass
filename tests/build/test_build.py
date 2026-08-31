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
