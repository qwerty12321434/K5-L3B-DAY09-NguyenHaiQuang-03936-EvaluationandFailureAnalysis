"""Independent integrity traps and combinatorial vectors beyond public examples."""
import copy
from itertools import combinations

import pytest

from lab9 import gate, stats

pytestmark = pytest.mark.student


def sample():
    spec = {"eval_set_version": "v2", "metrics": [{"id": "pass_rate", "blocking": True,
            "threshold": {"min": 0.8, "no_significant_drop": True}}],
            "slices": [{"name": "custom_slice", "metric": "pass_rate", "min": 0.8,
                        "no_significant_drop": True, "blocking": True}]}
    base = {"manifest": {"eval_set_sha": "unit", "items": 2, "seeds": [1, 2]},
            "metrics": {"pass_rate": 1.0}, "evaluator_failures": [],
            "rows": [{"item_id": item, "seed": seed, "pass_rate": True, "slices": ["custom_slice"]}
                     for item in ("a", "b") for seed in (1, 2)]}
    return spec, base


def test_advanced_valid_self_comparison_merges():
    spec, base = sample()
    assert gate.check(base, base, spec, spec)[0] == []


@pytest.mark.parametrize("trap", ["duplicate", "evaluator", "null", "infinity", "aggregate", "seeds", "slices"])
def test_advanced_integrity_blocks_independent_traps(trap):
    spec, base = sample()
    pr = copy.deepcopy(base)
    if trap == "duplicate":
        pr["rows"][-1] = copy.deepcopy(pr["rows"][0])
    elif trap == "evaluator":
        pr["evaluator_failures"] = ["a@1:grader crashed"]
    elif trap == "null":
        pr["rows"][0]["pass_rate"] = None
    elif trap == "infinity":
        pr["metrics"]["pass_rate"] = float("inf")
    elif trap == "aggregate":
        pr["metrics"]["pass_rate"] = 0.99
    elif trap == "seeds":
        pr["manifest"]["seeds"] = [1, 3]
        for row in pr["rows"]:
            if row["seed"] == 2:
                row["seed"] = 3
    else:
        for row in pr["rows"]:
            if row["item_id"] == "a":
                row["slices"] = []
    assert gate.check(pr, base, spec)[0] == ["integrity"]


@pytest.mark.parametrize("change", ["drop_metric", "drop_slice", "unblock", "drop_ci", "lower_floor"])
def test_advanced_ratchet_checks_metrics_and_slices(change):
    spec, base = sample()
    loose = copy.deepcopy(spec)
    if change == "drop_metric":
        loose["metrics"] = []
    elif change == "drop_slice":
        loose["slices"] = []
    elif change == "unblock":
        loose["slices"][0]["blocking"] = False
    elif change == "drop_ci":
        loose["slices"][0].pop("no_significant_drop")
    else:
        loose["metrics"][0]["threshold"]["min"] = 0.7
    assert any("ratchet" in p for p in gate.integrity_check(base, base, loose, spec))


def test_advanced_slice_supports_new_names():
    spec, base = sample()
    pr = copy.deepcopy(base)
    pr["rows"][0]["pass_rate"] = False
    blocked, _ = gate.slice_check(pr, base, spec)
    assert blocked == ["slice:custom_slice/pass_rate"]


def test_advanced_pass_estimators_match_enumerated_subsets():
    for n in range(1, 7):
        for c in range(n + 1):
            trials = [True] * c + [False] * (n - c)
            for k in range(1, n + 1):
                subsets = list(combinations(trials, k))
                assert stats.pass_at_k(n, c, k) == pytest.approx(sum(any(s) for s in subsets) / len(subsets))
                assert stats.pass_hat_k(n, c, k) == pytest.approx(sum(all(s) for s in subsets) / len(subsets))


@pytest.mark.parametrize("args", [(0, 0, 0), (5, -1, 1), (5, 6, 1), (5, 2, 6), (5.0, 2, 1), (True, 1, 1)])
def test_advanced_both_estimators_reject_bad_inputs(args):
    for fn in (stats.pass_at_k, stats.pass_hat_k):
        with pytest.raises(ValueError):
            fn(*args)
