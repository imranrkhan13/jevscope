"""Load labelled decisions and run the full study.

Input is JSONL, one record per (item, question, provider):

    {"key": "src/api/routes.py", "question": "file_type", "provider": "jev",
     "model": "jev-latest", "gold": "route",
     "answer": {"type": "choice", "choice": "route",
                "probabilities": {"route": 0.91, "service": 0.07, "test": 0.02},
                "confidence": 0.89},
     "latency_ms": 41, "cost_usd": 0.000032}

`answer` is the raw object from the Decisions API, unmodified. Keeping it
verbatim means the study can be re-run with different certainty definitions
without re-querying, and anyone can check the normalisation themselves.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reposcope.calibration import compare, metrics, risk_coverage
from reposcope.calibration.certainty import correctness_probability, normalize


@dataclass(frozen=True)
class Record:
    key: str
    question: str
    provider: str
    model: str
    gold: str
    answer: dict[str, Any]
    latency_ms: float = 0.0
    cost_usd: float = 0.0


def load(path: Path) -> list[Record]:
    records: list[Record] = []
    with Path(path).open() as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                raw = json.loads(line)
                records.append(
                    Record(
                        key=raw["key"],
                        question=raw["question"],
                        provider=raw["provider"],
                        model=raw.get("model", raw["provider"]),
                        gold=str(raw["gold"]),
                        answer=raw["answer"],
                        latency_ms=float(raw.get("latency_ms", 0)),
                        cost_usd=float(raw.get("cost_usd", 0)),
                    )
                )
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{path}:{lineno} — {exc}") from exc
    return records


@dataclass
class QuestionStudy:
    question: str
    provider: str
    model: str
    answer_type: str
    n: int
    calibration: metrics.CalibrationReport
    curve: list[risk_coverage.CoveragePoint]
    aurc: float
    choice: risk_coverage.ThresholdChoice
    coverage_at_2pct: risk_coverage.CoveragePoint | None
    #: Mean of (reported confidence - distribution-derived certainty).
    mean_confidence_gap: float | None


def study_question(
    records: list[Record], cost: risk_coverage.CostModel, *, resamples: int = 1000
) -> QuestionStudy:
    normalized = [normalize(r.answer) for r in records]
    correct = [n.prediction == r.gold for n, r in zip(normalized, records)]
    # Calibration is measured against the implied probability of being right,
    # which for a noul is not the raw value. See certainty.py.
    implied = [correctness_probability(n) for n in normalized]
    certainties = [n.certainty for n in normalized]

    gaps = [n.confidence_gap for n in normalized if n.confidence_gap is not None]

    curve = risk_coverage.risk_coverage_curve(certainties, correct)

    return QuestionStudy(
        question=records[0].question,
        provider=records[0].provider,
        model=records[0].model,
        answer_type=normalized[0].answer_type,
        n=len(records),
        calibration=metrics.evaluate(implied, correct, resamples=resamples),
        curve=curve,
        aurc=risk_coverage.aurc(curve),
        choice=risk_coverage.choose_threshold(certainties, correct, cost),
        coverage_at_2pct=risk_coverage.coverage_at_risk(curve, 0.02),
        mean_confidence_gap=(sum(gaps) / len(gaps)) if gaps else None,
    )


def pair_providers(
    records: list[Record], a_provider: str, b_provider: str, question: str
) -> list[compare.Paired]:
    """Join two providers on (key, question). Items missing from either side
    are dropped — an unpaired comparison is not a comparison."""
    index: dict[tuple[str, str], Record] = {}
    for r in records:
        if r.question == question:
            index[(r.provider, r.key)] = r

    keys = {k for (p, k) in index if p == a_provider} & {
        k for (p, k) in index if p == b_provider
    }

    pairs: list[compare.Paired] = []
    for key in sorted(keys):
        a, b = index[(a_provider, key)], index[(b_provider, key)]
        na, nb = normalize(a.answer), normalize(b.answer)
        pairs.append(
            compare.Paired(
                key=key,
                gold=a.gold,
                a_pred=na.prediction,
                b_pred=nb.prediction,
                a_certainty=na.certainty,
                b_certainty=nb.certainty,
                a_latency_ms=a.latency_ms,
                b_latency_ms=b.latency_ms,
                a_cost_usd=a.cost_usd,
                b_cost_usd=b.cost_usd,
            )
        )
    return pairs


@dataclass
class Study:
    dataset: str
    cost_model: risk_coverage.CostModel
    per_question: list[QuestionStudy]
    comparisons: list[tuple[str, compare.McNemar, compare.ProviderStats, compare.ProviderStats]]
    warnings: list[str]


def run(
    path: Path,
    *,
    cost: risk_coverage.CostModel | None = None,
    a_provider: str = "jev",
    b_provider: str = "llm",
    resamples: int = 1000,
) -> Study:
    cost = cost or risk_coverage.CostModel()
    records = load(path)
    warnings: list[str] = []

    grouped: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for r in records:
        grouped[(r.question, r.provider)].append(r)

    per_question = []
    for (question, provider), group in sorted(grouped.items()):
        if len(group) < 30:
            warnings.append(
                f"{question}/{provider}: only {len(group)} labelled items. "
                "Calibration estimates below ~100 items are dominated by sampling noise."
            )
        per_question.append(study_question(group, cost, resamples=resamples))

    comparisons = []
    for question in sorted({r.question for r in records}):
        pairs = pair_providers(records, a_provider, b_provider, question)
        if not pairs:
            continue
        comparisons.append(
            (
                question,
                compare.mcnemar(pairs),
                compare.provider_stats(pairs, "a", a_provider),
                compare.provider_stats(pairs, "b", b_provider),
            )
        )

    if not comparisons:
        warnings.append(
            f"No paired items between {a_provider!r} and {b_provider!r} — "
            "the head-to-head section is empty."
        )

    return Study(
        dataset=str(path),
        cost_model=cost,
        per_question=per_question,
        comparisons=comparisons,
        warnings=warnings,
    )
