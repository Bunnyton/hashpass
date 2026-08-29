# Foundation + Walking Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять чистый rebuild-каркас с CI и `Runner`-портом, и довести до сквозного walking skeleton: контейнер загружает тривиальное задание, проверяет его stub-чекером и выдаёт локальный ключ.

**Architecture:** Ports & adapters. Среда спрятана за интерфейсом `Runner` (адаптеры `TmpdirRunner`/`DockerRunner`/`NspawnRunner`). Логика (задание, чекер, ключ) не зависит от драйвера. Прод-механизм — overlay-компоновка слоёв + `systemd-nspawn -b`, доказан смоуком; изменения контейнера персистятся в upperdir.

**Tech Stack:** Python 3.13, pytest, ruff, systemd-nspawn + overlayfs, docker (rootless, для tier-2), GitHub Actions.

**Spec:** `docs/Архитектура (architecture).md` (разделы §1, §2, §3, §10).

## Global Constraints

- **Python 3.13**; `encoding="utf-8"` во всех файловых операциях.
- **pytest-маркеры:** `tier1` (pure, дефолт), `tier2` (docker/rootless-overlay, без sudo), `tier3` (nspawn, требует scoped passwordless sudo — запускается локально / на self-hosted раннере).
- **ruff** target `py313`, линт чистый.
- **Никакого мастер-ключа / обфускации / zip-пароля** в новом коде — никогда (§8/§9).
- Среда — только через `Runner`; прямых вызовов `systemd-nspawn`/`mount` вне `NspawnRunner` нет.
- **Нет захардкоженных путей** (`/opt/.hashpass` и т.п.) — через конфиг/env, дефолт задаётся в одном месте.
- Порт-механик берётся как референс из ветки dev: `git show origin/dev:config/images/base/.hash/dvs/<file>`.
- TDD, DRY, YAGNI, частые коммиты. Каждая задача заканчивается независимо тестируемым результатом.
- Sudo для tier-3 уже выдан scoped (`/etc/sudoers.d/hashpass-dev`): `systemd-nspawn, machinectl, mount, umount, tar, rsync`.

---

### Task 1: Project scaffold + CI

**Files:**
- Create: `pyproject.toml`
- Create: `src/hashpass/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `.github/workflows/ci.yml`
- Remove (git rm, сохранены в истории + ветке dev): `hashpass/` (старый пакет), `hashengine.py`, `hashpass.py`, `keygen.py`, `obfuscate.py`, `templates/`
- Keep: `docs/`, `install/`, `requirements/`, `ruff.toml`

**Interfaces:**
- Produces: пакет `hashpass` (src-layout), команда `pytest`, маркеры `tier1/2/3`.

- [ ] **Step 1: Убрать легаси-код из рабочего дерева (референс остаётся в git)**

```bash
git rm -r hashpass hashengine.py hashpass.py keygen.py obfuscate.py templates
```

- [ ] **Step 2: pyproject.toml (src-layout, pytest-маркеры)**

```toml
[project]
name = "hashpass"
version = "0.0.0"
requires-python = ">=3.13"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-m 'not tier3' -ra"
markers = [
    "tier1: pure logic, no containers",
    "tier2: docker/rootless-overlay, no sudo",
    "tier3: real systemd-nspawn, needs scoped sudo (local/self-hosted)",
]
```

- [ ] **Step 3: Пакет и первый тест**

```bash
mkdir -p src/hashpass tests
printf '__version__ = "0.0.0"\n' > src/hashpass/__init__.py
```

```python
# tests/test_smoke.py
import hashpass

def test_package_imports():
    assert hashpass.__version__ == "0.0.0"
