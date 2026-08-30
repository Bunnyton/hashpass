# Differential Canonicalization (risk-gate) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать и ВАЛИДИРОВАТЬ дифференциальную канонизацию: прогнать эталон k раз с безобидным шумом, выбросить поля, меняющиеся между прогонами, и получить стабильный инвариант, по которому принимается этап. Задача 5 — риск-гейт: если она не проходит, подход надо пересматривать (сообщить контроллеру).

**Architecture:** Pure-logic + `Runner`-порт (из Плана 1). `capture` снимает пост-прогонный снимок наблюдаемых путей (Observation = map path→FileState). `derive_canonical` вызывает `run_once` k раз и оставляет только поля, идентичные во всех прогонах. `matches` сверяет кандидата с каноном, используя size-adaptive `similarity` (Плана 2) — поля, отсутствующие в каноне (волатильные), не проверяются. Спайк — на `TmpdirRunner` (tier2), без nspawn: логика канонизации Runner-агностична.

**Tech Stack:** Python 3.13, pytest, ruff. stdlib + `hashpass.runner`/`hashpass.compare` (уже в `main`).

**Spec:** `docs/Архитектура (architecture).md` §5 (канонизация: дифф-прогоны + шум; толерантное сравнение).

## Global Constraints

- **Python 3.13**; `encoding="utf-8"` во всех файловых операциях.
- pytest-маркеры: `tier1` (pure — capture/differential/matches на синтетике или tmpdir-как-rootfs); `tier2` (noise/derive/спайк на `TmpdirRunner`, без sudo). ruff-чистота обязательна (тесты линтуются; magic-value в тестах → scoped `# noqa: PLR2004`).
- Только stdlib + `hashpass.compare` (Plan 2) + `hashpass.runner` (Plan 1). Без внешних зависимостей.
- **Приёмный инвариант ≠ материал ключа** (§6): `matches` возвращает `bool`, канон — данные для проверки.
- Пакет `src/hashpass/canon/`.
- TDD, DRY, YAGNI. Каждая задача — независимо тестируемый результат.
- **Задача 5 — риск-гейт.** Если спайк-тесты не проходят по существу (волатильное не обрезается / стабильное обрезается / неверное принимается), это находка о подходе — имплементер сообщает BLOCKED с деталями, не «чинит» подгонкой.

---

### Task 1: Observation model + capture

**Files:**
- Create: `src/hashpass/canon/__init__.py` (empty package marker, filled in Task 4)
- Create: `src/hashpass/canon/capture.py`
- Create: `tests/canon/__init__.py` (empty)
- Test: `tests/canon/test_capture.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) FileState(kind: str, text: str | None)` — `kind` in `{"file","dir","absent"}`; `text` = file contents (utf-8) or `None` (dir/absent/binary-unreadable).
  - `Observation = dict[str, FileState]`
  - `capture(rootfs: Path, observe: list[str], *, output_path: str | None = None) -> Observation` — для каждого пути в `observe`: если каталог — рекурсивно все файлы (ключ = путь относительно rootfs); если файл — сам файл; плюс, если задан `output_path`, ключ `"<output>"`. Пути в `observe`/`output_path` трактуются относительно `rootfs` (ведущий `/` срезается).

- [ ] **Step 1: Failing test**

```python
# tests/canon/test_capture.py
import pytest
from hashpass.canon.capture import FileState, capture


@pytest.mark.tier1
def test_capture_files_dirs_and_output(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "b.txt").write_text("world", encoding="utf-8")
    (tmp_path / "out").write_text("OUT", encoding="utf-8")

    obs = capture(tmp_path, ["a.txt", "d", "missing.txt"], output_path="out")
    assert obs["a.txt"] == FileState("file", "hello")
    assert obs["d/b.txt"] == FileState("file", "world")
    assert obs["missing.txt"] == FileState("absent", None)
    assert obs["<output>"] == FileState("file", "OUT")
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/canon/test_capture.py -v` → FAIL.

- [ ] **Step 3: capture.py**

