# Rule-based bank statement reader: no AI key needed. Statements are a header
# block of labelled values (account holder, account number, IFSC, balances)
# above a transaction table. This reader proposes the header values and one
# group of fields per transaction row; Jev then checks each value against the
# document. Wrapped description lines and column-only debit/credit placement
# stay for a human: the reader only takes what the text makes plain.
# Same rules as the JavaScript statement.js.

from __future__ import annotations

import re
from typing import Optional

STMT_HINT = re.compile(r"\b(statement|opening balance|closing balance|available balance)\b", re.I)
STMT_HINT2 = re.compile(r"\b(account|balance|debit|credit|transaction)\b", re.I)

MONEY_TOK = r"(?:Rs\.?|Rp\.?|₹|\$|€|£)?\s?\d[\d,]*(?:\.\d+)?"
DATE = r"\d{2}[/-]\d{2}[/-]\d{4}"
MDATE = r"\d{2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:AM|PM|am|pm))?"
# One table row: optional row number and transaction id, a date, then text, then amount and balance.
ROW = re.compile(
    r"^\s*(?:(\d{1,3})\s+)?(?:([A-Z]?\d{6,})\s+)?(" + DATE + "|" + MDATE + ")"
    r"(?:\s+(" + DATE + r"(?:\s+" + TIME + ")?|" + MDATE + r"(?:\s+" + TIME + ")?|" + TIME + "))?"
    r"\s+(.+?)\s+(" + MONEY_TOK + r")\s+(" + MONEY_TOK + r")\s*$"
)
DIRECTION = re.compile(r"(^|\s)(DR|CR|DEBIT|CREDIT)(?=\s|$)", re.I)
CHEQUE = re.compile(r"(^|\s)(-|\d{5,7})(?=\s|$)")
BRANCH_CODE = re.compile(r"(^|\s)(\d{4})(?=\s|$)")

# Header labels, normalised to lowercase. Values sit on the same line after a
# wide gap or on the next line.
HEADER_LABELS = [
    (re.compile(r"^account holders?(?:'?s)?(?: name)?$", re.I), "account_holder", "Account holder"),
    (re.compile(r"^customer (?:id|no|number)$", re.I), "customer_id", "Customer ID"),
    (re.compile(r"^branch(?: name)?$", re.I), "branch", "Branch"),
    (re.compile(r"^micr(?: code)?$", re.I), "micr_code", "MICR code"),
    (re.compile(r"^ifsc(?: code)?$", re.I), "ifsc_code", "IFSC code"),
    (re.compile(r"^account (?:number|no)$", re.I), "account_number", "Account number"),
    (re.compile(r"^account type$", re.I), "account_type", "Account type"),
    (re.compile(r"^(?:product name|product)$", re.I), "product_name", "Product name"),
    (re.compile(r"^(?:account )?currency$", re.I), "currency", "Currency"),
    (re.compile(r"^(period|searched by|statement period)$", re.I), "period", "Period"),
    (re.compile(r"^opening balance$", re.I), "opening_balance", "Opening balance"),
    (re.compile(r"^closing balance$", re.I), "closing_balance", "Closing balance"),
    (re.compile(r"^interest rate$", re.I), "interest_rate", "Interest rate"),
]
AS_OF = re.compile(r"\baccount statement as of\s+(.+?)\s*$", re.I)
BANK = re.compile(r"\bbank(?:ing|s)?\b", re.I)

MAX_STATEMENT_FIELDS = 90
MAX_STATEMENT_TXNS = 12

_squash_re = re.compile(r"[\uE000-\uF8FF\u200B-\u200D\uFEFF]")
_ws_re = re.compile(r"\s+")


def squash(s: str) -> str:
    return _ws_re.sub(" ", _squash_re.sub(" ", str(s))).strip()


def clean_money(s: str) -> str:
    return re.sub(r"^(?:Rs\.?|Rp\.?|₹|\$|€|£)\s?", "", s).replace(" ", "")


def is_bank_statement(text: Optional[str]) -> bool:
    """True when the text looks like a bank account statement."""
    t = str(text or "")
    return bool(STMT_HINT.search(t) and STMT_HINT2.search(t))


_LABEL_SHAPE = re.compile(r"^[A-Za-z][A-Za-z '&/.()-]{1,40}$")
_TWO_COL = re.compile(r"^\s*([A-Za-z][A-Za-z '&/.()-]{1,40}?)\s{2,}(.+?)\s*$")
_DAY_MONTH = re.compile(r"^\d{2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*$")


