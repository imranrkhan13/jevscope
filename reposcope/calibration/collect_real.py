"""Build a REAL evaluation dataset from public repositories.

What this does, end to end:

  1. Walks the five TRAIN repositories with RepoScope's own ingest
     (reposcope.ingest.walk) and assigns training labels with the documented
     path rules below. Training labels are deliberately cheap; only the
     measured labels are hand-reviewed.
  2. Trains two scikit-learn classifiers - a multinomial Naive Bayes and a
     logistic regression over TF-IDF - on the training files only.
  3. Reads the hand-reviewed labels for the three HELD-OUT repositories from
     datasets/real_labels.csv and runs both classifiers over every one of
     those files, recording real per-file prediction latency.
  4. Writes datasets/real.jsonl in the exact schema the calibration harness
     consumes: one record per (file, question, provider).

Nothing here is simulated. The measured files are real source files from
public, permissively licensed repositories; the labels were reviewed by hand;
the predictions come from two real, trained models. The repos, commits and
licences are listed in datasets/LABELING.md.

No API model was queried: neither Jev nor any LLM API appears in this dataset.
Provider names say exactly what ran.

    python -m reposcope.calibration.collect_real \
        --corpus /path/to/checkouts --labels datasets/real_labels.csv \
        -o datasets/real.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

from reposcope.ingest.walk import walk

CLASSES = ["entry_point", "model", "service", "test", "config", "utility", "legacy"]

#: The question every provider answers for every measured file.
FILE_TYPE_QUESTION = "file_type"
#: A noul question answered by the NB provider only, mirroring the demo set:
#: does this file deserve expensive analysis? Gold is derived from the
#: hand-reviewed label by a stated rule, not from a second judgement.
NOUL_QUESTION = "worth_deep_analysis"
NOUL_TRUE_LABELS = {"model", "service"}

TRAIN_REPOS = ["flask", "jinja", "black", "pytest", "fastapi"]
TEST_REPOS = ["requests", "httpx", "starlette"]

#: Roughly even training mix: at most this share of one repo's training files
#: may come from the test class, and each repo contributes at most `cap` files.
TRAIN_CAPS = {"flask": 55, "jinja": 45, "black": 60, "pytest": 70, "fastapi": 90}
TRAIN_TEST_SHARE = 0.45

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def rule_label(rel_path: str) -> str:
    """Path-only training label. Documented in datasets/LABELING.md; the
    measured (held-out) labels in real_labels.csv were each reviewed by hand,
    so noise here hurts only the models, never the measurement."""
    name = rel_path.rsplit("/", 1)[-1].lower()
    low = rel_path.lower()
    segments = set(low.split("/"))
    if (
        segments & {"tests", "test", "testing", "benchmarks", "benchmark"}
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    ):
        return "test"
    if name in {"__init__.py", "__main__.py", "api.py", "_api.py", "main.py", "_main.py",
                "cli.py", "__cli__.py", "manage.py"}:
        return "entry_point"
    if "compat" in name or name == "packages.py":
        return "legacy"
    if name in {"setup.py", "conf.py", "__version__.py", "config.py", "_config.py",
                "certs.py", "settings.py"}:
        return "config"
    if "util" in name or "helper" in name or "hook" in name:
        return "utility"
    if any(k in name for k in ("model", "structure", "types", "exception", "status",
                               "nodes", "schema", "fields", "params")):
        return "model"
    return "service"


def file_text(abs_path: Path, rel_path: str) -> str:
    """Feature text: path tokens weighted 3x, then the first ~120 lines."""
    try:
        head = abs_path.read_text(encoding="utf-8", errors="ignore")[:9000]
        head = "\n".join(head.splitlines()[:120])
    except OSError:
        head = ""
    path_tokens = " ".join(_TOKEN_RE.findall(rel_path.replace("/", " ").replace(".", " ").replace("_", " ")))
    return f"{path_tokens} {path_tokens} {path_tokens} {head}"


@dataclass
class Sample:
    repo: str
    rel_path: str
    abs_path: Path
    label: str


def collect_train(corpus: Path, seed: int = 11) -> list[Sample]:
    rng = random.Random(seed)
    samples: list[Sample] = []
    for repo in TRAIN_REPOS:
        root = corpus / repo
        files = [
            f for f in walk(root)
            if f.included and f.language == "python" and (f.loc or 0) > 0
        ]
        labelled = [(f, rule_label(f.rel_path)) for f in files]
        tests = [x for x in labelled if x[1] == "test"]
        rest = [x for x in labelled if x[1] != "test"]
        rng.shuffle(tests)
        rng.shuffle(rest)
        cap = TRAIN_CAPS[repo]
        n_test = min(len(tests), int(cap * TRAIN_TEST_SHARE))
        n_rest = min(len(rest), cap - n_test)
        picked = rest[:n_rest] + tests[:n_test]
        samples.extend(
            Sample(repo=repo, rel_path=f.rel_path, abs_path=f.abs_path, label=label)
            for f, label in picked
        )
    return samples


def load_gold(labels_csv: Path) -> list[Sample]:
    out: list[Sample] = []
    with labels_csv.open() as handle:
        for row in csv.DictReader(handle):
            label = row["label"].strip()
            if label not in CLASSES:
                raise ValueError(f"{labels_csv}: unknown label {label!r} for {row['repo']}:{row['path']}")
            out.append(
                Sample(
                    repo=row["repo"].strip(),
                    rel_path=row["path"].strip(),
                    abs_path=Path(),  # filled in once we know the corpus dir
                    label=label,
                )
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collect-real", description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True,
                        help="Directory holding the eight public-repo checkouts")
    parser.add_argument("--labels", type=Path, default=Path("datasets/real_labels.csv"))
    parser.add_argument("-o", "--out", type=Path, default=Path("datasets/real.jsonl"))
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args(argv)

    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.naive_bayes import MultinomialNB

    gold = load_gold(args.labels)
    for sample in gold:
        sample.abs_path = args.corpus / sample.repo / sample.rel_path
        if not sample.abs_path.is_file():
            raise SystemExit(f"labelled file missing from corpus: {sample.repo}/{sample.rel_path}")
    bad_repos = {s.repo for s in gold} - set(TEST_REPOS)
    if bad_repos:
        raise SystemExit(f"labels name non-held-out repos: {sorted(bad_repos)}")

    train = collect_train(args.corpus, seed=args.seed)
    print(f"train: {len(train)} files from {len(TRAIN_REPOS)} repos "
          f"({sum(1 for s in train if s.label == 'test')} test-class)")

    x_train = [file_text(s.abs_path, s.rel_path) for s in train]
    y_train = [s.label for s in train]

    nb_vec = CountVectorizer(token_pattern=r"[A-Za-z_][A-Za-z0-9_]+", min_df=2)
    nb = MultinomialNB(alpha=0.3)
    nb.fit(nb_vec.fit_transform(x_train), y_train)

    lr_vec = TfidfVectorizer(token_pattern=r"[A-Za-z_][A-Za-z0-9_]+", min_df=2,
                             ngram_range=(1, 2), sublinear_tf=True)
    lr = LogisticRegression(max_iter=3000, C=6.0, random_state=0)
    lr.fit(lr_vec.fit_transform(x_train), y_train)

    import sklearn
    records: list[str] = []
    stats = {"nb": 0, "logreg": 0}
    for sample in gold:
        key = f"{sample.repo}:{sample.rel_path}"
        text = file_text(sample.abs_path, sample.rel_path)

        start = time.perf_counter()
        nb_probs = nb.predict_proba(nb_vec.transform([text]))[0]
        nb_ms = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        lr_probs = lr.predict_proba(lr_vec.transform([text]))[0]
        lr_ms = (time.perf_counter() - start) * 1000

        for provider, classes, probs, ms in (
            ("nb", nb.classes_, nb_probs, nb_ms),
            ("logreg", lr.classes_, lr_probs, lr_ms),
        ):
            dist = {c: round(float(p), 4) for c, p in zip(classes, probs)}
            pick = max(dist, key=dist.get)
            stats[provider] += pick == sample.label
            records.append(json.dumps({
                "key": key, "question": FILE_TYPE_QUESTION, "provider": provider,
                "model": f"sklearn-{provider}-{sklearn.__version__}",
                "gold": sample.label,
                "answer": {"type": "choice", "choice": pick,
                           "probabilities": dist, "confidence": dist[pick]},
                "latency_ms": round(ms, 2), "cost_usd": 0.0,
            }))

        # The noul question: NB's posterior mass on the labels the stated rule
        # calls worth deep analysis.
        worth = sample.label in NOUL_TRUE_LABELS
        p_worth = float(sum(p for c, p in zip(nb.classes_, nb_probs) if c in NOUL_TRUE_LABELS))
        records.append(json.dumps({
            "key": key, "question": NOUL_QUESTION, "provider": "nb",
            "model": f"sklearn-nb-{sklearn.__version__}",
            "gold": "true" if worth else "false",
            "answer": {"type": "noul", "noul": round(min(0.999, max(0.001, p_worth)), 4)},
            "latency_ms": round(nb_ms, 2), "cost_usd": 0.0,
        }))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(records) + "\n")

    n = len(gold)
    print(f"held out: {n} hand-labelled files from {len(TEST_REPOS)} repos")
    for provider, hits in stats.items():
        print(f"  {provider}: accuracy {hits}/{n} = {hits / n:.3f}")
    print(f"wrote {args.out} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
