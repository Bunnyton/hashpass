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
    k_runs = 3

    def run_once() -> dict:
        i = next(counter)
        return {"result.txt": FileState("file", "answer"),
                "time.txt": FileState("file", str(i))}

    canon = derive_canonical(run_once, k=k_runs)
    assert canon == {"result.txt": FileState("file", "answer")}
    assert next(counter) == k_runs  # run_once called exactly k times

    with pytest.raises(ValueError, match="k must be"):
        derive_canonical(run_once, k=1)
