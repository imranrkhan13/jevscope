# Rule-based receipt reader: no AI key needed. Store receipts are not invoices:
# items with quantities and prices, then subtotal/tax/total/cash/change. This
# reader proposes every value it can find (merchant, date, each item with its
# quantity and price, every labelled total); Jev then checks each value against
# the document. Same rules as the JavaScript receipt.js.

from __future__ import annotations

import re
from typing import Optional

MONEY = re.compile(r"^(?:@)?(?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*$")
# Totals labels are never item names: "Subtotal", "PB1", "Pajak (10%)", "TUNAI"...
TOTAL_LABEL = re.compile(r"^(sub\s?-?\s?total|dpp|grand\s+total|total|amount|pajak|pb1|ppn|tax|gst|service(?:\s+charge|\s+chrg|chrg)?|svc|discount|diskon|disc|tunai|cash|kembali|change|kembalian|card|debit|credit|payment|pembayaran|go-?pay|ovo|dana|rounding|pembulatan|harga jual|vat|tip|delivery|balance due|amount due|tendered|due?|pay)\b", re.I)
DATE_LINE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}:\d{2}(?::\d{2})?\s?(?:am|pm)?)\b", re.I)
# "Receipt #KS-1141", "No. 5521"
RECEIPT_NO = re.compile(r"\b(receipt|rcpt|struk|nota)\s*(?:no|number|#|:)?\s*[:#]?\s*([A-Za-z0-9-]{3,})\b", re.I)
QTY_PRE = re.compile(r"^(\d{1,3}[xX]?)\s+")
QTY_SUFFIX = re.compile(r"\s+([xX]\d{1,3})\s+")
# "Pajak (10%) 8,500": like the shared AMOUNT but labels may carry parentheses.
PAIR = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 %.()'+]{1,30}?)\s*:?\s{0,4}((?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d,]*(?:\.\d+)?)\s*$")
LABEL_ONLY = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 ]{0,20}?)\s*(?:Rp\.?|Rs\.?|:)?\s*$")
MONEY_ONLY = re.compile(r"^\s*((?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*)\s*$")
RECEIPT_HINT = re.compile(r"(\bcash\b|\bchange\b|\btunai\b|\bkembali\b|\breceipt\b|\bstruk\b|\bnota\b|\bqty\b|\bcard\b|go-?pay|\bovo\b|\bsub\s?-?\s?total\b|\bservice\s+charge\b|\bitems?\b)", re.I)
# Category summary rows ("FOOD 1,213,000") sit between items and subtotal; they are totals, not items.
SUMMARY_ROW = re.compile(r"^(food|beverages?|drinks?|others?|makanan|minuman|snacks?|desserts?|household|grocery|misc|items?|ttl)$", re.I)
# "365000.00 TOTAL": some receipts print the amount before its label. Only the big
# totals labels pair backwards - a price line sitting above "Service" is usually the subtotal.
REVERSED_LABEL = re.compile(r"^(sub\s?-?\s?total|grand\s+total|total|amount due|balance due)$", re.I)
REVERSED_PAIR = re.compile(r"^\s*((?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*)\s{1,4}([A-Za-z][A-Za-z ()%]{0,24})\s*$")
INVOICE_WORD = re.compile(r"\b([il1]nvo[il1]ce|bill to|due date|remit)\b", re.I)

MAX_RECEIPT_FIELDS = 80
MAX_RECEIPT_ITEMS = 25

_squash_re = re.compile(r"[-​-‍﻿]")
_ws_re = re.compile(r"\s+")


def squash(s: str) -> str:
    return _ws_re.sub(" ", _squash_re.sub(" ", str(s))).strip()


