import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Readable } from "node:stream";
import info from "../v1/index.js";
import calibrateH from "../v1/calibrate.js";
import decideH from "../v1/decide.js";
import { makeExtract } from "../v1/extract.js";
import { _resetRateLimits, RATE } from "../_lib/http.js";
import { parseExtraction, buildPrompt } from "../_lib/providers.js";

const { examples } = JSON.parse(readFileSync(new URL("../../jevapi/spec/examples.json", import.meta.url)));

function call(handler, { method = "POST", body, headers = {}, raw } = {}) {
  const payload = raw ?? (body === undefined ? "" : JSON.stringify(body));
  const req = Readable.from(payload ? [Buffer.from(payload)] : []);
  req.method = method;
  req.headers = { "x-forwarded-for": "1.2.3.4", ...headers };
  return new Promise((resolve) => {
    const res = {
      headers: {},
      statusCode: 200,
      setHeader(k, v) { this.headers[k.toLowerCase()] = v; },
      end(s) { resolve({ status: this.statusCode, headers: this.headers, json: s ? JSON.parse(s) : null }); },
    };
    handler(req, res);
  });
}

beforeEach(() => _resetRateLimits());

test("GET /api/v1 describes the API", async () => {
  const r = await call(info, { method: "GET" });
  assert.equal(r.status, 200);
  assert.equal(r.json.name, "JevAPI");
  assert.equal(r.headers["access-control-allow-origin"], "*");
  assert.match(r.json.privacy, /never saves or logs/);
});

test("CORS preflight and wrong method", async () => {
  assert.equal((await call(decideH, { method: "OPTIONS" })).status, 204);
  const r = await call(decideH, { method: "GET" });
  assert.equal(r.status, 405);
});

test("calibrate returns a profile and optional evaluation", async () => {
  const r = await call(calibrateH, { body: { examples, options: { costError: 20 }, evaluate: true } });
  assert.equal(r.status, 200);
  assert.equal(r.json.profile.version, 1);
  assert.ok(r.json.evaluation.overall.n === examples.length);
});

test("calibrate rejects bad input with a clear 400", async () => {
  assert.equal((await call(calibrateH, { body: { examples: [] } })).status, 400);
  const bad = await call(calibrateH, { body: { examples: [{ confidence: 3, correct: true }] } });
  assert.equal(bad.status, 400);
  assert.match(bad.json.error.message, /0 to 1/);
  assert.equal((await call(calibrateH, { body: { examples, options: { costError: "lots" } } })).status, 400);
  assert.equal((await call(calibrateH, { raw: "{not json" })).status, 400);
  assert.equal((await call(calibrateH, { body: [1, 2] })).status, 400);
});

test("calibrate caps example count", async () => {
  const many = Array.from({ length: 5001 }, () => ({ confidence: 0.5, correct: true }));
  const r = await call(calibrateH, { body: { examples: many } });
  assert.equal(r.status, 400);
  assert.match(r.json.error.message, /at most 5000/);
});

test("decide with and without a profile", async () => {
  const { json: { profile } } = await call(calibrateH, { body: { examples } });
  const items = [
    { field: "invoice_number", value: "INV-1", confidence: 0.99 },
    { field: "total_amount", value: "10", confidence: 0.97 },
    { field: "due_date", value: "", confidence: 0.99 },
  ];
  const r = await call(decideH, { body: { profile, items } });
  assert.equal(r.status, 200);
  assert.equal(r.json.decisions.length, 3);
  assert.equal(r.json.decisions[0].action, "fill");
  assert.equal(r.json.decisions[1].action, "review");
  assert.equal(r.json.decisions[2].action, "review");
  const raw = await call(decideH, { body: { items } });
  assert.match(raw.json.note, /not calibrated/);
  const badProfile = await call(decideH, { body: { profile: { version: 9 }, items } });
  assert.equal(badProfile.status, 400);
  assert.equal(badProfile.json.error.code, "bad_profile");
});

test("body size limit", async () => {
  const r = await call(decideH, { raw: JSON.stringify({ items: [], pad: "x".repeat(1_000_100) }) });
  assert.equal(r.status, 413);
});

test("rate limit returns 429 with Retry-After, per IP", async () => {
  let last;
  for (let i = 0; i <= RATE.math; i++) last = await call(decideH, { body: { items: [{ value: "a", confidence: 0.5 }] } });
  assert.equal(last.status, 429);
  assert.ok(Number(last.headers["retry-after"]) > 0);
  const other = await call(decideH, { body: { items: [{ value: "a", confidence: 0.5 }] }, headers: { "x-forwarded-for": "5.6.7.8" } });
  assert.equal(other.status, 200);
});

const docText = "INVOICE INV-2231\nTotal due: 48,200.00\nDue 2026-10-15\nAcme Supplies";
const fields = [{ name: "invoice_number" }, { name: "total_amount", type: "number" }, { name: "due_date" }];