```

- [ ] **Step 4: Прогнать тест и линт**

Run: `pip install -e '.[dev]' && pytest -q && ruff check src tests`
Expected: 1 passed; ruff clean.

- [ ] **Step 5: CI workflow (tier1+2, без nspawn)**

```yaml
# .github/workflows/ci.yml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -e '.[dev]'
      - run: ruff check src tests
      - run: pytest -q -m "not tier3"
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "chore: clean-rebuild scaffold (src-layout, pytest, ruff, CI)"
```

---

### Task 2: `Runner` port + `TmpdirRunner`

**Files:**
- Create: `src/hashpass/runner/__init__.py`
- Create: `src/hashpass/runner/base.py`
- Create: `src/hashpass/runner/tmpdir.py`
- Test: `tests/runner/test_tmpdir.py`

**Interfaces:**
- Produces:
  - `RunResult(stdout: str, stderr: str, exit_code: int)`
  - `class Runner(Protocol)` с `prepare(lowers: list[Path]) -> None`, `run(argv: list[str]) -> RunResult`, `rootfs: Path` (свойство), `teardown() -> None`.
  - `TmpdirRunner(workdir: Path)` — реализация без изоляции (subprocess в tmpdir).

- [ ] **Step 1: Failing test**

```python
# tests/runner/test_tmpdir.py
from pathlib import Path
from hashpass.runner.tmpdir import TmpdirRunner

def test_run_captures_stdout_and_fs(tmp_path):
    r = TmpdirRunner(tmp_path)
    r.prepare([])
    res = r.run(["sh", "-c", "echo hello > f.txt; echo done"])
    assert res.exit_code == 0
    assert res.stdout.strip() == "done"
    assert (r.rootfs / "f.txt").read_text().strip() == "hello"
    r.teardown()
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/runner/test_tmpdir.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: base.py**

```python
# src/hashpass/runner/base.py
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

@dataclass
class RunResult:
    stdout: str
    stderr: str
    exit_code: int

@runtime_checkable
class Runner(Protocol):
    def prepare(self, lowers: list[Path]) -> None: ...
    def run(self, argv: list[str]) -> RunResult: ...
    @property
    def rootfs(self) -> Path: ...
    def teardown(self) -> None: ...
```

- [ ] **Step 4: tmpdir.py**

```python
# src/hashpass/runner/tmpdir.py
import shutil, subprocess
from pathlib import Path
from .base import RunResult

class TmpdirRunner:
    def __init__(self, workdir: Path):
        self._root = Path(workdir) / "rootfs"

    def prepare(self, lowers: list[Path]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        for low in lowers:
            shutil.copytree(low, self._root, dirs_exist_ok=True)

    def run(self, argv: list[str]) -> RunResult:
        p = subprocess.run(argv, cwd=self._root, capture_output=True, text=True, encoding="utf-8")
        return RunResult(p.stdout, p.stderr, p.returncode)

    @property
    def rootfs(self) -> Path:
        return self._root

    def teardown(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)
```

- [ ] **Step 5: Run → PASS, commit**

Run: `pytest tests/runner/test_tmpdir.py -v`
Expected: PASS.
```bash
git add -A && git commit -m "feat(runner): Runner port + TmpdirRunner"
```

---

### Task 3: Overlay compose (rootless + sudo helpers)

**Files:**
- Create: `src/hashpass/overlay.py`
- Test: `tests/test_overlay.py`

**Interfaces:**
- Produces:
  - `overlay_mount(lowers: list[Path], upper: Path, work: Path, mnt: Path, *, sudo: bool) -> None`
  - `overlay_umount(mnt: Path, *, sudo: bool) -> None`
  - lowerdir порядок: слева-верхний слой (как в overlay: `lowerdir=top:...:bottom`).

- [ ] **Step 1: Failing test (rootless, tier2)**