```python
# src/hashpass/canon/capture.py
"""Post-run snapshot of observed paths → Observation."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileState:
    kind: str  # "file" | "dir" | "absent"
    text: str | None


Observation = dict[str, "FileState"]


def _read(p: Path) -> FileState:
    if p.is_dir():
        return FileState("dir", None)
    if p.is_file():
        try:
            return FileState("file", p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            return FileState("file", None)
    return FileState("absent", None)


def capture(rootfs: Path, observe: list[str], *, output_path: str | None = None) -> Observation:
    rootfs = Path(rootfs)
    obs: Observation = {}
    for rel in observe:
        base = rootfs / rel.lstrip("/")
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    obs[str(f.relative_to(rootfs))] = _read(f)
        else:
            obs[rel.lstrip("/")] = _read(base)
    if output_path is not None:
        obs["<output>"] = _read(rootfs / output_path.lstrip("/"))
    return obs
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/canon/test_capture.py -v` (PASS), `ruff check src tests runtime` (clean).
```bash
git add -A && git commit -m "feat(canon): Observation model + capture"
```

---

### Task 2: Noise injector

**Files:**
- Create: `src/hashpass/canon/noise.py`
- Test: `tests/canon/test_noise.py`

**Interfaces:**
- Consumes: `Runner` (Plan 1, `hashpass.runner.base`).
- Produces:
  - `default_noise() -> list[list[str]]` — argv-списки безобидных ортогональных действий (создать+удалить временный каталог под относительным скретчем; спавн быстрых подпроцессов). Net-zero по состоянию.
  - `run_noise(runner, noise=None) -> None` — прогоняет каждый argv через `runner.run` (дефолт — `default_noise()`).

- [ ] **Step 1: Failing test**

```python
# tests/canon/test_noise.py
import pytest
from hashpass.canon.capture import capture
from hashpass.canon.noise import run_noise
from hashpass.runner.tmpdir import TmpdirRunner


@pytest.mark.tier2
def test_noise_perturbs_but_does_not_touch_observed(tmp_path):
    r = TmpdirRunner(tmp_path / "run")
    r.prepare([])
    r.run(["sh", "-c", "echo answer > result.txt"])
    before = capture(r.rootfs, ["result.txt"])
    run_noise(r)
    after = capture(r.rootfs, ["result.txt"])
    assert before == after  # observed path unchanged by noise
    r.teardown()
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/canon/test_noise.py -v -m tier2` → FAIL.

- [ ] **Step 3: noise.py**

```python
# src/hashpass/canon/noise.py
"""Harmless orthogonal noise: perturb incidental state without touching observed paths."""
from hashpass.runner.base import Runner


def default_noise() -> list[list[str]]:
    return [
        ["sh", "-c", "d=$(mktemp -d ./noise.XXXXXX); : > \"$d/f\"; rm -rf \"$d\""],
        ["sh", "-c", "for _ in 1 2 3; do (true &) ; done; wait 2>/dev/null || true"],
    ]


def run_noise(runner: Runner, noise: list[list[str]] | None = None) -> None:
    for cmd in noise if noise is not None else default_noise():
        runner.run(cmd)
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/canon/test_noise.py -v -m tier2` (PASS), `ruff check src tests runtime` (clean).
```bash
git add -A && git commit -m "feat(canon): harmless orthogonal noise injector"
```

---

### Task 3: Differential canonicalizer

**Files:**
- Create: `src/hashpass/canon/differential.py`
- Test: `tests/canon/test_differential.py`

**Interfaces:**
- Consumes: `FileState`/`Observation` (Task 1).
- Produces:
  - `canonicalize(observations: list[Observation]) -> Observation` — оставляет только ключи, чьё `FileState` идентично во ВСЕХ наблюдениях (присутствует и равно). Пустой список → `{}`.
  - `derive_canonical(run_once: Callable[[], Observation], *, k: int = 3) -> Observation` — вызывает `run_once()` k раз и канонизирует. `k < 2` → `ValueError`.

- [ ] **Step 1: Failing test**

