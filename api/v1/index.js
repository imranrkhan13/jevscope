import { endpoint, LIMITS, RATE } from "../_lib/http.js";
import { PROVIDERS } from "../_lib/providers.js";

export default endpoint({ methods: ["GET"], bucket: "info" }, async () => [
  200,
  {
    name: "JevAPI",
    version: "v1",
    about: "Should this extracted field be filled automatically, or checked by a person? Calibrated on your own examples.",
    docs: "https://jevscope.vercel.app/jevapi/docs",
    source: "https://github.com/imranrkhan13/jevscope",
    endpoints: {
      "POST /api/v1/calibrate": "{ examples: [{field, confidence, correct}], options?, evaluate? } -> { profile, evaluation? }",
      "POST /api/v1/decide": "{ profile?, items: [{field, value, confidence}], options? } -> { decisions, fill, review }",
      "POST /api/v1/verify": "{ text, fields?: [{name, value} | {name, options: [...]}], profile?, options?, jevProvider?, jevModel? } + header X-Jev-Key -> Jev checks every field (no fields: every labelled field is found first) -> { fields, decisions }",
      "POST /api/v1/extract": `{ provider: ${PROVIDERS.join("|")}, model, text, fields?: [{name, description?, type?}], judge?: "jev", profile?, options? } + header X-Provider-Key (+ X-Jev-Key when judge is jev); no fields = extract every field -> { fields, decisions }`,
    },
    jev: "Jev is TypeSafe's decision model (https://docs.typesafe.ai). JevAPI sends it one request per document with one yes/no or choice question per field, using your own key.",
    limits: { ...LIMITS, requestsPerMinute: { calibrate_and_decide: RATE.math, extract: RATE.extract, verify: RATE.extract } },
    privacy: "Stateless. JevAPI keeps nothing you send. Your AI and Jev keys pass through this server (hosted on Vercel) for one request; our code never saves or logs them. If that is not good enough, run the open-source package yourself.",
    free: "Free, no sign-up. Limits are per server and best effort. For heavy use, run the open-source package yourself.",
  },
]);
