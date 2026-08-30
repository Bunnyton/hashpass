# Logic Plane — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать чистые примитивы логического плана: движок хуков (`@command`/`@filter`/`@check`), нормализованный `Cmd`, и size-adaptive сравнение (шинглы+Jaccard / MinHash / exact) — фундамент, на который План D соберёт чекер.

**Architecture:** Всё pure-logic (tier1), без контейнеров и внешних зависимостей (MinHash на stdlib). Движок хуков — регистр с декораторами и диспетчерами. Сравнение size-adaptive: мелкий вход → точный Jaccard над множеством шинглов, крупный → MinHash-оценка Jaccard; exact crypto-hash как частный случай (threshold=1.0). Приёмный хэш служит проверке; ключ (key.py, План 1) — отдельный nonce.

**Tech Stack:** Python 3.13, pytest, ruff. Только stdlib (`shlex`, `re`, `hashlib`).

**Spec:** `docs/Архитектура (architecture).md` (§4 приём этапа, §5 канонизация/сравнение).

## Global Constraints

- **Python 3.13**; `encoding="utf-8"` во всех файловых операциях (здесь I/O почти нет — всё in-memory).
- **Только stdlib** — никаких numpy/datasketch/ssdeep. MinHash — на `hashlib`. (ssdeep из §5 — опция будущего плана, здесь OUT OF SCOPE.)
- **pytest-маркеры:** всё `@pytest.mark.tier1` (pure). ruff-чистота обязательна (тесты линтуются). Импорты сортированы, без `;`-строк.
- Пакет под `src/hashpass/`.
- Референс для порта: `git show origin/dev:config/images/basesettings/.hash/dvs/hooks/engine.py` и `git show origin/dev:config/images/base/.hash/dvs/cmd/__init__.py`. Портируем механику, пишем чисто и с тестами; **чиним баг `Cmd.is_similar`** (оригинал обращается к `other.cmd` вместо `other.basecmd`).
- **Приёмный хэш ≠ материал ключа** (§6): сравнение отдаёт `float`/`bool`, ключ не трогаем.
- TDD, DRY, YAGNI. Каждая задача — независимо тестируемый результат.

---

### Task 1: Hook engine

**Files:**
- Create: `src/hashpass/hooks.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Produces:
  - `class HookRegistry` с декораторами `command(stages=None)`, `filter(stages=None)`, `check(stages=None)` и диспетчерами:
    - `run_command(cmd: str, stage: int) -> dict` → `{"before": list[str], "cmd": list[str], "after": list[str]}`
    - `run_filter(cmd: str, data: str, stage: int) -> str`
    - `run_check(cmd: str, stage: int) -> bool | None`
  - Модульный дефолт `registry = HookRegistry()` и алиасы `command/filter/check`.
- Семантика (dev-референс): command-хуки по порядку; если `res["cmd"]` пуст — дальнейшие пропускаются; `before`/`after` аккумулируются. check: первый не-`None` (`True`/`False`); все `None` → `None`. `stages=None` = все этапы, иначе `stage in stages`.

- [ ] **Step 1: Failing test**

```python
# tests/test_hooks.py
import pytest
from hashpass.hooks import HookRegistry


@pytest.mark.tier1
def test_command_check_filter_dispatch():
    r = HookRegistry()

    @r.command(stages=None)
    def block_grep(cmd, stage):
        if cmd.split()[0] == "grep":
            return {"before": ["echo blocked"], "cmd": [], "after": []}
        return {"before": [], "cmd": [cmd], "after": []}

    assert r.run_command("grep x", 0) == {"before": ["echo blocked"], "cmd": [], "after": []}
    assert r.run_command("ls -la", 0) == {"before": [], "cmd": ["ls -la"], "after": []}

    @r.filter(stages=[0])
    def strip_size(cmd, data, stage):
        return data.replace("SIZE", "")

    assert r.run_filter("ls", "aSIZEb", 0) == "ab"
    assert r.run_filter("ls", "aSIZEb", 1) == "aSIZEb"

    @r.check(stages=None)
    def accept_ls(cmd, stage):
        if cmd == "ls":
            return True
        return None

    assert r.run_check("ls", 0) is True
    assert r.run_check("pwd", 0) is None
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/test_hooks.py -v` → FAIL (module not found).

- [ ] **Step 3: hooks.py**

```python
# src/hashpass/hooks.py
"""Runtime hook engine: @command / @filter / @check registration + dispatch."""
from collections.abc import Callable