```python
# tests/canon/test_differential.py
import itertools

import pytest
from hashpass.canon.capture import FileState
from hashpass.canon.differential import canonicalize, derive_canonical


@pytest.mark.tier1
def test_canonicalize_keeps_stable_drops_varying():
    stable = FileState("file", "answer")
    obs = [
        {"result.txt": stable, "time.txt": FileState("file", "1")},
        {"result.txt": stable, "time.txt": FileState("file", "2")},
        {"result.txt": stable, "time.txt": FileState("file", "3")},
    ]
    canon = canonicalize(obs)
    assert canon == {"result.txt": stable}  # time.txt varied → pruned
    assert canonicalize([]) == {}


@pytest.mark.tier1
def test_derive_canonical_runs_k_times_and_requires_k_ge_2():
    counter = itertools.count()

    def run_once():
        i = next(counter)
        return {"result.txt": FileState("file", "answer"),
                "time.txt": FileState("file", str(i))}

    canon = derive_canonical(run_once, k=3)
    assert canon == {"result.txt": FileState("file", "answer")}
    assert next(counter) == 3  # run_once called exactly k times

    with pytest.raises(ValueError, match="k must be"):
        derive_canonical(run_once, k=1)
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/canon/test_differential.py -v` → FAIL.

- [ ] **Step 3: differential.py**

```python
# src/hashpass/canon/differential.py
"""Differential canonicalization: keep only fields stable across all runs."""
from collections.abc import Callable

from hashpass.canon.capture import Observation


def canonicalize(observations: list[Observation]) -> Observation:
    if not observations:
        return {}
    first = observations[0]
    return {
        key: state
        for key, state in first.items()
        if all(key in obs and obs[key] == state for obs in observations)
    }


def derive_canonical(run_once: Callable[[], Observation], *, k: int = 3) -> Observation:
    if k < 2:
        msg = "k must be >= 2 for differential canonicalization"
        raise ValueError(msg)
    return canonicalize([run_once() for _ in range(k)])
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/canon/test_differential.py -v` (PASS), `ruff check src tests runtime` (clean).
```bash
git add -A && git commit -m "feat(canon): differential canonicalizer"
```

---

### Task 4: `matches` + package re-exports

**Files:**
- Modify: `src/hashpass/canon/__init__.py`
- Test: `tests/canon/test_matches.py`

**Interfaces:**
- Consumes: `FileState`/`Observation`/`capture` (Task 1), `canonicalize`/`derive_canonical` (Task 3), `default_noise`/`run_noise` (Task 2), `similarity` (Plan 2 `hashpass.compare`).
- Produces (в `canon/__init__.py`):
  - `matches(canonical, candidate, *, threshold=1.0, mode="line", k=1) -> bool` — для каждого поля канона: кандидат должен иметь его с тем же `kind`; для файлов с непустым текстом — `similarity(want, got, mode, k) >= threshold`; для `None`-текста — точное равенство. Поля вне канона не проверяются.
  - re-exports: `FileState, Observation, capture, canonicalize, derive_canonical, default_noise, run_noise, matches`.

- [ ] **Step 1: Failing test**

```python
# tests/canon/test_matches.py
import pytest
from hashpass.canon import FileState, matches


@pytest.mark.tier1
def test_matches_checks_only_canonical_fields():
    canon = {"result.txt": FileState("file", "answer")}
    # candidate matches the stable field, plus has an extra volatile field (ignored)
    ok = {"result.txt": FileState("file", "answer"), "time.txt": FileState("file", "999")}
    assert matches(canon, ok)
    # wrong stable field → reject
    bad = {"result.txt": FileState("file", "WRONG")}
    assert not matches(canon, bad)
    # missing stable field → reject
    assert not matches(canon, {})


@pytest.mark.tier1
def test_matches_tolerant_threshold():
    canon = {"out": FileState("file", "a\nb\nc")}
    close = {"out": FileState("file", "a\nb\nX")}
    assert matches(canon, close, mode="line", k=1, threshold=0.6)  # 2/3 lines
    assert not matches(canon, close, mode="line", k=1, threshold=0.9)
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/canon/test_matches.py -v` → FAIL.

- [ ] **Step 3: canon/__init__.py**

