from __future__ import annotations

import math
import random

import pytest

from reposcope.calibration import compare, metrics, risk_coverage
from reposcope.calibration.certainty import correctness_probability, normalize


# --- certainty normalisation -------------------------------------------------


def test_noul_certainty_is_symmetric_about_half():
    low = normalize({"type": "noul", "noul": 0.05})
    high = normalize({"type": "noul", "noul": 0.95})
    assert low.prediction == "false"
    assert high.prediction == "true"
    assert low.certainty == pytest.approx(high.certainty)
    assert low.certainty == pytest.approx(0.9)


def test_noul_at_half_is_zero_certainty():
    assert normalize({"type": "noul", "noul": 0.5}).certainty == 0.0


def test_noul_has_no_reported_confidence():
    # The API supplies no confidence field for noul; inventing one would be a lie.
    assert normalize({"type": "noul", "noul": 0.8}).reported_confidence is None


def test_correctness_probability_inverts_for_negative_noul():
    """The bug this guards: treating raw noul as P(correct) marks every
    confident 'no' as a near-certain error."""
    negative = normalize({"type": "noul", "noul": 0.02})
    assert correctness_probability(negative) == pytest.approx(0.98)
    positive = normalize({"type": "noul", "noul": 0.97})
    assert correctness_probability(positive) == pytest.approx(0.97)


def test_choice_uses_reported_confidence_and_records_margin():
    norm = normalize(
        {
            "type": "choice",
            "choice": "billing",
            "probabilities": {"billing": 0.95, "technical": 0.05, "sales": 0.0},
            "confidence": 0.93,
        }
    )
    assert norm.prediction == "billing"
    assert norm.certainty == pytest.approx(0.93)
    assert norm.distribution_certainty == pytest.approx(0.90)
    assert norm.confidence_gap == pytest.approx(0.03)


def test_score_rounds_to_nearest_level():
    norm = normalize(
        {
            "type": "score",
            "score": 1.27,
            "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
            "probabilities": {"0": 0.0, "1": 0.73, "2": 0.27},
            "confidence": 0.6,
        }
    )
    assert norm.prediction == "1"
    assert norm.certainty == pytest.approx(0.6)


def test_choice_falls_back_to_margin_without_confidence():
    norm = normalize(
        {"type": "choice", "choice": "a", "probabilities": {"a": 0.7, "b": 0.3}}
    )
    assert norm.certainty == pytest.approx(0.4)


def test_unknown_answer_type_is_rejected():
    with pytest.raises(ValueError):
        normalize({"type": "vibes", "vibes": 1})


# --- calibration metrics -----------------------------------------------------


def _synthetic(n: int, shift: float, seed: int = 0):
    """Confidences whose true accuracy is confidence - shift."""
    rng = random.Random(seed)
    conf, correct = [], []
    for _ in range(n):
        c = rng.uniform(0.5, 0.99)
        conf.append(c)
        correct.append(rng.random() < max(0.0, min(1.0, c - shift)))
    return conf, correct


def test_perfect_calibration_gives_near_zero_ece():
    conf, correct = _synthetic(4000, shift=0.0, seed=1)
    report = metrics.evaluate(conf, correct, resamples=0)
    assert report.ece.point < 0.03


def test_overconfidence_is_detected_with_right_sign():
    conf, correct = _synthetic(4000, shift=0.15, seed=2)
    report = metrics.evaluate(conf, correct, resamples=0)
    assert report.ece.point > 0.10
    assert report.overconfidence > 0.10


def test_underconfidence_has_negative_sign():
    conf, correct = _synthetic(4000, shift=-0.15, seed=3)
    assert metrics.evaluate(conf, correct, resamples=0).overconfidence < -0.05


def test_equal_mass_bins_are_populated():
    """Equal-width binning leaves most bins empty when confidence clusters high;
    equal-mass is why the reported ECE is not a statement about three points."""
    conf = [0.9 + i * 0.001 for i in range(200)]
    correct = [True] * 180 + [False] * 20
    mass = metrics.build_bins(conf, correct, n_bins=10, binning="equal_mass")
    width = metrics.build_bins(conf, correct, n_bins=10, binning="equal_width")
    assert len(mass) > len(width)
    assert all(b.count > 0 for b in mass)


def test_bootstrap_interval_contains_point_and_has_width():
    conf, correct = _synthetic(200, shift=0.05, seed=4)
    report = metrics.evaluate(conf, correct, resamples=300)
    assert report.ece.lower <= report.ece.point <= report.ece.upper
    assert report.ece.upper > report.ece.lower


def test_brier_rewards_confident_correctness():
    assert metrics.brier_score([1.0, 1.0], [True, True]) == 0.0
    assert metrics.brier_score([1.0, 1.0], [False, False]) == 1.0


def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError):
        metrics.evaluate([0.5], [True, False])


def test_calibrated_but_useless_model_is_not_praised():
    """Always answering 0.5 on a balanced task is perfectly calibrated and
    worthless — the report must expose that via Brier, not just ECE."""
    conf = [0.5] * 1000
    correct = [i % 2 == 0 for i in range(1000)]
    report = metrics.evaluate(conf, correct, resamples=0)
    assert report.ece.point < 0.01
    assert report.brier.point == pytest.approx(0.25, abs=0.01)


