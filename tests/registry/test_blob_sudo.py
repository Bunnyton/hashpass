"""Tier3: root-owned layers survive pack -> pull -> unpack with ownership and setuid intact."""
import io
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore
from hashpass.registry.blob import inspect_image_blob, pack_image_to_file, unpack_image_file


def _root_owned_layer(tmp_path: Path) -> Path:
    layer = tmp_path / "layer"
    (layer / "usr" / "bin").mkdir(parents=True)
    (layer / "usr" / "bin" / "sudo").write_text("#!/bin/sh\n", encoding="utf-8")
    (layer / "etc").mkdir()
    (layer / "etc" / "shadow").write_text("root:*:1::::::\n", encoding="utf-8")
    (layer / "link").symlink_to("/usr/bin/sudo")
    # sudo tar -c ... --owner=root --group=root --mode=... is not granted; instead chown via a
    # root-run tar extraction of a tar we build with uid 0 metadata:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for p in sorted(layer.rglob("*")):
            ti = tar.gettarinfo(str(p), arcname=str(p.relative_to(tmp_path)))
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            if p.name == "sudo":
                ti.mode = 0o4755
            if p.name == "shadow":
                ti.mode = 0o640
            tar.addfile(ti, p.open("rb") if p.is_file() else None)
    src_tar = tmp_path / "rootish.tar"
    src_tar.write_bytes(buf.getvalue())
    rooted = tmp_path / "rooted"
    rooted.mkdir()
    subprocess.run(["sudo", "tar", "-xpf", str(src_tar), "--same-owner", "-C", str(rooted)], check=True)
    return rooted / "layer"


@pytest.mark.tier3
def test_sudo_unpack_replaces_existing_root_owned_layer(tmp_path):
    layer = _root_owned_layer(tmp_path)
    assert Path(layer / "usr/bin/sudo").stat().st_uid == 0                # precondition: really root
    src = ImageStore(tmp_path / "src")
    img = src.save("base", "t", layer, (), sudo=True)
    blob = pack_image_to_file(img, tmp_path / "base.tar.gz")
    assert inspect_image_blob(blob).needs_root is True
    dst = ImageStore(tmp_path / "dst")
    assert unpack_image_file(blob, dst) == "base:t"                       # sudo chosen automatically
    got = dst.get("base:t").layer
    st = (got / "usr/bin/sudo").stat()
    assert st.st_uid == 0 and st.st_mode & stat.S_ISUID
    assert (got / "etc/shadow").stat().st_mode & 0o777 == 0o640  # noqa: PLR2004
    assert (got / "link").is_symlink()
    # second pull over the existing root-owned layer: swapped, no leftovers
    assert unpack_image_file(blob, dst) == "base:t"
    assert not list(dst.dir("base", "t").glob("layer.old-*"))
