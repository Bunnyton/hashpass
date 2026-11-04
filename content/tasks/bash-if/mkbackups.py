"""Архивы задания bash-if: python3 mkbackups.py (детерминированно, seed 11).

data/backups/ — 40 ночных бэкапов site-2026-09-01.tar.gz … : целые разного размера (от 4 до
120 тысяч байт; ни одного между 45 000 и 55 000, чтобы граница 50 000 не спорила с округлением),
битые (обрезаны) и пустые (0 байт).
"""
import datetime
import gzip
import io
import random
import shutil
import tarfile
from pathlib import Path

rnd = random.Random(11)
out = Path(__file__).parent / "data" / "backups"
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True)
day = datetime.date(2026, 9, 1)
kinds = ["ok"] * 28 + ["broken"] * 7 + ["empty"] * 5
rnd.shuffle(kinds)
for kind in kinds:
    name = f"site-{day.isoformat()}.tar.gz"
    day += datetime.timedelta(days=1)
    if kind == "empty":
        (out / name).write_bytes(b"")
        continue
    while True:
        size = rnd.randrange(4000, 120000)
        if not 40000 <= size <= 60000:
            break
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for fname, n in (("site/index.html", size), ("site/style.css", 300)):
            data = bytes(rnd.randrange(256) for _ in range(n))
            info = tarfile.TarInfo(fname)
            info.size, info.mtime, info.mode = len(data), 1767225600, 0o644
            tar.addfile(info, io.BytesIO(data))
    blob = gzip.compress(buf.getvalue(), mtime=0)
    if kind == "broken":
        blob = blob[: len(blob) // 2]
    (out / name).write_bytes(blob)
print(sorted(kinds).count("ok"), "ok")
