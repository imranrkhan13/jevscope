// Extraction by verification: instead of rules or an AI writer, Jev itself finds
// the value. For each target field we list the spans in the document that could
// be the value (amounts, dates, ids, lines), ask real Jev yes/no "is THIS the
// field?" for every candidate in one request, keep the candidate Jev is most
// sure of, and abstain to a human when no candidate clears the bar. No AI key,
// no per-type rules. Same rules as the Python extract.py.

import { askJev } from "./jev.js";
import { normalize } from "./certainty.js";

// Keep in sync with receipt.js: codes a document can print next to amounts.
const CUR = String.raw`(?:AED|AUD|BDT|BRL|CAD|CHF|CNY|CZK|DKK|EUR|GBP|HKD|HUF|IDR|INR|JPY|KRW|KWD|LKR|MXN|MYR|NOK|NPR|NZD|PHP|PKR|PLN|QAR|SAR|SEK|SGD|THB|TRY|TWD|USD|VND|ZAR)`;
const SYM = String.raw`(?:Rp\.?|Rs\.?|₹|\$|€|£|` + CUR + `)`;
const MONEY_TOKEN = new RegExp(String.raw`(?:${SYM}\s?)?\d[\d.,]*(?:\s?${CUR})?`, "g");
const DATE_TOKEN = /\b\d{1,2}\s?[./,-]\s?\d{1,2}\s?[./,-]\s?\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b/g;
const PHONE_TOKEN = /\(?\d{3}\)?[\s-]\d{3}[\s-]\s?\d{4}/g;
const SMALL_NUM = /\b\d{1,3}\b/g;
const ID_TOKEN = /\b(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]{3,}\b|\b\d{4,}\b/g;
const PAIR_VALUE = /^\s*[A-Za-z][A-Za-z0-9 %.()'+]{1,30}?\s*:\s{0,4}(.+?)\s*$/;
const TITLE_PHRASE = /\b[A-Z][A-Za-z&.'-]*(?: [A-Z][A-Za-z&.'-]*){1,3}\b/g;

const MAX_CANDIDATES = 8;
const MIN_CONFIDENCE = 0.5;

/** Guess what kind of span a field wants from its name: amount, date, id, text or any. */
export function fieldKind(name = "") {
  const n = String(name).toLowerCase();
  if (/amount|total|price|cash|change|due|tax|subtotal|balance|paid|cost|fee|tip/.test(n)) return "amount";
  if (/date|deadline|when/.test(n)) return "date";
  if (/(^|_)(no|number|num|id|code|nr|ref|reference|pages|qty|quantity|count)(_|$)/.test(n)) return "id";
  if (/name|vendor|merchant|company|store|address|recipient|sender|(^|_)(to|from)(_|$)/.test(n)) return "text";
  return "any";
}

