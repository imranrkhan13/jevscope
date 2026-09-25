import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalize, correctnessProbability, buildQuestions, answersToItems, askJev, checkFields, decideAll, discoverFields, vendorCandidates, coreFields, CURRENCY_HINTS, JEV_PROVIDERS, JevError, isResume, joinWrapped, resumeFields } from "../src/index.js";

const spec = JSON.parse(readFileSync(new URL("../../spec/jev_certainty.json", import.meta.url)));
const close = (a, b) => (a === null || b === null ? assert.equal(a, b) : assert.ok(Math.abs(a - b) < 1e-12, `${a} vs ${b}`));

test("certainty port matches jevscope's Python certainty.py on every case", () => {
  assert.equal(spec.source, "reposcope/calibration/certainty.py");
  for (const { answer, expected } of spec.cases) {
    const n = normalize(answer);
    assert.equal(n.answerType, expected.answerType);
    assert.equal(n.prediction, expected.prediction, JSON.stringify(answer));
    close(n.certainty, expected.certainty);
    close(n.reportedConfidence, expected.reportedConfidence);
    close(n.distributionCertainty, expected.distributionCertainty);
    close(correctnessProbability(n), expected.correctness);
  }
});

test("unknown answer type throws", () => {
  assert.throws(() => normalize({ type: "text" }), /Unknown Jev answer type/);
});

const FIELDS = [
  { name: "invoice_number", value: "INV-2231" },
  { name: "total", value: 1200.5, description: "amount due" },
  { name: "currency", options: ["USD", "INR", "EUR"] },
  { name: "po_number", value: "" },
];

test("buildQuestions: noul per candidate value, choice for options, skips blanks", () => {
  const q = buildQuestions(FIELDS);
  assert.deepEqual(Object.keys(q), ["f0", "f1", "f2"]);
  assert.equal(q.f0.type, "noul");
  assert.match(q.f0.instructions, /"INV-2231" as the invoice_number/);
  assert.deepEqual(Object.keys(q.f0.criteria), ["true", "false"]);
  assert.match(q.f1.instructions, /"1200.5" as the total \(amount due\)/);
  assert.equal(q.f2.type, "choice");
  assert.deepEqual(Object.keys(q.f2.criteria), ["USD", "INR", "EUR", "not_stated"]);
  assert.throws(() => buildQuestions([{ name: "x", options: Array.from({ length: 255 }, (_, i) => `o${i}`) }]), /at most 254/);
});

const ANSWERS = {
  f0: { type: "noul", noul: 0.97 },
  f1: { type: "noul", noul: 0.08 },
  f2: { type: "choice", choice: "INR", confidence: 0.9, probabilities: { USD: 0.01, INR: 0.98, EUR: 0.0, not_stated: 0.01 } },
};

test("answersToItems: noul p is the chance the value is right; choice uses the picked option's probability", () => {
  const items = answersToItems(FIELDS, ANSWERS);
  assert.deepEqual(items.map((i) => [i.field, i.value, i.confidence]), [
    ["invoice_number", "INV-2231", 0.97],
    ["total", 1200.5, 0.08],
    ["currency", "INR", 0.98],
    ["po_number", "", null],
  ]);
  assert.ok(Math.abs(items[1].jev.certainty - 0.84) < 1e-9); // a confident "no"
  const ns = answersToItems([{ name: "c", options: ["A"] }], { f0: { type: "choice", choice: "not_stated", probabilities: { A: 0.1, not_stated: 0.9 } } });
  assert.equal(ns[0].value, null);
});

test("Jev items flow into decide: confident yes fills, confident no and blanks go to a person", () => {
  const r = decideAll(null, answersToItems(FIELDS, ANSWERS));
  assert.deepEqual(r.decisions.map((d) => d.action), ["fill", "review", "fill", "review"]);
});

