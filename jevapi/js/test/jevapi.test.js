import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  calibrate, decide, decideAll, evaluate, fitIsotonic, applyIsotonic, ece, costThreshold, wilsonLower, validateProfile,
} from "../src/index.js";

const spec = (f) => JSON.parse(readFileSync(new URL(`../../spec/${f}`, import.meta.url)));
const { examples } = spec("examples.json");
const expected = spec("expected.json");

test("cost threshold follows the expected-cost rule", () => {
  assert.equal(costThreshold({ costError: 20, costReview: 1, reviewAccuracy: 1 }), 0.95);
  assert.equal(costThreshold({ costError: 2, costReview: 1, reviewAccuracy: 1 }), 0.5);
  assert.equal(costThreshold({ costError: 20, costReview: 1, reviewAccuracy: 0.98 }), 0.93);
  assert.equal(costThreshold({ costError: 0.5, costReview: 1, reviewAccuracy: 1 }), 0); // clamped
  assert.throws(() => costThreshold({ costError: 0, costReview: 1, reviewAccuracy: 1 }));
});

test("wilson lower bound is below the rate and tightens with more data", () => {
  assert.equal(wilsonLower(0, 0), 0);
  const small = wilsonLower(10, 10);
  const big = wilsonLower(100, 100);
  assert.ok(small < 1 && big < 1 && small < big);
  assert.ok(wilsonLower(50, 100) < 0.5);
});

test("isotonic output is monotone and in [0,1]", () => {
  const blocks = fitIsotonic(examples);
  for (let i = 1; i < blocks.length; i++) {
    assert.ok(blocks[i].p >= blocks[i - 1].p);
    assert.ok(blocks[i].lower >= blocks[i - 1].lower);
    assert.ok(blocks[i].lo > blocks[i - 1].hi);
  }
  let prev = -1;
  for (let x = 0; x <= 1.0001; x += 0.01) {
    const p = applyIsotonic(blocks, x);
    assert.ok(p >= prev - 1e-12 && p >= 0 && p <= 1);
    prev = p;
  }
  assert.equal(blocks.reduce((s, b) => s + b.n, 0), examples.length);
});

test("isotonic fixes a uniformly overconfident model", () => {
  // says 0.95, right half the time
  const ex = Array.from({ length: 200 }, (_, i) => ({ confidence: 0.95, correct: i % 2 === 0 }));
  const blocks = fitIsotonic(ex);
  assert.equal(blocks.length, 1);
  assert.ok(Math.abs(applyIsotonic(blocks, 0.95) - 0.5) < 0.01);
  const d = decide(calibrate(ex), { value: "x", confidence: 0.95 });
  assert.equal(d.action, "review");
});

test("ties map to one value", () => {
  const ex = [
    { confidence: 0.9, correct: true }, { confidence: 0.9, correct: false },
    { confidence: 0.9, correct: true }, { confidence: 0.5, correct: false },
  ];
  const b = fitIsotonic(ex);
  assert.equal(b.filter((x) => x.lo <= 0.9 && x.hi >= 0.9).length, 1);
});

test("empty values and missing confidence always go to review", () => {
  const p = calibrate(examples);
  for (const value of [null, undefined, "", "   ", []]) {
    assert.equal(decide(p, { field: "invoice_number", value, confidence: 1 }).action, "review");
  }
  for (const confidence of [null, undefined, NaN, -0.1, 1.2, "0.9"]) {
    assert.equal(decide(p, { field: "invoice_number", value: "A1", confidence }).action, "review");
  }
});

test("validator failure sends to review", () => {
  const p = calibrate(examples);
  const d = decide(p, { field: "invoice_number", value: "??", confidence: 0.99 }, { validate: (v) => /^[A-Z0-9-]+$/.test(v) });
  assert.equal(d.action, "review");
  assert.match(d.reason, /check/);
  const thrower = decide(p, { field: "invoice_number", value: "x", confidence: 0.99 }, { validate: () => { throw new Error("boom"); } });
  assert.equal(thrower.action, "review");
});