// Light OCR-junk cleanup on a candidate, same idea as receipt.js cleanLine.
const clean = (s) => String(s).replace(/[\s.,;:'‘’"`|]+$/g, "").replace(/^[^\p{L}\p{N}@à]+/u, "").trim();

const matches = (re, text) => {
  re.lastIndex = 0;
  const out = [];
  let m;
  while ((m = re.exec(text)) !== null) {
    const v = clean(m[0]);
    if (v) out.push(v);
  }
  return out;
};

// Amounts are candidates without a currency code: "CHF 54.50" is asked about as "54.50".
const stripCode = (v) => v.replace(new RegExp(`^${CUR}\\s?`), "").replace(new RegExp(`\\s?${CUR}$`), "");
const moneyCandidates = (text) => matches(MONEY_TOKEN, text).map(stripCode).filter((v) => {
  const digits = v.replace(/\D/g, "");
  return /[.,]/.test(v) || /[^\d\s.,]/.test(v) || digits.length >= 3;
});

const lineCandidates = (text) => String(text).split(/\r?\n/)
  .map((l) => l.replace(/\s+/g, " ").trim())
  .filter((l) => l && l.length <= 60 && /[A-Za-z]/.test(l))
  .slice(0, 10);

// Words of the field name used to spot its label in the text ("net_amount_due" -> net/amount/due).
const STOP = new Set(["of", "the", "a", "an", "no", "number", "in", "including"]);
const labelWords = (name) => String(name || "").toLowerCase().split(/[_\s-]+/).filter((w) => w && !STOP.has(w));

/** The spans of the document that could plausibly be this field's value.
 *  Candidates on a line that also carries the field's label come first; then document order. */
export function candidateSpans(document, field) {
  const text = String(document || "");
  const f = typeof field === "string" ? { name: field } : field || {};
  const kind = f.kind || fieldKind(f.name);
  const max = f.maxCandidates || MAX_CANDIDATES;
  const words = labelWords(f.label || f.name);
  const lines = text.split(/\r?\n/);
  // Closeness to the label: 2 = on the label's own line, 1 = wrapped 1-3 lines below
  // or 1-3 lines above it ("Total\n14\n197.450"), 0 = elsewhere. The value may repeat; any line counts.
  const nearScore = (v) => {
    let best = 0;
    if (!words.length) return 0;
    for (let i = 0; i < lines.length; i++) {
      if (!lines[i].includes(v)) continue;
      const ll = lines[i].toLowerCase();
      if (words.some((w) => ll.includes(w))) return 2;
      for (let k = Math.max(0, i - 3); k <= Math.min(lines.length - 1, i + 3); k++) {
        if (words.some((w) => lines[k].toLowerCase().includes(w))) best = Math.max(best, 1);
      }
    }
    return best;
  };
  let cands = [];
  if (kind === "amount") cands = moneyCandidates(text);
  else if (kind === "date") cands = matches(DATE_TOKEN, text);
  else if (kind === "id") {
    cands = [...matches(ID_TOKEN, text), ...matches(PHONE_TOKEN, text)];
    // A bare small number is only plausible on its label's own line ("Number of pages ... 3").
    cands.push(...matches(SMALL_NUM, text).filter((v) => nearScore(v) === 2));
  } else if (kind === "text") {
    cands = [...lineCandidates(text)];
    for (const l of lines) {
      const m = PAIR_VALUE.exec(l.replace(/\s+/g, " ").trim());
      if (m && m[1].length <= 60 && /[A-Za-z]/.test(m[1])) cands.push(m[1]);
    }
    cands.push(...matches(TITLE_PHRASE, text));
  } else {
    cands = [...moneyCandidates(text), ...matches(DATE_TOKEN, text), ...matches(ID_TOKEN, text), ...lineCandidates(text)];
  }
  const uniq = [...new Set(cands)];
  // Stable label-closeness boost: same-line first, then wrapped-near, then the rest in document order.
  const scored = uniq.map((v) => [nearScore(v), v]);
  scored.sort((a, b) => b[0] - a[0]);
  return scored.map(([, v]) => v).slice(0, max);
}

/** One noul question per (field, candidate): "Does the document give X as the <field>?" */
export function buildExtractQuestions(fields, document) {
  const questions = {};
  const map = fields.map((f0, i) => {
    const f = typeof f0 === "string" ? { name: f0 } : f0;
    const what = (f.label || f.name || "field").replace(/_/g, " ");
    const cands = candidateSpans(document, f);
    cands.forEach((c, j) => {
      const v = String(c);
      questions[`f${i}c${j}`] = {
        type: "noul",
        instructions: `Does the document give "${v}" as the ${what}?`,
        criteria: {
          true: `The document states the ${what} as "${v}" (formatting aside).`,
          false: `The document gives a different ${what}, or does not give one.`,
        },
      };
    });
    return { field: f, candidates: cands };
  });
  return { questions, map };
}

/** Ask real Jev to pick each field's value out of its candidate spans. One request for all fields. */
export async function extractByVerification({ document, fields, minConfidence = MIN_CONFIDENCE, ...opts }) {
  const list = fields.map((f) => (typeof f === "string" ? { name: f } : f));
  const { questions, map } = buildExtractQuestions(list, document);
  const empty = map.map(({ field, candidates }) => ({
    field: field.name, ...(field.label ? { label: field.label } : {}),
    value: null, confidence: null, jev: { type: "extract", candidates: candidates.length, top: null },
  }));
  if (!Object.keys(questions).length) return { items: empty, usage: null, model: null };
  const res = await askJev({ state: document, questions, ...opts });
  const answers = res.answers || {};
  const items = map.map(({ field, candidates }, i) => {
    let best = null;
    candidates.forEach((c, j) => {
      const a = answers[`f${i}c${j}`];
      if (!a) return;
      // For a noul answer the raw probability IS "the document gives this": certainty
      // would score a confidently-wrong candidate as high as a confidently-right one.
      const p = a.type === "noul" && a.noul != null ? Number(a.noul) : Number(normalize(a).certainty);
      if (!Number.isFinite(p)) return;
      if (!best || p > best.p) best = { c, p };
    });
    const extra = field.label ? { label: field.label } : {};
    if (!best) return { field: field.name, ...extra, value: null, confidence: null, jev: { type: "extract", candidates: candidates.length, top: null } };
    const keep = best.p >= minConfidence;
    return {
      field: field.name, ...extra,
      value: keep ? best.c : null, confidence: best.p,
      jev: { type: "extract", candidates: candidates.length, top: best.c, abstained: !keep },
    };
  });
  return { items, usage: res.usage || null, model: res.model || null };
}