class HookRegistry:
    def __init__(self) -> None:
        self._command: list[dict] = []
        self._filter: list[dict] = []
        self._check: list[dict] = []

    def command(self, stages: list[int] | None = None) -> Callable:
        def register(handler: Callable) -> Callable:
            self._command.append({"stages": stages, "handler": handler})
            return handler
        return register

    def filter(self, stages: list[int] | None = None) -> Callable:  # noqa: A003
        def register(handler: Callable) -> Callable:
            self._filter.append({"stages": stages, "handler": handler})
            return handler
        return register

    def check(self, stages: list[int] | None = None) -> Callable:
        def register(handler: Callable) -> Callable:
            self._check.append({"stages": stages, "handler": handler})
            return handler
        return register

    @staticmethod
    def _applies(stages: list[int] | None, stage: int) -> bool:
        return stages is None or stage in stages

    def run_command(self, cmd: str, stage: int) -> dict:
        res: dict = {"before": [], "cmd": [cmd], "after": []}
        for ch in self._command:
            if self._applies(ch["stages"], stage) and res["cmd"]:
                r = ch["handler"](cmd, stage)
                res["before"].extend(r["before"])
                res["after"].extend(r["after"])
                res["cmd"] = r["cmd"]
        return res

    def run_filter(self, cmd: str, data: str, stage: int) -> str:
        for ch in self._filter:
            if self._applies(ch["stages"], stage):
                data = ch["handler"](cmd, data, stage)
        return data

    def run_check(self, cmd: str, stage: int) -> bool | None:
        for ch in self._check:
            if self._applies(ch["stages"], stage):
                res = ch["handler"](cmd, stage)
                if res is not None:
                    return res
        return None


registry = HookRegistry()
command = registry.command
filter = registry.filter  # noqa: A001
check = registry.check
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/test_hooks.py -v` (PASS), `ruff check src tests runtime` (clean).
```bash
git add -A && git commit -m "feat(hooks): hook engine (command/filter/check registry + dispatch)"
```

---

### Task 2: `Cmd` normalized command

**Files:**
- Create: `src/hashpass/cmd.py`
- Test: `tests/test_cmd.py`

**Interfaces:**
- Produces: `class Cmd(raw)` с полями `raw, tokens, is_sudo, basecmd, short_flags: set, long_flags: set, args: list`; методы `has_flag`, `__eq__`, `__hash__`, `__contains__` (подмножество), `is_similar` (**через `other.basecmd`**); `parse_cmds(raw) -> list[Cmd]` (сплит по `&&`/`;`/`||`).

- [ ] **Step 1: Failing test**

```python
# tests/test_cmd.py
import pytest
from hashpass.cmd import Cmd, parse_cmds


@pytest.mark.tier1
def test_cmd_parse_eq_contains_similar():
    c = Cmd("sudo rm -rf /tmp/x")
    assert c.is_sudo
    assert c.basecmd == "rm"
    assert c.short_flags == {"r", "f"}
    assert c.args == ["/tmp/x"]
    assert c.has_flag("-r")
    assert c.has_flag("-f")
    assert not c.has_flag("--force")

    assert Cmd("ls -la") == Cmd("ls -la")
    assert Cmd("ls -la") != Cmd("ls -l")
    assert Cmd("rm -r") in Cmd("rm -rf /tmp/x")
    assert Cmd("rm -z") not in Cmd("rm -rf /tmp/x")
    assert Cmd("grep -i foo").is_similar(Cmd("grep -i bar"))
    assert not Cmd("grep -i foo").is_similar(Cmd("grep foo"))


@pytest.mark.tier1
def test_parse_cmds_splits():
    cmds = parse_cmds("apt update && apt install sl ; echo done")
    assert [c.basecmd for c in cmds] == ["apt", "apt", "echo"]
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/test_cmd.py -v` → FAIL.

- [ ] **Step 3: cmd.py** (ported from dev, `is_similar` fixed)

```python
# src/hashpass/cmd.py
"""Normalized shell command parsing/comparison."""
import re
import shlex


