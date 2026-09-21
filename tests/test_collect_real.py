"""Integrity checks for the real public-repo dataset.

These assert the dataset the demo loads is the dataset described in
datasets/LABELING.md - real files, valid schema, no simulated rows.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from reposcope.calibration import dataset
from reposcope.calibration.collect_real import CLASSES, NOUL_QUESTION, FILE_TYPE_QUESTION

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "datasets" / "real.jsonl"
LABELS = ROOT / "datasets" / "real_labels.csv"


def test_real_dataset_loads_and_pairs():
    records = dataset.load(REAL)
    assert len(records) == 543  # 181 files x (2 choice providers + 1 noul)
    keys = {r.key for r in records}
    assert len(keys) == 181
    pairs = dataset.pair_providers(records, "nb", "logreg", FILE_TYPE_QUESTION)
    assert len(pairs) == 181


def test_real_dataset_schema_and_labels():
    with LABELS.open() as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 181
    assert {r["repo"] for r in rows} == {"requests", "httpx", "starlette"}
    assert {r["label"] for r in rows} <= set(CLASSES)

    for line in REAL.read_text().splitlines():
        raw = json.loads(line)
        assert raw["question"] in {FILE_TYPE_QUESTION, NOUL_QUESTION}
        assert raw["provider"] in {"nb", "logreg"}
        assert raw["gold"] in CLASSES or raw["gold"] in {"true", "false"}
        answer = raw["answer"]
        if answer["type"] == "choice":
            assert set(answer["probabilities"]) == set(CLASSES)
            assert abs(sum(answer["probabilities"].values()) - 1.0) < 0.01
            assert answer["choice"] in answer["probabilities"]
        else:
            assert answer["type"] == "noul"
            assert 0.0 < answer["noul"] < 1.0
        # Real local models: no API cost, real measured latency.
        assert raw["cost_usd"] == 0.0
        assert raw["latency_ms"] > 0


def test_no_simulated_providers_in_real_dataset():
    records = dataset.load(REAL)
    # The simulated demo providers must never leak into the real set.
    assert {r.provider for r in records} == {"nb", "logreg"}
    assert all("jev" not in r.model for r in records)