```python
# tests/test_overlay.py
import os, subprocess
from pathlib import Path
import pytest
from hashpass.overlay import overlay_mount, overlay_umount

@pytest.mark.tier2
def test_rootless_overlay_write_lands_in_upper(tmp_path):
    low, up, wk, mnt = (tmp_path/d for d in ("low","up","wk","mnt"))
    for d in (low, up, wk, mnt): d.mkdir()
    (low/"base.txt").write_text("base")
    # rootless: выполняем в user+mount namespace через unshare
    script = f"""
from hashpass.overlay import overlay_mount, overlay_umount
from pathlib import Path
overlay_mount([Path("{low}")], Path("{up}"), Path("{wk}"), Path("{mnt}"), sudo=False)
assert (Path("{mnt}")/"base.txt").read_text() == "base"
(Path("{mnt}")/"new.txt").write_text("x")
overlay_umount(Path("{mnt}"), sudo=False)
assert (Path("{up}")/"new.txt").read_text() == "x"
print("OK")
"""
    r = subprocess.run(["unshare","-Umr","python3","-c",script],
                       capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": "src"})
    assert "OK" in r.stdout, r.stderr
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/test_overlay.py -v -m tier2`
Expected: FAIL (module not found).

- [ ] **Step 3: overlay.py**

```python
# src/hashpass/overlay.py
import subprocess
from pathlib import Path

def _run(argv: list[str], sudo: bool) -> None:
    subprocess.run((["sudo"] if sudo else []) + argv, check=True)

def overlay_mount(lowers, upper, work, mnt, *, sudo: bool) -> None:
    lowerdir = ":".join(str(p) for p in lowers)  # первый = верхний
    opts = f"lowerdir={lowerdir},upperdir={upper},workdir={work}"
    _run(["mount", "-t", "overlay", "overlay", "-o", opts, str(mnt)], sudo)

def overlay_umount(mnt, *, sudo: bool) -> None:
    _run(["umount", str(mnt)], sudo)
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/test_overlay.py -v -m tier2`
Expected: PASS.
```bash
git add -A && git commit -m "feat(overlay): rootless/sudo overlay compose"
```

---

### Task 4: `NspawnRunner` (tier3, real production driver)

**Files:**
- Create: `src/hashpass/runner/nspawn.py`
- Test: `tests/runner/test_nspawn.py`

**Interfaces:**
- Consumes: `overlay_mount/overlay_umount` (Task 3), `RunResult` (Task 2).
- Produces: `NspawnRunner(workdir: Path, base_tar: Path | None = None, base_dir: Path | None = None)`, реализует `Runner`. `run()` — одиночный запуск (`systemd-nspawn -D mnt <cmd>`). `boot()/poweroff()` — жизненный цикл boot-режима.

Референс проверенного смоука: extract (`sudo tar -xp`) → `overlay_mount(sudo=True)` → `sudo systemd-nspawn -q --register=no -D mnt <cmd>` → изменения в upperdir → `overlay_umount(sudo=True)`.

- [ ] **Step 1: Failing test (tier3)**

```python
# tests/runner/test_nspawn.py
import subprocess
from pathlib import Path
import pytest
from hashpass.runner.nspawn import NspawnRunner

@pytest.fixture(scope="session")
def base_tar(tmp_path_factory):
    d = tmp_path_factory.mktemp("base")
    tar = d / "rootfs.tar"
    cid = subprocess.run(["docker","create","debian:trixie-slim"],
                         capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["docker","export",cid,"-o",str(tar)], check=True)
    subprocess.run(["docker","rm",cid], check=True, capture_output=True)
    return tar

@pytest.mark.tier3
def test_nspawn_run_and_persist(tmp_path, base_tar):
    r = NspawnRunner(tmp_path, base_tar=base_tar)
    r.prepare([])
    res = r.run(["sh","-c",". /etc/os-release; echo $ID; id -u"])
    assert res.exit_code == 0
    assert "debian" in res.stdout and "0" in res.stdout
    r.run(["sh","-c","echo persisted > /root/p.txt"])
    assert (r.rootfs_upper / "root/p.txt").read_text().strip() == "persisted" or \
           r.run(["cat","/root/p.txt"]).stdout.strip() == "persisted"
    r.teardown()
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/runner/test_nspawn.py -v -m tier3`
Expected: FAIL (module not found).

