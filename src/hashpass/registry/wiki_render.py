"""
A wiki page as HTML: markdown without raw HTML, links of any kind but the ones running code.

User, 2026-11-03: «пока разрешить все ссылки». markdown-it's own `validateLink` already refuses
`javascript:`, `vbscript:`, `file:` and non-image `data:` -- the only links that would run code in
the reader's browser. A paragraph that is nothing but a YouTube link becomes an embedded player.
"""
import re

from markupsafe import Markup

from hashpass.registry.wiki_store import parse_tags

try:
    from markdown_it import MarkdownIt
except ImportError:                       # pragma: no cover - a pool without markdown-it
    MarkdownIt = None

_YOUTUBE = re.compile(
    r"\Ahttps?://(?:www\.|m\.)?(?:youtube\.com/watch\?(?:[^#\s]*&)?v=|youtu\.be/)([A-Za-z0-9_-]{11})(?:[?&#]\S*)?\Z")
_EMBED = ('<div class="wiki-video"><iframe src="https://www.youtube-nocookie.com/embed/{id}" '
          'title="YouTube" loading="lazy" allowfullscreen '
          'allow="accelerometer; encrypted-media; gyroscope; picture-in-picture"></iframe></div>\n')


def _md() -> "MarkdownIt":
    md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table").enable("strikethrough")
    default = md.renderer.rules.get("paragraph_open")

    def paragraph_open(tokens, idx, options, env):  # noqa: ANN202  (markdown-it's signature)
        vid = _lone_youtube(tokens, idx)
        if vid:
            env.setdefault("skip", set()).update({idx + 1, idx + 2})
            return _EMBED.format(id=vid)
        return default(tokens, idx, options, env) if default else md.renderer.renderToken(tokens, idx, options, env)

    def skippable(name: str):  # noqa: ANN202
        fallback = md.renderer.rules.get(name)

        def rule(tokens, idx, options, env):  # noqa: ANN202
            if idx in env.get("skip", ()):
                return ""
            return fallback(tokens, idx, options, env) if fallback else md.renderer.renderToken(tokens, idx, options, env)
        return rule

    md.renderer.rules["paragraph_open"] = paragraph_open
    md.renderer.rules["inline"] = skippable("inline")
    md.renderer.rules["paragraph_close"] = skippable("paragraph_close")
    return md


def _lone_youtube(tokens: list, idx: int) -> str | None:
    """Return the video id when the paragraph at `idx` holds one link and nothing else."""
    inline = tokens[idx + 1] if idx + 1 < len(tokens) else None
    if inline is None or inline.type != "inline":
        return None
    kids = [k for k in inline.children or [] if not (k.type == "text" and not k.content.strip())]
    if len(kids) == 1 and kids[0].type == "text":
        url = kids[0].content.strip()
    elif len(kids) == 3 and kids[0].type == "link_open" and kids[2].type == "link_close":  # noqa: PLR2004
        url = str(kids[0].attrGet("href") or "")
        if kids[1].content.strip().strip("<>") != url and kids[0].info != "auto":
            return None
    else:
        return None
    m = _YOUTUBE.match(url)
    return m.group(1) if m else None


def _title(body: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*#*\s*$", body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def render_page(text: str) -> tuple[Markup, list[str], str]:
    """Render one wiki page: (safe HTML, its tags, its title -- the first `# ...`)."""
    tags, body = parse_tags(text)
    if MarkdownIt is None:
        return Markup("<pre>{}</pre>").format(body), tags, _title(body)
    return Markup(_md().render(body, {})), tags, _title(body)  # noqa: S704  (no raw HTML, links validated)


def plain(text: str) -> str:
    """Return a page as plain text for search: no tags block, no markdown punctuation."""
    body = parse_tags(text)[1]
    body = re.sub(r"```.*?```", " ", body, flags=re.DOTALL)
    body = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    body = re.sub(r"[#*_`>|~]+", " ", body)
    return re.sub(r"\s+", " ", body).strip()


def snippet(text: str, q: str, width: int = 160) -> str:
    """About `width` characters of the page around the first match of `q` (else its start)."""
    flat = plain(text)
    title = _title(parse_tags(text)[1])
    if title and flat.startswith(title):
        flat = flat[len(title):].strip()
    at = flat.casefold().find(q.casefold()) if q else -1
    if at < 0:
        return flat[:width].rstrip() + ("…" if len(flat) > width else "")
    start = max(0, at - width // 3)
    piece = flat[start:start + width].strip()
    return ("…" if start else "") + piece + ("…" if start + width < len(flat) else "")
