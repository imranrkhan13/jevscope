// Rule-based bank statement reader: no AI key needed. Statements are a header
// block of labelled values (account holder, account number, IFSC, balances)
// above a transaction table. This reader proposes the header values and one
// group of fields per transaction row; Jev then checks each value against the
// document. Wrapped description lines and column-only debit/credit placement
// stay for a human: the reader only takes what the text makes plain.
// Same rules as the Python statement.py.

const STMT_HINT = /\b(statement|opening balance|closing balance|available balance)\b/i;
const STMT_HINT2 = /\b(account|balance|debit|credit|transaction)\b/i;

const MONEY_TOK = "(?:Rs\\.?|Rp\\.?|₹|\\$|€|£)?\\s?\\d[\\d,]*(?:\\.\\d+)?";
const DATE = "\\d{2}[/-]\\d{2}[/-]\\d{4}";
const MDATE = "\\d{2}\\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s+\\d{4}";
const TIME = "\\d{1,2}:\\d{2}(?::\\d{2})?(?:\\s*(?:AM|PM|am|pm))?";
// One table row: optional row number and transaction id, a date, then text, then amount and balance.
const ROW = new RegExp(
  "^\\s*(?:(\\d{1,3})\\s+)?(?:([A-Z]?\\d{6,})\\s+)?(" + DATE + "|" + MDATE + ")" +
  "(?:\\s+(" + DATE + "(?:\\s+" + TIME + ")?|" + MDATE + "(?:\\s+" + TIME + ")?|" + TIME + "))?" +
  "\\s+(.+?)\\s+(" + MONEY_TOK + ")\\s+(" + MONEY_TOK + ")\\s*$"
);
const DIRECTION = /(^|\s)(DR|CR|DEBIT|CREDIT)(?=\s|$)/i;
const CHEQUE = /(^|\s)(-|\d{5,7})(?=\s|$)/;
const BRANCH_CODE = /(^|\s)(\d{4})(?=\s|$)/;

