"""Core maths. A line-by-line port of the npm package (js/src/jevapi.js).

Both implementations are checked against the same spec file
(spec/expected.json), so a profile fitted in one gives identical decisions in
the other.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Mapping, Optional

PROFILE_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "costError": 20,
    "costReview": 1,
    "reviewAccuracy": 1,
    "maxRisk": None,
    "minExamples": 30,
    "conservative": True,
    "z": 1.2816,
}


def _round6(x: float) -> float:
    # Match JavaScript's Math.round (half rounds up), not Python's banker's rounding.
    return math.floor(x * 1e6 + 0.5) / 1e6


def _pct(x: float) -> str:
    return f"{math.floor(x * 100 + 0.5)}%"


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _num(x: float) -> Any:
    # Keep integral values as ints so JSON matches JavaScript output (1, not 1.0).
    return int(x) if isinstance(x, float) and x.is_integer() else x


def wilson_lower(k: int, n: int, z: float = DEFAULTS["z"]) -> float:
    if n <= 0:
        return 0
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))
    return _clamp01((centre - margin) / denom)


def _field_name(field: Any) -> str:
    if field is None:
        return "*"
    if isinstance(field, bool):
        return "true" if field else "false"
    return str(field)


def _check_example(e: Any, i: int) -> None:
    if not isinstance(e, Mapping):
        raise TypeError(f"example {i}: not an object")
    c = e.get("confidence")
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c) or c < 0 or c > 1:
        raise ValueError(f"example {i}: confidence must be a number from 0 to 1")
    if not isinstance(e.get("correct"), bool):
        raise TypeError(f"example {i}: correct must be true or false")


# ---------- isotonic calibration (pool adjacent violators) ----------


def fit_isotonic(examples: Iterable[Mapping[str, Any]], z: float = DEFAULTS["z"]) -> list[dict]:
    pts = sorted(((e["confidence"], 1 if e["correct"] else 0) for e in examples), key=lambda t: t[0])
    if not pts:
        return []
    groups: list[dict] = []
    for x, y in pts:
        if groups and groups[-1]["lo"] == x:
            groups[-1]["k"] += y
            groups[-1]["n"] += 1
        else:
            groups.append({"lo": x, "hi": x, "k": y, "n": 1})
    stack: list[dict] = []
    for g in groups:
        stack.append(dict(g))
        while len(stack) > 1:
            b, a = stack[-1], stack[-2]
            # merge on ">=": equal-rate neighbours become one block
            if a["k"] * b["n"] >= b["k"] * a["n"]:
                stack[-2:] = [{"lo": a["lo"], "hi": b["hi"], "k": a["k"] + b["k"], "n": a["n"] + b["n"]}]
            else:
                break
    out = []
    p_max = 0.0
    l_max = 0.0
    for b in stack:
        p_max = max(p_max, (b["k"] + 1) / (b["n"] + 2))
        l_max = max(l_max, wilson_lower(b["k"], b["n"], z))
        out.append(
            {
                "lo": _num(_round6(b["lo"])),
                "hi": _num(_round6(b["hi"])),
                "k": b["k"],
                "n": b["n"],
                "p": _num(_round6(p_max)),
                "lower": _num(_round6(l_max)),
            }
        )
    return out


def apply_isotonic(blocks: list[dict], x: float, key: str = "p") -> Optional[float]:
    if not blocks:
        return None
    if x <= blocks[0]["hi"]:
        return blocks[0][key]
    for i in range(1, len(blocks)):
        prev, cur = blocks[i - 1], blocks[i]
        if x < cur["lo"]:
            span = cur["lo"] - prev["hi"]
            t = (x - prev["hi"]) / span if span > 0 else 1
            return _num(_round6(prev[key] + t * (cur[key] - prev[key])))
        if x <= cur["hi"]:
            return cur[key]
    return blocks[-1][key]


# ---------- metrics ----------


def ece(confidences: list[float], correct: list[bool], n_bins: int = 10) -> float:
    n = len(confidences)
    if n == 0:
        return 0
    pairs = sorted(((c, 1 if y else 0) for c, y in zip(confidences, correct)), key=lambda t: t[0])
    total = 0.0
    for b in range(n_bins):
        start = (b * n) // n_bins
        end = ((b + 1) * n) // n_bins
        if end <= start:
            continue
        sc = 0.0
        sy = 0
        for i in range(start, end):
            sc += pairs[i][0]
            sy += pairs[i][1]
        m = end - start
        total += (m / n) * abs(sy / m - sc / m)
    return _num(_round6(total))


# ---------- thresholds ----------


def cost_threshold(o: Mapping[str, Any]) -> float:
    """Auto-fill when p > reviewAccuracy - costReview / costError."""
    ce, cr, ra = o["costError"], o["costReview"], o["reviewAccuracy"]
    if not (ce > 0):
        raise ValueError("costError must be above 0")
    if not (cr >= 0):
        raise ValueError("costReview must be 0 or more")
    return _num(_round6(_clamp01(ra - cr / ce)))


def _field_threshold(o: Mapping[str, Any]) -> float:
    t = cost_threshold(o)
    if o.get("maxRisk") is not None:
        t = max(t, _num(_round6(1 - o["maxRisk"])))
    return t


def _resolve(*layers: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for layer in layers:
        if layer:
            out.update(layer)
    return out


# ---------- fitting ----------


def calibrate(examples: list[Mapping[str, Any]], options: Optional[Mapping[str, Any]] = None) -> dict:
    """Build a JSON-serialisable calibration profile from labelled examples.

    examples: [{"field": str, "confidence": 0..1, "correct": bool}]
    options: global defaults plus options["fields"] = {name: {costError, maxRisk, ...}}
    """
    if not isinstance(examples, list):
        raise TypeError("examples must be an array")
    for i, e in enumerate(examples):
        _check_example(e, i)
    options = dict(options or {})
    field_options = options.pop("fields", {}) or {}
    rest = options
    defaults = _resolve(rest)
    by_field: dict[str, list] = {}
    for e in examples:
        by_field.setdefault(_field_name(e.get("field")), []).append(e)
    fields: dict[str, dict] = {}
    for name in sorted(by_field):
        lst = by_field[name]
        fo = field_options.get(name) or {}
        min_ex = fo.get("minExamples", defaults["minExamples"])
        own = len(lst) >= min_ex
        fields[name] = {
            "n": len(lst),
            "accuracy": _num(_round6(sum(1 for e in lst if e["correct"]) / len(lst))),
            "own": own,
            "blocks": fit_isotonic(lst, defaults["z"]) if own else [],
            "options": dict(fo),
        }
    for name in sorted(field_options):
        if name not in fields:
            fields[name] = {"n": 0, "accuracy": None, "own": False, "blocks": [], "options": dict(field_options[name])}
    saved = {k: rest[k] for k in DEFAULTS if k in rest}
    return {
        "version": PROFILE_VERSION,
        "n": len(examples),
        "defaults": saved,
        "pooled": fit_isotonic(examples, defaults["z"]),
        "fields": fields,
    }


def validate_profile(profile: Any) -> dict:
    if not isinstance(profile, Mapping):
        raise TypeError("profile must be an object")
    if profile.get("version") != PROFILE_VERSION:
        raise ValueError(f"unsupported profile version {profile.get('version')}")
    if not isinstance(profile.get("pooled"), list) or not isinstance(profile.get("fields"), Mapping):
        raise TypeError("profile is missing pooled or fields")
    return profile  # type: ignore[return-value]


# ---------- deciding ----------


def _is_empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "") or (isinstance(v, (list, tuple)) and len(v) == 0)


def decide(profile: Optional[Mapping[str, Any]], item: Mapping[str, Any], overrides: Optional[Mapping[str, Any]] = None) -> dict:
    """Return {field, action: "fill"|"review", confidence, lower, threshold, calibrated, source, reason}.

    profile may be None: the raw confidence is used and calibrated is False.
    overrides may include "validate": a callable; returning False sends the field to review.
    """
    if profile is not None:
        validate_profile(profile)
    field = _field_name(item.get("field"))
    f = profile["fields"].get(field) if profile is not None else None
    opts = _resolve(profile.get("defaults") if profile else None, f.get("options") if f else None, overrides)
    threshold = _field_threshold(opts)
    base = {"field": field, "threshold": threshold, "calibrated": False, "confidence": None, "lower": None}

    if _is_empty(item.get("value")):
        return {**base, "action": "review", "reason": "No value was extracted."}
    raw = item.get("confidence")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0 or raw > 1:
        return {**base, "action": "review", "reason": "The extractor gave no usable confidence."}
    validate: Optional[Callable[[Any], bool]] = opts.get("validate")
    if callable(validate):
        try:
            ok = bool(validate(item.get("value")))
        except Exception:
            ok = False
        if not ok:
            return {**base, "action": "review", "reason": "The value failed this field's check."}

    blocks = None
    source = "raw"
    if f and f["own"] and f["blocks"]:
        blocks, source = f["blocks"], "field"
    elif profile is not None and profile["pooled"]:
        blocks, source = profile["pooled"], "pooled"
    p = raw
    lower = raw
    if blocks:
        p = apply_isotonic(blocks, raw, "p")
        lower = apply_isotonic(blocks, raw, "lower")
    used = lower if (opts["conservative"] and blocks) else p
    fill = used >= threshold and used > 0
    if source == "raw":
        reason = f"Not calibrated: using the extractor's own {_pct(raw)}, which may be overconfident."
    else:
        basis = (
            f"this field's {f['n']} examples"
            if source == "field"
            else f"all {profile['n']} examples (this field has too few of its own)"
        )
        reason = f"Stated {_pct(raw)}; measured on {basis}, values like this are right about {_pct(p)} of the time"
        reason += (f" (at least {_pct(lower)})" if opts["conservative"] else "") + "."
    reason += (
        f" Clears the {_pct(threshold)} bar."
        if fill
        else f" Below the {_pct(threshold)} bar, so a person should check it."
    )
    return {
        "field": field,
        "action": "fill" if fill else "review",
        "confidence": _num(_round6(p)),
        "lower": _num(_round6(lower)),
        "threshold": threshold,
        "calibrated": source != "raw",
        "source": source,
        "reason": reason,
    }


def decide_all(profile, items, overrides=None) -> dict:
    decisions = [decide(profile, it, overrides) for it in items]
    return {
        "decisions": decisions,
        "fill": sum(1 for d in decisions if d["action"] == "fill"),
        "review": sum(1 for d in decisions if d["action"] == "review"),
    }


# ---------- honest evaluation (k-fold) ----------


def evaluate(examples: list[Mapping[str, Any]], options: Optional[Mapping[str, Any]] = None, k: int = 5) -> dict:
    """Held-out estimate of what JevAPI would do on new documents.

    Fold assignment is index % k on the given order (shuffle first if sorted).
    """
    options = dict(options or {})
    for i, e in enumerate(examples):
        _check_example(e, i)
    if len(examples) < k:
        raise ValueError(f"need at least {k} examples for {k}-fold evaluation")
    decided = []
    for fold in range(k):
        train = [e for i, e in enumerate(examples) if i % k != fold]
        test = [e for i, e in enumerate(examples) if i % k == fold]
        prof = calibrate(train, options)
        for e in test:
            decided.append((e, decide(prof, {"field": e.get("field"), "value": "x", "confidence": e["confidence"]})))

    field_opts = options.get("fields") or {}
    top = {k2: v for k2, v in options.items() if k2 != "fields"}

    def summarise(rows):
        n = len(rows)
        auto_count = auto_errors = 0
        cost = manual = 0.0
        for e, d in rows:
            o = _resolve(top, field_opts.get(d["field"]))
            review_each = o["costReview"] + (1 - o["reviewAccuracy"]) * o["costError"]
            manual += review_each
            if d["action"] == "fill":
                auto_count += 1
                if not e["correct"]:
                    auto_errors += 1
                    cost += o["costError"]
            else:
                cost += review_each
        return {
            "n": n,
            "accuracy": _num(_round6(sum(1 for e, _ in rows if e["correct"]) / n)),
            "coverage": _num(_round6(auto_count / n)),
            "autoErrorRate": _num(_round6(auto_errors / auto_count)) if auto_count else 0,
            "autoErrors": auto_errors,
            "eceRaw": ece([e["confidence"] for e, _ in rows], [e["correct"] for e, _ in rows]),
            "eceCalibrated": ece([d["confidence"] for _, d in rows], [e["correct"] for e, _ in rows]),
            "savingsVsManual": _num(_round6(1 - cost / manual)) if manual > 0 else 0,
        }

    names = sorted({_field_name(e.get("field")) for e, _ in decided})
    return {
        "k": k,
        "overall": summarise(decided),
        "fields": {name: summarise([r for r in decided if _field_name(r[0].get("field")) == name]) for name in names},
    }
