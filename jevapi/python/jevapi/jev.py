"""Ask Jev (TypeSafe's decision model) to check extracted values.

This is glue code. The judgement comes from Jev itself; the conversion of Jev's
answers into one certainty number is jevscope's own certainty.py, shipped here
unchanged (a test keeps it byte-identical to reposcope/calibration/certainty.py).

Bring your own Jev key. Nothing here stores it. Zero dependencies (urllib).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Optional, Sequence

from .certainty import normalize

#: Where Jev can be reached, per the providers' own docs:
#:   typesafe   https://docs.typesafe.ai/api.md
#:   venice     https://venice.ai/lp/jev
#:   openrouter https://openrouter.ai/docs/guides/community/jev
JEV_PROVIDERS: dict[str, dict[str, str]] = {
    "typesafe": {"url": "https://api.typesafe.ai/v1/systemone", "model": "jev-latest"},
    "venice": {"url": "https://api.venice.ai/api/v1/decisions", "model": "jev-latest"},
    "openrouter": {"url": "https://openrouter.ai/api/alpha/decisions", "model": "~typesafe/jev-latest"},
}

NOT_STATED = "not_stated"
MAX_OPTIONS = 254  # Jev takes up to 255 options; one slot is kept for "not_stated".
MAX_DISCOVERED = 50

_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 .&/()'\-]{0,39}?)\s*(?::|#|\bNo\.?(?=\s)|\bNumber\b)\s*(.+?)\s*$")
# "Sub total 21,450" / "GST 18% 3,861": a short label, then an amount at the end of the line.
_AMOUNT = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 %.]{1,30}?)\s+((?:[^\w\s]{1,3}\s?)?\d[\d,]*(?:\.\d+)?)\s*$")


class JevError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _snake(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return s[:60] or "field"


def discover_fields(text: str, limit: int = MAX_DISCOVERED) -> list[dict]:
    """Find every "Label: value" style field in a document, with no field list given.

    Deliberately simple and dependency-free: it proposes candidates, and Jev then
    checks each one against the document. For free-form documents, use an AI
    extractor with no field list instead (the hosted /api/v1/extract does that).
    """
    out: list[dict] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        m = _LINE.match(line) or _AMOUNT.match(line)
        if not m:
            continue
        label, value = m.group(1).strip(), m.group(2).strip()
        if not value or len(value) > 200 or len(label) < 2:
            continue
        name = _snake(label)
        base, k = name, 2
        while name in seen:
            name = f"{base}_{k}"
            k += 1
        seen.add(name)
        out.append({"name": name, "label": label, "value": value})
        if len(out) >= limit:
            break
    return out


def _describe(field: Mapping[str, Any]) -> str:
    name = str(field["name"])
    desc = str(field.get("description") or "").strip()
    return f"{name} ({desc})" if desc else name


def build_questions(fields: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    """One Jev question per field.

    A field with ``options`` becomes a Choice (Jev picks the option, or
    "not_stated"). Any other field needs a candidate ``value`` (from your own
    extractor, a regex, an LLM...) and becomes a Noul: "does the document give
    this value?". Jev never writes text, so it checks values; it does not invent them.
    """
    questions: dict[str, dict] = {}
    for i, f in enumerate(fields):
        qid = f"f{i}"
        what = _describe(f)
        options = f.get("options")
        if options:
            opts = [str(o) for o in options]
            if len(opts) > MAX_OPTIONS:
                raise ValueError(f"{f['name']}: at most {MAX_OPTIONS} options")
            criteria = {o: f"The document gives {o} as the {what}." for o in opts}
            criteria[NOT_STATED] = f"The document does not give a {what}, or gives something not listed."
            questions[qid] = {"type": "choice", "instructions": f"Which {what} does the document give?", "criteria": criteria}
        else:
            value = f.get("value")
            if value is None or (isinstance(value, str) and not value.strip()):
                continue  # nothing to check; decide() will send it to a person
            v = json.dumps(value) if not isinstance(value, str) else value
            questions[qid] = {
                "type": "noul",
                "instructions": f'Does the document give "{v}" as the {what}?',
                "criteria": {
                    "true": f'The document states the {what} as "{v}" (formatting aside).',
                    "false": f"The document gives a different {what}, or does not give one.",
                },
            }
    return questions


def answers_to_items(fields: Sequence[Mapping[str, Any]], answers: Mapping[str, Any]) -> list[dict]:
    """Turn Jev answers into JevAPI items: {field, value, confidence, jev}.

    confidence is the probability that the value is right:
      noul    the yes-probability itself (the question was "is this value right?")
      choice  the probability Jev gave the option it picked
    """
    items = []
    for i, f in enumerate(fields):
        a = answers.get(f"f{i}")
        if a is None:
            items.append({"field": f["name"], "value": f.get("value"), "confidence": None, "jev": None})
            continue
        n = normalize(a)
        start = len(items)
        if n.answer_type == "noul":
            items.append({"field": f["name"], "value": f.get("value"), "confidence": float(a["noul"]),
                          "jev": {"type": "noul", "noul": float(a["noul"]), "certainty": n.certainty}})
        elif n.answer_type == "choice":
            picked = n.prediction
            probs = a.get("probabilities") or {}
            p = float(probs.get(picked, n.certainty))
            items.append({"field": f["name"], "value": None if picked == NOT_STATED else picked, "confidence": p,
                          "jev": {"type": "choice", "choice": picked, "confidence": n.reported_confidence,
                                  "certainty": n.certainty}})
        else:
            items.append({"field": f["name"], "value": n.prediction, "confidence": n.certainty,
                          "jev": {"type": "score", "certainty": n.certainty}})
        if f.get("label") and len(items) > start:
            items[-1] = {"field": items[-1]["field"], "label": f["label"], **{k: v for k, v in items[-1].items() if k != "field"}}
    return items


def ask_jev(state: Any, questions: Mapping[str, Any], key: str, provider: str = "typesafe",
            model: Optional[str] = None, timeout: float = 30.0,
            opener: Optional[Callable[..., Any]] = None) -> dict:
    """POST one Decisions request. Returns the parsed JSON ({answers, usage, ...})."""
    if provider not in JEV_PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(JEV_PROVIDERS)}")
    if not key:
        raise ValueError("a Jev key is required (bring your own)")
    cfg = JEV_PROVIDERS[provider]
    body = json.dumps({"model": model or cfg["model"], "state": state, "questions": dict(questions)}).encode()
    req = urllib.request.Request(cfg["url"], data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise JevError(f"Jev ({provider}) returned HTTP {e.code}", e.code) from None


def check_fields(document: str, fields: Optional[Sequence[Mapping[str, Any]]], key: str, provider: str = "typesafe",
                 model: Optional[str] = None, **kw: Any) -> list[dict]:
    """Ask Jev about every field in one request and return items for decide_all().

    Pass fields=None to find every field in the document first (discover_fields).
    """
    if fields is None:
        fields = discover_fields(document)
    questions = build_questions(fields)
    answers = ask_jev(document, questions, key, provider, model, **kw).get("answers", {}) if questions else {}
    return answers_to_items(fields, answers)