- [ ] **Step 3: nspawn.py**

```python
# src/hashpass/runner/nspawn.py
import subprocess, time
from pathlib import Path
from .base import RunResult
from ..overlay import overlay_mount, overlay_umount

class NspawnRunner:
    def __init__(self, workdir: Path, *, base_tar: Path | None = None, base_dir: Path | None = None):
        self._wd = Path(workdir)
        self._base_tar, self._base_dir = base_tar, base_dir
        self._lower = self._wd/"lower"; self._upper = self._wd/"upper"
        self._work = self._wd/"work"; self._mnt = self._wd/"mnt"

    def prepare(self, lowers: list[Path]) -> None:
        for d in (self._lower, self._upper, self._work, self._mnt):
            d.mkdir(parents=True, exist_ok=True)
        if self._base_tar:
            subprocess.run(["sudo","tar","-xpf",str(self._base_tar),"-C",str(self._lower)], check=True)
        elif self._base_dir:
            subprocess.run(["sudo","rsync","-a",str(self._base_dir)+"/",str(self._lower)+"/"], check=True)
        stack = [Path(p) for p in lowers] + [self._lower]  # первый=верх
        overlay_mount(stack, self._upper, self._work, self._mnt, sudo=True)

    def run(self, argv: list[str]) -> RunResult:
        p = subprocess.run(
            ["sudo","systemd-nspawn","-q","--register=no","-D",str(self._mnt), *argv],
            capture_output=True, text=True, encoding="utf-8")
        return RunResult(p.stdout, p.stderr, p.returncode)

    def boot(self, machine: str) -> None:
        self._proc = subprocess.Popen(
            ["sudo","systemd-nspawn","-b","-q","-M",machine,"-D",str(self._mnt)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._machine = machine
        for _ in range(30):
            if subprocess.run(["sudo","machinectl","status",machine],
                              capture_output=True).returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError("machine did not register")

    def poweroff(self) -> None:
        subprocess.run(["sudo","machinectl","poweroff",self._machine], check=False)
        self._proc.wait(timeout=30)

    @property
    def rootfs(self) -> Path:
        return self._mnt

    @property
    def rootfs_upper(self) -> Path:
        return self._upper

    def teardown(self) -> None:
        overlay_umount(self._mnt, sudo=True)
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/runner/test_nspawn.py -v -m tier3`
Expected: PASS (NSPAWN + persist).
```bash
git add -A && git commit -m "feat(runner): NspawnRunner (production driver)"
```

---

### Task 5: Base image builder (env layer с рантаймом)

**Files:**
- Create: `src/hashpass/image/base.py`
- Create: `runtime/usr/bin/hash` (заглушка shell, ставится в образ; расширяется в Task 6)
- Test: `tests/image/test_base.py`

**Interfaces:**
- Produces: `build_base(dest: Path, *, from_tar: Path) -> Path` — распаковывает rootfs и кладёт рантайм-слой (`/usr/bin/hash`, `/.hash/`), возвращает путь base-образа (каталог).

- [ ] **Step 1: Failing test (tier2)**

```python
# tests/image/test_base.py
import pytest
from pathlib import Path
from hashpass.image.base import build_base

@pytest.mark.tier3
def test_build_base_has_runtime(tmp_path, base_tar):  # base_tar fixture reused via conftest
    base = build_base(tmp_path/"base", from_tar=base_tar)
    assert (base/"usr/bin/hash").exists()
    assert (base/".hash").is_dir()
```

- [ ] **Step 2: conftest выносит фикстуру base_tar**

