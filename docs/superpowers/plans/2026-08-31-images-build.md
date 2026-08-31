# Image Build Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author and build reusable images from Docker-like recipes: `image name:ver` + `from` (transitive, composable), `copy`/`run` build steps → a stored overlay layer; and run a bare image container.

**Architecture:** New `src/hashpass/recipe/` (recipe model + parser), `src/hashpass/imagestore/` (local store + `FROM`-DAG resolver → ordered deduped `lowers`), `src/hashpass/build.py` (`build` via overlay+nspawn, `run_image` bare). Reuses `overlay.py`, `runner.nspawn.NspawnRunner`, `image.base.build_base`.

**Tech Stack:** Python 3.13, stdlib only. Consumes in-repo `hashpass.overlay`, `hashpass.runner.nspawn`, `hashpass.image.base`. NO third-party deps.

**Spec:** `docs/superpowers/specs/2026-08-31-образы-задания-и-dsl-design.md` (§1 concepts, §2 image/layer model, §3.1 image directives only, §9 phase 1).

## Global Constraints

- **Python 3.13**; stdlib + in-repo only; `encoding="utf-8"` in every file operation.
- **ruff `select=["ALL"]` clean, including tests.** Module-level constants for magic values (PLR2004); `# noqa` only per repo convention. Do NOT add `from __future__ import annotations` (the repo evaluates annotations at runtime; adding it would trigger the flake8-type-checking rules).
- **Tiers:** parser + store + resolver (tasks 1–3) = **tier1** (pure logic + `tmp_path`, no containers). `build` + `run_image` (tasks 4–5, real overlay+nspawn+sudo) = **tier3** (`@pytest.mark.tier3`, `base_tar` fixture). No tier2 needed. Markers are registered in `pyproject.toml`; default `addopts` is `-m 'not tier3'`, so tier3 tests run only with an explicit `-m tier3`.
- **Reuse, do not reinvent:** overlay via `overlay.py`, RUN-execution + mount via `NspawnRunner`, base via `build_base`. Do not reimplement mounting.

### Exact external APIs consumed (verbatim — do not change these)

```python
# hashpass.overlay
def overlay_mount(lowers: list[Path], upper: Path, work: Path, mnt: Path, *, sudo: bool) -> None  # lowers[0]=topmost
def overlay_umount(mnt: Path, *, sudo: bool) -> None

# hashpass.runner.nspawn.NspawnRunner(workdir, *, base_tar=None, base_dir=None)
#   .prepare(lowers: list[Path])   # mkdirs lower/upper/work/mnt; extracts base_tar OR rsyncs base_dir into
#                                   # lower; overlay_mount([*lowers, self._lower], ...). stack = lowers + [base], first=top.
#   .run(argv) -> RunResult(stdout, stderr, exit_code)   # sudo systemd-nspawn -q --register=no -D <mnt> <argv>
#   .rootfs -> Path        # the merged mountpoint (/)
#   .rootfs_upper -> Path  # writable upperdir (the DELTA)
#   .teardown()            # umount

# hashpass.image.base.build_base(dest: Path, *, from_tar: Path) -> Path   # base rootfs dir (debian + runtime)

# tests/conftest.py: base_tar (session fixture) -> Path to a debian:trixie-slim rootfs tarball (docker export)
```

### Decisions beyond the brief (open details, simplest choice consistent with the pinned signatures)

1. **`build` always mounts a freshly-built base as the bottom-most lower** — for both the no-parents case (`lowers = [base]`) and the with-parents case (`lowers = [*resolved, base]`). Images store **only their own delta** (the upperdir), so a base is never itself stored; a child's resolved lowers therefore end at a stored *delta*, not a bootable rootfs. Always rebuilding the base underneath keeps `build` uniform and mirrors `NspawnRunner.prepare`, which likewise appends its base below the given lowers. This makes `build → store → run` round-trip end to end. (The brief's phrasing "the resolved lowers already end at a stored base" assumes stored bases; we do not store bases, so we append one.)
2. **Default version is `"latest"`** — used by both the `image` directive (a self-name with no `:ver`) and store ref-parsing (a bare `name` with no `:ver`). Kept identical in both places.
3. **Only full-line `#` comments are stripped**; an inline `#` is preserved verbatim so `run` command strings survive intact (a `run` body may legitimately contain `#`).
4. **The resolver dedups by ref identity** (each `name:ver` maps 1:1 to a layer dir in phase 1) and produces a topological order via post-order DFS + final reverse.
5. **The parser uses a directive dispatch table** (`_HANDLERS`) — this keeps `parse_recipe` under ruff's C901 complexity limit and embodies the spec's extensibility principle ("a new verb is an additive parser+model edit").
6. **`run_image` validates the ref implicitly** via `resolve_lowers((ref,), store)`, which calls `store.get(ref)` and raises `KeyError` for an unknown ref — no separate `store.get`.

