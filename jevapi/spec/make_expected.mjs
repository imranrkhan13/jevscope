// Writes spec/expected.json from the JS implementation; the Python package must match it exactly.
import { readFileSync, writeFileSync } from "node:fs";
import { calibrate, decide, evaluate } from "../js/src/index.js";
const { examples } = JSON.parse(readFileSync(new URL("./examples.json", import.meta.url)));
const options = { costError: 20, costReview: 1, fields: { total_amount: { costError: 50 }, due_date: { maxRisk: 0.1 } } };
const profile = calibrate(examples, options);
const probes = [];
for (const field of ["invoice_number", "total_amount", "due_date", "vendor_name", "unknown_field"]) {
  for (const c of [0, 0.5, 0.61, 0.8, 0.9, 0.95, 0.99, 1]) probes.push({ field, value: "v", confidence: c });
}
probes.push({ field: "total_amount", value: "", confidence: 0.99 });
probes.push({ field: "total_amount", value: "10", confidence: null });
const decisions = probes.map((p) => decide(profile, p));
const evaluation = evaluate(examples, options, 5);
writeFileSync(new URL("./expected.json", import.meta.url), JSON.stringify({ options, profile, probes, decisions, evaluation }, null, 1));
console.log(JSON.stringify(evaluation.overall), JSON.stringify(evaluation.fields.total_amount));