def statement_fields(text: str, limit: int = MAX_STATEMENT_FIELDS) -> list[dict]:
    """Read a bank statement: header fields, then one group per transaction row (date, description, type, amount, balance)."""
    limit = min(limit, MAX_STATEMENT_FIELDS)
    lines = str(text or "").splitlines()
    fields: list[dict] = []
    seen: set[str] = set()

    def add(name: str, label: str, value: Optional[str]) -> None:
        if len(fields) >= limit or value is None or value == "":
            return
        n = name
        k = 2
        while n in seen:
            n = f"{name}_{k}"
            k += 1
        seen.add(n)
        fields.append({"name": n, "label": label, "value": value})

    # Bank name: the first line naming a bank, else the first line.
    flat = [squash(l) for l in lines]
    bank_line = next((l for l in flat if BANK.search(l) and len(l) <= 60), None)
    if bank_line:
        add("bank_name", "Bank", bank_line)

    def label_of(l: str):
        if not _LABEL_SHAPE.match(l):
            return None
        for rx, name, lab in HEADER_LABELS:
            if rx.match(l.strip()):
                return name, lab
        return None

    is_row_line = lambda l: bool(ROW.match(l))

    i = 0
    while i < len(lines):
        l = flat[i]
        if not l:
            i += 1
            continue
        asof = AS_OF.search(l)
        if asof:
            add("statement_date", "Statement date", asof.group(1))
        # Two-column "Label    value".
        two_col = _TWO_COL.match(lines[i] if i < len(lines) else "")
        if two_col and not is_row_line(l):
            hit = label_of(two_col.group(1))
            if hit:
                v = re.sub(r"(^|\s)-(?=\s|$)", " ", squash(two_col.group(2)))
                if re.search(r"balance", hit[0], re.I):
                    v = clean_money(v)
                if re.search(r"period|searched", two_col.group(1), re.I):
                    v = re.sub(r"\s+to\s+", " to ", re.sub(r"^from\s+", "", squash(v)), flags=re.I)
                add(hit[0], hit[1], squash(v))
            i += 1
            continue
        # Label lines stacked, then value lines stacked ("Account Holder / Customer ID" then "ACME / 1234"),
        # or one label with its value on the next line.
        if label_of(l):
            run = []
            j = i
            while j < len(lines) and flat[j] and label_of(flat[j]):
                run.append(label_of(flat[j]))
                j += 1
            vals = []
            k = j
            while k < len(lines) and flat[k] and len(vals) < len(run):
                if is_row_line(flat[k]):
                    break
                vals.append(flat[k])
                k += 1
            if len(vals) == len(run):
                for x, hit in enumerate(run):
                    v = re.sub(r"(^|\s)-(?=\s|$)", " ", squash(vals[x]))
                    if re.search(r"balance", hit[0], re.I):
                        v = clean_money(v)
                    if re.search(r"period", hit[0], re.I):
                        v = re.sub(r"\s+to\s+", " to ", re.sub(r"^from\s+", "", squash(v)), flags=re.I)
                    add(hit[0], hit[1], squash(v))
                i = k
                continue
        i += 1

    # Transactions: rows of the statement table.
    txn = 0
    for i in range(len(lines)):
        if txn >= MAX_STATEMENT_TXNS:
            break
        m = ROW.match(lines[i])
        if not m:
            continue
        date, middle, amount, balance = m.group(3), m.group(5), m.group(6), m.group(7)
        desc = squash(middle)
        # Strip a value date, a cheque placeholder, a branch code, and a DR/CR marker; what is left is the description.
        desc = re.sub(r"^(" + DATE + "|" + MDATE + r")(\s+" + TIME + r")?\s+", "", desc)
        # A wrapped row can leave only a day-month fragment ("02 Jan") after the date; drop it.
        desc = _DAY_MONTH.sub("", desc)
        typ = ""
        dm = DIRECTION.search(desc)
        if dm:
            w = dm.group(2).upper()
            typ = "DR" if w == "DEBIT" else ("CR" if w == "CREDIT" else w)
            desc = squash(desc[: dm.start()] + " " + desc[dm.end():])
        desc = squash(BRANCH_CODE.sub(" ", CHEQUE.sub(" ", desc)))
        # A wrapped or split row can leave nothing readable; skip it rather than guess.
        if not desc and not typ:
            continue
        txn += 1
        add(f"txn_{txn}_date", f"Transaction {txn} date", date)
        if desc and len(desc) >= 4:
            add(f"txn_{txn}_description", f"Transaction {txn} description", desc)
        if typ:
            add(f"txn_{txn}_type", f"Transaction {txn} type", typ)
        add(f"txn_{txn}_amount", f"Transaction {txn} amount", clean_money(amount))
        add(f"txn_{txn}_balance", f"Transaction {txn} balance", clean_money(balance))
    return fields
