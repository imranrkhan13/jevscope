// JevAPI: decide, field by field, whether an extracted value is safe to
// auto-fill or should go to a human. Zero dependencies. Runs in Node and the browser.
//
// The idea in one line: a model's stated confidence is a claim. Gate turns it
// into a measured probability using the developer's own labelled examples, then
// applies a cost rule (what a wrong fill costs vs what a human check costs).

export const PROFILE_VERSION = 1;

const DEFAULTS = Object.freeze({
  costError: 20,        // cost of one wrong auto-fill, in "human checks"
  costReview: 1,        // cost of one human check
  reviewAccuracy: 1,    // humans are not perfect; 0.98 means 2% of checks still miss
  maxRisk: null,        // never auto-fill if chance of being wrong is above this
  minExamples: 30,      // below this, a field borrows the pooled calibration
  conservative: true,   // decide on the lower confidence bound, not the point estimate
  z: 1.2816,            // one-sided 90% Wilson lower bound
});

// ---------- small helpers ----------

function round6(x) {
  return Math.round(x * 1e6) / 1e6;
}

function clamp01(x) {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

export function wilsonLower(k, n, z = DEFAULTS.z) {
  if (n <= 0) return 0;
  const p = k / n;
  const z2 = z * z;
  const denom = 1 + z2 / n;
  const centre = p + z2 / (2 * n);
  const margin = z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n));
  return clamp01((centre - margin) / denom);
}

function checkExample(e, i) {
  if (!e || typeof e !== "object") throw new TypeError(`example ${i}: not an object`);
  if (typeof e.confidence !== "number" || !Number.isFinite(e.confidence) || e.confidence < 0 || e.confidence > 1) {
    throw new RangeError(`example ${i}: confidence must be a number from 0 to 1`);
  }
  if (typeof e.correct !== "boolean") throw new TypeError(`example ${i}: correct must be true or false`);
}

// ---------- isotonic calibration (pool adjacent violators) ----------

// Returns monotone blocks: [{lo, hi, k, n, p, lower}]
export function fitIsotonic(examples, z = DEFAULTS.z) {
  if (examples.length === 0) return [];
  const sorted = examples
    .map((e) => [e.confidence, e.correct ? 1 : 0])
    .sort((a, b) => a[0] - b[0]);
  // group exact ties first so equal inputs always map to one output
  const groups = [];
  for (const [x, y] of sorted) {
    const g = groups[groups.length - 1];
    if (g && g.lo === x) {
      g.k += y;
      g.n += 1;
    } else {
      groups.push({ lo: x, hi: x, k: y, n: 1 });
    }
  }
  const stack = [];
  for (const g of groups) {
    stack.push({ ...g });
    while (stack.length > 1) {
      const b = stack[stack.length - 1];
      const a = stack[stack.length - 2];
      // merge on ">=": equal-rate neighbours become one block, so smoothing sees the real sample size
      if (a.k * b.n >= b.k * a.n) {
        stack.splice(stack.length - 2, 2, { lo: a.lo, hi: b.hi, k: a.k + b.k, n: a.n + b.n });
      } else break;
    }
  }
  // Laplace-smoothed point estimate and Wilson lower bound, forced monotone.
  let pMax = 0;
  let lMax = 0;
  return stack.map((b) => {
    pMax = Math.max(pMax, (b.k + 1) / (b.n + 2));
    lMax = Math.max(lMax, wilsonLower(b.k, b.n, z));
    return { lo: round6(b.lo), hi: round6(b.hi), k: b.k, n: b.n, p: round6(pMax), lower: round6(lMax) };
  });
}

// Map a raw confidence through the blocks, interpolating between block edges.
export function applyIsotonic(blocks, x, key = "p") {
  if (!blocks || blocks.length === 0) return null;
  if (x <= blocks[0].hi) return blocks[0][key];
  for (let i = 1; i < blocks.length; i++) {
    const prev = blocks[i - 1];
    const cur = blocks[i];
    if (x < cur.lo) {
      const span = cur.lo - prev.hi;
      const t = span > 0 ? (x - prev.hi) / span : 1;
      return round6(prev[key] + t * (cur[key] - prev[key]));
    }
    if (x <= cur.hi) return cur[key];
  }
  return blocks[blocks.length - 1][key];
}

// ---------- metrics ----------

