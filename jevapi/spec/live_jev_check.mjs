// Live smoke test against the real Jev (TypeSafe). Needs TYPESAFE_API_KEY.
// Uses the three SYNTHETIC sample invoices with hand-written right and wrong
// candidate values, plus one run with no field list (auto-discovery). It checks
// that the integration works end to end and prints what Jev said. This is a
// smoke test, not a calibration study.
import { checkFields, decideAll, discoverFields } from "../js/src/index.js";
import { SAMPLES } from "../../web/jevapi/samples.js";
import { readFileSync } from "node:fs";

// Real public invoices (FCC public files, via RealKIE-FCC-Verified, CC BY-NC 4.0; see real_invoices.json).
const REAL = JSON.parse(readFileSync(new URL("./real_invoices.json", import.meta.url), "utf8"));
// SYNTHETIC resumes with hand labels (resumes.json).
const RESUMES = JSON.parse(readFileSync(new URL("./resumes.json", import.meta.url), "utf8"));
// The real-invoice run costs about 11k tokens, so it is off the per-ship gate: run it on demand with JEV_REAL_INVOICES=1.
const RUN_REAL = process.env.JEV_REAL_INVOICES === "1";

const key = process.env.TYPESAFE_API_KEY;
if (!key) {
  if (process.env.REQUIRE_LIVE_JEV) {
    console.error("TYPESAFE_API_KEY is not set, and this run requires a real Jev check. Not shipping.");
    process.exit(1);
  }
  console.log("TYPESAFE_API_KEY not set; skipping live Jev check.");
  process.exit(0);
}
const TRUTH = {
  clean: { vendor_name: ["Acme Supplies Pvt Ltd", "Kiran Traders"], invoice_number: ["INV-2231", "INV-2213"], total_amount: ["48,200.00", "1,205.00"] },
  messy: { vendor_name: ["North Star Logistics", "Mumbai Freight"], invoice_number: ["NS-8819", "NS-8891"], total_amount: ["25,311", "21,450"] },
  missing: { vendor_name: ["Blue Lotus Design Studio", "Lotus Traders"], invoice_number: ["BL-104", "BL-140"], due_date: [null, "2026-10-15"] },
};
let right = 0, total = 0, tokens = 0, requests = 0;
const rows = [];
try {
  for (const s of SAMPLES) {
    const t = TRUTH[s.id];
    if (!t) continue;
    const fields = [];
    const labels = [];
    for (const [name, [good, bad]] of Object.entries(t)) {
      if (good != null) { fields.push({ name, value: good }); labels.push(true); }
      fields.push({ name, value: bad }); labels.push(false);
    }
    fields.push({ name: "currency", options: ["INR", "USD", "EUR"] });
    labels.push(s.id === "messy" ? "not_stated|INR" : "INR");
    const out = await checkFields({ document: s.text, fields, key, provider: "typesafe" });
    requests += 1;
    tokens += out.usage?.input_tokens || 0;
    out.items.forEach((it, i) => {
      if (typeof it.confidence !== "number" || it.confidence < 0 || it.confidence > 1) throw new Error(`bad answer for ${s.id}/${it.field}: ${JSON.stringify(it)}`);
      const want = labels[i];
      const ok = typeof want === "boolean" ? (it.confidence >= 0.5) === want : want.split("|").includes(it.jev.choice);
      right += ok ? 1 : 0; total += 1;
      rows.push(`${ok ? "ok  " : "MISS"} ${s.id.padEnd(8)} ${it.field.padEnd(15)} ${String(it.value ?? it.jev.choice).padEnd(26)} jev=${it.confidence.toFixed(3)} (${it.jev.type}${typeof want === "boolean" ? `, truth=${want}` : `, want ${want}`})`);
    });
    console.log(`${s.id}: model ${out.model}, decisions ${JSON.stringify(decideAll(null, out.items).decisions.map((d) => d.action))}`);
  }
  // No field list: find every labelled field, then Jev checks each.
  const disc = await checkFields({ document: SAMPLES[0].text, fields: null, key, provider: "typesafe" });
  requests += 1;
  tokens += disc.usage?.input_tokens || 0;
  if (!disc.items.length || disc.items.some((it) => typeof it.confidence !== "number")) throw new Error("discovery run returned no usable Jev answers");
  console.log(rows.join("\n"));
  console.log("\nNo field list (clean invoice), fields found and Jev's yes-probability:");
  for (const it of disc.items) console.log(`  ${it.field.padEnd(14)} ${String(it.value).padEnd(32)} jev=${it.confidence.toFixed(3)}`);
  if (!disc.items.some((it) => it.field === "vendor") || !disc.items.some((it) => it.field === "currency")) throw new Error("discovery did not ask about vendor and currency");

  // Synthetic resume A, no field list: resume mode finds every detail, Jev checks each.
  {
    const r = RESUMES.resumes[0];
    const found = discoverFields(r.text);
    const gold = Object.keys(r.gold);
    const missing = gold.filter((k) => !found.some((f) => f.name === k && f.value === r.gold[k]));
    if (missing.length) throw new Error(`resume mode missed ${missing.join(", ")}`);
    const out = await checkFields({ document: r.text, fields: found, key, provider: "typesafe" });
    requests += 1;
    tokens += out.usage?.input_tokens || 0;
    if (out.items.some((it) => typeof it.confidence !== "number")) throw new Error("resume: unusable Jev answer");
    const acts = decideAll(null, out.items).decisions.map((x) => x.action);
    const yes = out.items.filter((it) => it.confidence >= 0.5).length;
    console.log(`\nSynthetic resume (no field list): ${found.length} fields found (all ${gold.length} hand-labelled values), Jev said yes to ${yes}/${found.length}; ${acts.filter((a) => a === "fill").length} fill, ${acts.filter((a) => a === "review").length} review.`);
    for (const it of out.items) if (it.confidence < 0.95) console.log(`  below bar: ${it.field} jev=${it.confidence.toFixed(2)}`);
  }

  if (RUN_REAL) {
  // Real invoices, no field list: vendor and currency must always be asked; Jev picks.
  console.log(`\nReal public invoices (${REAL.invoices.length}, from ${REAL.source.split(",")[0]}), no field list:`);
  let vRight = 0, cRight = 0, nYes = 0, fills = 0, reviews = 0, found = 0;
  for (const d of REAL.invoices) {
    const disc2 = discoverFields(d.text);
    if (!disc2.some((f) => f.name === "vendor" && f.options) || !disc2.some((f) => f.name === "currency")) throw new Error(`${d.id}: vendor or currency was not asked`);
    const net = Number(d.net_amount_due).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const fields = [...disc2, { name: "net_amount_due", value: net }];
    const out = await checkFields({ document: d.text, fields, key, provider: "typesafe" });
    requests += 1;
    tokens += out.usage?.input_tokens || 0;
    if (out.items.some((it) => typeof it.confidence !== "number")) throw new Error(`${d.id}: unusable Jev answer`);
    const v = out.items.find((it) => it.field === "vendor");
    const c = out.items.find((it) => it.field === "currency");
    const n = out.items[out.items.length - 1];
    const vOk = !!v.value && d.vendor_any.some((w) => v.value.toLowerCase().includes(w));
    const cOk = c.value === d.currency;
    vRight += vOk ? 1 : 0; cRight += cOk ? 1 : 0; nYes += n.confidence >= 0.5 ? 1 : 0;
    const acts = decideAll(null, out.items.slice(0, -1)).decisions.map((x) => x.action);
    fills += acts.filter((a) => a === "fill").length; reviews += acts.filter((a) => a === "review").length; found += acts.length;
    console.log(`  ${d.id.slice(0, 8)}  vendor=${JSON.stringify(v.value)} p=${v.confidence.toFixed(2)} ${vOk ? "ok" : "MISS"} | currency=${c.value} p=${c.confidence.toFixed(2)} ${cOk ? "ok" : "MISS"} | net ${net} jev=${n.confidence.toFixed(2)} | ${acts.length} fields found: ${acts.filter((a) => a === "fill").length} fill, ${acts.filter((a) => a === "review").length} review`);
  }
  console.log(`Real invoices: vendor right ${vRight}/${REAL.invoices.length}, currency right ${cRight}/${REAL.invoices.length}, Jev said yes to the dataset's net amount on ${nYes}/${REAL.invoices.length}. ${found} fields found: ${fills} fill, ${reviews} review.`);
  } else {
    console.log("\nReal-invoice check skipped (set JEV_REAL_INVOICES=1 to run it; about 11k tokens).");
  }
} catch (e) {
  console.error(`Live Jev check FAILED: ${e.message}${e.status ? ` (HTTP ${e.status})` : ""}`);
  process.exit(1);
}
console.log(`\nJev agreed with the hand labels on ${right}/${total} checks. ${requests} requests, ${tokens} input tokens.`);