test("discoverFields finds fields nobody listed, matching the Python version", () => {
  const f = discoverFields("ACME LTD\nInvoice No: INV-2231\nDue date: 2026-10-15\nSub total 21,450\nGST 18% 3,861\nThank you!\nInvoice No: X-2");
  assert.deepEqual(f.map((x) => [x.name, x.value ?? x.options.slice(0, 3)]), [
    ["vendor", ["ACME LTD"]], ["currency", ["INR", "USD", "EUR"]],
    ["invoice_no", "INV-2231"], ["due_date", "2026-10-15"], ["sub_total", "21,450"], ["gst_18", "3,861"], ["invoice_no_2", "X-2"],
  ]);
  assert.equal(f[2].label, "Invoice No");
  assert.deepEqual(discoverFields(""), []);
  assert.equal(discoverFields(Array.from({ length: 80 }, (_, i) => `Field ${i}: v`).join("\n")).length, 50);
});

test("vendor and currency are always asked on invoices, even with no labels", () => {
  const f = discoverFields("NORTH STAR LOGISTICS PVT LTD\n12 Dock Road\nInvoice\nFreight Mumbai -> Delhi\nT0TAL $25,311");
  assert.deepEqual(f.find((x) => x.name === "vendor").options, ["NORTH STAR LOGISTICS PVT LTD", "12 Dock Road"]);
  assert.equal(f.find((x) => x.name === "currency").options[0], "USD");
  // "Remit to" beats the letterhead; a labelled vendor or currency line is kept as is.
  assert.equal(vendorCandidates("Invoice\nRemit to:\nWTHI\nBilling Address:\nJohn Roach")[0], "WTHI");
  const labelled = discoverFields("Invoice\nVendor: Acme\nCurrency: INR");
  assert.deepEqual(labelled.map((x) => x.name), ["vendor", "currency"]);
  assert.equal(labelled[0].value, "Acme");
  // Not an invoice: no vendor or currency questions.
  assert.deepEqual(coreFields("Name: Imran\nSkills: Python"), []);
});

test("on 5 real public invoices, vendor and currency are always asked and the real vendor is an option", () => {
  const fx = JSON.parse(readFileSync(new URL("../../spec/real_invoices.json", import.meta.url), "utf8"));
  for (const d of fx.invoices) {
    const f = discoverFields(d.text);
    const v = f.find((x) => x.name === "vendor");
    assert.ok(v && v.options.some((o) => d.vendor_any.some((w) => o.toLowerCase().includes(w))), d.id);
    assert.equal(f.find((x) => x.name === "currency").options[0], "USD");
  }
});

test("resume mode reads every detail of 6 hand-labelled resumes (3 synthetic, 3 RenderCV layouts) exactly", () => {
  const fx = JSON.parse(readFileSync(new URL("../../spec/resumes.json", import.meta.url), "utf8"));
  for (const r of fx.resumes) {
    assert.equal(isResume(r.text), true);
    const got = Object.fromEntries(discoverFields(r.text).map((f) => [f.name, f.value]));
    assert.deepEqual(got, r.gold, r.id);
  }
  assert.equal(resumeFields(fx.resumes[0].text).find((f) => f.name === "job_1_company").label, "Job 1 company");
  // Nothing is computed that the resume does not say.
  assert.ok(!discoverFields(fx.resumes[0].text).some((f) => /years|experience_total/.test(f.name)));
});

