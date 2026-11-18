"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    if not human or len(human) != len(judge):
        raise ValueError("human and judge must be non-empty and have equal lengths")
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for h, j in zip(human, judge):
        if h not in {"PASS", "FAIL"} or j not in {"PASS", "FAIL"}:
            raise ValueError("labels must be PASS or FAIL")
        key = ("tp" if h == POS else "fp") if j == POS else ("fn" if h == POS else "tn")
        counts[key] += 1
    return counts


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    c = confusion(human, judge)
    predicted = c["tp"] + c["fp"]
    actual = c["tp"] + c["fn"]
    return (c["tp"] / predicted if predicted else 0.0,
            c["tp"] / actual if actual else 0.0)


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    c = confusion(human, judge)
    n = sum(c.values())
    observed = (c["tp"] + c["tn"]) / n
    expected = ((c["tp"] + c["fn"]) * (c["tp"] + c["fp"])
                + (c["tn"] + c["fp"]) * (c["tn"] + c["fn"])) / n**2
    if expected == 1:
        raise ValueError("kappa is undefined when expected agreement is 1")
    return (observed - expected) / (1 - expected)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    if any(not math.isfinite(x) or not 0 <= x <= 1
           for x in (observed_rate, sensitivity, specificity)):
        raise ValueError("rates must be finite probabilities")
    denominator = sensitivity + specificity - 1
    if denominator <= 0:
        raise ValueError("judge sensitivity + specificity must exceed 1")
    return min(1.0, max(0.0, (observed_rate + specificity - 1) / denominator))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy.stats import bootstrap

    left, right = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if left.ndim != 1 or right.ndim != 1 or left.size == 0 or left.shape != right.shape:
        raise ValueError("paired samples must be non-empty one-dimensional arrays of equal length")
    if not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
        raise ValueError("paired samples must be finite")
    if not isinstance(n_resamples, int) or n_resamples <= 0 or not 0 < confidence < 1:
        raise ValueError("n_resamples must be positive; confidence must be between 0 and 1")
    if np.array_equal(left, right):
        return 0.0, 0.0, 0.0
    if left.size < 2:
        raise ValueError("bootstrap needs at least two paired items")

    def difference(x, y, axis=-1):
        return np.mean(x - y, axis=axis)

    result = bootstrap((left, right), difference, paired=True, vectorized=True,
                       n_resamples=n_resamples, method="percentile",
                       confidence_level=confidence, rng=np.random.default_rng(rng))
    return (float(difference(left, right)), float(result.confidence_interval.low),
            float(result.confidence_interval.high))


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _validate_pass_counts(n, c, k)
    return 1.0 if n - c < k else 1 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _validate_pass_counts(n, c, k)
    return 0.0 if c < k else math.comb(c, k) / math.comb(n, k)


def _validate_pass_counts(n: int, c: int, k: int) -> None:
    if any(type(v) is not int for v in (n, c, k)) or not (n >= 1 and 0 <= c <= n and 1 <= k <= n):
        raise ValueError("require integers n >= 1, 0 <= c <= n, and 1 <= k <= n")
