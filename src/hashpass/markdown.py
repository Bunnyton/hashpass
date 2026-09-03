"""
A tiny Markdown -> ANSI renderer for terminal narrative (`read <file>`).

Deliberately small: headings, bold/italic, inline code, fenced code blocks, bullet and
numbered lists, and block quotes. A line on its own that is exactly `---` is NOT rendered
here -- it is a PAGE BREAK consumed by the pager before this runs.
"""
import re

_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_ITAL = "\x1b[3m"
_UNDER = "\x1b[4m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"
_H2 = 2   # heading level at/above which the brighter colour is used

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITAL_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    """Apply inline markup: **bold**, *italic*, `code`."""
    text = _BOLD_RE.sub(_BOLD + r"\1" + _RESET, text)
    text = _ITAL_RE.sub(_ITAL + r"\1" + _RESET, text)
    return _CODE_RE.sub(_YELLOW + r"\1" + _RESET, text)


def render_markdown(text: str) -> str:
    """Render a Markdown string to ANSI-styled terminal text."""
    out: list[str] = []
    in_code = False
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append(_DIM + "    " + line + _RESET)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            colour = _CYAN if level <= _H2 else _GREEN
            out.append(colour + _BOLD + _UNDER + heading.group(2).strip() + _RESET)
            continue
        bullet = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if bullet:
            out.append(f"{bullet.group(1)}{_GREEN}•{_RESET} {_inline(bullet.group(2))}")
            continue
        numbered = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if numbered:
            out.append(f"{numbered.group(1)}{_GREEN}{numbered.group(2)}.{_RESET} "
                       f"{_inline(numbered.group(3))}")
            continue
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            out.append(f"{_DIM}│ {_inline(quote.group(1))}{_RESET}")
            continue
        out.append(_inline(line))
    return "\n".join(out)