test("resume layouts: one field per bullet, right-hand and own-line dates, Company-then-Title, footers and durations skipped", () => {
  const get = (t) => Object.fromEntries(resumeFields(t).map((f) => [f.name, f.value]));
  const a = get("A B\na@b.co\n\nExperience\nAcme Corp                              Pune, India\nBackend Engineer                       Jan 2020 – Mar 2021\n• Built X.\n• Built Y.\n  and Z\nA B · Résumé    2\n\nEducation\nBSc in Physics    2019\nUniversity of Pune");
  assert.equal(a.job_1_company, "Acme Corp");
  assert.equal(a.job_1_title, "Backend Engineer");
  assert.equal(a.job_1_location, "Pune, India");
  assert.equal(a.job_1_dates, "Jan 2020 – Mar 2021");
  assert.equal(a.job_1_highlight_1, "Built X.");
  assert.equal(a.job_1_highlight_2, "Built Y. and Z");
  assert.equal(a.education_1_school, "University of Pune");
  assert.ok(!Object.values(a).some((v) => /Résumé/.test(v)));
  const b = get("A B\na@b.co\n\nExperience\nNexus AI, Co-Founder & CTO                      San Francisco, CA\n • Built it                                  June 2023 – present\n                                                  2 years 10 months\n\nSkills\nGo");
  assert.equal(b.job_1_company, "Nexus AI");
  assert.equal(b.job_1_title, "Co-Founder & CTO");
  assert.equal(b.job_1_dates, "June 2023 – present");
  assert.equal(b.job_1_highlight_1, "Built it");
  assert.ok(!Object.values(b).some((v) => /months/.test(v)));
  // Each company question names its job, so Jev knows which one is meant.
  assert.match(resumeFields("A B\na@b.co\n\nExperience\nEngineer    2020\nAcme, Pune\n\nSkills\nGo").find((f) => f.name === "job_1_company").description, /"Engineer" job/);
});

