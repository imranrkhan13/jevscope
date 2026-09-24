// Ask Jev (TypeSafe's decision model) to check extracted values. Glue code:
// the judgement is Jev's; turning Jev's answer into one number uses the port of
// jevscope's certainty.py. Bring your own key; nothing here stores it.
import { normalize } from "./certainty.js";

// Per each provider's docs: https://docs.typesafe.ai/api.md ,
// https://venice.ai/lp/jev , https://openrouter.ai/docs/guides/community/jev
export const JEV_PROVIDERS = Object.freeze({
  typesafe: { url: "https://api.typesafe.ai/v1/systemone", model: "jev-latest" },
  venice: { url: "https://api.venice.ai/api/v1/decisions", model: "jev-latest" },
  openrouter: { url: "https://openrouter.ai/api/alpha/decisions", model: "~typesafe/jev-latest" },
});
export const NOT_STATED = "not_stated";
export const MAX_OPTIONS = 254;
export const MAX_DISCOVERED = 50;

// Same patterns as the Python discover_fields.
const LINE = /^\s*([A-Za-z][A-Za-z0-9 .&/()'\-]{0,39}?)\s*(?::|#|\bNo\.?(?=\s)|\bNumber\b)\s*(.+?)\s*$/;
const AMOUNT = /^\s*([A-Za-z][A-Za-z0-9 %.]{1,30}?)\s+((?:[^\w\s]{1,3}\s?)?\d[\d,]*(?:\.\d+)?)\s*$/;
const snake = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "field";

// Vendor and currency are asked about on every invoice-like document, even when
// no line labels them: the vendor is often just the letterhead, and the currency
// is often only a symbol. Jev picks from the candidates (or says not_stated).
const INVOICE_HINT = /\b([il1]nvo[il1]ce|receipt|bill|amount due|t[o0]tal|payable|remit)\b/i;
const VENDOR_NAME = /^(vendor|vendor_name|seller|supplier|merchant|sold_by|issued_by)$/;
const VENDOR_LABEL = /^\s*(vendor|seller|supplier|merchant|payee|from|issued by|sold by|remit(?:\s+payment)?\s+to|remit address|send payment to|pay to|checks? (?:are )?payable to|make checks payable to)\b\s*[:\-]?\s*(.*)$/i;
const COMPANY = /\b(inc|llc|l\.l\.c|ltd|pvt|limited|corp|corporation|co|company|gmbh|plc|llp|group|media|communications|broadcast(?:ing)?|traders|studio|logistics|supplies|services|enterprises|industries|solutions|tv)\b\.?/i;
const NOT_VENDOR = /^(tax\s+)?(invoice|receipt|bill|statement|page|date|due|total|sub\s*total|amount|thank|description|qty|quantity|terms|bill\s*to|ship\s*to|attn|attention|phone|ph|fax|email|main|billing|remit|mail to|send payment|p\.?\s*o\.?\s*box)\b/i;
export const CURRENCY_HINTS = Object.freeze({
  INR: "Indian rupees (₹, Rs or INR)",
  USD: "US dollars ($, US$ or USD)",
  EUR: "euros (€ or EUR)",
  GBP: "British pounds (£ or GBP)",
  AED: "UAE dirhams (AED)",
  SGD: "Singapore dollars (S$ or SGD)",
  AUD: "Australian dollars (A$ or AUD)",
  CAD: "Canadian dollars (C$ or CAD)",
  JPY: "Japanese yen (¥ or JPY)",
  CNY: "Chinese yuan (CN¥, RMB or CNY)",
});
const MAX_VENDOR_OPTIONS = 8;

/** Candidate vendor names: labelled "From / Remit to" values, the letterhead lines, and company-looking lines. */
export function vendorCandidates(text, max = MAX_VENDOR_OPTIONS) {
  const lines = String(text || "").split(/\r?\n/).map((l) => l.replace(/\s+/g, " ").trim());
  const out = [];
  const seen = new Set();
  const add = (v) => {
    v = String(v || "").replace(/[:\-\s]+$/, "").trim();
    if (v.length < 2 || v.length > 60 || !/[A-Za-z]{2}/.test(v) || NOT_VENDOR.test(v)) return;
    if ((v.match(/\d/g) || []).length > v.length / 3) return;
    const k = v.toLowerCase();
    if (seen.has(k) || out.length >= max) return;
    seen.add(k);
    out.push(v);
  };
  lines.forEach((l, i) => {
    const m = l.match(VENDOR_LABEL);
    if (!m) return;
    if (m[2]) add(m[2]);
    else add(lines.slice(i + 1).find((x) => x));
  });
  lines.filter((l) => l).slice(0, 3).forEach(add);
  lines.forEach((l) => { if (COMPANY.test(l) && !VENDOR_LABEL.test(l)) add(l); });
  return out;
}

/** Vendor and currency questions for invoice-like text, unless a labelled field already covers them. */
export function coreFields(text, found = []) {
  const t = String(text || "");
  if (!INVOICE_HINT.test(t)) return [];
  const names = found.map((f) => f.name);
  const out = [];
  if (!names.some((n) => VENDOR_NAME.test(n))) {
    const options = vendorCandidates(t);
    if (options.length) out.push({ name: "vendor", label: "Vendor", description: "the business that issued this document and gets paid, not the customer or bill-to party", options, core: true });
  }
  if (!names.some((n) => /currency/.test(n))) {
    const seenCodes = Object.keys(CURRENCY_HINTS).filter((c) => new RegExp(`\\b${c}\\b`).test(t));
    const sym = [["₹", "INR"], ["Rs", "INR"], ["€", "EUR"], ["£", "GBP"], ["$", "USD"], ["¥", "JPY"]].filter(([s]) => t.includes(s)).map(([, c]) => c);
    const options = [...new Set([...seenCodes, ...sym, ...Object.keys(CURRENCY_HINTS)])];
    out.push({ name: "currency", label: "Currency", description: "the currency the amounts are in", options, hints: CURRENCY_HINTS, core: true });
  }
  return out;
}

/** Find every "Label: value" style field, with no field list given, plus vendor and currency on invoice-like text. Jev then checks each. */
export function discoverFields(text, limit = MAX_DISCOVERED) {
  const found = [];
  const seen = new Set();
  for (const line of String(text || "").split(/\r?\n/)) {
    const m = line.match(LINE) || line.match(AMOUNT);
    if (!m) continue;
    const label = m[1].trim();
    const value = m[2].trim();
    if (!value || value.length > 200 || label.length < 2) continue;
    let name = snake(label);
    const base = name;
    for (let k = 2; seen.has(name); k++) name = `${base}_${k}`;
    seen.add(name);
    found.push({ name, label, value });
  }
  const core = coreFields(text, found);
  return [...core, ...found].slice(0, Math.max(limit, core.length));
}

const describe = (f) => {
  const d = String(f.description || "").trim();
  return d ? `${f.name} (${d})` : String(f.name);
};
// Jev option keys stay short and plain; other option text gets a key like "o3".
const SAFE_KEY = /^[A-Za-z0-9_\-]{1,64}$/;
export const optionKey = (o, j) => (SAFE_KEY.test(o) && o !== NOT_STATED ? o : `o${j}`);
const isBlank = (v) => v == null || (typeof v === "string" && !v.trim());

/** One Jev question per field: choice when the field has options, else a noul on the candidate value. */
export function buildQuestions(fields) {
  const questions = {};
  fields.forEach((f, i) => {
    const what = describe(f);
    if (Array.isArray(f.options) && f.options.length) {
      const opts = f.options.map(String);
      if (opts.length > MAX_OPTIONS) throw new RangeError(`${f.name}: at most ${MAX_OPTIONS} options`);
      const criteria = {};
      const hints = f.hints || {};
      opts.forEach((o, j) => {
        criteria[optionKey(o, j)] = hints[o] ? `The ${f.name} is ${o}: ${hints[o]}.` : `The document gives "${o}" as the ${what}.`;
      });
      criteria[NOT_STATED] = `The document does not give a ${what}, or gives something not listed.`;
      questions[`f${i}`] = { type: "choice", instructions: `Which ${what} does the document give?`, criteria };
      return;
    }
    if (isBlank(f.value)) return;
    const v = typeof f.value === "string" ? f.value : JSON.stringify(f.value);
    questions[`f${i}`] = {
      type: "noul",
      instructions: `Does the document give "${v}" as the ${what}?`,
      criteria: {
        true: `The document states the ${what} as "${v}" (formatting aside).`,
        false: `The document gives a different ${what}, or does not give one.`,
      },
    };
  });
  return questions;
}

/** Jev answers -> JevAPI items { field, value, confidence, jev }. */
export function answersToItems(fields, answers = {}) {
  return fields.map((f, i) => {
    const a = answers[`f${i}`];
    const extra = f.label ? { label: f.label } : {};
    if (!a) return { field: f.name, ...extra, value: f.value ?? null, confidence: null, jev: null };
    const n = normalize(a);
    if (n.answerType === "noul") {
      const p = Number(a.noul);
      return { field: f.name, ...extra, value: f.value ?? null, confidence: p, jev: { type: "noul", noul: p, certainty: n.certainty } };
    }
    if (n.answerType === "choice") {
      const probs = a.probabilities || {};
      const p = n.prediction in probs ? Number(probs[n.prediction]) : n.certainty;
      const opts = (f.options || []).map(String);
      const j = opts.findIndex((o, k) => optionKey(o, k) === n.prediction);
      const picked = j >= 0 ? opts[j] : n.prediction;
      return {
        field: f.name,
        ...extra,
        value: n.prediction === NOT_STATED ? null : picked,
        confidence: p,
        jev: { type: "choice", choice: n.prediction === NOT_STATED ? NOT_STATED : picked, confidence: n.reportedConfidence, certainty: n.certainty },
      };
    }
    return { field: f.name, ...extra, value: n.prediction, confidence: n.certainty, jev: { type: "score", certainty: n.certainty } };
  });
}

export class JevError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "JevError";
    this.status = status;
  }
}

