// Rule-based form reader: no AI key needed. Forms are labelled blanks: a label
// ending in a colon with its value after it ("TO: Jane", "FAX NUMBER: 555..."),
// often several label/value pairs on one line. This reader proposes one field
// per filled blank; blanks left empty stay for a human to fill. Wrapped note
// and disclaimer paragraphs are not fields and are skipped.
// Same rules as the Python form.py.

export const MAX_FORM_FIELDS = 50;

// A label: letters and a few connectors, no digits, 2-40 chars, ends in a colon.
const LABEL = /^([A-Za-z][A-Za-z '/&().#-]{1,38}?):\s*(.*)$/;
const HAS_LETTER = /[A-Za-z]{2}/;
// Invoices, receipts, and statements have their own readers; a text with these
// blocks is not treated as a form. "receipt" alone does not block: fax cover
// sheets say "receipt of this transmission".
export const FORM_INVOICE_BLOCK = /\b([il1]nvo[il1]ce|amount due|due date|bill to|remit|sub\s?total|t[o0]tal)\b/i;

const snake = (s) => s.toLowerCase().replace(/['’]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const cleanLabel = (s) => s.trim().replace(/\s+/g, " ").replace(/\(.*?\)\s*$/, "").trim();
const squash = (s) => (s || "").replace(/\s+/g, " ").trim();

// Pairs on one line: wide gaps split "LABEL:   value   LABEL: value" into segments;
// a segment ending in a colon takes the next segment as its value when that
// segment holds no label of its own.
function pairsOnLine(line) {
  const segs = line.split(/\s{2,}/).map((x) => x.trim()).filter(Boolean);
  const pairs = [];
  for (let i = 0; i < segs.length; i++) {
    const m = segs[i].match(LABEL);
    if (!m || !HAS_LETTER.test(m[1]) || /\d/.test(m[1])) continue;
    const label = cleanLabel(m[1]);
    let value = m[2].trim();
    if (!value && i + 1 < segs.length && !LABEL.test(segs[i + 1])) value = segs[i + 1].trim();
    pairs.push([label, value || null]);
  }
  return pairs;
}

export function isForm(text) {
  if (!text || FORM_INVOICE_BLOCK.test(text)) return false;
  let count = 0;
  for (const line of text.split(/\r?\n/)) {
    count += pairsOnLine(line).length;
    if (count >= 3) return true;
  }
  return false;
}

export function formFields(text, limit = MAX_FORM_FIELDS) {
  limit = Math.min(limit, MAX_FORM_FIELDS);
  const fields = [];
  const seen = new Set();
  const add = (label, value) => {
    if (fields.length >= limit || !label) return;
    let name = snake(label);
    if (!name) return;
    for (let k = 2; seen.has(name); k++) name = `${snake(label)}_${k}`;
    seen.add(name);
    fields.push({ name, label, value: value ? squash(value) : null });
  };
  for (const line of text.split(/\r?\n/)) {
    for (const [label, value] of pairsOnLine(line)) {
      // Skip empty blanks the layout shows as "LABEL:" with the value line far away,
      // and tiny labels like "TO:" of a fax header are still real fields: keep them.
      add(label, value);
      if (fields.length >= limit) return fields;
    }
  }
  return fields;
}
