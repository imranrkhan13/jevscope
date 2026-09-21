"""Selective prediction: turn calibration into a threshold you can ship.

Calibration tells you whether confidence means what it says. It does not tell
you where to set a threshold. That is a cost question, and the answer moves
with the task: auto-filing a support ticket wrongly costs a minute, auto-
deleting a file wrongly costs an afternoon.

This module answers it directly. Given labelled decisions and a cost model —
what an error costs, what a human review costs — it produces the risk-coverage
curve and the threshold that minimises expected cost, with the honest caveat
that the threshold is fitted on a sample and will move on new data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoveragePoint:
    threshold: float
    #: Fraction of items the model handles automatically at this threshold.
    coverage: float
    #: Accuracy on the covered subset. This is the number that actually matters:
    #: overall accuracy is irrelevant if you only act on the confident half.
    selective_accuracy: float
    #: Error rate on the covered subset.
    selective_risk: float
    n_covered: int
    n_errors_auto: int
    n_deferred: int


@dataclass(frozen=True)
class CostModel:
    """What it costs to be wrong versus what it costs to ask a human.

    Units are arbitrary but must be consistent. cost_error / cost_review is the
    only ratio that matters; 50 means one automated mistake is as expensive as
    fifty human reviews.
    """

    cost_error: float = 50.0
    cost_review: float = 1.0
    #: Human reviewers are not oracles. At 0.95, deferring still leaves 5% wrong.
    review_accuracy: float = 1.0

    def expected_cost(self, point: CoveragePoint, n: int) -> float:
        if n == 0:
            return 0.0
        auto_errors = point.n_errors_auto
        review_errors = point.n_deferred * (1.0 - self.review_accuracy)
        return (
            (auto_errors + review_errors) * self.cost_error
            + point.n_deferred * self.cost_review
        ) / n


@dataclass(frozen=True)
class ThresholdChoice:
    threshold: float
    point: CoveragePoint
    expected_cost: float
    #: Cost of the two degenerate policies, for comparison.
    cost_review_everything: float
    cost_automate_everything: float

    @property
    def savings_vs_manual(self) -> float:
        if self.cost_review_everything == 0:
            return 0.0
        return 1.0 - (self.expected_cost / self.cost_review_everything)

    @property
    def beats_full_automation(self) -> bool:
        return self.expected_cost < self.cost_automate_everything


def risk_coverage_curve(
    certainties: list[float], correct: list[bool], *, steps: int = 101
) -> list[CoveragePoint]:
    """Sweep the threshold from 0 to 1 and record what happens at each stop."""
    n = len(certainties)
    if n == 0:
        return []

    points: list[CoveragePoint] = []
    for i in range(steps):
        t = i / (steps - 1)
        covered = [(c, y) for c, y in zip(certainties, correct) if c >= t]
        n_cov = len(covered)
        n_err = sum(1 for _, y in covered if not y)
        acc = (n_cov - n_err) / n_cov if n_cov else 1.0
        points.append(
            CoveragePoint(
                threshold=t,
                coverage=n_cov / n,
                selective_accuracy=acc,
                selective_risk=1.0 - acc,
                n_covered=n_cov,
                n_errors_auto=n_err,
                n_deferred=n - n_cov,
            )
        )
    return points


def aurc(points: list[CoveragePoint]) -> float:
    """Area under the risk-coverage curve. Lower is better.

    Single number for "how well does this certainty signal rank its own
    mistakes". It is independent of calibration: a model whose confidences are
    all inflated by 0.2 has terrible ECE and unchanged AURC. Both numbers are
    needed — AURC says the ordering is useful, ECE says the absolute value is
    trustworthy.
    """
    usable = sorted([p for p in points if p.n_covered > 0], key=lambda p: p.coverage)
    if len(usable) < 2:
        return usable[0].selective_risk if usable else 0.0
    area = 0.0
    for a, b in zip(usable[:-1], usable[1:]):
        area += (b.coverage - a.coverage) * (a.selective_risk + b.selective_risk) / 2
    span = usable[-1].coverage - usable[0].coverage
    return area / span if span > 0 else usable[0].selective_risk


def coverage_at_risk(points: list[CoveragePoint], max_risk: float) -> CoveragePoint | None:
    """Highest coverage achievable while keeping selective risk under a ceiling.

    This is usually the question a product owner actually asks: "how much can we
    automate if we accept at most 2% errors?"
    """
    eligible = [p for p in points if p.n_covered > 0 and p.selective_risk <= max_risk]
    return max(eligible, key=lambda p: p.coverage) if eligible else None


def choose_threshold(
    certainties: list[float],
    correct: list[bool],
    cost: CostModel,
    *,
    steps: int = 101,
) -> ThresholdChoice:
    """The cost-minimising threshold on this sample.

    Fitted on the data you pass in. If you select a threshold here and report
    its performance on the same items, the number is optimistic — hold out a
    split, or expect the shipped threshold to underperform the study.
    """
    n = len(certainties)
    points = risk_coverage_curve(certainties, correct, steps=steps)
    if not points:
        raise ValueError("no decisions to evaluate")

    scored = [(cost.expected_cost(p, n), p) for p in points]
    best_cost, best = min(scored, key=lambda pair: (pair[0], -pair[1].coverage))

    all_auto = points[0]
    n_errors_total = sum(1 for y in correct if not y)
    cost_auto = (n_errors_total * cost.cost_error) / n if n else 0.0
    cost_manual = (
        n * cost.cost_review + n * (1.0 - cost.review_accuracy) * cost.cost_error
    ) / n if n else 0.0

    assert all_auto.threshold == 0.0
    return ThresholdChoice(
        threshold=best.threshold,
        point=best,
        expected_cost=best_cost,
        cost_review_everything=cost_manual,
        cost_automate_everything=cost_auto,
    )
