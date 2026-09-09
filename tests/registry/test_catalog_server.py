"""Tier2: /catalog + push --task N over the live server via RemoteRegistry."""
import urllib.error
from http import HTTPStatus

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.remote import RemoteRegistry
from hashpass.taskdigest import task_digest


def _make_task_dir(root, marker="0") -> None:
    (root / "bundle").mkdir(parents=True)
    (root / "bundle" / "checks.json").write_text(f'{{"stages":[{marker}]}}', encoding="utf-8")
    (root / "task-meta.json").write_text('{"image_ref":"lab:1"}', encoding="utf-8")


def _seed_image(store, tmp_path, name) -> None:
    src = tmp_path / f"src-{name}"
    src.mkdir(exist_ok=True)
    (src / "f").write_text("x", encoding="utf-8")
    store.save(name, "1", src, ())


@pytest.mark.tier2
def test_push_task_number_shows_in_catalog_with_server_digest(registry, tmp_path):
    registry.users.add("a", "pw", role="author")
    c = RemoteRegistry(registry.base_url)
    tok = c.login("a", "pw")
    local = ImageStore(tmp_path / "local")
    _seed_image(local, tmp_path, "lab")
    c.push(local, "lab:1", token=tok)
    tdir = tmp_path / "task"
    tdir.mkdir()
    _make_task_dir(tdir)
    c.push_task(tdir, "lab", "1", publish=True, token=tok)

    cat = c.catalog(token=tok)
    assert len(cat) == 1
    entry = cat[0]
    assert entry["number"] == 1                   # auto-numbered by position
    assert entry["ref"] == "lab:1"
    assert entry["digest"] == task_digest(tdir)  # server-computed digest matches the local tree


@pytest.mark.tier2
def test_catalog_requires_token(registry):
    c = RemoteRegistry(registry.base_url)
    with pytest.raises(urllib.error.HTTPError) as exc:
        c.catalog(token="bogus")  # noqa: S106  (bad token for the 401 path)
    assert exc.value.code == HTTPStatus.UNAUTHORIZED