```python
# tests/conftest.py
import subprocess, pytest
@pytest.fixture(scope="session")
def base_tar(tmp_path_factory):
    d = tmp_path_factory.mktemp("base"); tar = d/"rootfs.tar"
    cid = subprocess.run(["docker","create","debian:trixie-slim"],
                         capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["docker","export",cid,"-o",str(tar)], check=True)
    subprocess.run(["docker","rm",cid], check=True, capture_output=True)
    return tar
```

- [ ] **Step 3: base.py + runtime/usr/bin/hash заглушка**

```python
# src/hashpass/image/base.py
import subprocess
from pathlib import Path
_RUNTIME = Path(__file__).resolve().parents[3] / "runtime"

def build_base(dest: Path, *, from_tar: Path) -> Path:
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sudo","tar","-xpf",str(from_tar),"-C",str(dest)], check=True)
    # runtime-слой (usr/bin/hash + /.hash) одним rsync — только granted-sudo
    subprocess.run(["sudo","rsync","-a",str(_RUNTIME)+"/",str(dest)+"/"], check=True)
    return dest
```
```bash
mkdir -p runtime/usr/bin runtime/.hash
cat > runtime/usr/bin/hash <<'SH'
#!/bin/sh
exec /bin/sh "$@"
SH
chmod 0755 runtime/usr/bin/hash
touch runtime/.hash/.keep
```
Примечание: используются только granted-sudo команды (`tar`, `rsync`). `build_base` требует sudo → тест помечен `tier3`.

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/image/test_base.py -v -m tier3`
Expected: PASS.
```bash
git add -A && git commit -m "feat(image): base image builder + runtime hash stub"
```

---

### Task 6: Минимальный инструментированный shell `hash`

**Files:**
- Modify: `runtime/usr/bin/hash` (переписать на python3)
- Test: `tests/test_shell_capture.py`

**Interfaces:**
- Produces: shell, который в цикле читает команду, выполняет через `/bin/sh -c`, пишет транскрипт в `/.hash/.cmd` (последняя команда) и `/.hash/.cmd.out` (её вывод); команды `task exit`/`exit` завершают; при наличии `readme.txt` печатает его один раз.

- [ ] **Step 1: Failing test (tier2, через DockerRunner-подобный запуск в tmpdir)**

```python
# tests/test_shell_capture.py
import subprocess, sys
from pathlib import Path

def test_shell_captures_last_cmd_and_output(tmp_path):
    root = tmp_path; (root/".hash").mkdir()
    shell = Path("runtime/usr/bin/hash").read_text()
    (root/"hash").write_text(shell); (root/"hash").chmod(0o755)
    # прогоняем shell, скармливая команды на stdin
    p = subprocess.run([sys.executable, str(root/"hash")],
                       cwd=root, input="echo hi\nexit\n",
                       capture_output=True, text=True)
    assert (root/".hash/.cmd").read_text().strip() == "echo hi"
    assert (root/".hash/.cmd.out").read_text().strip() == "hi"
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/test_shell_capture.py -v`
Expected: FAIL.

- [ ] **Step 3: runtime/usr/bin/hash (python)**

```python
#!/usr/bin/python3
import os, subprocess, sys
HASH = "/.hash" if os.path.isdir("/.hash") else os.path.join(os.getcwd(), ".hash")
def w(name, data): open(os.path.join(HASH, name), "w", encoding="utf-8").write(data)
def main():
    if os.path.isfile("readme.txt"):
        print(open("readme.txt", encoding="utf-8").read())
    for line in sys.stdin:
        cmd = line.strip()
        if cmd in ("exit", "task exit"): break
        if not cmd: continue
        w(".cmd", cmd)
        p = subprocess.run(["/bin/sh","-c",cmd], capture_output=True, text=True)
        sys.stdout.write(p.stdout); sys.stdout.flush()
        w(".cmd.out", p.stdout)
