"""
Source viewer helpers for the web: per-line syntax highlighting and Markdown preview.

Pygments and markdown-it come with `rich` (a `textual` dependency), so the pool needs no new
package; without them the code is shown plain and Markdown as text.
"""
import html

from markupsafe import Markup

try:
    from pygments.lexer import RegexLexer, bygroups
    from pygments.lexers import BashLexer, TextLexer, get_lexer_for_filename
    from pygments.token import STANDARD_TYPES, Comment, Keyword, Name, Number, String, Text
    from pygments.util import ClassNotFound
except ImportError:            # pragma: no cover - pygments ships with rich
    get_lexer_for_filename = None

try:
    from markdown_it import MarkdownIt
except ImportError:            # pragma: no cover - markdown-it ships with rich
    MarkdownIt = None

# Taskfile DSL words (stage/say/solve/...): the first word of a line is the directive.
_DSL = ("stage", "say", "solve", "hint", "on", "neutral", "observe", "run", "block", "settings",
        "read", "pager", "image", "hidden", "exec", "copy", "accept", "sudo", "variant", "similarity",
        "allow", "deny", "check", "from", "exclude", "apply", "pass", "fail", "tries", "output",
        "cmd", "bool", "ok", "root", "user", "env", "workdir", "expect", "grade", "meme")

if get_lexer_for_filename is not None:
    class TaskfileLexer(RegexLexer):
        """The hashpass Taskfile DSL: directives, quoted strings, numbers, # comments."""

        name = "Taskfile"
        tokens = {"root": [  # noqa: RUF012  (pygments' class-level table)
            (r"\n", Text),
            (r"^([ \t]*)(#.*)$", bygroups(Text, Comment.Single)),
            (r"^([ \t]*)(" + "|".join(_DSL) + r")\b", bygroups(Text, Keyword)),
            (r'"(\\.|[^"\\])*"', String.Double),
            (r"'[^']*'", String.Single),
            (r"\b(" + "|".join(_DSL) + r")\b", Name.Builtin),
            (r"\b\d+\b", Number),
            (r"[ \t]+#.*$", Comment.Single),
            (r"[^\s\"'#]+|[ \t]+|.", Text),
        ]}


def _lexer(path: str, text: str):  # noqa: ANN202
    name = path.rsplit("/", 1)[-1]
    if name == "Taskfile":
        return TaskfileLexer(stripnl=False, ensurenl=False)
    if text.startswith("#!") or "." not in name:
        return BashLexer(stripnl=False, ensurenl=False)
    try:
        return get_lexer_for_filename(name, stripnl=False, ensurenl=False)
    except ClassNotFound:
        return TextLexer(stripnl=False, ensurenl=False)


def _css_class(ttype) -> str:
    while ttype not in STANDARD_TYPES:
        ttype = ttype.parent
    return STANDARD_TYPES[ttype]


def highlight_lines(path: str, text: str) -> list[Markup]:
    """Return the file as escaped HTML lines, tokens wrapped in pygments' short classes."""
    body = text.removesuffix("\n")
    if get_lexer_for_filename is None:
        return [Markup(html.escape(line)) for line in body.split("\n")]  # noqa: S704  (escaped)
    lines: list[list[str]] = [[]]
    for ttype, value in _lexer(path, body).get_tokens(body):
        cls = _css_class(ttype)
        for i, part in enumerate(value.split("\n")):
            if i:
                lines.append([])
            if part:
                esc = html.escape(part)
                lines[-1].append(f"<span class='{cls}'>{esc}</span>" if cls else esc)
    return [Markup("".join(parts)) for parts in lines]  # noqa: S704  (every piece escaped above)


def render_markdown_html(text: str) -> Markup | None:
    """Return the Markdown as safe HTML (raw HTML in it stays text), or None without markdown-it."""
    if MarkdownIt is None:
        return None
    md = MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
    return Markup(md.render(text))  # noqa: S704
