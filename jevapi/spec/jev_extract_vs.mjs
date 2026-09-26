// Jev vs Lev, head-to-head on extraction by verification: the SAME questions and
// candidate spans go to real Jev (TypeSafe, baked this same ship into
// web/jevapi/samples_extract.json) and to a real local Lev server
// (jlt-commons/lev, Apache-2.0; encoder checkpoint convaiinnovations/laya,
// Apache-2.0). Lev runs encoder-only: no thinker, no escalation.
// Needs a Lev server on LEV_URL (default http://127.0.0.1:8080); without one the
// ship stops, like the live Jev check. Writes web/jevapi/samples_vs.json.
import { readFileSync, writeFileSync } from "node:fs";
import { buildExtractQuestions } from "../js/src/index.js";
import { DEFAULT_FIELDS, SAMPLES } from "../../web/jevapi/samples.js";

const LEV_URL = process.env.LEV_URL || "http://127.0.0.1:8080";
const LEV_MODEL = process.env.LEV_MODEL || "english";
const KEEP = 0.5; // same abstain bar as extractByVerification's MIN_CONFIDENCE

const norm = (v) => String(v ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
const match = (value, gold) => norm(value) != "" && norm(value) === norm(gold);

const health = await fetch(`${LEV_URL}/health`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
if (!health || health.status !== "ok") {
  console.error(`No Lev server on ${LEV_URL} (GET /health failed). The Jev vs Lev bake needs it; not shipping.`);
  process.exit(1);
}
console.log(`Lev server: ${JSON.stringify(health.loaded || health.model || "ok")}`);

const xb = JSON.parse(readFileSync(new URL("../../web/jevapi/samples_extract.json", import.meta.url), "utf8"));
if (!xb.samples || !Object.keys(xb.samples).length) throw new Error("samples_extract.json missing or empty - the live Jev bake runs first in the same ship");

const out = {
  checkedAt: new Date().toISOString().slice(0, 10),
  how: "Extraction by verification: identical candidate spans and noul questions to both models. Jev: hosted TypeSafe model, baked this same ship. Lev: jlt-commons/lev v0.2.0, encoder checkpoint convaiinnovations/laya (english, ModernBERT-large, 512-token context), run locally in the ship job, no thinker and no escalation. Both sides keep a value only at raw probability >= 0.5, else abstain. Gold = the sample's hand-set values.",
  jev: { model: xb.model, where: "hosted TypeSafe API" },
  lev: { model: LEV_MODEL, repo: "https://github.com/jlt-commons/lev", weights: "https://huggingface.co/convaiinnovations/laya" },
  samples: {},
  totals: { fields: 0, jevRight: 0, levRight: 0, bothRight: 0, neither: 0, jevAbstain: 0, levAbstain: 0 },
};

for (const [id, baked] of Object.entries(xb.samples)) {
  const smp = SAMPLES.find((x) => x.id === id);
  if (!smp || !smp.extracted) continue;
  const fields = smp.extracted.map((x) => ({ name: x.field, label: x.label || (DEFAULT_FIELDS.find((f) => f.name === x.field) || {}).label || x.field.replace(/_/g, " ") }));
  const { questions, map } = buildExtractQuestions(fields, smp.text);
  // Ask in chunks: one call carrying every question (160+ on the big samples) can
  // kill the encoder process; 24 per call stays light on a CPU runner.
  const CHUNK = 24;
  const ids = Object.keys(questions);
  const answers = {};
  let truncated = null;
  for (let off = 0; off < ids.length; off += CHUNK) {
    const part = Object.fromEntries(ids.slice(off, off + CHUNK).map((k) => [k, questions[k]]));
    let res = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      res = await fetch(`${LEV_URL}/v1/systemone`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: smp.text, questions: part, model: LEV_MODEL }),
      }).then((r) => r.json().then((j) => ({ ok: r.ok, j }))).catch((e) => ({ ok: false, j: { error: String(e) } }));
      if (res.ok && res.j.answers) break;
      await new Promise((r) => setTimeout(r, 5000));
    }
    if (!res || !res.ok || !res.j.answers) throw new Error(`Lev failed on sample ${id} (questions ${off}-${off + part.length ? Object.keys(part).length : 0}): ${JSON.stringify(res && res.j).slice(0, 300)}`);
    Object.assign(answers, res.j.answers);
    if (res.j.truncated) truncated = { ...(truncated || {}), ...res.j.truncated };
  }

  const row = { fields: [], jevRight: 0, levRight: 0, bothRight: 0, neither: 0, jevAbstain: 0, levAbstain: 0 };
  map.forEach(({ field, candidates }, i) => {
    let best = null;
    candidates.forEach((c, j) => {
      const a = answers[`f${i}c${j}`];
      if (!a) return;
      const p = a.type === "noul" && a.noul != null ? Number(a.noul) : null;
      if (p == null || !Number.isFinite(p)) return;
      if (!best || p > best.p) best = { c, p };
    });
    const gold = (smp.extracted.find((x) => x.field === field.name) || {}).value ?? null;
    const jevSide = baked.fields.find((x) => x.field === field.name) || { value: null, confidence: null };
    const levValue = best && best.p >= KEEP ? best.c : null;
    const levP = best ? best.p : null;
    const jOk = match(jevSide.value, gold);
    const lOk = match(levValue, gold);
    row.jevRight += jOk ? 1 : 0; row.levRight += lOk ? 1 : 0;
    row.bothRight += jOk && lOk ? 1 : 0; row.neither += !jOk && !lOk ? 1 : 0;
    row.jevAbstain += jevSide.value == null ? 1 : 0; row.levAbstain += levValue == null ? 1 : 0;
    row.fields.push({
      field: field.name, label: field.label, gold,
      jev: { value: jevSide.value, confidence: jevSide.confidence, right: jOk },
      lev: { value: levValue, confidence: levP, right: lOk, truncated: !!(truncated && (truncated[`f${i}c0`] != null || Object.keys(truncated).some((k) => k.startsWith(`f${i}c`)))) },
    });
  });
  out.samples[id] = row;
  out.totals.fields += row.fields.length;
  for (const k of ["jevRight", "levRight", "bothRight", "neither", "jevAbstain", "levAbstain"]) out.totals[k] += row[k];
  console.log(`${id}: Jev ${row.jevRight}/${row.fields.length} right, Lev ${row.levRight}/${row.fields.length} right${truncated ? " (Lev truncated some questions: 512-token context)" : ""}`);
}
console.log(`TOTAL: Jev ${out.totals.jevRight}/${out.totals.fields}, Lev ${out.totals.levRight}/${out.totals.fields}; both ${out.totals.bothRight}, neither ${out.totals.neither}; abstains Jev ${out.totals.jevAbstain}, Lev ${out.totals.levAbstain}`);
writeFileSync(new URL("../../web/jevapi/samples_vs.json", import.meta.url), JSON.stringify(out, null, 2) + "\n");
console.log("Wrote web/jevapi/samples_vs.json");
