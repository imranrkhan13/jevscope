"""Turn a Jev answer into a comparable (prediction, certainty) pair.

Jev returns three answer shapes and they do not carry certainty the same way:

  noul    a single probability in [0,1]. There is no `confidence` field at all;
          0.5 is maximal uncertainty and both tails are confident.
  choice  a selected option, a full distribution, and a `confidence` scalar.
  score   a probability-weighted score, a legend, a distribution, and
          `confidence`.

Any routing threshold that treats these three numbers as interchangeable is
wrong. A noul of 0.95 and a choice confidence of 0.95 do not mean the same
thing, and a naive `answer >= 0.9` rule silently auto-accepts every strong
*negative* noul as if it were uncertain.

This module maps all three onto one axis: certainty in [0,1], where 0 is "no
information" and 1 is "fully committed". Everything downstream — routing,
reliability bins, risk-coverage curves — consumes that single number, and the
raw answer is kept alongside so nothing is lost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

AnswerType = Literal["noul", "choice", "score"]


@dataclass(frozen=True)
class Normalized:
    """One Jev answer, flattened for evaluation."""

    answer_type: AnswerType
    #: The discrete thing the model committed to. For noul this is "true"/"false";
    #: for choice the option key; for score the rounded level index as a string.
    prediction: str
    #: Uniform 0-1 commitment. Comparable across answer types.
    certainty: float
    #: The provider's own confidence, where it supplies one. None for noul.
    reported_confidence: float | None
    #: Distribution-derived certainty, computed here for every type. Where the
    #: provider reports confidence too, the gap between them is itself a signal.
    distribution_certainty: float | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def confidence_gap(self) -> float | None:
        """reported_confidence - distribution_certainty.

        A persistent non-zero gap means the scalar `confidence` field is not a
        simple function of the distribution, which matters if you were planning
        to threshold on one and reason about the other.
        """
        if self.reported_confidence is None or self.distribution_certainty is None:
            return None
        return self.reported_confidence - self.distribution_certainty


def _normalized_entropy(probs: list[float]) -> float:
    """Shannon entropy scaled to [0,1] by the entropy of the uniform distribution."""
    clean = [p for p in probs if p > 0]
    if len(clean) <= 1:
        return 0.0
    entropy = -sum(p * math.log(p) for p in clean)
    return min(1.0, entropy / math.log(len(probs)))


def _margin(probs: list[float]) -> float:
    """Gap between the top two probabilities. Robust where entropy is not:
    a distribution with one dominant option and a long tail of near-zeros has
    middling entropy but a decisive margin."""
    if len(probs) < 2:
        return 1.0
    top, second = sorted(probs, reverse=True)[:2]
    return top - second


def normalize(answer: dict[str, Any]) -> Normalized:
    """Flatten one entry from the Decisions API `answers` map."""
    kind = answer.get("type")

    if kind == "noul":
        p = float(answer["noul"])
        return Normalized(
            answer_type="noul",
            prediction="true" if p >= 0.5 else "false",
            # 0.5 -> 0.0, and both 0.0 and 1.0 -> 1.0.
            certainty=abs(p - 0.5) * 2.0,
            reported_confidence=None,
            distribution_certainty=1.0 - _normalized_entropy([p, 1.0 - p]),
            raw=answer,
        )

    if kind == "choice":
        probs_map: dict[str, float] = answer.get("probabilities") or {}
        probs = [float(v) for v in probs_map.values()]
        reported = answer.get("confidence")
        dist = _margin(probs) if probs else None
        return Normalized(
            answer_type="choice",
            prediction=str(answer["choice"]),
            certainty=float(reported) if reported is not None else (dist or 0.0),
            reported_confidence=float(reported) if reported is not None else None,
            distribution_certainty=dist,
            raw=answer,
        )

    if kind == "score":
        probs_map = answer.get("probabilities") or {}
        probs = [float(v) for v in probs_map.values()]
        reported = answer.get("confidence")
        dist = _margin(probs) if probs else None
        # The returned score is probability-weighted and can land between two
        # levels; the discrete commitment is the nearest level.
        level = str(int(round(float(answer["score"]))))
        return Normalized(
            answer_type="score",
            prediction=level,
            certainty=float(reported) if reported is not None else (dist or 0.0),
            reported_confidence=float(reported) if reported is not None else None,
            distribution_certainty=dist,
            raw=answer,
        )

    raise ValueError(f"Unknown Jev answer type: {kind!r}")


def correctness_probability(norm: Normalized) -> float:
    """The model's implied probability that its own prediction is right.

    This is what calibration is measured against, and it is NOT the same as
    certainty. For a noul answer of 0.05 the prediction is "false" and the
    implied probability of being right is 0.95. Conflating the two is the
    single most common way a calibration study gets the sign wrong on half the
    dataset.
    """
    if norm.answer_type == "noul":
        p = float(norm.raw["noul"])
        return p if norm.prediction == "true" else 1.0 - p

    probs = norm.raw.get("probabilities") or {}
    if probs:
        return float(probs.get(norm.prediction, norm.certainty))
    return norm.certainty