if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/test_shell_capture.py -v`
Expected: PASS.
```bash
git add -A && git commit -m "feat(shell): minimal instrumented hash shell with capture"
```

---

### Task 7: Task-модель + loader + stub-checker + локальный ключ

**Files:**
- Create: `src/hashpass/task.py`
- Create: `src/hashpass/key.py`
- Create: `src/hashpass/check.py`
- Test: `tests/test_task_check_key.py`

**Interfaces:**
- Produces:
  - `Task.load(dir: Path) -> Task` (поля: `readme: str`, `check: dict`)
  - `local_key(task_id: str, stage: int, nonce: str) -> str` — детерминированный nonce-ключ (НЕ из артефакта; §6). Формат `key{<hex16>}`.
  - `stub_check(rootfs: Path, spec: dict) -> bool` — поддерживает `{"kind":"path_exists","path":"..."}`.

- [ ] **Step 1: Failing test**

```python
# tests/test_task_check_key.py
from pathlib import Path
from hashpass.task import Task
from hashpass.check import stub_check
from hashpass.key import local_key

def test_task_load_and_stub_check_and_key(tmp_path):
    (tmp_path/"readme.txt").write_text("do it")
    (tmp_path/"task.toml").write_text(
        'id="demo"\n[check]\nkind="path_exists"\npath="done.txt"\n')
    t = Task.load(tmp_path)
    assert t.readme == "do it" and t.check["kind"] == "path_exists"
    assert stub_check(tmp_path, t.check) is False
    (tmp_path/"done.txt").write_text("x")
    assert stub_check(tmp_path, t.check) is True
    k1 = local_key("demo", 0, "n1"); k2 = local_key("demo", 0, "n1")
    assert k1 == k2 and k1.startswith("key{") and k1.endswith("}")
    assert local_key("demo", 0, "n2") != k1
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/test_task_check_key.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализация**

```python
# src/hashpass/key.py
import hashlib
def local_key(task_id: str, stage: int, nonce: str) -> str:
    d = hashlib.sha256(f"{task_id}|{stage}|{nonce}".encode("utf-8")).digest()
    return "key{" + d[:8].hex() + "}"
```
```python
# src/hashpass/check.py
from pathlib import Path
def stub_check(rootfs: Path, spec: dict) -> bool:
    if spec.get("kind") == "path_exists":
        return (Path(rootfs) / spec["path"]).exists()
    raise ValueError(f"unknown check kind: {spec.get('kind')}")
```
```python
# src/hashpass/task.py
import tomllib
from dataclasses import dataclass
from pathlib import Path
@dataclass
class Task:
    id: str
    readme: str
    check: dict
    @classmethod
    def load(cls, d: Path) -> "Task":
        d = Path(d)
        meta = tomllib.loads((d/"task.toml").read_text(encoding="utf-8"))
        readme = (d/"readme.txt").read_text(encoding="utf-8").strip() if (d/"readme.txt").exists() else ""
        return cls(id=meta["id"], readme=readme, check=meta["check"])
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/test_task_check_key.py -v`
Expected: PASS.
```bash
git add -A && git commit -m "feat: task model + stub checker + local nonce key"
```

---

### Task 8: Walking skeleton — оркестратор (tier2, TmpdirRunner)

**Files:**
- Create: `src/hashpass/play.py`
- Test: `tests/test_play_tmpdir.py`

**Interfaces:**
- Consumes: `Runner` (Task 2), `Task`/`stub_check`/`local_key` (Task 7).
- Produces: `play(runner: Runner, task_dir: Path, *, nonce: str) -> str | None` — монтирует задание в rootfs, гоняет вход через shell-транскрипт (для tier2 — упрощённо: применяет решение из теста), проверяет `check`, при успехе возвращает `local_key`, иначе `None`.

- [ ] **Step 1: Failing test**

