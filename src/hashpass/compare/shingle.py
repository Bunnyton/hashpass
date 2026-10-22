"""Shingling + exact Jaccard."""

# Characters nobody sees: zero-width space/joiners, word joiner, BOM -- pasted text drags them in.
_INVISIBLE = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))


def _line(raw: str) -> str:
    """One line as a reader sees it: no invisible characters, no edge spaces, single inner spaces."""
    return " ".join(raw.translate(_INVISIBLE).split())


def shingle(text: str, *, mode: str = "word", k: int = 3) -> frozenset[str]:
    if mode == "line":
        # In line mode, each non-blank line is one shingle; k parameter is ignored. Whitespace and
        # invisible characters are insignificant: a copied answer drags in trailing spaces,
        # \r or a BOM, and `ls -l` pads columns to the widest entry (mc, links, 2026-10-23).
        return frozenset(line for line in map(_line, text.splitlines()) if line)
    if mode == "char":
        units: str | list[str] = text
    elif mode == "word":
        units = text.split()
    else:
        msg = f"unknown shingle mode: {mode}"
        raise ValueError(msg)
    if not units:
        return frozenset()
    if len(units) < k:
        return frozenset([units if mode == "char" else " ".join(units)])
    joiner = "" if mode == "char" else " "
    return frozenset(joiner.join(units[i : i + k]) for i in range(len(units) - k + 1))


def jaccard(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 1.0
