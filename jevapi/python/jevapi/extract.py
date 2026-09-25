# Extraction by verification: instead of rules or an AI writer, Jev itself finds
# the value. For each target field we list the spans in the document that could
# be the value (amounts, dates, ids, lines), ask real Jev yes/no "is THIS the
# field?" for every candidate in one request, keep the candidate Jev is most
# sure of, and abstain to a human when no candidate clears the bar. No AI key,
# no per-type rules. Same rules as the JavaScript extract.js.

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

from .certainty import normalize
from .jev import ask_jev

# Keep in sync with receipt.py: codes a document can print next to amounts.
CUR = r"(?:AED|AUD|BDT|BRL|CAD|CHF|CNY|CZK|DKK|EUR|GBP|HKD|HUF|IDR|INR|JPY|KRW|KWD|LKR|MXN|MYR|NOK|NPR|NZD|PHP|PKR|PLN|QAR|SAR|SEK|SGD|THB|TRY|TWD|USD|VND|ZAR)"
SYM = r"(?:Rp\.?|Rs\.?|₹|\$|€|£|" + CUR + ")"
MONEY_TOKEN = re.compile(rf"(?:{SYM}\s?)?\d[\d.,]*(?:\s?{CUR})?")
DATE_TOKEN = re.compile(r"\b\d{1,2}\s?[./,-]\s?\d{1,2}\s?[./,-]\s?\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
PHONE_TOKEN = re.compile(r"\(?\d{3}\)?[\s-]\d{3}[\s-]\s?\d{4}")
SMALL_NUM = re.compile(r"\b\d{1,3}\b")
ID_TOKEN = re.compile(r"\b(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]{3,}\b|\b\d{4,}\b")
PAIR_VALUE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 %.()'+]{1,30}?\s*:\s{0,4}(.+?)\s*$")
TITLE_PHRASE = re.compile(r"\b[A-Z][A-Za-z&.'-]*(?: [A-Z][A-Za-z&.'-]*){1,3}\b")

MAX_CANDIDATES = 8
MIN_CONFIDENCE = 0.5

_KIND_AMOUNT = re.compile(r"amount|total|price|cash|change|due|tax|subtotal|balance|paid|cost|fee|tip")
_KIND_DATE = re.compile(r"date|deadline|when")
_KIND_ID = re.compile(r"(^|_)(no|number|num|id|code|nr|ref|reference|pages|qty|quantity|count)(_|$)")
_KIND_TEXT = re.compile(r"name|vendor|merchant|company|store|address|recipient|sender|(^|_)(to|from)(_|$)")


def field_kind(name: str = "") -> str:
    """Guess what kind of span a field wants from its name: amount, date, id, text or any."""
    n = str(name).lower()
    if _KIND_AMOUNT.search(n):
        return "amount"
    if _KIND_DATE.search(n):
        return "date"
    if _KIND_ID.search(n):
        return "id"
    if _KIND_TEXT.search(n):
        return "text"
    return "any"


_JUNK_TAIL = re.compile(r"[\s.,;:'‘’\"`|]+$")
_JUNK_HEAD = re.compile(r"^[^\w@à]+", re.UNICODE)


def _clean(s: str) -> str:
    return _JUNK_HEAD.sub("", _JUNK_TAIL.sub("", str(s))).strip()


def _matches(rx: re.Pattern, text: str) -> list[str]:
    return [v for v in (_clean(m.group(0)) for m in rx.finditer(text)) if v]


def _strip_code(v: str) -> str:
    """Amounts are candidates without a currency code: "CHF 54.50" is asked about as "54.50"."""
    return re.sub(r"\s?" + CUR + "$", "", re.sub("^" + CUR + r"\s?", "", v))


def _money_candidates(text: str) -> list[str]:
    out = []
    for v in (_strip_code(v) for v in _matches(MONEY_TOKEN, text)):
        digits = re.sub(r"\D", "", v)
        if re.search(r"[.,]", v) or re.search(r"[^\d\s.,]", v) or len(digits) >= 3:
            out.append(v)
    return out


def _line_candidates(text: str) -> list[str]:
    lines = [re.sub(r"\s+", " ", l).strip() for l in str(text).splitlines()]
    return [l for l in lines if l and len(l) <= 60 and re.search(r"[A-Za-z]", l)][:10]


_STOP = {"of", "the", "a", "an", "no", "number", "in", "including"}


def _label_words(name: str) -> list[str]:
    """Words of the field name used to spot its label in the text ("net_amount_due" -> net/amount/due)."""
    return [w for w in re.split(r"[_\s-]+", str(name or "").lower()) if w and w not in _STOP]


def candidate_spans(document: Any, field: Any) -> list[str]:
    """The spans of the document that could plausibly be this field's value.
    Candidates on a line that also carries the field's label come first; then document order."""
    text = str(document or "")
    f = {"name": field} if isinstance(field, str) else dict(field or {})
    kind = f.get("kind") or field_kind(f.get("name", ""))
    maxc = int(f.get("maxCandidates") or MAX_CANDIDATES)
    words = _label_words(f.get("label") or f.get("name", ""))
    lines = text.splitlines()

    def near_score(v: str) -> int:
        # Closeness to the label: 2 = on the label's own line, 1 = wrapped 1-3 lines below
        # or 1-3 lines above it ("Total\n14\n197.450"), 0 = elsewhere. The value may repeat; any line counts.
        if not words:
            return 0
        best = 0
        for i, line in enumerate(lines):
            if v not in line:
                continue
            if any(w in line.lower() for w in words):
                return 2
            for k in range(max(0, i - 3), min(len(lines) - 1, i + 3) + 1):
                if any(w in lines[k].lower() for w in words):
                    best = max(best, 1)
        return best

    if kind == "amount":
        cands = _money_candidates(text)
    elif kind == "date":
        cands = _matches(DATE_TOKEN, text)
    elif kind == "id":
        cands = _matches(ID_TOKEN, text) + _matches(PHONE_TOKEN, text)
        # A bare small number is only plausible on its label's own line ("Number of pages ... 3").
        cands += [n for n in _matches(SMALL_NUM, text) if near_score(n) == 2]
    elif kind == "text":
        cands = list(_line_candidates(text))
        for l in lines:
            m = PAIR_VALUE.match(re.sub(r"\s+", " ", l).strip())
            if m and len(m.group(1)) <= 60 and re.search(r"[A-Za-z]", m.group(1)):
                cands.append(m.group(1))
        cands += _matches(TITLE_PHRASE, text)
    else:
        cands = _money_candidates(text) + _matches(DATE_TOKEN, text) + _matches(ID_TOKEN, text) + _line_candidates(text)
    uniq = list(dict.fromkeys(cands))
    # Stable label-closeness boost: same-line first, then wrapped-near, then the rest in document order.
    return sorted(uniq, key=lambda v: -near_score(v))[:maxc]


def build_extract_questions(fields: Sequence[Any], document: Any):
    """One noul question per (field, candidate): "Does the document give X as the <field>?" """
    questions: dict[str, Any] = {}
    fmap = []
    for i, f0 in enumerate(fields):
        f = {"name": f0} if isinstance(f0, str) else dict(f0)
        what = str(f.get("label") or f.get("name") or "field").replace("_", " ")
        cands = candidate_spans(document, f)
        for j, c in enumerate(cands):
            v = str(c)
            questions[f"f{i}c{j}"] = {
                "type": "noul",
                "instructions": f'Does the document give "{v}" as the {what}?',
                "criteria": {
                    "true": f'The document states the {what} as "{v}" (formatting aside).',
                    "false": f"The document gives a different {what}, or does not give one.",
                },
            }
        fmap.append({"field": f, "candidates": cands})
    return {"questions": questions, "map": fmap}


def extract_by_verification(document: Any, fields: Sequence[Any], key: str,
                            min_confidence: float = MIN_CONFIDENCE, **opts) -> dict:
    """Ask real Jev to pick each field's value out of its candidate spans. One request for all fields."""
    flist = [{"name": f} if isinstance(f, str) else dict(f) for f in fields]
    built = build_extract_questions(flist, document)
    questions, fmap = built["questions"], built["map"]

    def blank(f, cands):
        item = {"field": f.get("name"), "value": None, "confidence": None,
                "jev": {"type": "extract", "candidates": len(cands), "top": None}}
        if f.get("label"):
            item["label"] = f["label"]
        return item

    if not questions:
        return {"items": [blank(m["field"], m["candidates"]) for m in fmap], "usage": None, "model": None}
    res = ask_jev(state=document, questions=questions, key=key, **opts)
    answers = res.get("answers") or {}
    items = []
    for i, m in enumerate(fmap):
        f, cands = m["field"], m["candidates"]
        best = None
        for j, c in enumerate(cands):
            a = answers.get(f"f{i}c{j}")
            if not a:
                continue
            # For a noul answer the raw probability IS "the document gives this": certainty
            # would score a confidently-wrong candidate as high as a confidently-right one.
            if a.get("type") == "noul" and a.get("noul") is not None:
                p = a["noul"]
            else:
                p = normalize(a).certainty
            try:
                p = float(p)
            except (TypeError, ValueError):
                continue
            if best is None or p > best[1]:
                best = (c, p)
        if best is None:
            items.append(blank(f, cands))
            continue
        keep = best[1] >= min_confidence
        item = {"field": f.get("name"), "value": best[0] if keep else None, "confidence": best[1],
                "jev": {"type": "extract", "candidates": len(cands), "top": best[0], "abstained": not keep}}
        if f.get("label"):
            item["label"] = f["label"]
        items.append(item)
    return {"items": items, "usage": res.get("usage"), "model": res.get("model")}
