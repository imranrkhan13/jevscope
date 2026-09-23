import { LIMITS, badRequest } from "./http.js";

const OPTION_KEYS = ["costError", "costReview", "reviewAccuracy", "maxRisk", "minExamples", "conservative"];

// Keep only known numeric/boolean options; functions (validate) can't come over HTTP anyway.
export function cleanOptions(o, where = "options") {
  if (o == null) return {};
  if (typeof o !== "object" || Array.isArray(o)) throw badRequest(`${where} must be an object`);
  const out = {};
  for (const k of OPTION_KEYS) {
    if (o[k] === undefined) continue;
    const v = o[k];
    if (k === "conservative") {
      if (typeof v !== "boolean") throw badRequest(`${where}.${k} must be true or false`);
    } else if (k === "maxRisk" && v === null) {
      // allowed
    } else if (typeof v !== "number" || !Number.isFinite(v)) {
      throw badRequest(`${where}.${k} must be a number`);
    }
    out[k] = v;
  }
  if (o.fields !== undefined) {
    if (typeof o.fields !== "object" || Array.isArray(o.fields) || o.fields === null) throw badRequest(`${where}.fields must be an object`);
    const keys = Object.keys(o.fields);
    if (keys.length > LIMITS.fields) throw badRequest(`at most ${LIMITS.fields} fields`);
    out.fields = {};
    for (const name of keys) out.fields[name] = cleanOptions(o.fields[name], `${where}.fields.${name}`);
  }
  return out;
}

export function listOf(v, name, max) {
  if (!Array.isArray(v)) throw badRequest(`${name} must be an array`);
  if (v.length === 0) throw badRequest(`${name} is empty`);
  if (v.length > max) throw badRequest(`${name} has ${v.length} entries; the hosted API takes at most ${max}. Use the free package locally for more.`);
  return v;
}
