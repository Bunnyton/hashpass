"""Tests for derive_checks: per-stage canonical + pinned comparator derivation."""
import itertools
from collections.abc import Callable

import pytest

from hashpass.canon import FileState
from hashpass.runner.tmpdir import TmpdirRunner
from hashpass.taskcode.derive import _has_signal, derive_checks
from hashpass.taskcode.execute import OUTPUT_KEY
from hashpass.taskcode.model import StageCode, TaskCode


def _factory(tmp_path) -> Callable[[], TmpdirRunner]:
    """Create a factory that yields fresh TmpdirRunners."""
    counter = itertools.count()

    def make() -> TmpdirRunner:
        r = TmpdirRunner(tmp_path / f"derive{next(counter)}")
        r.prepare([])
        return r

    return make


@pytest.mark.tier1
def test_derive_checks_keeps_stable_prunes_volatile(tmp_path) -> None:
    """Test that derive_checks keeps stable fields and prunes volatile ones."""
    task = TaskCode(
        id="demo",
        setup=(),
        stages=(
            StageCode(
                commands=("echo answer > result.txt", "date +%s%N > time.txt"),
                observe=("result.txt", "time.txt"),
            ),
        ),
    )
    derived = derive_checks(_factory(tmp_path), task, passes=3)
    canonical = derived.stages[0].canonical

    # DISCRIMINATION: a vacuous/empty derivation, or one that fails to prune, must FAIL here.
    assert canonical, "canonical must be non-empty (a vacuous pass fails this)"
    assert canonical["result.txt"] == FileState("file", "answer\n")   # stable field survived
    assert "time.txt" not in canonical                                 # volatile field pruned
    assert derived.task_id == "demo"

    # comparator params pinned per stage (§5)
    assert derived.stages[0].mode == "line"
    assert derived.stages[0].threshold == 1.0


@pytest.mark.tier1
def test_derive_checks_requires_min_passes(tmp_path) -> None:
    """Test that derive_checks requires passes >= _MIN_K."""
    task = TaskCode(
        id="demo",
        setup=(),
        stages=(StageCode(commands=("echo answer > result.txt",), observe=("result.txt",)),),
    )
    with pytest.raises(ValueError, match="passes must be"):
        derive_checks(_factory(tmp_path), task, passes=1)


@pytest.mark.tier1
def test_derive_checks_raises_on_vacuous_canonical(tmp_path):
    """A stage with only a volatile FS field and empty output has no stable signal."""
    # observed file is volatile (pruned) and output is empty → no stable signal
    task = TaskCode(id="demo", setup=(), stages=(
        StageCode(commands=("date +%s%N > t.txt",), observe=("t.txt",)),))
    with pytest.raises(ValueError, match="vacuous"):
        derive_checks(_factory(tmp_path), task, passes=3)


@pytest.mark.tier1
def test_has_signal_rejects_whitespace_only_output():
    assert not _has_signal({OUTPUT_KEY: FileState("file", "  \n")})   # whitespace-only → no signal
    assert _has_signal({OUTPUT_KEY: FileState("file", "answer")})     # real output → signal
    assert _has_signal({"result.txt": FileState("file", "x")})        # FS field → signal