def snake(s: str) -> str:
    return (re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", s.lower()))[:60] or "field")


def is_receipt(text: Optional[str]) -> bool:
    """True when the text looks like a store receipt: cash/change/qty words and amounts, and not an invoice."""
    t = str(text or "")
    if not RECEIPT_HINT.search(t) or INVOICE_WORD.search(t):
        return False
    # Pair lines whose label is words only ("TOTAL 46.636"), not digit soup like a fax stamp ("JAN 1 2 1999").
    def counts(l):
        m = PAIR.match(l)
        if m:
            return not re.search(r"\d", m.group(1))
        return bool(MONEY_ONLY.match(l))
    amounts = sum(1 for l in t.splitlines() if counts(l))
    return amounts >= 2


_MONEY_TAIL = re.compile(r"^(.*?)\s+(@?(?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*)$", re.S)


def take_money(line: str):
    """Split trailing money tokens off a line: "BASO KUAH 1 43.636 43.636" -> ("BASO KUAH 1", ["43.636", "43.636"])."""
    out = []
    rest = line.strip()
    for _ in range(2):
        m = _MONEY_TAIL.match(rest)
        if not m:
            break
        tok = m.group(2).replace(" ", "")
        # Money has a separator, a currency mark, or at least 3 digits; a bare "5" or "12" is a quantity.
        if not re.search(r"[.,@]|[^\d.,\s]", tok) and len(re.sub(r"\D", "", tok)) < 3:
            break
        out.insert(0, tok)
        rest = m.group(1)
    return rest, out


def receipt_fields(text: str, limit: int = MAX_RECEIPT_FIELDS) -> list[dict]:
    """Read a store receipt: merchant, date, one group of fields per item, then every labelled total."""
    limit = min(limit, MAX_RECEIPT_FIELDS)
    lines = str(text or "").splitlines()
    fields: list[dict] = []
    seen: set[str] = set()
    used = [False] * len(lines)

    def add(name: str, label: str, value: Optional[str]) -> None:
        if len(fields) >= limit:
            return
        n = name
        k = 2
        while n in seen:
            n = f"{name}_{k}"
            k += 1
        seen.add(n)
        fields.append({"name": n, "label": label, "value": value})

    # Merchant: the first line, when it is a name, not a number soup or a keyword line.
    first_idx = next((i for i, l in enumerate(lines) if squash(l)), None)
    if first_idx is not None:
        f = squash(lines[first_idx])
        if not re.search(r"\d", f) and len(f) <= 50 and len(f.split(" ")) <= 7 and not TOTAL_LABEL.search(f) and not re.match(r"^\W", f):
            add("merchant", "Merchant", f)
            used[first_idx] = True

    # First date or time in the document.
    for i, l in enumerate(lines):
        m = DATE_LINE.search(squash(l))
        if m:
            add("date", "Date", m.group(1))
            break
    no = RECEIPT_NO.search(str(text or ""))
    if no:
        add("receipt_number", "Receipt number", no.group(2))

    # Items: "1 EGG TART 13,000", "Ash Chick Sambal Matah 5 75.000", "1X S-Bubble Milk Tea @20,000 20,000",
    # "Kopi Susu Kampung. x1 19.000", "BASO KUAH 1 43.636 43.636". A zero price marks a modifier line ("Less Ice 0"), skipped.
    item = 0
    for i in range(len(lines)):
        if item >= MAX_RECEIPT_ITEMS:
            break
        raw = squash(lines[i])
        if not raw or used[i] or TOTAL_LABEL.search(raw):
            continue
        rest, money = take_money(raw)
        if not money or re.sub(r"[^\d.]", "", money[-1]) == "0" or not re.search(r"[A-Za-z]", rest):
            continue
        qty = ""
        m = QTY_PRE.match(rest)
        if m:
            qty = m.group(1)
            rest = rest[m.end():]
        else:
            m = QTY_SUFFIX.search(rest)
            if m:
                qty = m.group(1)
                rest = (rest[: m.start()] + " " + rest[m.end():]).strip()
            else:
                m = re.search(r"\s+([xX]?\d{1,3})$", rest)
                if m:
                    qty = m.group(1)
                    rest = rest[: m.start()].strip()
        unit = ""
        if len(money) == 2:
            unit = money[0]
        elif money[0].startswith("@"):
            continue  # "@price" with no line total: not an item row
        price = money[-1].lstrip("@")
        if not rest or len(rest) > 60 or SUMMARY_ROW.match(rest):
            continue
        # A bare numbering label ("No. 5521") is the bill number, not an item.
        if re.match(r"^(no\.?|number|bill|order)$", rest, re.I):
            continue
        used[i] = True
        item += 1
        add(f"item_{item}_name", f"Item {item} name", rest)
        if qty:
            add(f"item_{item}_qty", f"Item {item} quantity", qty)
        if unit:
            add(f"item_{item}_unit_price", f"Item {item} unit price", unit.lstrip("@"))
        add(f"item_{item}_price", f"Item {item} price", price)

    # Totals and any other "Label amount" or "Label: amount" lines.
    for i in range(len(lines)):
        raw = squash(lines[i])
        if not raw or used[i]:
            continue
        label = None
        value = None
        nl = squash(lines[i + 1]) if i + 1 < len(lines) else ""
        # A totals label alone on its line ("Total\n14\n197.450", "PB1\n60,394"): the value is
        # the LAST of the money-only lines right below it - wrapped receipts often print a stray
        # count first. This runs before PAIR so "PB1" is not misread as label "PB" value "1".
        lm = LABEL_ONLY.match(raw)
        if lm and TOTAL_LABEL.search(raw):
            j = i + 1
            last = None
            last_idx = -1
            while j < len(lines) and not used[j]:
                nm = MONEY_ONLY.match(squash(lines[j]))
                if not nm:
                    break
                last = nm.group(1).replace(" ", "")
                last_idx = j
                j += 1
            if last is not None:
                # Value-above-label layout ("20,000\nTOTAL\n50,000\nCASH"): when exactly one
                # money line sits below and it already belongs to the NEXT totals label, this
                # label's value is the money line above it. Leave the line below for its label.
                after = squash(lines[last_idx + 1]) if last_idx + 1 < len(lines) else ""
                above = None
                if i - 1 >= 0 and not used[i - 1]:
                    above = MONEY_ONLY.match(squash(lines[i - 1]))
                if last_idx == i + 1 and after and LABEL_ONLY.match(after) and TOTAL_LABEL.search(after) and above:
                    label = squash(lm.group(1))
                    value = above.group(1).replace(" ", "")
                    used[i - 1] = True
                else:
                    label = squash(lm.group(1))
                    value = last
                    for k in range(i + 1, last_idx + 1):
                        used[k] = True
            else:
                # Wrapped label: "Service" on one line, "charge 42,135" on the next.
                wm = re.match(r"^([A-Za-z][A-Za-z ]{0,15}?)\s+((?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*)$", nl)
                if wm and TOTAL_LABEL.search(lm.group(1) + " " + wm.group(1)):
                    label = squash(lm.group(1) + " " + wm.group(1))
                    value = wm.group(2).replace(" ", "")
                    used[i + 1] = True
        if not label:
            # "365000.00 TOTAL": amount first, label after (same line, or on two lines). The two-line
            # form only fires when the label has no money line of its own below - otherwise that
            # money belongs to the label ("Subtotal\n179.500"), not to the price above it.
            m = PAIR.match(raw)
            rv = REVERSED_PAIR.match(raw)
            rvm = MONEY_ONLY.match(raw)
            if m and re.search(r"[A-Za-z]", m.group(1)):
                label = squash(m.group(1))
                value = m.group(2).replace(" ", "")
            elif rv and REVERSED_LABEL.match(rv.group(2)):
                label = squash(rv.group(2))
                value = rv.group(1).replace(" ", "")
            elif (rvm and LABEL_ONLY.match(nl) and REVERSED_LABEL.match(nl)
                    and not (i + 2 < len(lines) and MONEY_ONLY.match(squash(lines[i + 2])))):
                label = squash(LABEL_ONLY.match(nl).group(1))
                value = rvm.group(1).replace(" ", "")
                used[i + 1] = True
        if not label:
            continue
        # A non-total "line" worth zero is a modifier note ("Less Ice 0"), not a field.
        if not TOTAL_LABEL.search(raw) and re.sub(r"\.", "", re.sub(r"[^\d.]", "", str(value))) == "0":
            continue
        # A non-total pair is only kept when the value is money-shaped (has a separator or 3+
        # digits): "Kailan 2" or "ITEMS: 13" are noise, "Tax 61,849" is a field.
        if not TOTAL_LABEL.search(raw) and not re.search(r"[.,]", str(value)) and len(re.sub(r"\D", "", str(value))) < 3:
            continue
        used[i] = True
        add(snake(label), label, value)
    return fields
