# Rule-based form reader: no AI key needed. Forms are labelled blanks: a label
# ending in a colon with its value after it ("TO: Jane", "FAX NUMBER: 555..."),
# often several label/value pairs on one line. This reader proposes one field
# per filled blank; blanks left empty stay for a human to fill. Wrapped note
# and disclaimer paragraphs are not fields and are skipped.
# Same rules as the JavaScript form.js.

from __future__ import annotations

import re
from typing import Optional

MAX_FORM_FIELDS = 50

# A label: letters and a few connectors, no digits, 2-40 chars, ends in a colon.
LABEL = re.compile(r"^([A-Za-z][A-Za-z '/&().#-]{1,38}?):\s*(.*)$")
HAS_LETTER = re.compile(r"[A-Za-z]{2}")
# Invoices, receipts, and statements have their own readers; a text with these
# blocks is not treated as a form. "receipt" alone does not block: fax cover
# sheets say "receipt of this transmission".
FORM_INVOICE_BLOCK = re.compile(r"\b([il1]nvo[il1]ce|amount due|due date|bill to|remit|sub\s?total|t[o0]tal)\b", re.I)


def snake(s: str) -> str:
    s = re.sub(r"['’]", "", s.lower())
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", s))


def clean_label(s: str) -> str:
    return re.sub(r"\(.*?\)\s*$", "", re.sub(r"\s+", " ", s.strip())).strip()


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def pairs_on_line(line: str):
    """Pairs on one line: wide gaps split "LABEL:   value   LABEL: value" into segments;
    a segment ending in a colon takes the next segment as its value when that
    segment holds no label of its own."""
    segs = [x.strip() for x in re.split(r"\s{2,}", line) if x.strip()]
    pairs = []
    for i, seg in enumerate(segs):
        m = LABEL.match(seg)
        if not m or not HAS_LETTER.search(m.group(1)) or re.search(r"\d", m.group(1)):
            continue
        label = clean_label(m.group(1))
        value = m.group(2).strip()
        if not value and i + 1 < len(segs) and not LABEL.match(segs[i + 1]):
            value = segs[i + 1].strip()
        pairs.append((label, value or None))
    return pairs


def is_form(text: Optional[str]) -> bool:
    if not text or FORM_INVOICE_BLOCK.search(text):
        return False
    count = 0
    for line in text.splitlines():
        count += len(pairs_on_line(line))
        if count >= 3:
            return True
    return False


def form_fields(text: str, limit: int = MAX_FORM_FIELDS) -> list[dict]:
    limit = min(limit, MAX_FORM_FIELDS)
    fields: list[dict] = []
    seen: set[str] = set()

    def add(label: str, value: Optional[str]) -> None:
        if len(fields) >= limit or not label:
            return
        base = snake(label)
        if not base:
            return
        name = base
        k = 2
        while name in seen:
            name = f"{base}_{k}"
            k += 1
        seen.add(name)
        fields.append({"name": name, "label": label, "value": squash(value) if value else None})

    for line in str(text or "").splitlines():
        for label, value in pairs_on_line(line):
            add(label, value)
            if len(fields) >= limit:
                return fields
    return fields