test("no profile means uncalibrated and says so", () => {
  const d = decide(null, { field: "x", value: "v", confidence: 0.97 });
  assert.equal(d.calibrated, false);
  assert.equal(d.action, "fill");
  assert.match(d.reason, /Not calibrated/);
});

test("fields with too few examples borrow the pooled calibration", () => {
  const p = calibrate(examples);
  assert.equal(p.fields.vendor_name.own, false);
  const d = decide(p, { field: "vendor_name", value: "Acme", confidence: 0.99 });
  assert.equal(d.source, "pooled");
  assert.equal(decide(p, { field: "never_seen", value: "v", confidence: 0.9 }).source, "pooled");
  assert.equal(decide(p, { field: "invoice_number", value: "v", confidence: 0.9 }).source, "field");
});

test("per-field costs and maxRisk raise the bar", () => {
  const p = calibrate(examples, { fields: { total_amount: { costError: 100 }, due_date: { maxRisk: 0.01 } } });
  assert.equal(decide(p, { field: "total_amount", value: "1", confidence: 0.99 }).threshold, 0.99);
  assert.equal(decide(p, { field: "due_date", value: "1", confidence: 0.99 }).threshold, 0.99);
  assert.equal(decide(p, { field: "invoice_number", value: "1", confidence: 0.99 }).threshold, 0.95);
});

test("conservative mode is never looser than point-estimate mode", () => {
  const p = calibrate(examples);
  for (const c of [0.7, 0.8, 0.9, 0.95, 0.99]) {
    const cons = decide(p, { field: "invoice_number", value: "v", confidence: c });
    const loose = decide(p, { field: "invoice_number", value: "v", confidence: c }, { conservative: false });
    if (cons.action === "fill") assert.equal(loose.action, "fill");
  }
});

test("profile round-trips through JSON", () => {
  const p = calibrate(examples, expected.options);
  const again = JSON.parse(JSON.stringify(p));
  const item = { field: "total_amount", value: "9", confidence: 0.93 };
  assert.deepEqual(decide(again, item), decide(p, item));
  assert.throws(() => validateProfile({ version: 99 }));
});

test("decideAll counts fills and reviews", () => {
  const p = calibrate(examples);
  const r = decideAll(p, [
    { field: "invoice_number", value: "INV-1", confidence: 0.99 },
    { field: "total_amount", value: "", confidence: 0.99 },
  ]);
  assert.equal(r.fill + r.review, 2);
  assert.equal(r.review >= 1, true);
});

test("bad examples are rejected with a clear error", () => {
  assert.throws(() => calibrate([{ confidence: 2, correct: true }]), /0 to 1/);
  assert.throws(() => calibrate([{ confidence: 0.5, correct: "yes" }]), /true or false/);
  assert.throws(() => calibrate("nope"));
});

test("ece is 0 for a perfectly calibrated set and positive for an overconfident one", () => {
  assert.equal(ece([0.5, 0.5], [true, false], 1), 0);
  assert.ok(ece([0.99, 0.99, 0.99, 0.99], [true, false, false, false], 1) > 0.7);
});

test("calibration reduces ECE on overconfident fields (held-out)", () => {
  const r = evaluate(examples, expected.options, 5);
  assert.ok(r.fields.total_amount.eceCalibrated < r.fields.total_amount.eceRaw);
  assert.ok(r.overall.eceCalibrated < r.overall.eceRaw);
  assert.ok(r.overall.coverage >= 0 && r.overall.coverage <= 1);
});

test("matches the shared spec (profile, decisions, evaluation)", () => {
  assert.deepEqual(calibrate(examples, expected.options), expected.profile);
  assert.deepEqual(expected.probes.map((p) => decide(expected.profile, p)), expected.decisions);
  assert.deepEqual(evaluate(examples, expected.options, 5), expected.evaluation);
});
