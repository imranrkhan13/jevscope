// POST /api/v1/verify: Jev checks each candidate value against the document,
// then JevAPI decides fill or review. Header: X-Jev-Key (your own TypeSafe key).
// Leave out "fields" and JevAPI finds every "Label: value" field in the text first.
import { checkFields, decideAll, validateProfile } from "../../jevapi/js/src/index.js";
import { endpoint, LIMITS, RATE, badRequest } from "../_lib/http.js";
import { cleanOptions, listOf } from "../_lib/validate.js";
import { jevConfig, jevFailure, jevKey } from "../_lib/jev.js";

export function cleanJevFields(v) {
  return listOf(v, "fields", LIMITS.fields).map((f, i) => {
    if (!f || typeof f.name !== "string" || !/^[\w.\- ]{1,60}$/.test(f.name)) throw badRequest(`fields[${i}].name must be a short name`);
    const out = { name: f.name };
    if (typeof f.description === "string") out.description = f.description.slice(0, 300);
    if (f.options != null) {
      if (!Array.isArray(f.options) || !f.options.length || f.options.length > 254 || !f.options.every((o) => typeof o === "string" && o.length <= 100)) {
        throw badRequest(`fields[${i}].options must be 1-254 short strings`);
      }
      out.options = f.options;
    } else {
      const val = f.value;
      if (val != null && !["string", "number", "boolean"].includes(typeof val)) throw badRequest(`fields[${i}].value must be text, a number or true/false`);
      if (typeof val === "string" && val.length > 500) throw badRequest(`fields[${i}].value is too long`);
      out.value = val ?? null;
    }
    return out;
  });
}

export function parseProfile(p) {
  if (p == null) return null;
  try {
    return validateProfile(p);
  } catch (e) {
    throw badRequest(`profile: ${e.message}`, "bad_profile");
  }
}

export function makeVerify(fetchImpl) {
  return endpoint({ bucket: "jev", rate: RATE.extract }, async (body, req) => {
    const key = jevKey(req);
    if (!key) throw badRequest("Send your own Jev key (from TypeSafe) in the X-Jev-Key header. JevAPI's code doesn't store keys.", "missing_key");
    const cfg = jevConfig(body);
    if (typeof body.text !== "string" || !body.text.trim()) throw badRequest("text must be the document's text (read PDFs in your app first)");
    if (body.text.length > LIMITS.textChars) throw badRequest(`text is ${body.text.length} characters; the hosted API takes at most ${LIMITS.textChars}`);
    const discovered = body.fields == null;
    const fields = discovered ? null : cleanJevFields(body.fields);
    const profile = parseProfile(body.profile);
    let out;
    try {
      out = await checkFields({ document: body.text, fields, key, ...cfg, fetchImpl });
    } catch (e) {
      throw jevFailure(e);
    }
    const result = decideAll(profile, out.items, cleanOptions(body.options));
    return [200, {
      judge: "jev",
      discovered,
      jevModel: out.model,
      usage: out.usage,
      fields: out.items,
      ...result,
      calibrated: !!profile,
      note: (discovered ? (out.items.length ? `No field list sent: found ${out.items.length} fields in the text (labelled lines, plus vendor and currency on invoices). ` : "No field list sent and no labelled fields found; send fields, or use /api/v1/extract with your AI key. ") : "") +
        (profile ? "Jev's probabilities were calibrated with your profile." : "No profile sent: these are Jev's raw probabilities. Measure them on your own labelled documents with /api/v1/calibrate before trusting them."),
    }];
  });
}

export default makeVerify((...a) => fetch(...a));