/** POST one request to Jev. Returns the parsed JSON ({ answers, usage, model }). */
export async function askJev({ state, questions, key, provider = "typesafe", model, fetchImpl = globalThis.fetch, timeoutMs = 30000 }) {
  const cfg = JEV_PROVIDERS[provider];
  if (!cfg) throw new RangeError(`provider must be one of ${Object.keys(JEV_PROVIDERS).join(", ")}`);
  if (!key) throw new TypeError("a Jev key is required (bring your own)");
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), timeoutMs);
  try {
    const r = await fetchImpl(cfg.url, {
      method: "POST",
      signal: c.signal,
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: model || cfg.model, state, questions }),
    });
    let j = null;
    try {
      j = await r.json();
    } catch {
      j = null;
    }
    if (!r.ok) {
      const detail = j && (j.error?.message || j.detail || j.message);
      throw new JevError(`Jev (${provider}) returned HTTP ${r.status}${detail ? `: ${String(typeof detail === "string" ? detail : JSON.stringify(detail)).slice(0, 300)}` : ""}`, r.status);
    }
    return j || {};
  } catch (e) {
    if (e.name === "AbortError") throw new JevError(`Jev (${provider}) took longer than ${timeoutMs / 1000}s`, 504);
    throw e;
  } finally {
    clearTimeout(t);
  }
}

/** Ask Jev about every field in one request; returns { items, usage, model }. No fields -> discoverFields first. */
export async function checkFields({ document, fields, ...opts }) {
  const list = fields == null ? discoverFields(document) : fields;
  const questions = buildQuestions(list);
  if (!Object.keys(questions).length) return { items: answersToItems(list, {}), usage: null, model: null };
  const res = await askJev({ state: document, questions, ...opts });
  return { items: answersToItems(list, res.answers || {}), usage: res.usage || null, model: res.model || null };
}