---

### Task 1: Recipe model + parser (tier1)

Parse a Docker-like image recipe into a frozen `Recipe`. Phase-1 directives only: `image`, `from`, `copy`, `run`. Reserved later-phase directives (`stage`/`voice`/`hidden`/`readme`) and any unknown directive raise a clear `ValueError`.

**Files:**
- Create: `src/hashpass/recipe/__init__.py` (empty package marker)
- Create: `src/hashpass/recipe/model.py`
- Create: `src/hashpass/recipe/parse.py`
- Create: `tests/recipe/__init__.py` (empty)
- Test: `tests/recipe/test_parse.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `@dataclass(frozen=True) CopyStep(src: str, dst: str)`
  - `@dataclass(frozen=True) Recipe(name: str, version: str, parents: tuple[str, ...], copies: tuple[CopyStep, ...], runs: tuple[str, ...])`
  - `image_ref(r: Recipe) -> str` → `"{name}:{version}"`
  - `parse_recipe(text: str) -> Recipe`
  - `load_recipe(path: Path) -> Recipe`

- [ ] **Step 1: Write the failing test**

```python
# tests/recipe/test_parse.py
import pytest

from hashpass.recipe.model import CopyStep, Recipe, image_ref
from hashpass.recipe.parse import load_recipe, parse_recipe

_RECIPE = """\
# a phase-1 image recipe

image log-archive:1
from  base, coreutils-lab:1
copy  assets/ /home/student/
run   mkdir -p /var/log/app
run   touch /var/log/app/app.log
"""


@pytest.mark.tier1
def test_parse_full_recipe():
    recipe = parse_recipe(_RECIPE)
    assert recipe == Recipe(
        name="log-archive",
        version="1",
        parents=("base", "coreutils-lab:1"),
        copies=(CopyStep("assets/", "/home/student/"),),
        runs=("mkdir -p /var/log/app", "touch /var/log/app/app.log"),
    )
    assert image_ref(recipe) == "log-archive:1"


@pytest.mark.tier1
def test_missing_image_raises():
    with pytest.raises(ValueError, match="missing a required 'image"):
        parse_recipe("run echo hi\n")


@pytest.mark.tier1
def test_reserved_stage_directive_raises():
    with pytest.raises(ValueError, match="phase 1"):
        parse_recipe('image t:1\nstage "do the thing"\n')


@pytest.mark.tier1
def test_unknown_directive_raises():
    with pytest.raises(ValueError, match="unknown directive"):
        parse_recipe("image t:1\nfrobnicate stuff\n")


@pytest.mark.tier1
def test_load_recipe_from_disk(tmp_path):
    path = tmp_path / "Imagefile"
    path.write_text("image solo:2\n", encoding="utf-8")
    recipe = load_recipe(path)
    assert recipe.name == "solo"
    assert recipe.version == "2"
    assert recipe.parents == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/recipe/test_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hashpass.recipe'`.

- [ ] **Step 3a: Write `recipe/model.py`**

```python
# src/hashpass/recipe/model.py
"""Image/task recipe model: parsed Imagefile as frozen dataclasses (phase 1: images only)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CopyStep:
    """A `copy <src> <dst>` build step: host source and in-image destination."""

    src: str
    dst: str


@dataclass(frozen=True)
class Recipe:
    """A parsed phase-1 image recipe: self-name/version, parents, and build steps."""

    name: str
    version: str
    parents: tuple[str, ...]
    copies: tuple[CopyStep, ...]
    runs: tuple[str, ...]


def image_ref(r: Recipe) -> str:
    """Return the recipe's self-reference `name:version`."""
    return f"{r.name}:{r.version}"
```