```python
# tests/test_play_tmpdir.py
from pathlib import Path
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.play import play

def test_play_returns_key_on_pass(tmp_path):
    task = tmp_path/"task"; task.mkdir()
    (task/"readme.txt").write_text("create done.txt")
    (task/"task.toml").write_text('id="demo"\n[check]\nkind="path_exists"\npath="done.txt"\n')
    r = TmpdirRunner(tmp_path/"run"); r.prepare([task])
    assert play(r, task, nonce="n") is None      # ещё не решено
    r.run(["sh","-c","touch done.txt"])
    assert play(r, task, nonce="n").startswith("key{")
    r.teardown()
```

- [ ] **Step 2: Run → FAIL**

Run: `pytest tests/test_play_tmpdir.py -v`
Expected: FAIL.

- [ ] **Step 3: play.py**

```python
# src/hashpass/play.py
from pathlib import Path
from .task import Task
from .check import stub_check
from .key import local_key
from .runner.base import Runner

def play(runner: Runner, task_dir: Path, *, nonce: str) -> str | None:
    task = Task.load(Path(task_dir))
    if stub_check(runner.rootfs, task.check):
        return local_key(task.id, 0, nonce)
    return None
```

- [ ] **Step 4: Run → PASS, commit**

Run: `pytest tests/test_play_tmpdir.py -v`
Expected: PASS.
```bash
git add -A && git commit -m "feat: play orchestrator (walking skeleton logic)"
```

---

### Task 9: Walking skeleton — сквозной тест на nspawn (tier3)

**Files:**
- Create: `tests/integration/test_walking_skeleton.py`

**Interfaces:**
- Consumes: `build_base` (Task 5), `NspawnRunner` (Task 4), `play` (Task 8).

- [ ] **Step 1: Integration test (tier3)**

```python
# tests/integration/test_walking_skeleton.py
import pytest
from pathlib import Path
from hashpass.image.base import build_base
from hashpass.runner.nspawn import NspawnRunner
from hashpass.play import play

@pytest.mark.tier3
def test_end_to_end_boot_solve_key(tmp_path, base_tar):
    base = build_base(tmp_path/"base", from_tar=base_tar)
    task = tmp_path/"task"; task.mkdir()
    (task/"readme.txt").write_text("touch /root/done.txt")
    (task/"task.toml").write_text('id="demo"\n[check]\nkind="path_exists"\npath="root/done.txt"\n')
    r = NspawnRunner(tmp_path/"run", base_dir=base); r.prepare([task])
    assert play(r, task, nonce="n") is None
    r.run(["sh","-c","touch /root/done.txt"])       # «студент решает»
    key = play(r, task, nonce="n")
    assert key and key.startswith("key{")
    r.teardown()
```

Примечание по `check.path`: для nspawn `rootfs` = точка монтирования, файл создаётся как `/root/done.txt` → проверяем относительный `root/done.txt` от `rootfs`.

- [ ] **Step 2: Run → PASS**

Run: `pytest tests/integration/test_walking_skeleton.py -v -m tier3`
Expected: PASS — boot/overlay/solve/key end-to-end на реальном nspawn.

- [ ] **Step 3: Commit + прогнать всё**

Run: `ruff check src tests && pytest -q -m "not tier3" && pytest -q -m tier3`
```bash
git add -A && git commit -m "test: walking skeleton end-to-end on nspawn (tier3)"
```

---

## Что дальше (отдельные планы, аргументируются из docs/Архитектура)

- **План B — Ядро-логика:** движок хуков (`@command/@filter/@check`), `Cmd`, size-adaptive сравнение (Jaccard/MinHash/exact/ssdeep). §4.
- **План C — Дифф-канонизация (риск-гейт):** k-прогоны + шум, обрезка нестабильных полей; spike на 3 формах заданий. §5.
- **План D — Чекер + задание-как-код + кодоген + курация observe.** §3/§4.
- **План E — Ключи + evidence + сервер (реестр+подпись).** §6/§8.
- **План F — Оффлайн-петля + интерактивные подсказки.** §7.
- **План G — Миграция контента.** §10-план.
