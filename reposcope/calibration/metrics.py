"""Calibration metrics, with the caveats that usually get omitted.

Three things this module does that a quick ECE script does not:

1. Equal-mass bins by default. Equal-width bins are the textbook default and
   they are misleading on real model output, where confidence piles up near
   1.0: most bins end up nearly empty and ECE becomes a statement about a
   handful of points.

2. Bootstrap confidence intervals on every metric. With a few hundred labelled
   items, ECE has enough sampling variance that a point estimate of 0.03 and
   one of 0.06 are frequently indistinguishable. Publishing a bare number
   invites a conclusion the data does not support.

3. Separate reporting of discrimination (Brier, accuracy) from calibration
   (ECE, reliability). A model can be perfectly calibrated and useless — always
   answer 0.5 on a balanced task — so calibration alone is never the verdict.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Bin:
    lower: float
    upper: float
    count: int
    mean_confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        """Signed: positive means overconfident in this bin."""
        return self.mean_confidence - self.accuracy


@dataclass(frozen=True)
class Interval:
    point: float
    lower: float
    upper: float

    def __str__(self) -> str:
        return f"{self.point:.4f} [{self.lower:.4f}, {self.upper:.4f}]"


@dataclass(frozen=True)
class CalibrationReport:
    n: int
    accuracy: Interval
    ece: Interval
    mce: float
    brier: Interval
    log_loss: float
    mean_confidence: float
    bins: list[Bin]
    binning: str

    @property
    def overconfidence(self) -> float:
        """Mean confidence minus accuracy. Positive means the model overclaims."""
        return self.mean_confidence - self.accuracy.point


def _equal_mass_edges(confidences: list[float], n_bins: int) -> list[float]:
    ordered = sorted(confidences)
    if not ordered:
        return [0.0, 1.0]
    edges = [0.0]
    for i in range(1, n_bins):
        idx = min(len(ordered) - 1, int(i * len(ordered) / n_bins))
        edges.append(ordered[idx])
    edges.append(1.0 + 1e-9)
    # Collapse duplicates: heavy ties at 1.0 would otherwise create empty bins.
    deduped = [edges[0]]
    for e in edges[1:]:
        if e > deduped[-1]:
            deduped.append(e)
    return deduped


def _equal_width_edges(n_bins: int) -> list[float]:
    return [i / n_bins for i in range(n_bins)] + [1.0 + 1e-9]


def build_bins(
    confidences: list[float],
    correct: list[bool],
    *,
    n_bins: int = 10,
    binning: str = "equal_mass",
) -> list[Bin]:
    edges = (
        _equal_mass_edges(confidences, n_bins)
        if binning == "equal_mass"
        else _equal_width_edges(n_bins)
    )
    bins: list[Bin] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        members = [(c, y) for c, y in zip(confidences, correct) if lo <= c < hi]
        if not members:
            continue
        conf = sum(c for c, _ in members) / len(members)
        acc = sum(1 for _, y in members if y) / len(members)
        bins.append(Bin(lo, min(hi, 1.0), len(members), conf, acc))
    return bins


def expected_calibration_error(bins: list[Bin], n: int) -> float:
    if n == 0:
        return 0.0
    return sum(b.count * abs(b.gap) for b in bins) / n


def maximum_calibration_error(bins: list[Bin]) -> float:
    return max((abs(b.gap) for b in bins), default=0.0)


def brier_score(confidences: list[float], correct: list[bool]) -> float:
    if not confidences:
        return 0.0
    return sum((c - (1.0 if y else 0.0)) ** 2 for c, y in zip(confidences, correct)) / len(
        confidences
    )


def log_loss(confidences: list[float], correct: list[bool], eps: float = 1e-12) -> float:
    if not confidences:
        return 0.0
    total = 0.0
    for c, y in zip(confidences, correct):
        p = min(max(c, eps), 1.0 - eps)
        total += -math.log(p) if y else -math.log(1.0 - p)
    return total / len(confidences)


def _bootstrap(
    confidences: list[float],
    correct: list[bool],
    statistic,
    *,
    resamples: int,
    alpha: float,
    seed: int,
) -> Interval:
    point = statistic(confidences, correct)
    n = len(confidences)
    if n < 2 or resamples <= 0:
        return Interval(point, point, point)

    rng = random.Random(seed)
    draws: list[float] = []
    indices = range(n)
    for _ in range(resamples):
        sample = [rng.choice(indices) for _ in indices]
        draws.append(statistic([confidences[i] for i in sample], [correct[i] for i in sample]))
    draws.sort()
    q_lo = draws[int((alpha / 2) * resamples)]
    q_hi = draws[min(resamples - 1, int((1 - alpha / 2) * resamples))]

    # Basic (reverse-percentile) interval, not the percentile interval.
    #
    # ECE is a mean of absolute deviations, so it is biased upward: resampling
    # adds noise, and noise can only increase |confidence - accuracy| on
    # average. With the percentile interval that bias lands in the interval
    # itself, which produces the absurd result of a CI that does not contain
    # its own point estimate. The basic interval reflects the bootstrap
    # distribution back through the point estimate and cancels it to first
    # order. For unbiased statistics like accuracy the two agree closely.
    lower = 2 * point - q_hi
    upper = 2 * point - q_lo

    # These metrics are non-negative and bounded; clamp rather than report
    # an impossible bound.
    return Interval(point, max(0.0, min(lower, point)), min(1.0, max(upper, point)))


def evaluate(
    confidences: list[float],
    correct: list[bool],
    *,
    n_bins: int = 10,
    binning: str = "equal_mass",
    resamples: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
) -> CalibrationReport:
    """Full calibration report.

    `confidences` must be the model's implied probability that its own
    prediction is correct — see certainty.correctness_probability. Passing raw
    noul values here inverts half the dataset.
    """
    if len(confidences) != len(correct):
        raise ValueError("confidences and correct must be the same length")

    n = len(confidences)

    def _ece(c: list[float], y: list[bool]) -> float:
        return expected_calibration_error(build_bins(c, y, n_bins=n_bins, binning=binning), len(c))

    def _acc(_c: list[float], y: list[bool]) -> float:
        return sum(1 for v in y if v) / len(y) if y else 0.0

    bins = build_bins(confidences, correct, n_bins=n_bins, binning=binning)

    return CalibrationReport(
        n=n,
        accuracy=_bootstrap(
            confidences, correct, _acc, resamples=resamples, alpha=alpha, seed=seed
        ),
        ece=_bootstrap(confidences, correct, _ece, resamples=resamples, alpha=alpha, seed=seed + 1),
        mce=maximum_calibration_error(bins),
        brier=_bootstrap(
            confidences, correct, brier_score, resamples=resamples, alpha=alpha, seed=seed + 2
        ),
        log_loss=log_loss(confidences, correct),
        mean_confidence=sum(confidences) / n if n else 0.0,
        bins=bins,
        binning=binning,
    )
