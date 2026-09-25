// Rule-based receipt reader: no AI key needed. Store receipts are not invoices:
// items with quantities and prices, then subtotal/tax/total/cash/change. This
// reader proposes every value it can find (merchant, date, each item with its
// quantity and price, every labelled total); Jev then checks each value against
// the document. Same rules as the Python receipt.py.

// ISO currency codes a receipt can print next to its amounts ("Total : CHF 54.50", "4.50 CHF 9.00").
const CUR = String.raw`(?:AED|AUD|BDT|BRL|CAD|CHF|CNY|CZK|DKK|EUR|GBP|HKD|HUF|IDR|INR|JPY|KRW|KWD|LKR|MXN|MYR|NOK|NPR|NZD|PHP|PKR|PLN|QAR|SAR|SEK|SGD|THB|TRY|TWD|USD|VND|ZAR)`;
const SYM = String.raw`(?:Rp\.?|Rs\.?|₹|\$|€|£|` + CUR + `)`;
// Values are stored without a currency code: "CHF 54.50" is kept as "54.50".
const stripCode = (v) => String(v).replace(new RegExp(`^${CUR}`), "").replace(new RegExp(`${CUR}$`), "");
// OCR often leaves edge junk after the last amount on a line ("Total : CHF 54,50 a", "3.85 ‘").
// Drop trailing punctuation runs, and one trailing stray word of up to 3 letters right after money.
const JUNK_PUNCT = /[\s.,;:'‘’"`|]+$/;
const JUNK_WORD = (line) => {
  const m = line.match(new RegExp(`^(.*(?:[0-9]|${CUR}))\\s+[A-Za-z]{1,3}$`));
  return m ? m[1] : line;
};
const cleanLine = (line) => JUNK_WORD(line.replace(JUNK_PUNCT, "").replace(/^[^\p{L}\p{N}@à]+/u, ""));
const MONEY = new RegExp(String.raw`^(?:@|à)?(?:${SYM}\s?)?\d[\d.,]*$`);
const hasDigit = (s) => /\d/.test(s);
// Totals labels are never item names: "Subtotal", "PB1", "Pajak (10%)", "TUNAI"...
// Same words, anywhere in the line: a line carrying a totals word is never an item, even with OCR junk in front.
const TOTAL_WORD = /\b(sub\s?-?\s?total|dpp|grand\s+total|total|amount|pajak|pb1|ppn|tax|gst|service(?:\s+charge|\s+chrg|chrg)?|svc|discount|diskon|disc|tunai|cash|kembali|change|kembalian|card|debit|credit|payment|pembayaran|go-?pay|ovo|dana|rounding|pembulatan|harga jual|vat|tip|delivery|kembalian|balance due|amount due|tendered|due?|pay|incl\.?|mwst|mehrwertsteuer|ust|tva|gesamt|summe|betrag|netto|entspricht)\b/i;
const TOTAL_LABEL = /^(sub\s?-?\s?total|dpp|grand\s+total|total|amount|pajak|pb1|ppn|tax|gst|service(?:\s+charge|\s+chrg|chrg)?|svc|discount|diskon|disc|tunai|cash|kembali|change|kembalian|card|debit|credit|payment|pembayaran|go-?pay|ovo|dana|rounding|pembulatan|harga jual|vat|tip|delivery|kembalian|balance due|amount due|tendered|due?|pay|incl\.?|mwst|mehrwertsteuer|ust|tva|gesamt|summe|betrag|netto|entspricht)\b/i;
const DATE_LINE = /\b(\d{1,2}[./,-]\s?\d{1,2}[./,-]\s?\d{2,4}|\d{1,2}:\d{2}(?::\d{2})?\s?(?:am|pm)?)\b/i;
// "Receipt #KS-1141", "No. 5521"
const RECEIPT_NO = /\b(receipt|rcpt|struk|nota|rech(?:\.|nung)?)\s*(?:no|number|nr\.?|#|:)?\s*[:#,]?\s*([A-Za-z0-9-]{3,})\b/i;
// "2xLatte" (no space) and "2 Latte" both start with a quantity.
const QTY_JOINED = /^([0-9Il]{1,3})[xX](?=\S)/;  // OCR often reads 1 as I or l
const QTY_PRE = /^(\d{1,3}[xX]?)\s+/;
const QTY_SUFFIX = /\s+([xX]\d{1,3})\s+/;
// "Pajak (10%) 8,500": like the shared AMOUNT but labels may carry parentheses.
const PAIR = new RegExp(String.raw`^\s*(?:\d{1,2}\s+)?([A-Za-z][A-Za-z0-9 %.()'+]{1,30}?)\s*:?\s{0,4}((?:${SYM}\s?)?\d[\d,]*(?:\.\d+)?(?:\s?${CUR})?)\s*$`);
// "365000.00 TOTAL": some receipts print the amount before its label. Only the big
// totals labels pair backwards - a price line sitting above "Service" is usually the subtotal.
const REVERSED_LABEL = /^(sub\s?-?\s?total|grand\s+total|total|amount due|balance due)$/i;
const REVERSED_PAIR = new RegExp(String.raw`^\s*((?:${SYM}\s?)?\d[\d.,]*)\s{1,4}([A-Za-z][A-Za-z ()%]{0,24})\s*$`);
const LABEL_ONLY = /^\s*([A-Za-z][A-Za-z0-9 ]{0,20}?)\s*(?:Rp\.?|Rs\.?|:)?\s*$/;
const MONEY_ONLY = new RegExp(String.raw`^\s*((?:${SYM}\s?)?\d[\d.,]*)\s*$`);
const RECEIPT_HINT = new RegExp(String.raw`(\bcash\b|\bchange\b|\btunai\b|\bkembali\b|\breceipt\b|\bstruk\b|\bnota\b|\bqty\b|\bcard\b|go-?pay|\bovo\b|\bsub\s?-?\s?total\b|\bservice\s+charge\b|\bitems?\b|\btotal\s*[:.]?\s*(?:${CUR}\s?)?\d|\btisch\b|\bmwst\b|\bmehrwertsteuer\b|\bquittung\b|\bbedienung\b|\bbon\b|\bkvitto\b|\brecu\b|\bscontrino\b)`, "i");
// Category summary rows ("FOOD 1,213,000") sit between items and subtotal; they are totals, not items.
const SUMMARY_ROW = /^(food|beverages?|drinks?|others?|makanan|minuman|snacks?|desserts?|household|grocery|misc|items?|ttl)$/i;
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
  const amounts = t.split(/\r?\n/).map(cleanLine).filter((l) => {
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
    const m = rest.match(new RegExp(String.raw`^(.*?)\s+([@à]?(?:${SYM}\s?)?\d[\d.,]*(?:\s?${CUR})?)$`, "s"));
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
  const lines = String(text || "").split(/\r?\n/).map(cleanLine);
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
    if (!raw || used[i] || TOTAL_WORD.test(raw)) continue;
    let [rest, money] = takeMoney(raw);
    if (!money.length || money[money.length - 1].replace(/[^\d.]/g, "") === "0" || !/[A-Za-z]/.test(rest)) continue;
    let qty = "";
    let m = rest.match(QTY_JOINED);
    if (!m) m = rest.match(QTY_PRE);
    if (m) { qty = m[1].replace(/[Il]/g, "1"); rest = rest.slice(m[0].length); }
    else {
      m = rest.match(QTY_SUFFIX);
      if (m) { qty = m[1]; rest = (rest.slice(0, m.index) + " " + rest.slice(m.index + m[0].length)).trim(); }
      else {
        m = rest.match(/\s+([xX]?\d{1,3})$/);
        if (m) { qty = m[1]; rest = rest.slice(0, m.index).trim(); }
      }
    }
    rest = rest.replace(/[@à]\s*$/, "").replace(/[\s&+]+$/, "").trim();
    if (money.length === 2) rest = rest.replace(/\s+[aAà@]$/, "").trim(); // trailing "a" is an OCR-read "à"
    if (/(?:^|\s)(nr|no|nummer|number)\.?$/i.test(rest)) continue; // a "… Nr." line is a label, not an item
    let unit = "";
    if (money.length === 2) unit = stripCode(money[0].replace(/^[@à]/, ""));
    else if (/^[@à]/.test(money[0])) continue; // "@price" with no line total: not an item row
    const price = stripCode(money[money.length - 1].replace(/^[@à]/, ""));
    if (!rest || rest.length > 60 || SUMMARY_ROW.test(rest)) continue;
    // A bare numbering label ("No. 5521") is the bill number, not an item.
    if (/^(no\.?|number|bill|order)$/i.test(rest)) continue;
    used[i] = true;
    item += 1;
    add(`item_${item}_name`, `Item ${item} name`, rest);
    if (qty) add(`item_${item}_qty`, `Item ${item} quantity`, qty);
    if (unit) add(`item_${item}_unit_price`, `Item ${item} unit price`, unit);
    add(`item_${item}_price`, `Item ${item} price`, price);
  }

  // Totals and any other "Label amount" or "Label: amount" lines, including a label on one line
  // and its amount on the next ("Total\n57.000").
  for (let i = 0; i < lines.length; i++) {
    const raw = squash(lines[i]);
    if (!raw || used[i]) continue;
    // A totals label alone on its line ("Total\n14\n197.450", "PB1\n60,394"): the value is
    // the LAST of the money-only lines right below it - wrapped receipts often print a stray
    // count first. This runs before PAIR so "PB1" is not misread as label "PB" value "1".
    const lm = raw.match(LABEL_ONLY);
    const nl = i + 1 < lines.length ? squash(lines[i + 1]) : "";
    let label = null, value = null;
    if (lm && TOTAL_LABEL.test(raw)) {
      let j = i + 1, last = null, lastIdx = -1;
      while (j < lines.length && !used[j]) {
        const nm = squash(lines[j]).match(MONEY_ONLY);
        if (!nm) break;
        last = nm[1].replace(/\s/g, ""); lastIdx = j; j++;
      }
      if (last != null) {
        // Value-above-label layout ("20,000\nTOTAL\n50,000\nCASH"): when exactly one money
        // line sits below and it already belongs to the NEXT totals label, this label's value
        // is the money line above it. Leave the line below for its own label.
        const after = lastIdx + 1 < lines.length ? squash(lines[lastIdx + 1]) : "";
        const above = i - 1 >= 0 && !used[i - 1] ? squash(lines[i - 1]).match(MONEY_ONLY) : null;
        if (lastIdx === i + 1 && after && LABEL_ONLY.test(after) && TOTAL_LABEL.test(after) && above) {
          label = squash(lm[1]); value = stripCode(above[1].replace(/\s/g, ""));
          used[i - 1] = true;
        } else {
          label = squash(lm[1]); value = stripCode(last);
          for (let k = i + 1; k <= lastIdx; k++) used[k] = true;
        }
      } else {
        // Wrapped label: "Service" on one line, "charge 42,135" on the next.
        const wm = nl.match(new RegExp(String.raw`^([A-Za-z][A-Za-z ]{0,15}?)\s+((?:${SYM}\s?)?\d[\d.,]*)$`));
        if (wm && TOTAL_LABEL.test(lm[1] + " " + wm[1])) {
          label = squash(lm[1] + " " + wm[1]); value = stripCode(wm[2].replace(/\s/g, ""));
          used[i + 1] = true;
        }
      }
    }
    if (!label) {
      // "365000.00 TOTAL": amount first, label after (same line, or on two lines). The two-line
      // form only fires when the label has no money line of its own below - otherwise that
      // money belongs to the label ("Subtotal\n179.500"), not to the price above it.
      const m = raw.match(PAIR);
      const rv = raw.match(REVERSED_PAIR);
      const rvm = raw.match(MONEY_ONLY);
      if (m && /[A-Za-z]/.test(m[1])) {
        label = squash(m[1]); value = stripCode(m[2].replace(/\s/g, ""));
      } else if (rv && REVERSED_LABEL.test(rv[2])) {
        label = squash(rv[2]); value = stripCode(rv[1].replace(/\s/g, ""));
      } else if (rvm && LABEL_ONLY.test(nl) && REVERSED_LABEL.test(nl)
          && !(i + 2 < lines.length && MONEY_ONLY.test(squash(lines[i + 2])))) {
        label = squash(nl.match(LABEL_ONLY)[1]); value = stripCode(rvm[1].replace(/\s/g, ""));
        used[i + 1] = true;
      }
    }
    if (!label) continue;
    // A non-total pair is only kept when the value is money-shaped (has a separator or 3+
    // digits): "Kailan 2" or "ITEMS: 13" are noise, "Tax 61,849" is a field.
    if (!TOTAL_LABEL.test(raw) && !/[.,]/.test(value) && value.replace(/\D/g, "").length < 3) continue;
    // A non-total "line" worth zero is a modifier note ("Less Ice 0"), not a field.
    if (!TOTAL_LABEL.test(raw) && String(value).replace(/[^\d.]/g, "").replace(/\./g, "") === "0") continue;
    used[i] = true;
    add(snake(label), label, value);
  }
  return fields;
}