function fakeFetch(replyText, status = 200, capture = {}) {
  return async (url, init) => {
    capture.url = url;
    capture.init = init;
    const body = url.includes("openai")
      ? { choices: [{ message: { content: replyText } }] }
      : url.includes("anthropic")
        ? { content: [{ type: "text", text: replyText }] }
        : { candidates: [{ content: { parts: [{ text: replyText }] } }] };
    return { ok: status < 400, status, json: async () => (status < 400 ? body : { error: { message: "Invalid API key" } }) };
  };
}

test("extract needs the caller's own key", async () => {
  const r = await call(makeExtract(fakeFetch("{}")), { body: { provider: "openai", model: "m", text: docText, fields } });
  assert.equal(r.status, 400);
  assert.equal(r.json.error.code, "missing_key");
});

for (const provider of ["openai", "anthropic", "gemini"]) {
  test(`extract relays to ${provider} with the caller's key and gates the result`, async () => {
    const cap = {};
    const reply = '```json\n{"fields":{"invoice_number":{"value":"INV-2231","confidence":0.99},"total_amount":{"value":48200,"confidence":0.97},"due_date":{"value":null,"confidence":0.4}}}\n```';
    const r = await call(makeExtract(fakeFetch(reply, 200, cap)), {
      body: { provider, model: "some-model", text: docText, fields },
      headers: { "x-provider-key": "sk-test-123" },
    });
    assert.equal(r.status, 200);
    assert.equal(r.json.fields[0].value, "INV-2231");
    assert.equal(r.json.decisions[2].action, "review"); // null value
    assert.equal(r.json.calibrated, false);
    const sent = JSON.stringify(cap.init.headers);
    assert.ok(sent.includes("sk-test-123"));
    assert.ok(!JSON.stringify(r.json).includes("sk-test-123"), "key must never be echoed back");
  });
}

test("extract maps provider auth errors to 502 without leaking the key", async () => {
  const r = await call(makeExtract(fakeFetch("", 401)), {
    body: { provider: "openai", model: "m", text: docText, fields },
    headers: { "x-provider-key": "sk-secret" },
  });
  assert.equal(r.status, 502);
  assert.equal(r.json.error.code, "provider_auth");
  assert.ok(!JSON.stringify(r.json).includes("sk-secret"));
});

test("extract validates provider, model, text and fields", async () => {
  const h = makeExtract(fakeFetch("{}"));
  const hdr = { "x-provider-key": "k" };
  assert.equal((await call(h, { body: { provider: "x", model: "m", text: "t", fields }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { provider: "openai", model: "bad model!", text: "t", fields }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { provider: "openai", model: "m", text: "", fields }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { provider: "openai", model: "m", text: "x".repeat(60001), fields }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { provider: "openai", model: "m", text: "t", fields: [{ name: "" }] }, headers: hdr })).status, 400);
});

test("parseExtraction tolerates messy replies", () => {
  const f = [{ name: "a" }, { name: "b" }, { name: "c" }];
  const out = parseExtraction('Sure! {"a": {"value": "x", "confidence": "0.8"}, "b": "plain", "c": {"value": 1, "confidence": 7}}', f);
  assert.deepEqual(out, [
    { field: "a", value: "x", confidence: 0.8 },
    { field: "b", value: "plain", confidence: null },
    { field: "c", value: 1, confidence: 1 },
  ]);
  assert.deepEqual(parseExtraction("not json", [{ name: "a" }]), [{ field: "a", value: null, confidence: null }]);
  assert.match(buildPrompt("doc", f), /DOCUMENT:\ndoc/);
});

// ---------- Jev ----------
import { makeVerify } from "../v1/verify.js";

function jevFetch(answers, status = 200, capture = { calls: [] }, llmReply) {
  return async (url, init) => {
    capture.calls.push({ url, init });
    if (url.includes("typesafe") || url.includes("venice") || url.includes("openrouter")) {
      const body = status < 400 ? { model: "jev-1.13.0", answers, usage: { input_tokens: 420, output_tokens: 30 } } : { detail: "Invalid API key" };
      return { ok: status < 400, status, json: async () => body };
    }
    return { ok: true, status: 200, json: async () => ({ choices: [{ message: { content: llmReply } }] }) };
  };
}
const jevFields = [{ name: "invoice_number", value: "INV-2231" }, { name: "total_amount", value: "48,200.00" }, { name: "currency", options: ["USD", "INR"] }];
const jevAnswers = { f0: { type: "noul", noul: 0.99 }, f1: { type: "noul", noul: 0.2 }, f2: { type: "choice", choice: "not_stated", confidence: 0.8, probabilities: { USD: 0.1, INR: 0.05, not_stated: 0.85 } } };

test("verify needs the caller's Jev key", async () => {
  const r = await call(makeVerify(jevFetch({})), { body: { text: docText, fields: jevFields } });
  assert.equal(r.status, 400);
  assert.equal(r.json.error.code, "missing_key");
});

