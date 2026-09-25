// Rule-based receipt reader: no AI key needed. Store receipts are not invoices:
// items with quantities and prices, then subtotal/tax/total/cash/change. This
// reader proposes every value it can find (merchant, date, each item with its
// quantity and price, every labelled total); Jev then checks each value against
// the document. Same rules as the Python receipt.py.

const MONEY = /^(?:@)?(?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*$/;
const hasDigit = (s) => /\d/.test(s);
// Totals labels are never item names: "Subtotal", "PB1", "Pajak (10%)", "TUNAI"...
const TOTAL_LABEL = /^(sub\s?-?\s?total|dpp|grand\s+total|total|amount|pajak|pb1|ppn|tax|gst|service(?:\s+charge|\s+chrg|chrg)?|svc|discount|diskon|disc|tunai|cash|kembali|change|kembalian|card|debit|credit|payment|pembayaran|go-?pay|ovo|dana|rounding|pembulatan|harga jual|vat|tip|delivery|kembalian|balance due|amount due|tendered)\b/i;
const DATE_LINE = /\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}:\d{2}(?::\d{2})?\s?(?:am|pm)?)\b/i;
// "Receipt #KS-1141", "No. 5521"
const RECEIPT_NO = /\b(receipt|rcpt|struk|nota)\s*(?:no|number|#|:)?\s*[:#]?\s*([A-Za-z0-9-]{3,})\b/i;
const QTY_PRE = /^(\d{1,3}[xX]?)\s+/;
const QTY_SUFFIX = /\s+([xX]\d{1,3})\s+/;
// "Pajak (10%) 8,500": like the shared AMOUNT but labels may carry parentheses.
const PAIR = /^\s*([A-Za-z][A-Za-z0-9 %.()']{1,30}?)\s*:?\s{0,4}((?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d,]*(?:\.\d+)?)\s*$/;
const LABEL_ONLY = /^\s*([A-Za-z][A-Za-z ]{1,20}?)\s*(?:Rp\.?|Rs\.?|:)?\s*$/;
const MONEY_ONLY = /^\s*((?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*)\s*$/;
const RECEIPT_HINT = /(\bcash\b|\bchange\b|\btunai\b|\bkembali\b|\breceipt\b|\bstruk\b|\bnota\b|\bqty\b|\bcard\b|go-?pay|\bovo\b)/i;
const INVOICE_WORD = /\b([il1]nvo[il1]ce|bill to|due date|remit)\b/i;

export const MAX_RECEIPT_FIELDS = 80;
export const MAX_RECEIPT_ITEMS = 25;

const squash = (s) => String(s).replace(/[-​-‍﻿]/g, " ").replace(/\s+/g, " ").trim();
const snake = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "field";

/** True when the text looks like a store receipt: cash/change/qty words and amounts, and not an invoice. */
export function isReceipt(text) {
  const t = String(text || "");
  if (!RECEIPT_HINT.test(t) || INVOICE_WORD.test(t)) return false;
  // Pair lines whose label is words only ("TOTAL 46.636"), not digit soup like a fax stamp ("JAN 1 2 1999").
  const amounts = t.split(/\r?\n/).filter((l) => {
    const m = l.match(PAIR);
    if (m) return !/\d/.test(m[1]);
    return MONEY_ONLY.test(l);
  }).length;
  return amounts >= 2;
}

// Split trailing money tokens off a line: "BASO KUAH 1 43.636 43.636" -> ["BASO KUAH 1", ["43.636", "43.636"]].
function takeMoney(line) {
  const out = [];
  let rest = line.trim();
  for (let k = 0; k < 2; k++) {
    const m = rest.match(/^(.*?)\s+(@?(?:Rp\.?|Rs\.?|₹|\$|€|£)?\s?\d[\d.,]*)$/s);
    if (!m) break;
    const tok = m[2].replace(/\s/g, "");
    // Money has a separator, a currency mark, or at least 3 digits; a bare "5" or "12" is a quantity.
    if (!/[.,@]|[^\d.,\s]/.test(tok) && tok.replace(/\D/g, "").length < 3) break;
    out.unshift(tok);
    rest = m[1];
  }
  return [rest, out];
}

/** Read a store receipt: merchant, date, one group of fields per item, then every labelled total. */
export function receiptFields(text, limit = MAX_RECEIPT_FIELDS) {
  const lines = String(text || "").split(/\r?\n/);
  const fields = [];
  const seen = new Set();
  const used = new Array(lines.length).fill(false);
  const add = (name, label, value) => {
    if (fields.length >= limit) return;
    let n = name;
    for (let k = 2; seen.has(n); k++) n = `${name}_${k}`;
    seen.add(n);
    fields.push(value == null ? { name: n, label, value: null } : { name: n, label, value });
  };

  // Merchant: the first line, when it is a name, not a number soup or a keyword line.
  const first = lines.find((l) => squash(l));
  if (first) {
    const f = squash(first);
    if (!hasDigit(f) && f.length <= 50 && f.split(" ").length <= 7 && !TOTAL_LABEL.test(f) && !/^\W/.test(f)) {
      add("merchant", "Merchant", f);
      used[lines.indexOf(first)] = true;
    }
  }

  // First date or time in the document.
  for (let i = 0; i < lines.length; i++) {
    const m = squash(lines[i]).match(DATE_LINE);
    if (m) {
      add("date", "Date", m[1]);
      break;
    }
  }
  const no = String(text || "").match(RECEIPT_NO);
  if (no) add("receipt_number", "Receipt number", no[2]);

  // Items: "1 EGG TART 13,000", "Ash Chick Sambal Matah 5 75.000", "1X S-Bubble Milk Tea @20,000 20,000",
  // "Kopi Susu Kampung. x1 19.000", "BASO KUAH 1 43.636 43.636". A zero price marks a modifier line ("Less Ice 0"), skipped.
  let item = 0;
  for (let i = 0; i < lines.length && item < MAX_RECEIPT_ITEMS; i++) {
    const raw = squash(lines[i]);
    if (!raw || used[i] || TOTAL_LABEL.test(raw)) continue;
    let [rest, money] = takeMoney(raw);
    if (!money.length || money[money.length - 1].replace(/[^\d.]/g, "") === "0" || !/[A-Za-z]/.test(rest)) continue;
    let qty = "";
    let m = rest.match(QTY_PRE);
    if (m) { qty = m[1]; rest = rest.slice(m[0].length); }
    else {
      m = rest.match(QTY_SUFFIX);
      if (m) { qty = m[1]; rest = (rest.slice(0, m.index) + " " + rest.slice(m.index + m[0].length)).trim(); }
      else {
        m = rest.match(/\s+([xX]?\d{1,3})$/);
        if (m) { qty = m[1]; rest = rest.slice(0, m.index).trim(); }
      }
    }
    let unit = "";
    if (money.length === 2) unit = money[0];
    else if (money[0].startsWith("@")) continue; // "@price" with no line total: not an item row
    const price = money[money.length - 1].replace(/^@/, "");
    if (!rest || rest.length > 60) continue;
    used[i] = true;
    item += 1;
    add(`item_${item}_name`, `Item ${item} name`, rest);
    if (qty) add(`item_${item}_qty`, `Item ${item} quantity`, qty);
    if (unit) add(`item_${item}_unit_price`, `Item ${item} unit price`, unit.replace(/^@/, ""));
    add(`item_${item}_price`, `Item ${item} price`, price);
  }

  // Totals and any other "Label amount" or "Label: amount" lines, including a label on one line
  // and its amount on the next ("Total\n57.000").
  for (let i = 0; i < lines.length; i++) {
    const raw = squash(lines[i]);
    if (!raw || used[i]) continue;
    let m = raw.match(PAIR);
    let label = null, value = null;
    if (m && /[A-Za-z]/.test(m[1])) {
      label = squash(m[1]); value = m[2].replace(/\s/g, "");
    } else {
      const lm = raw.match(LABEL_ONLY);
      const nm = i + 1 < lines.length ? squash(lines[i + 1]).match(MONEY_ONLY) : null;
      if (lm && nm && TOTAL_LABEL.test(raw)) {
        label = squash(lm[1]); value = nm[1].replace(/\s/g, "");
        used[i + 1] = true;
      }
    }
    if (!label) continue;
    // A non-total "line" worth zero is a modifier note ("Less Ice 0"), not a field.
    if (!TOTAL_LABEL.test(raw) && String(value).replace(/[^\d.]/g, "").replace(/\./g, "") === "0") continue;
    used[i] = true;
    add(snake(label), label, value);
  }
  return fields;
}