```python
# src/hashpass/canon/__init__.py
"""Differential canonicalization + tolerant matching against a canonical invariant."""
from hashpass.canon.capture import FileState, Observation, capture
from hashpass.canon.differential import canonicalize, derive_canonical
from hashpass.canon.noise import default_noise, run_noise
from hashpass.compare import similarity

__all__ = ["FileState", "Observation", "canonicalize", "capture", "default_noise",
           "derive_canonical", "matches", "run_noise"]


def matches(canonical: Observation, candidate: Observation, *,
            threshold: float = 1.0, mode: str = "line", k: int = 1) -> bool:
    for key, want in canonical.items():
        got = candidate.get(key)
        if got is None or got.kind != want.kind:
            return False
        if want.kind == "file":
            if want.text is None or got.text is None:
                if want.text != got.text:
                    return False
            elif similarity(want.text, got.text, mode=mode, k=k) < threshold:
                return False
    return True
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/canon/test_matches.py -v` (PASS), `ruff check src tests runtime` (clean), `pytest -q -m "not tier3"` (green).
```bash
git add -A && git commit -m "feat(canon): tolerant matches() + package re-exports"
```

---

### Task 5: SPIKE — risk-gate validation (tier2)

**Files:**
- Test: `tests/canon/test_spike.py`

**Interfaces:**
- Consumes: `capture`, `derive_canonical`, `matches`, `run_noise` (canon), `TmpdirRunner` (Plan 1).

**RISK-GATE:** This test validates the core bet. If it fails on the merits (volatile field NOT pruned, stable field pruned, or a wrong solution accepted), do NOT paper over it — report BLOCKED with the exact observations, because it means the differential-canonicalization approach needs rework.

- [ ] **Step 1: Spike test**

```python
# tests/canon/test_spike.py
import itertools

import pytest
from hashpass.canon import capture, derive_canonical, matches, run_noise
from hashpass.runner.tmpdir import TmpdirRunner


def _runner_run_once(tmp_path, sol_cmds, observe):
    counter = itertools.count()

    def run_once():
        r = TmpdirRunner(tmp_path / f"r{next(counter)}")
        r.prepare([])
        for c in sol_cmds:
            r.run(["sh", "-c", c])
        run_noise(r)
        obs = capture(r.rootfs, observe)
        r.teardown()
        return obs

    return run_once


@pytest.mark.tier2
def test_spike_deterministic_stable_and_discriminating(tmp_path):
    observe = ["result.txt"]
    ref = ["echo answer > result.txt"]
    canon = derive_canonical(_runner_run_once(tmp_path, ref, observe), k=3)
    assert canon["result.txt"].text.strip() == "answer"
    assert matches(canon, _runner_run_once(tmp_path, ref, observe)())
    wrong = _runner_run_once(tmp_path, ["echo WRONG > result.txt"], observe)()
    assert not matches(canon, wrong)


@pytest.mark.tier2
def test_spike_time_noise_auto_pruned(tmp_path):
    # ref writes a STABLE answer + a VOLATILE nanosecond timestamp
    observe = ["result.txt", "time.txt"]
    ref = ["echo answer > result.txt", "date +%s%N > time.txt"]
    canon = derive_canonical(_runner_run_once(tmp_path, ref, observe), k=3)
    # THE core bet: volatile field auto-pruned, stable field kept
    assert "result.txt" in canon
    assert "time.txt" not in canon
    # a correct solution at a different time still matches (timestamp not checked)
    assert matches(canon, _runner_run_once(tmp_path, ref, observe)())
    # a wrong result is rejected even though it also carries a (different) timestamp
    wrong = _runner_run_once(
        tmp_path, ["echo WRONG > result.txt", "date +%s%N > time.txt"], observe)()
    assert not matches(canon, wrong)
```

- [ ] **Step 2: Run → PASS (risk-gate)**

Run: `pytest tests/canon/test_spike.py -v -m tier2` (must PASS — this validates the approach), then `pytest -q -m "not tier3"` (green) and `ruff check src tests runtime` (clean). If a spike assertion fails on the merits, report BLOCKED with the actual canon/observations rather than adjusting the test.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "test(canon): risk-gate spike — differential canonicalization validated"
```

---

## Out of scope (future plans)

- **tier3 nspawn validation** канонизации — интегрируется в План D (реальный чекер + захват из nspawn).
- **Гранулярность/пороги per-stage** (§5) — пинятся в конфиге задания (План D).
- **Захват через watchdog вживую** (как в dev) — не нужен: пост-прогонный снимок проще и Runner-агностичен.
