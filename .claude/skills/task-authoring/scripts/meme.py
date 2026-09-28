#!/usr/bin/env python3
"""
meme.py -- turn a meme picture into terminal art for a task finale (photo-like, big).

    meme.py list [query]                       # imgflip templates (name + url), optionally filtered
    meme.py render <template name | URL | file> [--width 100] [--mode braille|ascii] [--light]
                                               [--gamma 1.0] [--no-dither]

`braille` (default) packs 2x4 pixels per character -- a real "photo" look at 80-100 columns
(the style of docs/Задания/Мемы.md: DARK areas become dots, so the picture reads on a dark
terminal). `ascii` uses a density ramp (` .:-=+*#%@`, dark = dense) -- coarser, any font.
`--light` flips the polarity for a light terminal. Blank margin rows are cropped. Prints to
stdout; paste under `cat <<'ART'` in hp/finale.
"""
import argparse
import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

_API = "https://api.imgflip.com/get_memes"
_UA = {"User-Agent": "Mozilla/5.0 (hashpass meme.py)"}   # imgflip answers 403 to a bare urllib UA
_RAMP = " .:-=+*#%@"
_DOTS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))   # braille bit per (row, col)
_BLANK = "⠀"


def _templates() -> list[dict]:
    req = urllib.request.Request(_API, headers=_UA)
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.load(resp)["data"]["memes"]


def _fetch(src: str) -> Image.Image:
    if Path(src).is_file():
        return Image.open(src)
    if not src.startswith(("http://", "https://")):
        hits = [m for m in _templates() if src.lower() in m["name"].lower()]
        if not hits:
            sys.exit(f"no imgflip template matches {src!r}; try: meme.py list <word>")
        src = hits[0]["url"]
        print(f"# {hits[0]['name']}  {src}", file=sys.stderr)
    req = urllib.request.Request(src, headers=_UA)  # noqa: S310
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return Image.open(io.BytesIO(resp.read()))


def _prep(img: Image.Image, width_px: int, height_px: int, *, gamma: float, light: bool) -> Image.Image:
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
    pr.add_argument("--width", type=int, default=100)
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
    if a.mode == "braille":
        print(render_braille(img, a.width, gamma=a.gamma, light=a.light, dither=not a.no_dither))
    else:
        print(render_ascii(img, a.width, gamma=a.gamma, light=a.light))
    return 0


if __name__ == "__main__":
    sys.exit(main())
