"""Run a calibration study from the command line.

    python -m reposcope.calibration.cli datasets/sample.jsonl -o report.html
    python -m reposcope.calibration.cli data.jsonl --cost-error 200 --cost-review 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reposcope.calibration import dataset, report
from reposcope.calibration.risk_coverage import CostModel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibration-lab", description=__doc__)
    parser.add_argument("dataset", type=Path, help="JSONL of labelled decisions")
    parser.add_argument("-o", "--out", type=Path, default=Path("calibration_report.html"))
    parser.add_argument("--cost-error", type=float, default=50.0)
    parser.add_argument("--cost-review", type=float, default=1.0)
    parser.add_argument("--review-accuracy", type=float, default=1.0)
    parser.add_argument("--a", default="jev", help="first provider (default: jev)")
    parser.add_argument("--b", default="llm", help="second provider (default: llm)")
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--title", default="Jev Calibration Lab")
    args = parser.parse_args(argv)

    if not args.dataset.exists():
        print(f"No such dataset: {args.dataset}", file=sys.stderr)
        return 2

    study = dataset.run(
        args.dataset,
        cost=CostModel(
            cost_error=args.cost_error,
            cost_review=args.cost_review,
            review_accuracy=args.review_accuracy,
        ),
        a_provider=args.a,
        b_provider=args.b,
        resamples=args.resamples,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report.render(study, title=args.title))

    for warning in study.warnings:
        print(f"  warning: {warning}", file=sys.stderr)

    print(f"\n{args.dataset}  →  {args.out}\n")
    for s in study.per_question:
        cal = s.calibration
        print(f"  {s.question:<24} {s.provider:<6} n={s.n:<5}")
        print(f"    accuracy  {cal.accuracy}")
        print(f"    ECE       {cal.ece}")
        print(f"    AURC      {s.aurc:.4f}   Brier {cal.brier.point:.4f}")
        print(
            f"    threshold {s.choice.threshold:.2f}  "
            f"covers {s.choice.point.coverage * 100:.0f}%  "
            f"risk {s.choice.point.selective_risk * 100:.1f}%  "
            f"saves {s.choice.savings_vs_manual * 100:.0f}% vs manual\n"
        )
    for question, mc, a, b in study.comparisons:
        print(f"  {question}: {mc.verdict(a.name, b.name)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
