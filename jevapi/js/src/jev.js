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

/** Find every "Label: value" style field, with no field list given. Jev then checks each. */
export function discoverFields(text, limit = MAX_DISCOVERED) {
  const out = [];
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
    out.push({ name, label, value });
    if (out.length >= limit) break;
  }
  return out;
}

const describe = (f) => {
  const d = String(f.description || "").trim();
  return d ? `${f.name} (${d})` : String(f.name);
};
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
      for (const o of opts) criteria[o] = `The document gives ${o} as the ${what}.`;
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
      return {
        field: f.name,
        ...extra,
        value: n.prediction === NOT_STATED ? null : n.prediction,
        confidence: p,
        jev: { type: "choice", choice: n.prediction, confidence: n.reportedConfidence, certainty: n.certainty },
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
