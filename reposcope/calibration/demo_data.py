"""Generate a DEMONSTRATION dataset so the harness runs before you have labels.

This is simulated data with a deliberately planted flaw: the synthetic "jev"
provider is well calibrated, the synthetic "llm" provider is overconfident by
roughly 12 points. That is there so you can confirm the harness detects a known
defect — it is a test of the instrument, not a measurement of any real model.

Nothing generated here may be published as a result. Replace it with real
output from `python -m reposcope.calibration.collect` once you have gold labels.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

FILE_TYPES = ["entry_point", "model", "route", "service", "test", "config", "utility", "dead_code"]

PATH_HINTS = {
    "route": ["api/routes/{}.py", "app/api/{}.ts"],
    "model": ["models/{}.py", "db/models/{}.py"],
    "service": ["services/{}.py", "lib/services/{}.ts"],
    "test": ["tests/test_{}.py", "__tests__/{}.spec.ts"],
    "config": ["config/{}.py", "{}.config.ts"],
    "utility": ["utils/{}.py", "lib/{}.ts"],
    "entry_point": ["main.py", "manage.py", "src/index.ts"],
    "dead_code": ["legacy/{}.py", "old/{}.py"],
}

WORDS = ["user", "order", "auth", "billing", "search", "cache", "queue", "report", "sync", "nav"]


def _answer(rng: random.Random, gold: str, inflate: float) -> dict:
    """A choice answer that is calibrated by construction, then spoiled by
    `inflate`.

    The order matters. Draw the stated confidence first, then decide
    correctness as a coin weighted by (stated - inflate). At inflate=0 a stated
    0.9 is right 90% of the time by definition, which is exactly what a
    calibration harness should score near zero. Generating a distribution first
    and reading confidence off it does NOT produce calibration — that was the
    bug in the first version of this file, and the harness caught it.
    """
    stated = min(0.985, max(0.30, rng.betavariate(8.0, 1.5)))
    correct = rng.random() < max(0.02, min(1.0, stated - inflate))

    gold_idx = FILE_TYPES.index(gold)
    if correct:
        pick = gold_idx
    else:
        pick = rng.randrange(len(FILE_TYPES) - 1)
        pick += pick >= gold_idx

    # Distribute the remaining mass over the other options, weighted randomly.
    others = [i for i in range(len(FILE_TYPES)) if i != pick]
    weights = [rng.gammavariate(1.0, 1.0) for _ in others]
    scale = (1.0 - stated) / sum(weights)

    probs = [0.0] * len(FILE_TYPES)
    probs[pick] = stated
    for i, w in zip(others, weights):
        probs[i] = w * scale

    return {
        "type": "choice",
        "choice": FILE_TYPES[pick],
        "probabilities": {FILE_TYPES[i]: round(probs[i], 4) for i in range(len(FILE_TYPES))},
        "confidence": round(stated, 4),
    }


def _noul(rng: random.Random, gold_true: bool, inflate: float) -> dict:
    """Same construction for the type with no confidence field."""
    stated = min(0.985, max(0.55, rng.betavariate(7.0, 1.5)))
    correct = rng.random() < max(0.02, min(1.0, stated - inflate))
    says_true = gold_true if correct else not gold_true
    return {"type": "noul", "noul": round(stated if says_true else 1.0 - stated, 4)}


def generate(out: Path, n_files: int = 400, seed: int = 7) -> Path:
    rng = random.Random(seed)
    lines: list[str] = []

    for i in range(n_files):
        gold = rng.choice(FILE_TYPES)
        template = rng.choice(PATH_HINTS[gold])
        key = template.format(f"{rng.choice(WORDS)}_{i}") if "{}" in template else f"{i}/{template}"

        # Calibrated provider.
        answer = _answer(rng, gold, inflate=0.0)
        lines.append(
            json.dumps(
                {
                    "key": key, "question": "file_type", "provider": "jev",
                    "model": "jev-latest", "gold": gold, "answer": answer,
                    "latency_ms": round(rng.gauss(38, 9), 1),
                    "cost_usd": round(rng.gauss(3.1e-5, 4e-6), 9),
                }
            )
        )

        # Overconfident provider — planted so the report should flag it.
        answer = _answer(rng, gold, inflate=0.12)
        lines.append(
            json.dumps(
                {
                    "key": key, "question": "file_type", "provider": "llm",
                    "model": "demo-llm", "gold": gold, "answer": answer,
                    "latency_ms": round(rng.gauss(1850, 520), 1),
                    "cost_usd": round(rng.gauss(2.4e-3, 3e-4), 9),
                }
            )
        )

        # A noul question, to exercise the type that has no confidence field.
        worth = gold in {"entry_point", "route", "service", "model"}
        lines.append(
            json.dumps(
                {
                    "key": key, "question": "worth_deep_analysis", "provider": "jev",
                    "model": "jev-latest", "gold": "true" if worth else "false",
                    "answer": _noul(rng, worth, inflate=0.0),
                    "latency_ms": round(rng.gauss(31, 7), 1),
                    "cost_usd": round(rng.gauss(2.2e-5, 3e-6), 9),
                }
            )
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "datasets/demo.jsonl")
    print(f"wrote {generate(target)}  (SIMULATED — not publishable as a result)")