# --- risk / coverage ---------------------------------------------------------


def test_coverage_falls_as_threshold_rises():
    cert = [0.1, 0.4, 0.6, 0.9]
    correct = [False, False, True, True]
    curve = risk_coverage.risk_coverage_curve(cert, correct, steps=11)
    coverages = [p.coverage for p in curve]
    assert coverages == sorted(coverages, reverse=True)
    assert curve[0].coverage == 1.0


def test_selective_accuracy_improves_with_a_useful_signal():
    cert = [i / 100 for i in range(100)]
    correct = [i >= 50 for i in range(100)]
    curve = risk_coverage.risk_coverage_curve(cert, correct)
    at_full = next(p for p in curve if p.threshold == 0.0)
    at_high = next(p for p in curve if abs(p.threshold - 0.6) < 1e-9)
    assert at_high.selective_accuracy > at_full.selective_accuracy


def test_aurc_lower_for_a_signal_that_ranks_its_errors():
    good_cert = [i / 100 for i in range(100)]
    correct = [i >= 30 for i in range(100)]
    good = risk_coverage.aurc(risk_coverage.risk_coverage_curve(good_cert, correct))
    shuffled = list(good_cert)
    random.Random(0).shuffle(shuffled)
    bad = risk_coverage.aurc(risk_coverage.risk_coverage_curve(shuffled, correct))
    assert good < bad


def test_expensive_errors_push_the_threshold_up():
    rng = random.Random(5)
    cert = [rng.uniform(0, 1) for _ in range(500)]
    correct = [rng.random() < c for c in cert]
    cheap = risk_coverage.choose_threshold(cert, correct, risk_coverage.CostModel(2, 1))
    costly = risk_coverage.choose_threshold(cert, correct, risk_coverage.CostModel(500, 1))
    assert costly.threshold >= cheap.threshold


def test_free_review_defers_everything():
    rng = random.Random(6)
    cert = [rng.uniform(0, 1) for _ in range(200)]
    correct = [rng.random() < c for c in cert]
    choice = risk_coverage.choose_threshold(
        cert, correct, risk_coverage.CostModel(cost_error=1000, cost_review=0.0)
    )
    assert choice.point.coverage < 0.2


def test_coverage_at_risk_respects_the_ceiling():
    cert = [i / 100 for i in range(100)]
    correct = [i >= 20 for i in range(100)]
    curve = risk_coverage.risk_coverage_curve(cert, correct)
    point = risk_coverage.coverage_at_risk(curve, 0.02)
    assert point is not None and point.selective_risk <= 0.02


def test_empty_dataset_raises_rather_than_returning_a_number():
    with pytest.raises(ValueError):
        risk_coverage.choose_threshold([], [], risk_coverage.CostModel())


# --- head to head ------------------------------------------------------------


def _pair(key, gold, a, b):
    return compare.Paired(key, gold, a, b, 0.9, 0.9, 10, 10, 0.0, 0.0)


def test_mcnemar_flags_small_samples_as_inconclusive():
    pairs = [_pair(f"f{i}", "x", "x", "y") for i in range(4)]
    result = compare.mcnemar(pairs)
    assert not result.significant or result.discordant < 10
    assert "too few" in result.verdict("jev", "llm")


def test_mcnemar_detects_a_real_lopsided_split():
    pairs = [_pair(f"a{i}", "x", "x", "y") for i in range(40)]
    pairs += [_pair(f"b{i}", "x", "y", "x") for i in range(5)]
    result = compare.mcnemar(pairs)
    assert result.significant
    assert "jev beats llm".lower() in result.verdict("jev", "llm").lower()


def test_mcnemar_uses_exact_test_below_25_discordant():
    pairs = [_pair(f"a{i}", "x", "x", "y") for i in range(8)]
    pairs += [_pair(f"b{i}", "x", "y", "x") for i in range(6)]
    assert compare.mcnemar(pairs).exact


def test_concordant_results_are_not_significant():
    pairs = [_pair(f"f{i}", "x", "x", "x") for i in range(100)]
    result = compare.mcnemar(pairs)
    assert result.discordant == 0
    assert not result.significant


def test_provider_stats_cost_per_correct():
    pairs = [
        compare.Paired("f1", "x", "x", "y", 0.9, 0.9, 10, 100, 0.001, 0.01),
        compare.Paired("f2", "x", "x", "x", 0.9, 0.9, 30, 300, 0.001, 0.01),
    ]
    stats = compare.provider_stats(pairs, "a", "jev")
    assert stats.accuracy == 1.0
    assert stats.cost_per_correct == pytest.approx(0.001)
    assert stats.mean_latency_ms == pytest.approx(20)


def test_p_values_are_probabilities():
    for n_a, n_b in [(0, 0), (3, 3), (30, 10), (100, 1)]:
        pairs = [_pair(f"a{i}", "x", "x", "y") for i in range(n_a)]
        pairs += [_pair(f"b{i}", "x", "y", "x") for i in range(n_b)]
        p = compare.mcnemar(pairs).p_value
        assert 0.0 <= p <= 1.0 and not math.isnan(p)