// Expected calibration error with equal-mass bins (same choice as Calibration Lab).
export function ece(confidences, correct, nBins = 10) {
  const n = confidences.length;
  if (n === 0) return 0;
  const pairs = confidences.map((c, i) => [c, correct[i] ? 1 : 0]).sort((a, b) => a[0] - b[0]);
  let total = 0;
  for (let b = 0; b < nBins; b++) {
    const start = Math.floor((b * n) / nBins);
    const end = Math.floor(((b + 1) * n) / nBins);
    if (end <= start) continue;
    let sc = 0;
    let sy = 0;
    for (let i = start; i < end; i++) {
      sc += pairs[i][0];
      sy += pairs[i][1];
    }
    const m = end - start;
    total += (m / n) * Math.abs(sy / m - sc / m);
  }
  return round6(total);
}

// ---------- thresholds ----------

// Auto-fill when expected cost of filling < expected cost of a human check:
//   (1 - p) * costError  <  costReview + (1 - reviewAccuracy) * costError
//   p  >  reviewAccuracy - costReview / costError
export function costThreshold({ costError, costReview, reviewAccuracy }) {
  if (!(costError > 0)) throw new RangeError("costError must be above 0");
  if (!(costReview >= 0)) throw new RangeError("costReview must be 0 or more");
  return round6(clamp01(reviewAccuracy - costReview / costError));
}

function fieldThreshold(opts) {
  let t = costThreshold(opts);
  if (opts.maxRisk != null) t = Math.max(t, round6(1 - opts.maxRisk));
  return t;
}

function resolveOptions(profileDefaults, fieldOverrides, callOverrides) {
  return { ...DEFAULTS, ...(profileDefaults || {}), ...(fieldOverrides || {}), ...(callOverrides || {}) };
}

// ---------- fitting a profile ----------

/**
 * Build a calibration profile from labelled examples.
 * examples: [{ field, confidence, correct }]
 * options: global defaults, plus options.fields = { fieldName: { costError, maxRisk, ... } }
 */
export function calibrate(examples, options = {}) {
  if (!Array.isArray(examples)) throw new TypeError("examples must be an array");
  examples.forEach(checkExample);
  const { fields: fieldOptions = {}, ...rest } = options;
  const defaults = { ...DEFAULTS, ...rest };
  const byField = new Map();
  for (const e of examples) {
    const f = e.field == null ? "*" : String(e.field);
    if (!byField.has(f)) byField.set(f, []);
    byField.get(f).push(e);
  }
  const fields = {};
  for (const name of [...byField.keys()].sort()) {
    const list = byField.get(name);
    const minEx = (fieldOptions[name] && fieldOptions[name].minExamples) ?? defaults.minExamples;
    fields[name] = {
      n: list.length,
      accuracy: round6(list.filter((e) => e.correct).length / list.length),
      own: list.length >= minEx,
      blocks: list.length >= minEx ? fitIsotonic(list, defaults.z) : [],
      options: fieldOptions[name] || {},
    };
  }
  for (const name of Object.keys(fieldOptions).sort()) {
    if (!fields[name]) fields[name] = { n: 0, accuracy: null, own: false, blocks: [], options: fieldOptions[name] };
  }
  const saved = {};
  for (const k of Object.keys(DEFAULTS)) if (rest[k] !== undefined) saved[k] = rest[k];
  return {
    version: PROFILE_VERSION,
    n: examples.length,
    defaults: saved,
    pooled: fitIsotonic(examples, defaults.z),
    fields,
  };
}

export function validateProfile(profile) {
  if (!profile || typeof profile !== "object") throw new TypeError("profile must be an object");
  if (profile.version !== PROFILE_VERSION) throw new RangeError(`unsupported profile version ${profile.version}`);
  if (!Array.isArray(profile.pooled) || typeof profile.fields !== "object") throw new TypeError("profile is missing pooled or fields");
  return profile;
}

// ---------- deciding ----------

function isEmpty(v) {
  return v == null || (typeof v === "string" && v.trim() === "") || (Array.isArray(v) && v.length === 0);
}

/**
 * decide(profile, { field, value, confidence }, overrides?) ->
 *   { field, action: "fill" | "review", confidence, lower, threshold, calibrated, reason }
 * profile may be null: then raw confidence is used and calibrated is false.
 */
