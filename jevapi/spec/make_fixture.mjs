// Builds spec/examples.json: SYNTHETIC labelled examples for tests and the demo.
// An overconfident extractor: says ~0.9-0.99 but is right far less often on some fields.
import { writeFileSync } from "node:fs";
let s = 20260923;
// mulberry32: small deterministic PRNG
const rnd = () => {
  s = (s + 0x6d2b79f5) >>> 0;
  let t = s;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const fields = {
  invoice_number: { n: 200, trueAcc: (c) => 1 - (1 - c) * 0.6 },  // honest, slightly underconfident
  total_amount:   { n: 200, trueAcc: (c) => 0.35 + 0.55 * c },     // overconfident: says 99%, right ~89%
  due_date:       { n: 120, trueAcc: (c) => c - 0.15 },            // overconfident by ~15 points
  vendor_name:    { n: 12,  trueAcc: (c) => 0.5 + 0.45 * c },   // too few examples -> pooled
};
const out = [];
for (const [field, spec] of Object.entries(fields)) {
  for (let i = 0; i < spec.n; i++) {
    const c = Math.round((0.6 + 0.39 * Math.sqrt(rnd())) * 1000) / 1000;
    out.push({ field, confidence: c, correct: rnd() < spec.trueAcc(c) });
  }
}
// interleave so k-fold by index mixes fields
out.sort((a, b) => ((a.confidence * 7919) % 1) - ((b.confidence * 7919) % 1));
writeFileSync(new URL("./examples.json", import.meta.url), JSON.stringify({ synthetic: true, note: "SYNTHETIC test data, not real extractions", examples: out }, null, 1));
console.log(out.length);
