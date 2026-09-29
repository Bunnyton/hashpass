#!/usr/bin/env python3
"""
meme.py -- turn a meme picture into terminal art for a task finale (photo-like, big).

    meme.py list [query]                       # imgflip templates (name + url), optionally filtered
    meme.py render <template name | URL | file> [--width 80] [--max-rows 45] [--mode braille|ascii]
                                               [--light] [--gamma 1.0] [--no-dither]

`braille` (default) packs 2x4 pixels per character -- a real "photo" look at 80-100 columns
(the style of docs/Задания/Мемы.md: DARK areas become dots, so the picture reads on a dark
terminal). `ascii` uses a density ramp (` .:-=+*#%@`, dark = dense) -- coarser, any font.
`--light` flips the polarity for a light terminal. Blank margin rows are cropped; a tall picture
is re-rendered narrower until it fits `--max-rows`. Needs Pillow (`python3-pil`). Prints to stdout;
paste under `cat <<'ART'` in hp/finale.
"""
import argparse
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

_API = "https://api.imgflip.com/get_memes"
_UA = {"User-Agent": "Mozilla/5.0 (hashpass meme.py)"}   # imgflip answers 403 to a bare urllib UA
_RAMP = " .:-=+*#%@"
_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))   # braille bit per (row, col)
_BLANK = "⠀"
_ATTEMPTS = 3
_CACHE = Path.home() / ".cache" / "hashpass-memes"   # downloads are kept: re-render works offline


def _templates() -> list[dict]:
    req = urllib.request.Request(_API, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.load(resp)["data"]["memes"]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        sys.exit(f"cannot reach imgflip ({exc}); pass a local image file or a direct URL instead")


def _fetch(src: str) -> Image.Image:
    if Path(src).is_file():
        return _decode(Path(src).read_bytes(), src)
    if not src.startswith(("http://", "https://")):
        hits = [m for m in _templates() if src.lower() in m["name"].lower()]
        if not hits:
            sys.exit(f"no imgflip template matches {src!r}; try: meme.py list <word>")
        src = hits[0]["url"]
        print(f"# {hits[0]['name']}  {src}", file=sys.stderr)
    cached = _CACHE / (hashlib.sha256(src.encode()).hexdigest()[:16] + Path(src).suffix)
    if cached.is_file():
        try:
            return _decode(cached.read_bytes(), str(cached))
        except SystemExit:
            cached.unlink()                       # a broken download: fetch again
    req = urllib.request.Request(src, headers=_UA)  # noqa: S310
    err: Exception | None = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                data = resp.read()
            break
        except (urllib.error.URLError, OSError) as exc:
            err = exc
            print(f"# attempt {attempt}/{_ATTEMPTS} failed: {exc}", file=sys.stderr)
    else:
        sys.exit(f"cannot download {src}: {err}")
    img = _decode(data, src)                      # cache only what decodes
    _CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return img


def _decode(data: bytes, what: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        sys.exit(f"not an image I can read ({what}): {exc}")
    return img


def _prep(img: Image.Image, width_px: int, height_px: int, *, gamma: float, light: bool) -> Image.Image:
    if img.mode in ("RGBA", "LA") or "transparency" in img.info:     # transparent -> white paper
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    g = ImageOps.equalize(ImageOps.autocontrast(img.convert("L")))   # spread the tones: faces pop
    if gamma != 1.0:
        g = g.point(lambda v: int(255 * (v / 255) ** gamma))
    if not light:                        # default: dark pixels -> ink (dots / dense chars)
        g = ImageOps.invert(g)
    return g.resize((width_px, height_px), Image.LANCZOS)


def _crop(lines: list[str], blank: str) -> str:
    """Drop fully blank rows at the top and bottom (a meme's white margins)."""
    while lines and not lines[0].strip(blank + " "):
        lines.pop(0)
    while lines and not lines[-1].strip(blank + " "):
        lines.pop()
    return "\n".join(lines)


def render_braille(img: Image.Image, width: int, *, gamma: float, light: bool, dither: bool) -> str:
    aspect = img.height / img.width
    cols, rows = width, max(1, round(width * 2 * aspect / 4 * 0.9))   # cell = 2x4 px, ~0.9 for font shape
    g = _prep(img, cols * 2, rows * 4, gamma=gamma, light=light)
    bw = g.convert("1", dither=Image.FLOYDSTEINBERG if dither else Image.NONE)
    px = bw.load()
    out = []
    for r in range(rows):
        line = []
        for c in range(cols):
            code = 0x2800
            for dy in range(4):
                for dx in range(2):
                    if px[c * 2 + dx, r * 4 + dy]:          # ink pixel -> lit dot
                        code |= _DOTS[dy][dx]
            line.append(chr(code))
        out.append("".join(line).rstrip(_BLANK))
    return _crop(out, _BLANK)


def render_ascii(img: Image.Image, width: int, *, gamma: float, light: bool) -> str:
    aspect = img.height / img.width
    cols, rows = width, max(1, round(width * aspect * 0.5))
    g = _prep(img, cols, rows, gamma=gamma, light=light)
    px = g.load()
    lines = ["".join(_RAMP[px[c, r] * (len(_RAMP) - 1) // 255] for c in range(cols)).rstrip()
             for r in range(rows)]
    return _crop(lines, "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list")
    pl.add_argument("query", nargs="?", default="")
    pr = sub.add_parser("render")
    pr.add_argument("source")
    pr.add_argument("--width", type=int, default=80, help="columns (80 fits every terminal)")
    pr.add_argument("--max-rows", type=int, default=45,
                    help="re-render narrower until the art fits this many rows (0 = no cap)")
    pr.add_argument("--mode", choices=["braille", "ascii"], default="braille")
    pr.add_argument("--light", action="store_true",
                    help="flip polarity for a light terminal (default: dark areas are ink)")
    pr.add_argument("--gamma", type=float, default=1.0, help=">1 darker midtones, <1 lighter")
    pr.add_argument("--no-dither", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "list":
        for m in _templates():
            if a.query.lower() in m["name"].lower():
                print(f"{m['name']:<45} {m['url']}")
        return 0
    img = _fetch(a.source)
    width = a.width
    while True:
        if a.mode == "braille":
            art = render_braille(img, width, gamma=a.gamma, light=a.light, dither=not a.no_dither)
        else:
            art = render_ascii(img, width, gamma=a.gamma, light=a.light)
        rows = art.count("\n") + 1
        if not a.max_rows or rows <= a.max_rows or width <= 40:            # noqa: PLR2004
            break
        width = max(40, int(width * a.max_rows / rows))                   # a tall meme: narrower
    print(art)
    return 0


if __name__ == "__main__":
    sys.exit(main())
