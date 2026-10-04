#!/usr/bin/env python3
"""
meme.py -- turn a meme picture into terminal art for a task finale (photo-like, big).

    meme.py list [query]                       # imgflip templates (name + url), optionally filtered
    meme.py render <template name | URL | file> [--width 80] [--max-rows 40]
                                               [--mode color|braille|ascii] [--label TEXT@X,Y ...]
                                               [--light] [--gamma 1.0] [--no-dither]

`color` (default) is a real photo: each cell is `▀` with the TOP pixel as the foreground colour and
the BOTTOM pixel as the background (24-bit ANSI), so 80 columns x 40 rows = an 80x80 colour picture
-- faces and shapes read at a glance, on dark and light terminals alike. `--label "student@0.2,0.6"`
stamps crisp terminal text (bold white on black, like a meme caption) centred at that fraction of the width/height:
the meme's captions, which pixel text could never carry at this size.
`braille` packs 2x4 pixels per character -- a real "photo" look at 80-100 columns
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


_RESET = "\x1b[0m"


def _label_cells(labels: list[str], cols: int, rows: int) -> dict[tuple[int, int], str]:
    """Map `TEXT@X,Y` (fractions of width/height, the label's centre) to {(row, col): char}."""
    cells: dict[tuple[int, int], str] = {}
    for spec in labels:
        text, _, pos = spec.rpartition("@")
        if not text:
            sys.exit(f"--label wants TEXT@X,Y (fractions 0..1), got {spec!r}")
        fx, fy = (float(v) for v in pos.split(","))
        text = f" {text} "
        row = min(rows - 1, max(0, round(fy * (rows - 1))))
        start = min(cols - len(text), max(0, round(fx * cols - len(text) / 2)))
        for i, ch in enumerate(text):
            cells[(row, start + i)] = ch
    return cells


_LABEL = "\x1b[1;97;40m"                 # bold bright white on black: a meme caption
_CUBE = (0, 95, 135, 175, 215, 255)


def _sgr_truecolor(layer: int, rgb: tuple[int, int, int]) -> str:
    return f"\x1b[{layer};2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _sgr_256(layer: int, rgb: tuple[int, int, int]) -> str:
    return f"\x1b[{layer};5;{_xterm256(rgb)}m"


def _xterm256(rgb: tuple[int, int, int]) -> int:
    """Nearest xterm-256 index: the 6x6x6 colour cube or the 24-step grey ramp, whichever is closer."""
    idx = [min(range(6), key=lambda i, v=v: abs(_CUBE[i] - v)) for v in rgb]
    cube = tuple(_CUBE[i] for i in idx)
    grey_i = min(23, max(0, round((sum(rgb) / 3 - 8) / 10)))
    grey = (8 + 10 * grey_i,) * 3
    def dist(a: tuple[int, ...]) -> int:
        return sum((x - y) ** 2 for x, y in zip(a, rgb, strict=True))
    return 232 + grey_i if dist(grey) < dist(cube) else 16 + 36 * idx[0] + 6 * idx[1] + idx[2]


def _trim_white(rgb: Image.Image, *, near: int = 235) -> Image.Image:
    """Crop blank white edges (a template's empty caption panels), so the picture fills the art."""
    ink = rgb.convert("L").point(lambda v: 255 if v < near else 0)
    box = ink.getbbox()
    return rgb.crop(box) if box else rgb


def render_color(img: Image.Image, width: int, *, labels: list[str], truecolor: bool = True) -> str:
    """Truecolor half-blocks: one cell = `▀`, fg = top pixel, bg = bottom pixel (square pixels)."""
    if img.mode in ("RGBA", "LA", "P") or "transparency" in img.info:
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    rgb = _trim_white(img.convert("RGB"))
    rgb = ImageOps.autocontrast(rgb, cutoff=1, preserve_tone=True)   # stretch light only, keep hues
    cols, rows = width, max(1, round(width * img.height / img.width / 2))
    small = rgb.resize((cols, rows * 2), Image.LANCZOS)
    if truecolor:                                # step-4 channels: invisible, but more repeats
        small = small.point(lambda v: min(255, (v + 2) // 4 * 4))
    px = small.load()
    text = _label_cells(labels, cols, rows)
    sgr = _sgr_truecolor if truecolor else _sgr_256
    out = []
    for r in range(rows):
        line: list[str] = []
        fg = bg = None                           # emit only the half that changed: small art
        for c in range(cols):
            if (r, c) in text:
                if fg != "label":
                    line.append(_LABEL)
                    fg = bg = "label"
                line.append(text[(r, c)])
                continue
            if fg == "label":
                line.append(_RESET)
                fg = bg = None
            top, bot = px[c, r * 2], px[c, r * 2 + 1]
            if top != fg:
                line.append(sgr(38, top))
                fg = top
            if bot != bg:
                line.append(sgr(48, bot))
                bg = bot
            line.append("▀")
        out.append("".join(line) + _RESET)
    return "\n".join(out)


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
    pr.add_argument("--max-rows", type=int, default=40,
                    help="re-render narrower until the art fits this many rows (0 = no cap)")
    pr.add_argument("--mode", choices=["color", "braille", "ascii"], default="color")
    pr.add_argument("--256", dest="truecolor", action="store_false",
                    help="xterm-256 palette (half the bytes, visibly posterized); default 24-bit colour")
    pr.add_argument("--label", action="append", default=[], metavar="TEXT@X,Y",
                    help="caption centred at fractions of width,height (repeatable), color mode only")
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
        if a.mode == "color":
            art = render_color(img, width, labels=a.label, truecolor=a.truecolor)
        elif a.mode == "braille":
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