test("verify asks TypeSafe's Jev once and decides from Jev's probabilities", async () => {
  const cap = { calls: [] };
  const r = await call(makeVerify(jevFetch(jevAnswers, 200, cap)), { body: { text: docText, fields: jevFields }, headers: { "x-jev-key": "ts-secret" } });
  assert.equal(r.status, 200);
  assert.equal(cap.calls.length, 1);
  assert.equal(cap.calls[0].url, "https://api.typesafe.ai/v1/systemone");
  const sent = JSON.parse(cap.calls[0].init.body);
  assert.equal(sent.model, "jev-latest");
  assert.equal(sent.state, docText);
  assert.deepEqual(Object.values(sent.questions).map((q) => q.type), ["noul", "noul", "choice"]);
  assert.equal(r.json.judge, "jev");
  assert.equal(r.json.discovered, false);
  assert.equal(r.json.jevModel, "jev-1.13.0");
  assert.deepEqual(r.json.decisions.map((d) => d.action), ["fill", "review", "review"]);
  assert.equal(r.json.fields[2].value, null);
  assert.ok(!JSON.stringify(r.json).includes("ts-secret"));
});

test("verify with no fields finds every labelled field, then Jev checks each", async () => {
  const cap = { calls: [] };
  const text = "Invoice No: INV-2231\nDue date: 2026-10-15\nTotal 48,200.00";
  const answers = { f0: { type: "noul", noul: 0.99 }, f1: { type: "noul", noul: 0.97 }, f2: { type: "noul", noul: 0.6 } };
  const r = await call(makeVerify(jevFetch(answers, 200, cap)), { body: { text }, headers: { "x-jev-key": "k" } });
  assert.equal(r.status, 200);
  assert.equal(r.json.discovered, true);
  assert.deepEqual(r.json.fields.map((f) => f.field), ["invoice_no", "due_date", "total"]);
  assert.deepEqual(r.json.decisions.map((d) => d.action), ["fill", "fill", "review"]);
  assert.match(r.json.note, /found 3 labelled fields/);
});

test("verify maps Jev auth errors to 502 jev_auth without leaking the key", async () => {
  const r = await call(makeVerify(jevFetch({}, 401)), { body: { text: docText, fields: jevFields }, headers: { "x-jev-key": "ts-secret" } });
  assert.equal(r.status, 502);
  assert.equal(r.json.error.code, "jev_auth");
  assert.ok(!JSON.stringify(r.json).includes("ts-secret"));
});

test("verify validates fields and provider", async () => {
  const h = makeVerify(jevFetch(jevAnswers));
  const hdr = { "x-jev-key": "k" };
  assert.equal((await call(h, { body: { text: docText, fields: [{ name: "x", options: [] }] }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { text: docText, fields: [{ name: "x", value: { a: 1 } }] }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { text: docText, fields: [] }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { text: docText, fields: jevFields, jevProvider: "nope" }, headers: hdr })).status, 400);
  assert.equal((await call(h, { body: { text: "", fields: jevFields }, headers: hdr })).status, 400);
});

test("extract with judge jev: Jev's probability replaces the AI's self-reported confidence", async () => {
  const cap = { calls: [] };
  const reply = '{"fields":{"invoice_number":{"value":"INV-2231","confidence":0.99},"total_amount":{"value":48200,"confidence":0.99},"due_date":{"value":null,"confidence":0.4}}}';
  const answers = { f0: { type: "noul", noul: 0.98 }, f1: { type: "noul", noul: 0.3 } };
  const r = await call(makeExtract(jevFetch(answers, 200, cap, reply)), {
    body: { provider: "openai", model: "m", text: docText, fields, judge: "jev" },
    headers: { "x-provider-key": "sk", "x-jev-key": "ts" },
  });
  assert.equal(r.status, 200);
  assert.equal(cap.calls.length, 2);
  assert.equal(r.json.judge, "jev");
  assert.equal(r.json.fields[1].aiConfidence, 0.99);
  assert.equal(r.json.fields[1].confidence, 0.3);
  assert.deepEqual(r.json.decisions.map((d) => d.action), ["fill", "review", "review"]);
  const r2 = await call(makeExtract(jevFetch(answers, 200, { calls: [] }, reply)), { body: { provider: "openai", model: "m", text: docText, fields, judge: "jev" }, headers: { "x-provider-key": "sk" } });
  assert.equal(r2.json.error.code, "missing_jev_key");
});

test("extract with no fields asks the AI for every field and keeps what it finds", async () => {
  const cap = { calls: [] };
  const reply = '{"fields":{"vendor_name":{"value":"Acme","confidence":0.9},"invoice_number":{"value":"INV-2231","confidence":0.95},"bad name!":{"value":"x","confidence":1}}}';
  const r = await call(makeExtract(jevFetch({ f0: { type: "noul", noul: 0.99 }, f1: { type: "noul", noul: 0.99 } }, 200, cap, reply)), {
    body: { provider: "openai", model: "m", text: docText, judge: "jev" },
    headers: { "x-provider-key": "sk", "x-jev-key": "ts" },
  });
  assert.equal(r.status, 200);
  assert.equal(r.json.discovered, true);
  assert.match(JSON.parse(cap.calls[0].init.body).messages[0].content, /Extract every field/);
  assert.deepEqual(r.json.fields.map((f) => f.field), ["vendor_name", "invoice_number"]);
  assert.deepEqual(r.json.decisions.map((d) => d.action), ["fill", "fill"]);
});