class Cmd:
    def __init__(self, raw: str) -> None:
        self.raw = raw.strip()
        self.tokens = shlex.split(self.raw)
        self.is_sudo = bool(self.tokens) and self.tokens[0] == "sudo"
        self._parse()

    def _parse(self) -> None:
        tokens = self.tokens[1:] if self.is_sudo else self.tokens
        self.short_flags: set[str] = set()
        self.long_flags: set[str] = set()
        self.args: list[str] = []
        self.basecmd = tokens[0] if tokens else ""
        for token in tokens[1:]:
            if token.startswith("--"):
                self.long_flags.add(token[2:].split("=")[0])
            elif token.startswith("-") and len(token) > 1:
                self.short_flags.update(token[1:])
            else:
                self.args.append(token)

    def has_flag(self, flag: str) -> bool:
        if flag.startswith("--"):
            return flag[2:] in self.long_flags
        if flag.startswith("-"):
            return flag[1:] in self.short_flags
        return False

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Cmd):
            return NotImplemented
        return (self.basecmd == other.basecmd and self.short_flags == other.short_flags
                and self.long_flags == other.long_flags and self.args == other.args)

    def __hash__(self) -> int:
        return hash((self.basecmd, frozenset(self.short_flags),
                     frozenset(self.long_flags), tuple(self.args)))

    def __contains__(self, cmd: object) -> bool:
        if not isinstance(cmd, Cmd):
            return NotImplemented
        return (self.basecmd == cmd.basecmd
                and cmd.short_flags <= self.short_flags
                and cmd.long_flags <= self.long_flags
                and all(a in self.args for a in cmd.args))

    def is_similar(self, other: object) -> bool:
        if not isinstance(other, Cmd):
            return False
        return (self.basecmd == other.basecmd
                and self.short_flags == other.short_flags
                and self.long_flags == other.long_flags)

    def __repr__(self) -> str:
        sudo = "sudo " if self.is_sudo else ""
        return f"<Cmd {sudo}{self.basecmd} {sorted(self.short_flags)} {self.args}>"


def parse_cmds(raw: str) -> list[Cmd]:
    parts = re.split(r"\s*(?:&&|\|\||;)\s*", raw.strip())
    return [Cmd(p) for p in parts if p.strip()]
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/test_cmd.py -v` (PASS), `ruff check src tests runtime` (clean).
```bash
git add -A && git commit -m "feat(cmd): normalized Cmd parsing/comparison (is_similar bug fixed)"
```

---

### Task 3: Shingling + exact Jaccard

**Files:**
- Create: `src/hashpass/compare/__init__.py` (empty package marker, filled in Task 5)
- Create: `src/hashpass/compare/shingle.py`
- Create: `tests/compare/__init__.py` (empty)
- Test: `tests/compare/test_shingle.py`

**Interfaces:**
- Produces:
  - `shingle(text: str, *, mode: str = "word", k: int = 3) -> frozenset[str]` — `mode` in `{"char","word","line"}`.
  - `jaccard(a, b) -> float` — `|a∩b|/|a∪b|`; обе пустые → `1.0`.

- [ ] **Step 1: Failing test**

```python
# tests/compare/test_shingle.py
import pytest
from hashpass.compare.shingle import jaccard, shingle


@pytest.mark.tier1
def test_shingle_modes_and_jaccard():
    assert shingle("abcd", mode="char", k=2) == frozenset({"ab", "bc", "cd"})
    assert shingle("a b c", mode="word", k=2) == frozenset({"a b", "b c"})
    assert shingle("x\n\ny", mode="line") == frozenset({"x", "y"})

    assert jaccard(frozenset(), frozenset()) == 1.0
    assert jaccard({"a"}, set()) == 0.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/compare/test_shingle.py -v` → FAIL.

- [ ] **Step 3: shingle.py**

```python
# src/hashpass/compare/shingle.py
"""Shingling + exact Jaccard."""


def shingle(text: str, *, mode: str = "word", k: int = 3) -> frozenset[str]:
    if mode == "line":
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
    return frozenset(joiner.join(units[i:i + k]) for i in range(len(units) - k + 1))


