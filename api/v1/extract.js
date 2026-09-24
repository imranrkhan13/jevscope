import { checkFields, decideAll, validateProfile } from "../../jevapi/js/src/index.js";
import { jevConfig, jevFailure, jevKey } from "../_lib/jev.js";
import { endpoint, LIMITS, RATE, badRequest } from "../_lib/http.js";
import { cleanOptions, listOf } from "../_lib/validate.js";
import { PROVIDERS, buildPrompt, callProvider, parseExtraction } from "../_lib/providers.js";

export function makeExtract(fetchImpl) {
  return endpoint({ bucket: "extract", rate: RATE.extract }, async (body, req) => {
    const key = String((req.headers || {})["x-provider-key"] || "").trim();
    if (!key) throw badRequest("Send your own AI key in the X-Provider-Key header. JevAPI's code doesn't store keys.", "missing_key");
    if (!PROVIDERS.includes(body.provider)) throw badRequest(`provider must be one of ${PROVIDERS.join(", ")}`);
    if (typeof body.model !== "string" || !/^[\w.\-:/@]{1,100}$/.test(body.model)) throw badRequest("model must be your provider's model id");
    if (typeof body.text !== "string" || !body.text.trim()) throw badRequest("text must be the document's text (read PDFs in your app first)");
    if (body.text.length > LIMITS.textChars) throw badRequest(`text is ${body.text.length} characters; the hosted API takes at most ${LIMITS.textChars}`);
    // No "fields": the AI is asked to extract every field it can find.
    const fields = body.fields == null ? null : listOf(body.fields, "fields", LIMITS.fields).map((f, i) => {
      if (!f || typeof f.name !== "string" || !/^[\w.\- ]{1,60}$/.test(f.name)) throw badRequest(`fields[${i}].name must be a short name`);
      return { name: f.name, description: typeof f.description === "string" ? f.description.slice(0, 300) : "", type: typeof f.type === "string" ? f.type.slice(0, 30) : "" };
    });
    let profile = null;
    if (body.profile != null) {
      try {
        profile = validateProfile(body.profile);
      } catch (e) {
        throw badRequest(`profile: ${e.message}`, "bad_profile");
      }
    }
    const reply = await callProvider({ provider: body.provider, model: body.model, key, prompt: buildPrompt(body.text, fields), fetchImpl });
    let extracted = parseExtraction(reply, fields);
    // judge: "jev" -> Jev checks each value the AI read; Jev's probability replaces the AI's self-reported confidence.
    let jev = null;
    if (body.judge === "jev") {
      const jkey = jevKey(req);
      if (!jkey) throw badRequest('judge "jev" needs your Jev key (from TypeSafe) in the X-Jev-Key header.', "missing_jev_key");
      const cfg = jevConfig(body);
      const toCheck = extracted.map((x) => ({ name: x.field, value: x.value, description: ((fields || []).find((f) => f.name === x.field) || {}).description }));
      try {
        jev = await checkFields({ document: body.text, fields: toCheck, key: jkey, ...cfg, fetchImpl });
      } catch (e) {
        throw jevFailure(e);
      }
      extracted = extracted.map((x, i) => ({ ...x, aiConfidence: x.confidence, confidence: jev.items[i].confidence, jev: jev.items[i].jev }));
    } else if (body.judge != null) {
      throw badRequest('judge must be "jev" or left out');
    }
    const result = decideAll(profile, extracted, cleanOptions(body.options));
    return [
      200,
      {
        judge: jev ? "jev" : "self-reported",
        discovered: !fields,
        ...(jev ? { jevModel: jev.model, jevUsage: jev.usage } : {}),
        fields: extracted,
        ...result,
        calibrated: !!profile,
        note: profile
          ? "Confidence was calibrated with your profile."
          : "No profile sent: these are the model's own confidences, which are often too high. Calibrate with /api/v1/calibrate.",
      },
    ];
  });
}

export default makeExtract((...a) => fetch(...a));
