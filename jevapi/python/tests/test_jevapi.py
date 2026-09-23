import json
import math
from pathlib import Path

import pytest

from jevapi import (
    apply_isotonic,
    calibrate,
    cost_threshold,
    decide,
    decide_all,
    ece,
    evaluate,
    fit_isotonic,
    validate_profile,
    wilson_lower,
)

SPEC = Path(__file__).resolve().parents[2] / "spec"
EXAMPLES = json.loads((SPEC / "examples.json").read_text())["examples"]
EXPECTED = json.loads((SPEC / "expected.json").read_text())


def test_cost_threshold():
    assert cost_threshold({"costError": 20, "costReview": 1, "reviewAccuracy": 1}) == 0.95
    assert cost_threshold({"costError": 2, "costReview": 1, "reviewAccuracy": 1}) == 0.5
    assert cost_threshold({"costError": 20, "costReview": 1, "reviewAccuracy": 0.98}) == 0.93
    assert cost_threshold({"costError": 0.5, "costReview": 1, "reviewAccuracy": 1}) == 0
    with pytest.raises(ValueError):
        cost_threshold({"costError": 0, "costReview": 1, "reviewAccuracy": 1})


def test_wilson():
    assert wilson_lower(0, 0) == 0
    assert wilson_lower(10, 10) < wilson_lower(100, 100) < 1
    assert wilson_lower(50, 100) < 0.5


def test_isotonic_monotone():
    blocks = fit_isotonic(EXAMPLES)
    for a, b in zip(blocks, blocks[1:]):
        assert b["p"] >= a["p"] and b["lower"] >= a["lower"] and b["lo"] > a["hi"]
    prev = -1
    for i in range(101):
        p = apply_isotonic(blocks, i / 100)
        assert 0 <= p <= 1 and p >= prev - 1e-12
        prev = p
    assert sum(b["n"] for b in blocks) == len(EXAMPLES)


def test_overconfident_model_goes_to_review():
    ex = [{"confidence": 0.95, "correct": i % 2 == 0} for i in range(200)]
    blocks = fit_isotonic(ex)
    assert len(blocks) == 1
    assert abs(apply_isotonic(blocks, 0.95) - 0.5) < 0.01
    assert decide(calibrate(ex), {"value": "x", "confidence": 0.95})["action"] == "review"


@pytest.mark.parametrize("value", [None, "", "   ", []])
def test_empty_value_review(value):
    p = calibrate(EXAMPLES)
    assert decide(p, {"field": "invoice_number", "value": value, "confidence": 1})["action"] == "review"


@pytest.mark.parametrize("conf", [None, math.nan, -0.1, 1.2, "0.9", True])
def test_bad_confidence_review(conf):
    p = calibrate(EXAMPLES)
    assert decide(p, {"field": "invoice_number", "value": "A1", "confidence": conf})["action"] == "review"


def test_validator():
    p = calibrate(EXAMPLES)
    d = decide(p, {"field": "invoice_number", "value": "??", "confidence": 0.99}, {"validate": lambda v: v.isalnum()})
    assert d["action"] == "review"

    def boom(_):
        raise RuntimeError

    assert decide(p, {"field": "invoice_number", "value": "x", "confidence": 0.99}, {"validate": boom})["action"] == "review"


def test_uncalibrated():
    d = decide(None, {"field": "x", "value": "v", "confidence": 0.97})
    assert d["calibrated"] is False and d["action"] == "fill" and "Not calibrated" in d["reason"]


def test_pooled_fallback():
    p = calibrate(EXAMPLES)
    assert p["fields"]["vendor_name"]["own"] is False
    assert decide(p, {"field": "vendor_name", "value": "Acme", "confidence": 0.99})["source"] == "pooled"
    assert decide(p, {"field": "invoice_number", "value": "v", "confidence": 0.9})["source"] == "field"


def test_field_costs():
    p = calibrate(EXAMPLES, {"fields": {"total_amount": {"costError": 100}, "due_date": {"maxRisk": 0.01}}})
    assert decide(p, {"field": "total_amount", "value": "1", "confidence": 0.99})["threshold"] == 0.99
    assert decide(p, {"field": "due_date", "value": "1", "confidence": 0.99})["threshold"] == 0.99


def test_json_round_trip():
    p = calibrate(EXAMPLES, EXPECTED["options"])
    again = json.loads(json.dumps(p))
    item = {"field": "total_amount", "value": "9", "confidence": 0.93}
    assert decide(again, item) == decide(p, item)
    with pytest.raises(ValueError):
        validate_profile({"version": 99})


def test_decide_all():
    r = decide_all(calibrate(EXAMPLES), [{"field": "a", "value": "", "confidence": 1}, {"field": "a", "value": "x", "confidence": 0.1}])
    assert r["fill"] + r["review"] == 2


def test_bad_examples():
    with pytest.raises(ValueError):
        calibrate([{"confidence": 2, "correct": True}])
    with pytest.raises(TypeError):
        calibrate([{"confidence": 0.5, "correct": "yes"}])


def test_ece():
    assert ece([0.5, 0.5], [True, False], 1) == 0
    assert ece([0.99] * 4, [True, False, False, False], 1) > 0.7


def test_calibration_helps_heldout():
    r = evaluate(EXAMPLES, EXPECTED["options"], 5)
    assert r["fields"]["total_amount"]["eceCalibrated"] < r["fields"]["total_amount"]["eceRaw"]
    assert r["overall"]["eceCalibrated"] < r["overall"]["eceRaw"]


# The same spec file the npm package is tested against: identical numbers, both languages.
def test_spec_profile():
    assert calibrate(EXAMPLES, EXPECTED["options"]) == EXPECTED["profile"]


def test_spec_decisions():
    assert [decide(EXPECTED["profile"], p) for p in EXPECTED["probes"]] == EXPECTED["decisions"]


def test_spec_evaluation():
    assert evaluate(EXAMPLES, EXPECTED["options"], 5) == EXPECTED["evaluation"]
