"""Shingling + exact Jaccard."""


def shingle(text: str, *, mode: str = "word", k: int = 3) -> frozenset[str]:
    if mode == "line":
        # In line mode, each non-blank line is one shingle; k parameter is ignored.
        return frozenset(line for line in text.splitlines() if line.strip())
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
