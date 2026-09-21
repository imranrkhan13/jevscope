# RepoScope / Calibration Lab

Two pieces. **RepoScope** analyses a GitHub repository — parses it, builds a
real dependency graph, and uses Jev to decide which files are worth expensive
analysis. **Calibration Lab** is the part that matters: a selective-prediction
harness that measures whether a decision model's confidence score is worth
thresholding on, and tells you where to set the threshold.

```bash
pip install -e ".[dev]"
python -m reposcope.calibration.cli datasets/real.jsonl -o reports/report.html \
    --a nb --b logreg --title 'Calibration Lab — real public-repo study'
pytest -q                 # 75 tests
```

The hosted lab at [jevscope.vercel.app](https://jevscope.vercel.app) runs the
same study in the browser: click **Use the real dataset**.

To rebuild the real dataset from scratch, clone the eight public repos listed
in `datasets/LABELING.md` into one directory and run:

```bash
python -m reposcope.calibration.collect_real --corpus /path/to/checkouts
```

## Why this exists

The Decisions API guide says to evaluate Jev on your own examples before
choosing production thresholds, and then supplies no tooling to do it. That is
the gap. The entire value proposition of a System One model rests on
calibrated confidence, and calibration is not a property you can assert — it
is a measurement, on a labelled set, with error bars.

So: pick a real high-volume classification task (every file in a repository
gets a type), label ground truth by hand, run both Jev and an LLM over
identical inputs, and measure.

## What it measures, and why each number is there

**Calibration** — ECE, MCE, reliability diagram. Does a stated 0.9 mean 90%?

**Discrimination** — AURC, Brier, risk-coverage curve. Does the confidence
*ordering* separate right answers from wrong ones?

These are independent and you need both. A model that always answers 0.5 on a
balanced task is perfectly calibrated and worthless (there's a test asserting
the report doesn't praise it). A model whose confidences are uniformly inflated
by 0.2 has terrible ECE and perfect AURC — the ranking still works, you just
can't read the threshold off the stated number.

**Threshold selection** — given what an error costs versus what a human review
costs, the cost-minimising operating point. This is the question the docs leave
to the reader, and the answer moves a lot:

```
cost_error=50   →  t=0.96, covers 12% of files, 31% cheaper than manual
cost_error=8    →  t=0.82, covers 64% of files
```

## Four things done deliberately

**All three answer types on one axis.** `noul` carries no `confidence` field —
0.5 is maximal uncertainty and *both* tails are confident. `choice` and `score`
carry a scalar confidence. A rule like `answer >= 0.9` silently auto-accepts
every strong negative noul as if it were uncertain. `certainty.py` maps all
three to a comparable [0,1], and keeps `correctness_probability` separate,
because for a noul of 0.02 the prediction is "false" and the implied
probability of being right is 0.98. Conflating those two inverts half the
dataset — the most common way a calibration study gets silently wrong.

**Equal-mass bins.** Equal-width bins are the textbook default and they
mislead on real output, where confidence piles up near 1.0 and most bins end up
nearly empty. In the reliability diagram, bar width encodes bin population, so
a dramatic-looking point on three files reads as three files.

**Basic, not percentile, bootstrap.** ECE is a mean of absolute deviations and
therefore biased upward — resampling adds noise, and noise can only increase
|confidence − accuracy|. The percentile interval puts that bias inside the
interval and produces a CI that doesn't contain its own point estimate. The
reverse-percentile interval cancels it. This showed up during development as
`0.0380 [0.0392, 0.1026]`; the fix is in `metrics.py` with the reasoning.

**Paired comparison with McNemar's test.** Both providers see identical input
for identical items, so differences aren't confounded. Below 25 discordant
pairs it uses the exact binomial rather than the chi-square approximation, and
below 10 it refuses to name a winner at all. "Jev 84%, LLM 87%" on 200 items
is usually a coin flip, and the report says so.

## On the real dataset

`datasets/real.jsonl` is measured, not simulated: all 181 Python files in
three public repos (requests, httpx, starlette), labelled by hand, classified
by two scikit-learn models trained only on five *other* public repos (flask,
jinja, black, pytest, fastapi). Both models land at 69-70% accuracy and
McNemar's test cannot separate them (p=0.815) - but their confidence means
opposite things: the Naive Bayes says 0.98 on average and is right 69% of the
time (ECE 0.299), while the logistic regression says 0.76 and is right 70% of
the time (ECE 0.103). A threshold on the first number over-automates; a
threshold on the second works. That gap, invisible in accuracy, is the whole
point of the harness. Repos, commits, licences, the labelling rubric and the
method live in `datasets/LABELING.md`; the collector is
`reposcope/calibration/collect_real.py`.

No API model was queried for this dataset, so it says nothing about Jev or
any LLM - the providers are named as exactly what ran.

## On the demo dataset

`datasets/demo.jsonl` is **simulated** and cannot be published as a result. It
exists so the harness can be verified against a known defect: the synthetic
`jev` provider is calibrated by construction, and the synthetic `llm` provider
is overconfident by 12 points. The harness recovers exactly that —
ECE 0.048 versus 0.146.

The first version of that generator was wrong: it built a distribution and read
confidence off the argmax, which produces an *under*confident provider, not a
calibrated one. The harness caught it (ECE 0.29 on data meant to score near
zero). Calibration is generated by drawing the stated confidence first and
*then* deciding correctness as a coin weighted by it.

Real numbers require real labels. `gold_labels` in the schema is the table for
them; the honest minimum is 150–300 files across 5–8 repositories, labelled by
someone who knows the codebases.

## Layout

```
reposcope/
  ingest/       clone, walk, exclusion rules, language detection
  calibration/  certainty  metrics  risk_coverage  compare  dataset  report  cli
  persistence/  full schema — runs, files, symbols, dep_edges, decisions, claims
  graph/        dependency graph (in progress)
tests/          72 tests
```

The dependency graph is the source of truth for every relationship claim, and
`dep_edges.reliability` separates AST-exact edges from inferred ones so
generated prose can only cite the exact ones. No model output is ever written
to the graph.

## Known limits

- Thresholds are fitted on the evaluation sample and are optimistic. Hold out a
  split before shipping one.
- ECE is bin-count sensitive. The report states its binning; compare ECEs only
  across identical settings.
- The graph handles Python and TypeScript. Other languages are inventoried but
  not parsed, and the coverage numbers say so rather than hiding it.
