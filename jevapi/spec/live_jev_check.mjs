// Live smoke test against the real Jev (TypeSafe). Needs TYPESAFE_API_KEY.
// Uses the three SYNTHETIC sample invoices with hand-written right and wrong
// candidate values, plus one run with no field list (auto-discovery). It checks
// that the integration works end to end and prints what Jev said. This is a
// smoke test, not a calibration study.
import { checkFields, decideAll } from "../js/src/index.js";
import { SAMPLES } from "../../web/jevapi/samples.js";

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
} catch (e) {
  console.error(`Live Jev check FAILED: ${e.message}${e.status ? ` (HTTP ${e.status})` : ""}`);
  process.exit(1);
}
console.log(`\nJev agreed with the hand labels on ${right}/${total} checks. ${requests} requests, ${tokens} input tokens.`);
