// Shared helpers for the JevAPI hosted endpoints. Stateless: nothing is stored.
export const LIMITS = Object.freeze({
  bodyBytes: 1_000_000,
  examples: 5000,
  items: 200,
  textChars: 60_000,
  fields: 50,
});

// Best-effort rate limit, per server instance (no shared store on the free plan).
const WINDOW_MS = 60_000;
const buckets = new Map();
export const RATE = Object.freeze({ math: 60, extract: 10 });

export function rateLimit(key, limit, now = Date.now()) {
  let b = buckets.get(key);
  if (!b || now - b.start >= WINDOW_MS) {
    b = { start: now, count: 0 };
    buckets.set(key, b);
  }
  b.count += 1;
  if (buckets.size > 10_000) {
    for (const [k, v] of buckets) if (now - v.start >= WINDOW_MS) buckets.delete(k);
  }
  const remaining = Math.max(0, limit - b.count);
  const reset = Math.ceil((b.start + WINDOW_MS - now) / 1000);
  return { ok: b.count <= limit, remaining, reset, limit };
}

export function _resetRateLimits() {
  buckets.clear();
}

export function clientIp(req) {
  const h = req.headers || {};
  const fwd = String(h["x-forwarded-for"] || "").split(",")[0].trim();
  return fwd || String(h["x-real-ip"] || "") || "unknown";
}

export function send(res, status, body, extraHeaders = {}) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Provider-Key");
  res.setHeader("Cache-Control", "no-store");
  for (const [k, v] of Object.entries(extraHeaders)) res.setHeader(k, String(v));
  res.end(JSON.stringify(body));
}

export function fail(res, status, code, message, extra = {}) {
  send(res, status, { error: { code, message } }, extra);
}

export async function readJson(req) {
  if (req.body !== undefined && req.body !== null) {
    if (typeof req.body === "object" && !Buffer.isBuffer(req.body)) return req.body;
    const s = Buffer.isBuffer(req.body) ? req.body.toString("utf8") : String(req.body);
    if (s.length > LIMITS.bodyBytes) throw Object.assign(new Error("Body is too large (max 1 MB)."), { status: 413 });
    return JSON.parse(s);
  }
  let size = 0;
  const chunks = [];
  for await (const c of req) {
    size += c.length;
    if (size > LIMITS.bodyBytes) throw Object.assign(new Error("Body is too large (max 1 MB)."), { status: 413 });
    chunks.push(c);
  }
  const s = Buffer.concat(chunks).toString("utf8");
  return s ? JSON.parse(s) : {};
}

// Wraps a handler with CORS preflight, method check, size limit, JSON parsing and rate limiting.
export function endpoint({ methods = ["POST"], rate = RATE.math, bucket }, fn) {
  return async function handler(req, res) {
    if (req.method === "OPTIONS") return send(res, 204, {});
    if (!methods.includes(req.method)) return fail(res, 405, "method_not_allowed", `Use ${methods.join(" or ")}.`, { Allow: methods.join(", ") });
    const rl = rateLimit(`${bucket}:${clientIp(req)}`, rate);
    const rlHeaders = { "X-RateLimit-Limit": rl.limit, "X-RateLimit-Remaining": rl.remaining, "X-RateLimit-Reset": rl.reset };
    if (!rl.ok) return fail(res, 429, "rate_limited", `Too many requests. Try again in ${rl.reset}s.`, { ...rlHeaders, "Retry-After": rl.reset });
    const len = Number((req.headers || {})["content-length"] || 0);
    if (len > LIMITS.bodyBytes) return fail(res, 413, "too_large", "Body is too large (max 1 MB).", rlHeaders);
    let body = {};
    if (req.method === "POST") {
      try {
        body = await readJson(req);
      } catch (e) {
        return fail(res, e.status || 400, e.status === 413 ? "too_large" : "bad_json", e.status ? e.message : "Body must be valid JSON.", rlHeaders);
      }
      if (!body || typeof body !== "object" || Array.isArray(body)) return fail(res, 400, "bad_request", "Body must be a JSON object.", rlHeaders);
    }
    try {
      const [status, out] = await fn(body, req);
      return send(res, status, out, rlHeaders);
    } catch (e) {
      const status = e.status || (e instanceof TypeError || e instanceof RangeError ? 400 : 500);
      return fail(res, status, e.code || (status === 400 ? "bad_request" : "server_error"), status === 500 ? "Something went wrong." : e.message, rlHeaders);
    }
  };
}

export function badRequest(message, code = "bad_request") {
  return Object.assign(new Error(message), { status: 400, code });
}
