import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normalize, correctnessProbability, buildQuestions, answersToItems, askJev, checkFields, decideAll, discoverFields, JEV_PROVIDERS, JevError } from "../src/index.js";

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
  assert.deepEqual(f.map((x) => [x.name, x.value]), [
    ["invoice_no", "INV-2231"], ["due_date", "2026-10-15"], ["sub_total", "21,450"], ["gst_18", "3,861"], ["invoice_no_2", "X-2"],
  ]);
  assert.equal(f[0].label, "Invoice No");
  assert.deepEqual(discoverFields(""), []);
  assert.equal(discoverFields(Array.from({ length: 80 }, (_, i) => `Field ${i}: v`).join("\n")).length, 50);
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
  const out = await checkFields({ document: "Invoice No: INV-2231\nTotal: 500", key: "k", fetchImpl: fakeFetch(200, { answers: { f0: { type: "noul", noul: 0.99 }, f1: { type: "noul", noul: 0.4 } } }, seen) });
  const q = JSON.parse(seen[0].init.body).questions;
  assert.match(q.f0.instructions, /"INV-2231" as the invoice_no/);
  assert.deepEqual(out.items.map((i) => [i.field, i.label, i.value, i.confidence]), [["invoice_no", "Invoice No", "INV-2231", 0.99], ["total", "Total", "500", 0.4]]);
});
