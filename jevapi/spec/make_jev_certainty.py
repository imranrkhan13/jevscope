"""Regenerate jev_certainty.json from the ORIGINAL reposcope/calibration/certainty.py.
Run from the repo root: python jevapi/spec/make_jev_certainty.py"""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from reposcope.calibration.certainty import normalize, correctness_probability  # noqa: E402

answers = [
    {"type": "noul", "noul": 0.99}, {"type": "noul", "noul": 0.93}, {"type": "noul", "noul": 0.5},
    {"type": "noul", "noul": 0.05}, {"type": "noul", "noul": 0.0}, {"type": "noul", "noul": 1.0},
    {"type": "choice", "choice": "returns", "confidence": 1.0, "probabilities": {"shipping": 0.0, "returns": 1.0, "billing": 0.0}},
    {"type": "choice", "choice": "returns", "confidence": 0.42, "probabilities": {"returns": 0.55, "shipping": 0.3, "billing": 0.15}},
    {"type": "choice", "choice": "a", "probabilities": {"a": 0.6, "b": 0.4}},
    {"type": "choice", "choice": "a"},
    {"type": "score", "score": 1.43, "confidence": 0.35, "legend": {"0": "x", "1": "y", "2": "z"}, "probabilities": {"0": 0.0, "1": 0.57, "2": 0.43}},
    {"type": "score", "score": 2.5, "probabilities": {"0": 0.0, "1": 0.0, "2": 0.5, "3": 0.5}},
    {"type": "score", "score": 1.86, "confidence": 0.89, "probabilities": {"0": 0.0, "1": 0.14, "2": 0.86}},
]
out = []
for a in answers:
    n = normalize(a)
    out.append({"answer": a, "expected": {
        "answerType": n.answer_type, "prediction": n.prediction, "certainty": n.certainty,
        "reportedConfidence": n.reported_confidence, "distributionCertainty": n.distribution_certainty,
        "correctness": correctness_probability(n)}})
p = pathlib.Path(__file__).with_name("jev_certainty.json")
p.write_text(json.dumps({"source": "reposcope/calibration/certainty.py", "cases": out}, indent=1) + "\n")
print(f"wrote {len(out)} cases to {p}")
