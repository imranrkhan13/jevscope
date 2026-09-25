// Evaluate extraction by verification against the rule reader, on the shared gold sets.
// Offline (free): candidate coverage (is the gold value even among the spans?) and the
// rule reader's exact-match accuracy on the same fields.
// Live (TYPESAFE_API_KEY + JEV_EXTRACT_EVAL=1): one Jev request per document picks each
// field's value out of its candidates; writes the results to jev_extract_eval.json.
// Small on purpose: 5 documents, 13 fields, 5 requests.
import { readFileSync, writeFileSync } from "node:fs";
import { candidateSpans, extractByVerification, discoverFields } from "../js/src/index.js";

const load = (f) => JSON.parse(readFileSync(new URL(`./${f}`, import.meta.url), "utf8"));
const norm = (v) => String(v ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
const receipts = load("receipts.json").receipts;
const invoices = load("real_invoices.json").invoices;
const forms = load("forms.json").forms;

const docs = [];
for (const r of [receipts[0], receipts[9]]) {
  docs.push({ id: r.id, text: r.text, fields: ["total", "cash", "change"].filter((f) => r.gold[f] != null).map((f) => ({ name: f, gold: r.gold[f] })) });
}
const swiss = receipts.find((r) => r.id === "synthetic-swiss-1");
docs.push({ id: swiss.id, text: swiss.text, fields: [{ name: "total", gold: swiss.gold.total }] });
const inv = invoices[0];
docs.push({ id: inv.id, text: inv.text, fields: [
  { name: "vendor", gold: inv.vendor_any },
  { name: "net_amount_due", gold: inv.net_amount_due },
] });
const form = forms[0];
docs.push({ id: form.id, text: form.text, fields: ["date", "fax_number", "number_of_pages_including_cover_sheet"].map((f) => ({ name: f, gold: form.gold[f] })) });

const match = (value, gold) => {
  const gs = Array.isArray(gold) ? gold : [gold];
  return gs.some((g) => norm(g) === norm(value));
};

console.log("== offline: candidate coverage + rule-reader baseline ==");
const out = { date: new Date().toISOString().slice(0, 10), docs: [] };
let cov = 0, base = 0, n = 0;
for (const d of docs) {
  const got = Object.fromEntries(discoverFields(d.text).map((f) => [f.name, f.value ?? null]));
  const row = { id: d.id, fields: [] };
  for (const f of d.fields) {
    const cands = candidateSpans(d.text, f);
    const covered = cands.some((c) => match(c, f.gold));
    const readerOk = match(got[f.name], f.gold);
    cov += covered ? 1 : 0; base += readerOk ? 1 : 0; n += 1;
    row.fields.push({ field: f.name, gold: f.gold, candidates: cands.length, covered, reader_value: got[f.name] ?? null, reader_ok: readerOk });
    console.log(`${covered ? "cov " : "MISS"} ${d.id}/${f.name}: ${cands.length} candidates, reader ${readerOk ? "ok" : "miss"} (${JSON.stringify(got[f.name] ?? null)})`);
  }
  out.docs.push(row);
}
out.offline = { fields: n, candidate_coverage: cov, rule_reader_exact: base };
console.log(`coverage ${cov}/${n}, rule reader exact ${base}/${n}`);

const key = process.env.TYPESAFE_API_KEY;
if (process.env.JEV_EXTRACT_EVAL === "1" && key) {
  console.log("== live: Jev picks the value ==");
  let right = 0, abstained = 0, tokens = 0, requests = 0;
  for (const [di, d] of docs.entries()) {
    const res = await extractByVerification({ document: d.text, fields: d.fields.map((f) => ({ name: f.name })), key, provider: "typesafe" });
    requests += 1; tokens += res.usage?.input_tokens || 0;
    res.items.forEach((it, fi) => {
      const ok = match(it.value, d.fields[fi].gold);
      right += ok ? 1 : 0; abstained += it.value == null ? 1 : 0;
      out.docs[di].fields[fi].jev_value = it.value;
      out.docs[di].fields[fi].jev_confidence = it.confidence;
      out.docs[di].fields[fi].jev_ok = ok;
      console.log(`${ok ? "ok  " : it.value == null ? "abst" : "MISS"} ${d.id}/${it.field}: ${JSON.stringify(it.value)} (${it.confidence == null ? "-" : it.confidence.toFixed(2)}, ${it.jev.candidates} candidates)`);
    });
  }
  out.live = { fields: n, jev_extract_exact: right, abstained, requests, input_tokens: tokens, model: "typesafe default" };
  console.log(`jev-extract exact ${right}/${n}, abstained ${abstained}, ${requests} requests, ${tokens} input tokens`);
  writeFileSync(new URL("./jev_extract_eval.json", import.meta.url), JSON.stringify(out, null, 2) + "\n");
  console.log("wrote jev_extract_eval.json");
} else {
  console.log("live part skipped (set JEV_EXTRACT_EVAL=1 and TYPESAFE_API_KEY)");
}