test("a Jev-judged value says it is Jev's raw number, not the extractor's", () => {
  const r = decideAll(null, [{ field: "a", value: "x", confidence: 0.99, jev: { type: "noul", noul: 0.99 } }, { field: "b", value: "y", confidence: 0.99 }]);
  assert.match(r.decisions[0].reason, /Jev's raw 99%/);
  assert.match(r.decisions[1].reason, /extractor's own 99%/);
});

test("wrapped lines are joined back together, and invoices are not read as resumes", () => {
  assert.equal(joinWrapped("availability-aware schedul-", "  ing and booking"), "availability-aware scheduling and booking");
  assert.equal(joinWrapped("resume uploads, job-", "  description parsing"), "resume uploads, job-description parsing");
  assert.equal(joinWrapped("GitHub Actions, NGINX,", "Azure, GCP"), "GitHub Actions, NGINX, Azure, GCP");
  assert.equal(isResume("ACME LTD\nInvoice No: 1\nTotal: 5"), false);
  assert.equal(isResume("Name\nSkills\nPython"), false);
});

test("choice options with spaces get plain keys, and answers map back to the option text", () => {
  const fields = [{ name: "vendor", options: ["ACME LTD", "Kiran Traders"] }, { name: "currency", options: ["INR", "USD"], hints: CURRENCY_HINTS }];
  const q = buildQuestions(fields);
  assert.deepEqual(Object.keys(q.f0.criteria), ["o0", "o1", "not_stated"]);
  assert.match(q.f0.criteria.o0, /"ACME LTD" as the vendor/);
  assert.match(q.f1.criteria.USD, /US dollars/);
  const items = answersToItems(fields, { f0: { type: "choice", choice: "o0", probabilities: { o0: 0.9, o1: 0.05, not_stated: 0.05 } }, f1: { type: "choice", choice: "not_stated", probabilities: { INR: 0.2, USD: 0.1, not_stated: 0.7 } } });
  assert.deepEqual(items.map((i) => [i.value, i.jev.choice, i.confidence]), [["ACME LTD", "ACME LTD", 0.9], [null, "not_stated", 0.7]]);
});

function fakeFetch(status, body, seen) {
  return async (url, init) => {
    seen.push({ url, init });
    return { ok: status < 300, status, json: async () => body };
  };
}

test("askJev posts TypeSafe's documented request shape", async () => {
  const seen = [];
  const res = await askJev({ state: "doc", questions: { q: { type: "noul", instructions: "?" } }, key: "k1", fetchImpl: fakeFetch(200, { answers: { q: { type: "noul", noul: 0.7 } } }, seen) });
  assert.equal(seen[0].url, "https://api.typesafe.ai/v1/systemone");
  assert.equal(seen[0].init.headers.Authorization, "Bearer k1");
  assert.deepEqual(JSON.parse(seen[0].init.body), { model: "jev-latest", state: "doc", questions: { q: { type: "noul", instructions: "?" } } });
  assert.equal(res.answers.q.noul, 0.7);
  assert.equal(JEV_PROVIDERS.venice.url, "https://api.venice.ai/api/v1/decisions");
});

test("askJev errors are clear and never include the key", async () => {
  await assert.rejects(askJev({ state: "d", questions: {}, key: "secret-key", fetchImpl: fakeFetch(401, { detail: "bad key" }, []) }), (e) => e instanceof JevError && e.status === 401 && !e.message.includes("secret-key"));
  await assert.rejects(askJev({ state: "d", questions: {}, key: "" }), /Jev key is required/);
  await assert.rejects(askJev({ state: "d", questions: {}, key: "k", provider: "nope" }), /provider must be/);
});

test("checkFields sends one request for all fields and returns usage", async () => {
  const seen = [];
  const out = await checkFields({ document: "Invoice INV-2231", fields: FIELDS, key: "k", fetchImpl: fakeFetch(200, { model: "jev-1.13.0", answers: ANSWERS, usage: { input_tokens: 400, output_tokens: 30 } }, seen) });
  assert.equal(seen.length, 1);
  assert.equal(out.model, "jev-1.13.0");
  assert.equal(out.usage.input_tokens, 400);
  assert.equal(out.items[0].confidence, 0.97);
});

test("checkFields with no field list discovers fields, then Jev checks each", async () => {
  const seen = [];
  const out = await checkFields({ document: "Invoice No: INV-2231\nTotal: 500", key: "k", fetchImpl: fakeFetch(200, { answers: { f0: { type: "choice", choice: "not_stated", probabilities: { not_stated: 0.8 } }, f1: { type: "noul", noul: 0.99 }, f2: { type: "noul", noul: 0.4 } } }, seen) });
  const q = JSON.parse(seen[0].init.body).questions;
  assert.equal(q.f0.type, "choice");
  assert.match(q.f1.instructions, /"INV-2231" as the invoice_no/);
  assert.deepEqual(out.items.map((i) => [i.field, i.label, i.value, i.confidence]), [["currency", "Currency", null, 0.8], ["invoice_no", "Invoice No", "INV-2231", 0.99], ["total", "Total", "500", 0.4]]);
});

test("company-first layout: product beside the title, project headings with a subtitle, wrapped bullets and page numbers", () => {
  const get = (t) => Object.fromEntries(resumeFields(t).map((f) => [f.name, f.value]));
  const a = get("A B\na@b.co\nProfile\nBuilds APIs.\nExperience\nAcme Labs   Jan 2024 – Present\nBackend Developer   ShipIt\nTracking for small shops\n• Shipped more than\n60 features, fixes, and reports.\n• Used Go, Rust, and\nZig.\nOrbit Co   2022 – 2023\nEngineer   Pune, India\n1\nSelected Projects | Backend\nQueueLens   |   Queue viewer | Python, Redis\n• Shows stuck jobs.\nAdditional Engineering Projects\nShelfScan   – Reads barcodes.\nTinyForms   – Form builder.\n2");
  assert.equal(a.summary, "Builds APIs.");
  assert.equal(a.job_1_company, "Acme Labs");
  assert.equal(a.job_1_title, "Backend Developer");
  assert.equal(a.job_1_product, "ShipIt");
  assert.equal(a.job_1_location, undefined);
  assert.equal(a.job_1_about, "Tracking for small shops");
  assert.equal(a.job_1_highlight_1, "Shipped more than 60 features, fixes, and reports.");
  assert.equal(a.job_1_highlight_2, "Used Go, Rust, and Zig.");
  assert.equal(a.job_2_location, "Pune, India");
  assert.equal(a.job_2_product, undefined);
  assert.equal(a.job_3_title, undefined);
  assert.equal(a.project_1_name, "QueueLens");
  assert.equal(a.project_1_summary, "Queue viewer");
  assert.equal(a.project_1_tech, "Python, Redis");
  assert.equal(a.project_2_name, "ShelfScan");
  assert.equal(a.project_2_summary, "Reads barcodes.");
  assert.equal(a.project_3_name, "TinyForms");
  assert.ok(!Object.keys(a).some((k) => k.startsWith("education")));
  assert.ok(!Object.values(a).includes("1") && !Object.values(a).includes("2"));
});

// ---- Receipts, bank statements, forms (real public datasets; see spec/*.json for source and license) ----
import { isReceipt, receiptFields, isBankStatement, statementFields, isForm, formFields } from "../src/index.js";

const specOf = (f) => JSON.parse(readFileSync(new URL(`../../spec/${f}`, import.meta.url), "utf8"));

test("receipts: 10 real CORD receipts give the dataset's items and totals", () => {
  const fx = specOf("receipts.json");
  for (const d of fx.receipts) {
    assert.equal(isReceipt(d.text), true, d.id);
    const got = Object.fromEntries(discoverFields(d.text).map((f) => [f.name, f.value ?? null]));
    for (const [k, v] of Object.entries(d.gold)) assert.deepEqual(got[k], v, `${d.id} ${k}`);
  }
});

test("bank statements: 3 statements give header fields and transaction rows", () => {
  const fx = specOf("bank_statements.json");
  for (const d of fx.bank_statements) {
    assert.equal(isBankStatement(d.text), true, d.id);
    const got = Object.fromEntries(discoverFields(d.text).map((f) => [f.name, f.value ?? null]));
    for (const [k, v] of Object.entries(d.gold)) assert.deepEqual(got[k], v, `${d.id} ${k}`);
  }
});

test("forms: 5 real FUNSD forms give their filled blanks, empty blanks stay null", () => {
  const fx = specOf("forms.json");
  for (const d of fx.forms) {
    assert.equal(isForm(d.text), true, d.id);
    const got = Object.fromEntries(discoverFields(d.text).map((f) => [f.name, f.value ?? null]));
    for (const [k, v] of Object.entries(d.gold)) assert.deepEqual(got[k], v, `${d.id} ${k}`);
  }
});

test("the readers do not fight each other: invoices, resumes and scans keep their routes", () => {
  // Real invoices stay on the generic + vendor/currency route.
  const inv = specOf("real_invoices.json");
  for (const d of inv.invoices) {
    assert.equal(isReceipt(d.text), false, d.id);
    assert.equal(isBankStatement(d.text), false, d.id);
    assert.equal(isForm(d.text), false, d.id);
    assert.ok(discoverFields(d.text).some((f) => f.name === "vendor"), d.id);
  }
  // Resumes stay resumes.
  const res = specOf("resumes.json");
  for (const r of res.resumes) assert.ok(discoverFields(r.text).some((f) => f.name === "name"), r.id);
  // A messy scan of an invoice is not a receipt just because an OCR fragment says "receipt".
  const scan = "1nvoice\nBlll To: Acme\nAM0UNT DUE: 700.00\nremit to\nreceipt of payment\nJAN 1 2 1999\n83443897";
  assert.equal(isReceipt(scan), false);
  assert.equal(isForm(scan), false);
  // A receipt is not a form, a form is not a receipt, a statement is neither.
  const fx = specOf("receipts.json");
  assert.equal(isForm(fx.receipts[0].text), false);
  const ff = specOf("forms.json");
  assert.equal(isReceipt(ff.forms[2].text), false);
  const bs = specOf("bank_statements.json");
  assert.equal(isReceipt(bs.bank_statements[0].text), false);
  assert.equal(isForm(bs.bank_statements[0].text), false);
});