- [ ] **Step 3b: Write `recipe/parse.py`**

A directive dispatch table keeps `parse_recipe` simple (under ruff's C901 limit) and additive. `_Acc` is a private, mutable accumulator; each `_do_*` handler mutates it; `_reject` raises for reserved/unknown directives.

```python
# src/hashpass/recipe/parse.py
"""Line-based parser for phase-1 image recipes (Imagefile): image/from/copy/run only."""
from dataclasses import dataclass, field
from pathlib import Path

from hashpass.recipe.model import CopyStep, Recipe

_RESERVED = ("stage", "voice", "hidden", "readme")
_COPY_ARGC = 2
_DEFAULT_VERSION = "latest"


@dataclass
class _Acc:
    """Mutable accumulator for directives parsed so far."""

    name: str | None = None
    version: str = _DEFAULT_VERSION
    parents: list[str] = field(default_factory=list)
    copies: list[CopyStep] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)


def _do_image(value: str, acc: _Acc) -> None:
    if acc.name is not None:
        msg = "duplicate 'image' directive"
        raise ValueError(msg)
    name, _, version = value.partition(":")
    acc.name = name
    acc.version = version or _DEFAULT_VERSION


def _do_from(value: str, acc: _Acc) -> None:
    acc.parents.extend(ref.strip() for ref in value.split(",") if ref.strip())


def _do_copy(value: str, acc: _Acc) -> None:
    fields = value.split()
    if len(fields) != _COPY_ARGC:
        msg = f"copy requires <src> <dst>: {value!r}"
        raise ValueError(msg)
    acc.copies.append(CopyStep(fields[0], fields[1]))


def _do_run(value: str, acc: _Acc) -> None:
    acc.runs.append(value)


_HANDLERS = {"image": _do_image, "from": _do_from, "copy": _do_copy, "run": _do_run}


def _reject(keyword: str) -> None:
    if keyword in _RESERVED:
        msg = f"directive {keyword!r} is reserved for a later phase (not supported in phase 1)"
        raise ValueError(msg)
    msg = f"unknown directive: {keyword!r}"
    raise ValueError(msg)


def parse_recipe(text: str) -> Recipe:
    """
    Parse Imagefile text into a Recipe (phase-1 image directives only).

    Recognizes `image <name>:<ver>` (required, once), `from <ref>[, <ref> ...]`
    (declaration order preserved across directives), `copy <src> <dst>`, and
    `run <command>`. Blank lines and full-line `#` comments are ignored; an
    inline `#` is left intact so `run` command strings stay verbatim. Reserved
    later-phase directives (stage/voice/hidden/readme) and any unknown
    directive raise ValueError.

    Args:
        text: The Imagefile contents.

    Returns:
        The parsed Recipe.

    Raises:
        ValueError: On a missing/duplicate `image`, a reserved directive, an
            unknown directive, or a malformed `copy`.

    """
    acc = _Acc()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        value = parts[1] if len(parts) > 1 else ""
        handler = _HANDLERS.get(parts[0])
        if handler is None:
            _reject(parts[0])
        else:
            handler(value, acc)
    if not acc.name:
        msg = "recipe is missing a required 'image <name>:<ver>' directive"
        raise ValueError(msg)
    return Recipe(acc.name, acc.version, tuple(acc.parents), tuple(acc.copies), tuple(acc.runs))


def load_recipe(path: Path) -> Recipe:
    """Read an Imagefile from disk and parse it (see `parse_recipe`)."""
    return parse_recipe(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/recipe/test_parse.py -v`
Expected: PASS (5 tests). Then `ruff check src tests` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/recipe tests/recipe
git commit -m "feat(recipe): phase-1 image recipe model + line-based parser"
```

---

### Task 2: Local image store (tier1)

A local filesystem store laid out as `<root>/<name>/<version>/{layer/, meta.json}`. `save` copies a layer dir in; `get`/`exists` look up by `name:ver` (a bare `name` defaults to `"latest"`).

**Files:**
- Create: `src/hashpass/imagestore/__init__.py` (empty package marker)
- Create: `src/hashpass/imagestore/store.py`
- Create: `tests/imagestore/__init__.py` (empty)
- Test: `tests/imagestore/test_store.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `@dataclass(frozen=True) StoredImage(name: str, version: str, layer: Path, parents: tuple[str, ...])`
  - `ImageStore(root: Path)` with:
    - `save(name: str, version: str, layer_dir: Path, parents: tuple[str, ...]) -> StoredImage`
    - `get(ref: str) -> StoredImage` (raises `KeyError` if absent)
    - `exists(ref: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/imagestore/test_store.py
from pathlib import Path

import pytest

from hashpass.imagestore.store import ImageStore, StoredImage


def _make_layer(tmp_path, name) -> Path:
    src = tmp_path / f"src-{name}"
    src.mkdir()
    (src / f"{name}.txt").write_text(name, encoding="utf-8")
    return src


@pytest.mark.tier1
def test_save_then_get_roundtrips(tmp_path):
    store = ImageStore(tmp_path / "images")
    src = _make_layer(tmp_path, "nettools")
    saved = store.save("nettools", "1", src, ("base",))
    assert isinstance(saved, StoredImage)

    got = store.get("nettools:1")
    assert got.name == "nettools"
    assert got.version == "1"
    assert got.parents == ("base",)
    assert (got.layer / "nettools.txt").read_text(encoding="utf-8") == "nettools"


@pytest.mark.tier1
def test_exists_true_and_false(tmp_path):
    store = ImageStore(tmp_path / "images")
    store.save("nettools", "1", _make_layer(tmp_path, "nettools"), ())
    assert store.exists("nettools:1")
    assert not store.exists("nettools:2")


@pytest.mark.tier1
def test_bare_ref_defaults_to_latest(tmp_path):
    store = ImageStore(tmp_path / "images")
    store.save("nettools", "latest", _make_layer(tmp_path, "nettools"), ())
    assert store.exists("nettools")
    assert store.get("nettools").version == "latest"


@pytest.mark.tier1
def test_get_missing_raises_keyerror(tmp_path):
    store = ImageStore(tmp_path / "images")
    with pytest.raises(KeyError):
        store.get("ghost:1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/imagestore/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hashpass.imagestore'`.

- [ ] **Step 3: Write `imagestore/store.py`**

For tier1 the layer dirs are debi-owned test dirs, so `shutil.copytree` is the right tool. (Phase-1 `build` writes only world-readable artifacts into the upperdir, so `save` reads a root-owned upperdir fine in tier3 too; a later phase with restrictive modes/whiteouts would switch `save` to `sudo rsync`.)

```python
# src/hashpass/imagestore/store.py
"""Local image store: images/<name>/<version>/{layer/,meta.json}."""
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_VERSION = "latest"


@dataclass(frozen=True)
class StoredImage:
    """A stored image: its name/version, on-disk layer dir, and parent refs."""

    name: str
    version: str
    layer: Path
    parents: tuple[str, ...]


def _split_ref(ref: str) -> tuple[str, str]:
    name, sep, version = ref.partition(":")
    return name, (version if sep else _DEFAULT_VERSION)


class ImageStore:
    """A local filesystem image store rooted at an images/ directory."""

    def __init__(self, root: Path) -> None:
        """
        Initialize the store at the given images/ root (created on demand).

        Args:
            root: Directory that holds per-image <name>/<version>/ trees.

        """
        self._root = Path(root)

    def _dir(self, name: str, version: str) -> Path:
        return self._root / name / version

    def save(
        self,
        name: str,
        version: str,
        layer_dir: Path,
        parents: tuple[str, ...],
    ) -> StoredImage:
        """
        Copy a layer directory into the store and record its parents.

        Args:
            name: Image name.
            version: Image version.
            layer_dir: Source rootfs-delta directory copied in as the layer.
            parents: Direct `from` refs, in declaration order.

        Returns:
            The StoredImage describing the saved entry.

        """
        dest = self._dir(name, version)
        layer = dest / "layer"
        if layer.exists():
            shutil.rmtree(layer)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copytree(layer_dir, layer)
        meta = {"name": name, "version": version, "parents": list(parents)}
        (dest / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return StoredImage(name, version, layer, parents)

    def get(self, ref: str) -> StoredImage:
        """
        Look up a stored image by `name:version` (a bare name uses 'latest').

        Args:
            ref: Image reference, `name` or `name:version`.

        Returns:
            The StoredImage for the reference.

        Raises:
            KeyError: If no image is stored under the reference.

        """
        name, version = _split_ref(ref)
        dest = self._dir(name, version)
        meta_path = dest / "meta.json"
        if not meta_path.exists():
            raise KeyError(ref)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return StoredImage(name, version, dest / "layer", tuple(meta["parents"]))

    def exists(self, ref: str) -> bool:
        """Return whether an image is stored under the reference."""
        name, version = _split_ref(ref)
        return (self._dir(name, version) / "meta.json").exists()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/imagestore/test_store.py -v`
Expected: PASS (4 tests). Then `ruff check src tests` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/imagestore tests/imagestore
git commit -m "feat(imagestore): local image store (layer + meta.json)"
```

---

### Task 3: FROM-DAG resolver (tier1)

Resolve a recipe's direct `parents` to a deterministic, deduped overlay `lowers` list (topmost first). This is a topological sort — a node precedes all of its ancestors — with declaration order as the tie-break (the rightmost `from` has the highest priority = topmost). A shared ancestor appears exactly once, at the bottom.

**Files:**
- Create: `src/hashpass/imagestore/resolve.py`
- Test: `tests/imagestore/test_resolve.py`

**Interfaces:**
- Consumes: `ImageStore` (Task 2) — reads each ref's own `parents` via `store.get(ref).parents` and its `layer`.
- Produces: `resolve_lowers(parents: tuple[str, ...], store: ImageStore) -> list[Path]`

- [ ] **Step 1: Write the failing test**

The diamond test is the genuine determinism/dedup check: `d` from `(b, c)`, both from `a`. The exact-list assertion `[c.layer, b.layer, a.layer]` proves ordering (rightmost `c` topmost), dedup (`a` once — a duplicate would break equality), and that the shared ancestor sits at the bottom.

```python
# tests/imagestore/test_resolve.py
import pytest

from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore, StoredImage


def _seed(store, tmp_path, name, parents) -> StoredImage:
    src = tmp_path / f"src-{name}"
    src.mkdir()
    (src / f"{name}.txt").write_text(name, encoding="utf-8")
    return store.save(name, "1", src, parents)


@pytest.mark.tier1
def test_linear_chain_topmost_first(tmp_path):
    store = ImageStore(tmp_path / "images")
    a = _seed(store, tmp_path, "a", ())
    b = _seed(store, tmp_path, "b", ("a:1",))
    c = _seed(store, tmp_path, "c", ("b:1",))
    assert resolve_lowers(("c:1",), store) == [c.layer, b.layer, a.layer]


@pytest.mark.tier1
def test_diamond_dedups_shared_ancestor_at_bottom(tmp_path):
    store = ImageStore(tmp_path / "images")
    a = _seed(store, tmp_path, "a", ())
    b = _seed(store, tmp_path, "b", ("a:1",))
    c = _seed(store, tmp_path, "c", ("a:1",))
    _seed(store, tmp_path, "d", ("b:1", "c:1"))

    lowers = resolve_lowers(("b:1", "c:1"), store)
    # rightmost `from` (c) is highest priority => topmost; shared ancestor a
    # appears exactly once, at the bottom; result is fully deterministic.
    assert lowers == [c.layer, b.layer, a.layer]
    assert lowers[-1] == a.layer


@pytest.mark.tier1
def test_empty_parents_returns_empty(tmp_path):
    store = ImageStore(tmp_path / "images")
    assert resolve_lowers((), store) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/imagestore/test_resolve.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_lowers'`.

- [ ] **Step 3: Write `imagestore/resolve.py`**

Post-order DFS (emit a node after its parents) over `parents` in declaration order, then reverse the whole list. The `visited` set dedups (and makes the walk cycle-safe). Reversing a declaration-order post-order puts the rightmost parent topmost and a shared ancestor at the bottom.

```python
# src/hashpass/imagestore/resolve.py
"""FROM-DAG resolver: transitive parent closure -> deterministic deduped overlay lowers."""
from pathlib import Path

from hashpass.imagestore.store import ImageStore


def resolve_lowers(parents: tuple[str, ...], store: ImageStore) -> list[Path]:
    """
    Resolve a recipe's direct parents to an ordered, deduped overlay lowers list.

    Topmost-first: a later-declared parent has higher priority (sits higher /
    earlier); each parent's own ancestors sit below it; a shared ancestor
    appears exactly once at its lowest required position. This is a topological
    sort (a node precedes all of its ancestors) with declaration order as the
    tie-break, realized as a post-order DFS (a node emitted after its parents)
    that is reversed at the end.

    Args:
        parents: Direct `from` refs, in declaration order.
        store: Image store used to look up each ref's own parents.

    Returns:
        Layer directories, topmost first (bottommost last).

    """
    visited: set[str] = set()
    post: list[Path] = []

    def visit(ref: str) -> None:
        if ref in visited:
            return
        visited.add(ref)
        img = store.get(ref)
        for parent in img.parents:
            visit(parent)
        post.append(img.layer)

    for ref in parents:
        visit(ref)
    post.reverse()
    return post
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/imagestore/test_resolve.py -v`
Expected: PASS (3 tests). Then `pytest -m "not tier3"` (all tier1 green) and `ruff check src tests` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/imagestore/resolve.py tests/imagestore/test_resolve.py
git commit -m "feat(imagestore): deterministic FROM-DAG resolver -> ordered lowers"
```

---

### Task 4: `build` — recipe → stored layer (tier3)

Mount the resolved parent lowers over a fresh base, apply `copy`/`run` steps, and store the upperdir as the image's own layer (the delta). Real overlay + systemd-nspawn + scoped sudo.

**Files:**
- Create: `src/hashpass/build.py`
- Create: `tests/build/__init__.py` (empty)
- Test: `tests/build/test_build.py`

**Interfaces:**
- Consumes: `resolve_lowers` (Task 3), `ImageStore`/`StoredImage` (Task 2), `Recipe` (Task 1), `overlay_mount`/`overlay_umount` (`hashpass.overlay`), `build_base` (`hashpass.image.base`).
- Produces: `build(recipe: Recipe, store: ImageStore, *, base_tar: Path, workdir: Path, sudo: bool = True) -> StoredImage`

**Environment:** tier3 requires real `systemd-nspawn`, scoped passwordless sudo (mount/umount/tar/rsync/systemd-nspawn), and `docker` (for the `base_tar` session fixture). Runs only with `-m tier3`.

- [ ] **Step 1: Write the failing test**

Assert on the **stored layer dir** (host-side), which is the true artifact: `demo`'s layer contains `marker`; the `child`'s layer contains `child-marker` but **not** `marker` (proving it stores only the delta — `marker` lives in demo's lower). Also assert the resolver reports the child topmost over demo.

```python
# tests/build/test_build.py
import pytest

from hashpass.build import build
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore
from hashpass.recipe.parse import parse_recipe


@pytest.mark.tier3
def test_build_stores_delta_layer(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")

    demo = build(
        parse_recipe("image demo:1\nrun touch /marker\n"),
        store,
        base_tar=base_tar,
        workdir=tmp_path / "b-demo",
    )
    assert (demo.layer / "marker").exists()

    child = build(
        parse_recipe("image child:1\nfrom demo:1\nrun touch /child-marker\n"),
        store,
        base_tar=base_tar,
        workdir=tmp_path / "b-child",
    )
    # the child's stored layer holds ONLY its own delta (marker came from demo)
    assert (child.layer / "child-marker").exists()
    assert not (child.layer / "marker").exists()
    # child's closure is topmost-first: child over demo
    assert resolve_lowers(("child:1",), store) == [child.layer, demo.layer]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/build/test_build.py -v -m tier3`
Expected: FAIL with `ModuleNotFoundError: No module named 'hashpass.build'`.

- [ ] **Step 3: Write `build.py` (the `build` function)**

The base is built fresh and appended as the bottom-most lower for **both** the no-parents and with-parents cases (see Decision 1). `copy` writes through the mount host-side (lands in upper); `run` executes inside via `systemd-nspawn` exactly as `NspawnRunner.run` does. `finally` guarantees umount; the upperdir survives umount, so `save` copies it afterward.

```python
# src/hashpass/build.py
"""Build reusable images from recipes (overlay + nspawn) and run bare images."""
import subprocess
from pathlib import Path

from hashpass.image.base import build_base
from hashpass.imagestore.resolve import resolve_lowers
from hashpass.imagestore.store import ImageStore, StoredImage
from hashpass.overlay import overlay_mount, overlay_umount
from hashpass.recipe.model import Recipe


def build(
    recipe: Recipe,
    store: ImageStore,
    *,
    base_tar: Path,
    workdir: Path,
    sudo: bool = True,
) -> StoredImage:
    """
    Build a recipe into a stored image layer (the overlay delta).

    Mounts the resolved parent lowers over a fresh base, applies `copy` and
    `run` steps, then stores the upperdir as the image's own layer (delta).

    Args:
        recipe: The parsed recipe to build.
        store: Image store to resolve parents from and save the result into.
        base_tar: Rootfs tarball for the bottom base layer.
        workdir: Scratch directory for base/upper/work/mnt.
        sudo: Whether overlay mounts use sudo (True for real nspawn).

    Returns:
        The StoredImage for the newly built layer.

    """
    workdir = Path(workdir)
    lowers = resolve_lowers(recipe.parents, store)
    base = build_base(workdir / "base", from_tar=base_tar)
    upper = workdir / "upper"
    work = workdir / "work"
    mnt = workdir / "mnt"
    for d in (upper, work, mnt):
        d.mkdir(parents=True, exist_ok=True)
    overlay_mount([*lowers, base], upper, work, mnt, sudo=sudo)
    try:
        for step in recipe.copies:
            dst = mnt / step.dst.lstrip("/")
            subprocess.run(["sudo", "rsync", "-a", step.src, str(dst)], check=True)
        for cmd in recipe.runs:
            subprocess.run(
                ["sudo", "systemd-nspawn", "-q", "--register=no",
                 "-D", str(mnt), "sh", "-c", cmd],
                check=True,
            )
    finally:
        overlay_umount(mnt, sudo=sudo)
    return store.save(recipe.name, recipe.version, upper, recipe.parents)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/build/test_build.py -v -m tier3`
Expected: PASS (1 test). Then `ruff check src tests` (clean).

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/build.py tests/build
git commit -m "feat(build): build a recipe into a stored overlay layer"
```

---

### Task 5: `run_image` (bare) + end-to-end round-trip (tier3)

Run a bare stored image: resolve its closure (the image itself topmost), mount it over a fresh base, and hand back a prepared `NspawnRunner`. The end-to-end test proves `build → store → run` round-trips a real image.

**Files:**
- Modify: `src/hashpass/build.py` (add `run_image`)
- Test: `tests/build/test_build.py` (add the round-trip test)

**Interfaces:**
- Consumes: `build` (Task 4, used by the test), `resolve_lowers` (Task 3), `ImageStore` (Task 2), `build_base` (`hashpass.image.base`), `NspawnRunner` (`hashpass.runner.nspawn`).
- Produces: `run_image(ref: str, store: ImageStore, workdir: Path, *, base_tar: Path) -> NspawnRunner` — a **prepared** runner over the overlay stack `[ref-layer, …ancestors…, base]`. The caller drives it with `.run(...)`/`.rootfs` and must `.teardown()`.

- [ ] **Step 1: Write the failing test**

Assert on a marker file surviving `build → store → run`: build `demo:1` (`run touch /marker`), then `run_image("demo:1", …)` and check the marker is visible inside the container. `&& echo OK` prints `OK` only when the file is present, so `stdout == "OK"` proves the round-trip.

```python
# add to tests/build/test_build.py
@pytest.mark.tier3
def test_build_then_run_image_roundtrips(tmp_path, base_tar):
    store = ImageStore(tmp_path / "images")
    build(
        parse_recipe("image demo:1\nrun touch /marker\n"),
        store,
        base_tar=base_tar,
        workdir=tmp_path / "build",
    )
    runner = run_image("demo:1", store, tmp_path / "run", base_tar=base_tar)
    try:
        res = runner.run(["sh", "-c", "test -f /marker && echo OK"])
        assert res.stdout.strip() == "OK"
    finally:
        runner.teardown()
```

Update the imports at the top of `tests/build/test_build.py` to pull in `run_image`:

```python
from hashpass.build import build, run_image
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/build/test_build.py::test_build_then_run_image_roundtrips -v -m tier3`
Expected: FAIL with `ImportError: cannot import name 'run_image'`.

- [ ] **Step 3: Add `run_image` to `build.py`**

Add the `NspawnRunner` import and the function. `resolve_lowers((ref,), store)` returns the ref's own layer topmost plus its ancestors and raises `KeyError` if `ref` is absent; `NspawnRunner(..., base_dir=base).prepare(lowers)` appends a fresh base below → net stack `[ref-layer, …ancestors…, base]`.

Add to the import block:

```python
from hashpass.runner.nspawn import NspawnRunner
```

(so the block reads, in order: `hashpass.image.base`, `hashpass.imagestore.resolve`, `hashpass.imagestore.store`, `hashpass.overlay`, `hashpass.recipe.model`, `hashpass.runner.nspawn`).

Append the function:

```python
def run_image(ref: str, store: ImageStore, workdir: Path, *, base_tar: Path) -> NspawnRunner:
    """
    Prepare an NspawnRunner over a stored image's overlay closure (bare env).

    Resolves the image's transitive layer closure (the image itself topmost)
    and mounts it over a fresh base, returning the prepared runner. The caller
    drives it with `.run(...)`/`.rootfs` and must `.teardown()` when done.

    Args:
        ref: Image reference `name` or `name:version` to run.
        store: Image store holding the image and its ancestors.
        workdir: Scratch directory for base and the runner tree.
        base_tar: Rootfs tarball for the bottom base layer.

    Returns:
        A prepared NspawnRunner (no task; a bare image environment).

    """
    workdir = Path(workdir)
    lowers = resolve_lowers((ref,), store)  # raises KeyError if ref is absent
    base = build_base(workdir / "base", from_tar=base_tar)
    runner = NspawnRunner(workdir / "run", base_dir=base)
    runner.prepare(lowers)
    return runner
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/build/test_build.py -v -m tier3`
Expected: PASS (2 tests). Then the full sweep and lint:
- `pytest -m "not tier3"` (all tier1 green)
- `ruff check src tests` (clean)

- [ ] **Step 5: Commit**

```bash
git add src/hashpass/build.py tests/build/test_build.py
git commit -m "feat(build): run_image (bare) + build->store->run e2e round-trip"
```

---

## Out of scope (later phases — the parser RESERVES these with a clear error)

- **Phase 2 — Task-on-image:** `stage`/`solve`/`observe`/`check` blocks and derivation on the mounted chain (reuse `taskcode`); the hidden `/hp` layer + `on enter/pass` + the `HP_*` contract; clean paths.
- **Phase 3 — Interactivity:** events over `HookRegistry`; conditional `hint` (`tries`/`idle`/`cmd`/`output`, `neutral`); `say`/`show file`/`exec file`/`exec cmd`; the typewriter renderer (`settings.type-mode`/`type-speed`, pager); `voice`; `react`.
- **Phase 4 — Registry:** push/pull of images by name; write authentication (same on-disk format).
- **Phase 5 — Content migration:** the 24 tasks per the playbook.

**Note on multi-`from` conflicts (§2.2):** path-conflict *resolution* by priority (rightmost `from` wins — overlay sees the topmost lower first) **is** implemented, via the resolver ordering in Task 3 and the overlay stacking in Task 4. The cosmetic build-time *warning* about conflicting paths is not in the brief's task set and is left for a follow-up; it does not affect build correctness.

Reuse `overlay`/`nspawn`/`build_base` throughout; do not reimplement mounting.