// Header labels, normalised to lowercase. Values sit on the same line after a
// wide gap or on the next line.
const HEADER_LABELS = [
  [/^account holders?(?:'?s)?(?: name)?$/i, "account_holder", "Account holder"],
  [/^customer (?:id|no|number)$/i, "customer_id", "Customer ID"],
  [/^branch(?: name)?$/i, "branch", "Branch"],
  [/^micr(?: code)?$/i, "micr_code", "MICR code"],
  [/^ifsc(?: code)?$/i, "ifsc_code", "IFSC code"],
  [/^account (?:number|no)$/i, "account_number", "Account number"],
  [/^account type$/i, "account_type", "Account type"],
  [/^(?:product name|product)$/i, "product_name", "Product name"],
  [/^(?:account )?currency$/i, "currency", "Currency"],
  [/^(period|searched by|statement period)$/i, "period", "Period"],
  [/^opening balance$/i, "opening_balance", "Opening balance"],
  [/^closing balance$/i, "closing_balance", "Closing balance"],
  [/^interest rate$/i, "interest_rate", "Interest rate"],
];
const AS_OF = /\baccount statement as of\s+(.+?)\s*$/i;
const BANK = /\bbank(?:ing|s)?\b/i;
const cleanMoney = (s) => s.replace(/^(?:Rs\.?|Rp\.?|₹|\$|€|£)\s?/, "").replace(/\s/g, "");
const squash = (s) => String(s).replace(/[-​-‍﻿]/g, " ").replace(/\s+/g, " ").trim();

export const MAX_STATEMENT_FIELDS = 90;
export const MAX_STATEMENT_TXNS = 12;

/** True when the text looks like a bank account statement. */
export function isBankStatement(text) {
  const t = String(text || "");
  return STMT_HINT.test(t) && STMT_HINT2.test(t);
}

/** Read a bank statement: header fields, then one group per transaction row (date, description, type, amount, balance). */
export function statementFields(text, limit = MAX_STATEMENT_FIELDS) {
  const lines = String(text || "").split(/\r?\n/);
  const fields = [];
  const seen = new Set();
  const add = (name, label, value) => {
    if (fields.length >= limit || value == null || value === "") return;
    let n = name;
    for (let k = 2; seen.has(n); k++) n = `${name}_${k}`;
    seen.add(n);
    fields.push({ name: n, label, value });
  };

  // Bank name: the first line naming a bank, else the first line.
  const flat = lines.map(squash);
  const bankLine = flat.find((l) => BANK.test(l) && l.length <= 60);
  if (bankLine) add("bank_name", "Bank", bankLine);

  const labelOf = (l) => {
    if (!/^[A-Za-z][A-Za-z '&/.()-]{1,40}$/.test(l)) return null;
    for (const [re, name, lab] of HEADER_LABELS) if (re.test(l.trim())) return [name, lab];
    return null;
  };
  const isRowLine = (l) => ROW.test(l);
  for (let i = 0; i < lines.length; i++) {
    const l = flat[i];
    if (!l) continue;
    const asof = l.match(AS_OF);
    if (asof) add("statement_date", "Statement date", asof[1]);
    // Two-column "Label    value".
    const twoCol = (lines[i] || "").match(/^\s*([A-Za-z][A-Za-z '&/.()-]{1,40}?)\s{2,}(.+?)\s*$/);
    if (twoCol && !isRowLine(l)) {
      const hit = labelOf(twoCol[1]);
      if (hit) {
        let v = squash(twoCol[2]).replace(/(^|\s)-(?=\s|$)/g, " ");
        if (/balance/i.test(hit[0])) v = cleanMoney(v);
        if (/period|searched/i.test(twoCol[1])) v = squash(v).replace(/^from\s+/i, "").replace(/\s+to\s+/i, " to ");
        add(hit[0], hit[1], squash(v));
      }
      continue;
    }
    // Label lines stacked, then value lines stacked ("Account Holder / Customer ID" then "ACME / 1234"),
    // or one label with its value on the next line.
    if (labelOf(l)) {
      const run = [];
      let j = i;
      while (j < lines.length && flat[j] && labelOf(flat[j])) { run.push(labelOf(flat[j])); j++; }
      const vals = [];
      let k = j;
      while (k < lines.length && flat[k] && vals.length < run.length) {
        if (isRowLine(flat[k])) break;
        vals.push(flat[k]); k++;
      }
      if (vals.length === run.length) {
        run.forEach((hit, x) => {
          let v = squash(vals[x]).replace(/(^|\s)-(?=\s|$)/g, " ");
          if (/balance/i.test(hit[0])) v = cleanMoney(v);
          if (/period/i.test(hit[0])) v = squash(v).replace(/^from\s+/i, "").replace(/\s+to\s+/i, " to ");
          add(hit[0], hit[1], squash(v));
        });
        i = k - 1;
      }
    }
  }

  // Transactions: rows of the statement table.
  let txn = 0;
  for (let i = 0; i < lines.length && txn < MAX_STATEMENT_TXNS; i++) {
    const m = lines[i].match(ROW);
    if (!m) continue;
    const [, , , date, , middle, amount, balance] = m;
    let desc = squash(middle);
    // Strip a value date, a cheque placeholder, a branch code, and a DR/CR marker; what is left is the description.
    desc = desc.replace(new RegExp("^(" + DATE + "|" + MDATE + ")(\\s+" + TIME + ")?\\s+"), "");
    // A wrapped row can leave only a day-month fragment ("02 Jan") after the date; drop it.
    desc = desc.replace(new RegExp("^\\d{2}\\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s*$"), "");
    let type = "";
    const dm = desc.match(DIRECTION);
    if (dm) { type = dm[2].toUpperCase().replace(/^(DEBIT|CREDIT)$/i, (x) => x.toUpperCase() === "DEBIT" ? "DR" : "CR"); desc = squash(desc.slice(0, dm.index) + " " + desc.slice(dm.index + dm[0].length)); }
    desc = squash(desc.replace(CHEQUE, " ").replace(BRANCH_CODE, " "));
    // A wrapped or split row can leave nothing readable; skip it rather than guess.
    if (!desc && !type) continue;
    txn += 1;
    add(`txn_${txn}_date`, `Transaction ${txn} date`, date);
    if (desc && desc.length >= 4) add(`txn_${txn}_description`, `Transaction ${txn} description`, desc);
    if (type) add(`txn_${txn}_type`, `Transaction ${txn} type`, type);
    add(`txn_${txn}_amount`, `Transaction ${txn} amount`, cleanMoney(amount));
    add(`txn_${txn}_balance`, `Transaction ${txn} balance`, cleanMoney(balance));
  }
  return fields;
}