export function decide(profile, item, overrides = {}) {
  if (profile) validateProfile(profile);
  const field = item.field == null ? "*" : String(item.field);
  const f = profile ? profile.fields[field] : undefined;
  const opts = resolveOptions(profile && profile.defaults, f && f.options, overrides);
  const threshold = fieldThreshold(opts);
  const base = { field, threshold, calibrated: false, confidence: null, lower: null };

  if (isEmpty(item.value)) return { ...base, action: "review", reason: "No value was extracted." };
  const raw = item.confidence;
  if (typeof raw !== "number" || !Number.isFinite(raw) || raw < 0 || raw > 1) {
    return { ...base, action: "review", reason: "The extractor gave no usable confidence." };
  }
  if (typeof opts.validate === "function") {
    let ok = false;
    try {
      ok = !!opts.validate(item.value);
    } catch {
      ok = false;
    }
    if (!ok) return { ...base, action: "review", reason: "The value failed this field's check." };
  }

  let blocks = null;
  let source = "raw";
  if (f && f.own && f.blocks.length) {
    blocks = f.blocks;
    source = "field";
  } else if (profile && profile.pooled.length) {
    blocks = profile.pooled;
    source = "pooled";
  }
  let p = raw;
  let lower = raw;
  if (blocks) {
    p = applyIsotonic(blocks, raw, "p");
    lower = applyIsotonic(blocks, raw, "lower");
  }
  const used = opts.conservative && blocks ? lower : p;
  const fill = used >= threshold && used > 0;
  const pct = (x) => `${Math.round(x * 100)}%`;
  let reason;
  if (source === "raw") {
    reason = `Not calibrated: using the extractor's own ${pct(raw)}, which may be overconfident.`;
  } else {
    const basis = source === "field" ? `this field's ${f.n} examples` : `all ${profile.n} examples (this field has too few of its own)`;
    reason = `Stated ${pct(raw)}; measured on ${basis}, values like this are right about ${pct(p)} of the time` +
      (opts.conservative ? ` (at least ${pct(lower)})` : "") + `.`;
  }
  reason += fill ? ` Clears the ${pct(threshold)} bar.` : ` Below the ${pct(threshold)} bar, so a person should check it.`;
  return {
    field,
    action: fill ? "fill" : "review",
    confidence: round6(p),
    lower: round6(lower),
    threshold,
    calibrated: source !== "raw",
    source,
    reason,
  };
}

/** decideAll(profile, [{ field, value, confidence }]) -> { decisions, fill, review } */
export function decideAll(profile, items, overrides = {}) {
  const decisions = items.map((it) => decide(profile, it, overrides));
  return {
    decisions,
    fill: decisions.filter((d) => d.action === "fill").length,
    review: decisions.filter((d) => d.action === "review").length,
  };
}

// ---------- honest evaluation (k-fold) ----------

/**
 * Held-out estimate of what Gate would do on new documents.
 * Fold assignment is index % k on the given order (shuffle first if your data is sorted).
 */
export function evaluate(examples, options = {}, k = 5) {
  examples.forEach(checkExample);
  if (examples.length < k) throw new RangeError(`need at least ${k} examples for ${k}-fold evaluation`);
  const decided = [];
  for (let fold = 0; fold < k; fold++) {
    const train = examples.filter((_, i) => i % k !== fold);
    const test = examples.filter((_, i) => i % k === fold);
    const prof = calibrate(train, options);
    for (const e of test) {
      const d = decide(prof, { field: e.field, value: "x", confidence: e.confidence });
      decided.push({ e, d });
    }
  }
  const costsFor = (field) => resolveOptions(options, options.fields && options.fields[field]);
  const summarise = (rows) => {
    const n = rows.length;
    let autoCount = 0;
    let autoErrors = 0;
    let cost = 0;
    let manual = 0;
    for (const r of rows) {
      const o = costsFor(r.d.field);
      const reviewEach = o.costReview + (1 - o.reviewAccuracy) * o.costError;
      manual += reviewEach;
      if (r.d.action === "fill") {
        autoCount += 1;
        if (!r.e.correct) {
          autoErrors += 1;
          cost += o.costError;
        }
      } else cost += reviewEach;
    }
    return {
      n,
      accuracy: round6(rows.filter((r) => r.e.correct).length / n),
      coverage: round6(autoCount / n),
      autoErrorRate: autoCount ? round6(autoErrors / autoCount) : 0,
      autoErrors,
      eceRaw: ece(rows.map((r) => r.e.confidence), rows.map((r) => r.e.correct)),
      eceCalibrated: ece(rows.map((r) => r.d.confidence), rows.map((r) => r.e.correct)),
      savingsVsManual: manual > 0 ? round6(1 - cost / manual) : 0,
    };
  };
  const fields = {};
  const names = [...new Set(decided.map((r) => (r.e.field == null ? "*" : String(r.e.field))))].sort();
  for (const name of names) fields[name] = summarise(decided.filter((r) => (r.e.field == null ? "*" : String(r.e.field)) === name));
  return { k, overall: summarise(decided), fields };
}
