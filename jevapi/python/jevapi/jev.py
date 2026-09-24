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
from .resume import is_resume, resume_fields

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


# Vendor and currency are asked about on every invoice-like document, even when
# no line labels them: the vendor is often just the letterhead, and the currency
# is often only a symbol. Jev picks from the candidates (or says not_stated).
# Same rules as the JS coreFields.
_INVOICE_HINT = re.compile(r"\b([il1]nvo[il1]ce|receipt|bill|amount due|t[o0]tal|payable|remit)\b", re.I)
_VENDOR_NAME = re.compile(r"^(vendor|vendor_name|seller|supplier|merchant|sold_by|issued_by)$")
_VENDOR_LABEL = re.compile(r"^\s*(vendor|seller|supplier|merchant|payee|from|issued by|sold by|remit(?:\s+payment)?\s+to|remit address|send payment to|pay to|checks? (?:are )?payable to|make checks payable to)\b\s*[:\-]?\s*(.*)$", re.I)
_COMPANY = re.compile(r"\b(inc|llc|l\.l\.c|ltd|pvt|limited|corp|corporation|co|company|gmbh|plc|llp|group|media|communications|broadcast(?:ing)?|traders|studio|logistics|supplies|services|enterprises|industries|solutions|tv)\b\.?", re.I)
_NOT_VENDOR = re.compile(r"^(tax\s+)?(invoice|receipt|bill|statement|page|date|due|total|sub\s*total|amount|thank|description|qty|quantity|terms|bill\s*to|ship\s*to|attn|attention|phone|ph|fax|email|main|billing|remit|mail to|send payment|p\.?\s*o\.?\s*box)\b", re.I)
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
CURRENCY_HINTS: dict[str, str] = {
    "INR": "Indian rupees (₹, Rs or INR)",
    "USD": "US dollars ($, US$ or USD)",
    "EUR": "euros (€ or EUR)",
    "GBP": "British pounds (£ or GBP)",
    "AED": "UAE dirhams (AED)",
    "SGD": "Singapore dollars (S$ or SGD)",
    "AUD": "Australian dollars (A$ or AUD)",
    "CAD": "Canadian dollars (C$ or CAD)",
    "JPY": "Japanese yen (¥ or JPY)",
    "CNY": "Chinese yuan (CN¥, RMB or CNY)",
}
MAX_VENDOR_OPTIONS = 8


def option_key(option: str, j: int) -> str:
    """Jev option keys stay short and plain; other option text gets a key like "o3"."""
    return option if _SAFE_KEY.match(option) and option != NOT_STATED else f"o{j}"


def vendor_candidates(text: str, limit: int = MAX_VENDOR_OPTIONS) -> list[str]:
    """Candidate vendor names: labelled "From / Remit to" values, the letterhead lines, and company-looking lines."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in str(text or "").splitlines()]
    out: list[str] = []
    seen: set[str] = set()

    def add(v: Optional[str]) -> None:
        v = re.sub(r"[:\-\s]+$", "", str(v or "")).strip()
        if len(v) < 2 or len(v) > 60 or not re.search(r"[A-Za-z]{2}", v) or _NOT_VENDOR.match(v):
            return
        if sum(c.isdigit() for c in v) > len(v) / 3:
            return
        if v.lower() in seen or len(out) >= limit:
            return
        seen.add(v.lower())
        out.append(v)

    for i, l in enumerate(lines):
        m = _VENDOR_LABEL.match(l)
        if not m:
            continue
        if m.group(2):
            add(m.group(2))
        else:
            add(next((x for x in lines[i + 1:] if x), None))
    for l in [l for l in lines if l][:3]:
        add(l)
    for l in lines:
        if _COMPANY.search(l) and not _VENDOR_LABEL.match(l):
            add(l)
    return out


def core_fields(text: str, found: Sequence[Mapping[str, Any]] = ()) -> list[dict]:
    """Vendor and currency questions for invoice-like text, unless a labelled field already covers them."""
    t = str(text or "")
    if not _INVOICE_HINT.search(t):
        return []
    names = [str(f["name"]) for f in found]
    out: list[dict] = []
    if not any(_VENDOR_NAME.match(n) for n in names):
        options = vendor_candidates(t)
        if options:
            out.append({"name": "vendor", "label": "Vendor",
                        "description": "the business that issued this document and gets paid, not the customer or bill-to party",
                        "options": options, "core": True})
    if not any("currency" in n for n in names):
        codes = [c for c in CURRENCY_HINTS if re.search(rf"\b{c}\b", t)]
        sym = [c for s, c in (("₹", "INR"), ("Rs", "INR"), ("€", "EUR"), ("£", "GBP"), ("$", "USD"), ("¥", "JPY")) if s in t]
        options = list(dict.fromkeys(codes + sym + list(CURRENCY_HINTS)))
        out.append({"name": "currency", "label": "Currency", "description": "the currency the amounts are in",
                    "options": options, "hints": dict(CURRENCY_HINTS), "core": True})
    return out


def discover_fields(text: str, limit: int = MAX_DISCOVERED) -> list[dict]:
    """Find every "Label: value" style field in a document, with no field list given.

    A resume is read section by section instead (resume.resume_fields). On
    invoice-like text it also always asks about the vendor and the currency
    (core_fields), since those are often unlabelled. Deliberately simple and
    dependency-free: it proposes candidates, and Jev then checks each one against
    the document. For free-form documents, use an AI extractor with no field list
    instead (the hosted /api/v1/extract does that).
    """
    if is_resume(text):
        return resume_fields(text)
    found: list[dict] = []
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
        found.append({"name": name, "label": label, "value": value})
    core = core_fields(text, found)
    return (core + found)[: max(limit, len(core))]


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
            hints = f.get("hints") or {}
            criteria = {option_key(o, j): (f"The {f['name']} is {o}: {hints[o]}." if o in hints
                                           else f'The document gives "{o}" as the {what}.') for j, o in enumerate(opts)}
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
            opts = [str(o) for o in (f.get("options") or [])]
            picked = next((o for j, o in enumerate(opts) if option_key(o, j) == n.prediction), n.prediction)
            probs = a.get("probabilities") or {}
            p = float(probs.get(n.prediction, n.certainty))
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