def jaccard(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 1.0
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/compare/test_shingle.py -v` (PASS), `ruff check src tests runtime` (clean).
```bash
git add -A && git commit -m "feat(compare): shingling + exact Jaccard"
```

---

### Task 4: MinHash (pure stdlib)

**Files:**
- Create: `src/hashpass/compare/minhash.py`
- Test: `tests/compare/test_minhash.py`

**Interfaces:**
- Produces:
  - `minhash_signature(shingles, *, num_perm=128) -> tuple[int, ...]` — для каждой перестановки `i`: `min` по `sha1(f"{i}:{s}")`. Пустое множество → сигнатура из `num_perm` значений `_MAX` (sentinel).
  - `minhash_jaccard(sig_a, sig_b) -> float` — доля совпавших позиций; длины должны совпадать (иначе `ValueError`).

- [ ] **Step 1: Failing test**

```python
# tests/compare/test_minhash.py
import pytest
from hashpass.compare.minhash import minhash_jaccard, minhash_signature
from hashpass.compare.shingle import jaccard, shingle


@pytest.mark.tier1
def test_minhash_estimates_jaccard():
    a = shingle(" ".join(str(i) for i in range(200)), mode="word", k=2)
    b = shingle(" ".join(str(i) for i in range(100, 300)), mode="word", k=2)
    sa = minhash_signature(a, num_perm=256)
    sb = minhash_signature(b, num_perm=256)
    assert minhash_signature(a, num_perm=256) == sa
    assert minhash_jaccard(sa, sa) == 1.0
    assert abs(minhash_jaccard(sa, sb) - jaccard(a, b)) < 0.1


@pytest.mark.tier1
def test_minhash_length_mismatch_raises():
    with pytest.raises(ValueError, match="length"):
        minhash_jaccard((1, 2), (1, 2, 3))
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/compare/test_minhash.py -v` → FAIL.

- [ ] **Step 3: minhash.py**

```python
# src/hashpass/compare/minhash.py
"""Pure-stdlib MinHash signatures + Jaccard estimate."""
import hashlib

_MAX = (1 << 64) - 1


def _h(shingle: str, i: int) -> int:
    digest = hashlib.sha1(f"{i}:{shingle}".encode()).digest()  # noqa: S324
    return int.from_bytes(digest[:8], "big")


def minhash_signature(shingles: set[str] | frozenset[str], *, num_perm: int = 128) -> tuple[int, ...]:
    if not shingles:
        return tuple(_MAX for _ in range(num_perm))
    return tuple(min(_h(s, i) for s in shingles) for i in range(num_perm))


def minhash_jaccard(sig_a: tuple[int, ...], sig_b: tuple[int, ...]) -> float:
    if len(sig_a) != len(sig_b):
        msg = "signature length mismatch"
        raise ValueError(msg)
    if not sig_a:
        return 1.0
    return sum(1 for x, y in zip(sig_a, sig_b, strict=True) if x == y) / len(sig_a)
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/compare/test_minhash.py -v` (PASS), `ruff check src tests runtime` (clean).
```bash
git add -A && git commit -m "feat(compare): pure-stdlib MinHash signatures + jaccard estimate"
```

---

### Task 5: Size-adaptive similarity + accept + exact hash

**Files:**
- Modify: `src/hashpass/compare/__init__.py`
- Test: `tests/compare/test_similarity.py`

**Interfaces:**
- Consumes: `shingle`/`jaccard` (Task 3), `minhash_signature`/`minhash_jaccard` (Task 4).
- Produces (в `compare/__init__.py`):
  - `similarity(a, b, *, mode="word", k=3, size_threshold=4096, num_perm=128) -> float` — `max(len(a),len(b)) <= size_threshold` → точный `jaccard`; иначе → `minhash_jaccard`. Оба пустых → `1.0`.
  - `accept(a, b, *, threshold, **kw) -> bool` — `similarity(...) >= threshold`.
  - `exact_hash(data: str) -> str` — `sha256` hex.

- [ ] **Step 1: Failing test**

```python
# tests/compare/test_similarity.py
import pytest
from hashpass.compare import accept, exact_hash, similarity


@pytest.mark.tier1
def test_similarity_small_path_exact_jaccard():
    assert similarity("a b c", "a b c", size_threshold=4096) == 1.0
    assert similarity("a b c d", "a b c e", mode="word", k=1, size_threshold=4096) == pytest.approx(3 / 5)
    assert similarity("", "", size_threshold=4096) == 1.0


@pytest.mark.tier1
def test_similarity_large_path_uses_minhash():
    big_a = " ".join(str(i) for i in range(2000))
    big_b = " ".join(str(i) for i in range(1000, 3000))
    s = similarity(big_a, big_b, mode="word", k=2, size_threshold=100, num_perm=256)
    assert 0.2 < s < 0.45


@pytest.mark.tier1
def test_accept_threshold_and_exact_hash():
    assert accept("a b c", "a b x", mode="word", k=1, threshold=0.3, size_threshold=4096)
    assert not accept("a b c", "x y z", mode="word", k=1, threshold=0.3, size_threshold=4096)
    assert exact_hash("hi") == exact_hash("hi")
    assert exact_hash("hi") != exact_hash("ho")
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/compare/test_similarity.py -v` → FAIL.

- [ ] **Step 3: compare/__init__.py**

```python
# src/hashpass/compare/__init__.py
"""Size-adaptive similarity: exact Jaccard for small inputs, MinHash for large."""
import hashlib

from hashpass.compare.minhash import minhash_jaccard, minhash_signature
from hashpass.compare.shingle import jaccard, shingle

__all__ = ["accept", "exact_hash", "jaccard", "shingle", "similarity"]


def similarity(a: str, b: str, *, mode: str = "word", k: int = 3,
               size_threshold: int = 4096, num_perm: int = 128) -> float:
    if not a and not b:
        return 1.0
    sa, sb = shingle(a, mode=mode, k=k), shingle(b, mode=mode, k=k)
    if max(len(a), len(b)) <= size_threshold:
        return jaccard(sa, sb)
    return minhash_jaccard(minhash_signature(sa, num_perm=num_perm),
                           minhash_signature(sb, num_perm=num_perm))


def accept(a: str, b: str, *, threshold: float, **kw: object) -> bool:
    return similarity(a, b, **kw) >= threshold


def exact_hash(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/compare/test_similarity.py -v` (PASS), `ruff check src tests runtime` (clean), `pytest -q -m "not tier3"` (green).
```bash
git add -A && git commit -m "feat(compare): size-adaptive similarity + accept + exact_hash"
```

---

### Task 6: Integration — hooks + Cmd + compare compose

**Files:**
- Test: `tests/test_logic_integration.py`

**Interfaces:**
- Consumes: `HookRegistry` (Task 1), `Cmd` (Task 2), `accept` (Task 5).

- [ ] **Step 1: Integration test**

```python
# tests/test_logic_integration.py
import pytest
from hashpass.cmd import Cmd
from hashpass.compare import accept
from hashpass.hooks import HookRegistry


@pytest.mark.tier1
def test_filter_then_compare_accepts_within_threshold():
    r = HookRegistry()

    @r.filter(stages=None)
    def drop_timestamp(cmd, data, stage):
        return "\n".join(line.split(" ", 1)[-1] for line in data.splitlines())

    ref = r.run_filter("ls", "10:00 a\n10:00 b", 0)
    got = r.run_filter("ls", "11:59 a\n12:00 b", 0)
    assert ref == got
    assert accept(ref, got, mode="line", k=1, threshold=1.0, size_threshold=4096)


@pytest.mark.tier1
def test_check_hook_uses_cmd_normalization():
    r = HookRegistry()

    @r.check(stages=None)
    def wants_recursive_rm(cmd, stage):
        c = Cmd(cmd)
        if c.basecmd == "rm" and c.has_flag("-r"):
            return True
        return None

    assert r.run_check("rm -rf /tmp/x", 0) is True
    assert r.run_check("sudo rm -r /tmp/x", 0) is True
    assert r.run_check("rm /tmp/x", 0) is None
```

- [ ] **Step 2: Run → PASS**

Run: `pytest tests/test_logic_integration.py -v` (PASS), then `pytest -q -m "not tier3"` (green) and `ruff check src tests runtime` (clean).

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test: logic-plane integration (filter+compare, check+Cmd)"
```

---

## Out of scope (future plans)

- **ssdeep / CTPH** (§5, крупные бинарно-фрагментные) — требует C-зависимости; позже.
- **Дифф-канонизация** (§5, риск-гейт) — отдельный план (нужен `Runner`).
- **Чекер-сборка** (хэш + условия метода + `@check`) и **conditions**-слой — План D.
