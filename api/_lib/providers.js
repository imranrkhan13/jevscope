// Bring-your-own-key relay to an LLM. The caller's key is used for one request
// and is never stored or logged. The model id is always the caller's choice.
export const PROVIDERS = ["openai", "anthropic", "gemini"];

export function buildPrompt(text, fields) {
  const list = fields
    .map((f) => `- ${f.name}${f.type ? ` (${f.type})` : ""}${f.description ? `: ${f.description}` : ""}`)
    .join("\n");
  return [
    "Extract these fields from the document below.",
    list,
    "",
    'Reply with JSON only, shaped like {"fields": {"<name>": {"value": <value or null>, "confidence": <number 0-1>}}}.',
    "confidence is your probability that the value is exactly right. Use null when the field is not in the document.",
    "",
    "DOCUMENT:",
    text,
  ].join("\n");
}

function withTimeout(ms) {
  const c = new AbortController();
  const t = setTimeout(() => c.abort(), ms);
  return { signal: c.signal, done: () => clearTimeout(t) };
}

export async function callProvider({ provider, model, key, prompt, fetchImpl = fetch, timeoutMs = 25_000 }) {
  const t = withTimeout(timeoutMs);
  try {
    let r;
    if (provider === "openai") {
      r = await fetchImpl("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        signal: t.signal,
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model, messages: [{ role: "user", content: prompt }], response_format: { type: "json_object" } }),
      });
      const j = await safeJson(r);
      if (!r.ok) throw providerError(r.status, j);
      return j?.choices?.[0]?.message?.content ?? "";
    }
    if (provider === "anthropic") {
      r = await fetchImpl("https://api.anthropic.com/v1/messages", {
        method: "POST",
        signal: t.signal,
        headers: { "x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json" },
        body: JSON.stringify({ model, max_tokens: 2048, messages: [{ role: "user", content: prompt }] }),
      });
      const j = await safeJson(r);
      if (!r.ok) throw providerError(r.status, j);
      return (j?.content || []).filter((b) => b.type === "text").map((b) => b.text).join("");
    }
    if (provider === "gemini") {
      r = await fetchImpl(`https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`, {
        method: "POST",
        signal: t.signal,
        headers: { "x-goog-api-key": key, "Content-Type": "application/json" },
        body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }], generationConfig: { responseMimeType: "application/json" } }),
      });
      const j = await safeJson(r);
      if (!r.ok) throw providerError(r.status, j);
      return (j?.candidates?.[0]?.content?.parts || []).map((p) => p.text || "").join("");
    }
    throw Object.assign(new Error(`provider must be one of ${PROVIDERS.join(", ")}`), { status: 400 });
  } catch (e) {
    if (e.name === "AbortError") throw Object.assign(new Error("The AI provider took too long (25s)."), { status: 504, code: "provider_timeout" });
    throw e;
  } finally {
    t.done();
  }
}

async function safeJson(r) {
  try {
    return await r.json();
  } catch {
    return null;
  }
}

function providerError(status, j) {
  // Pass the provider's message through (it never contains the key), but not the whole body.
  const msg = j?.error?.message || j?.error?.status || `status ${status}`;
  const code = status === 401 || status === 403 ? "provider_auth" : status === 429 ? "provider_rate_limited" : "provider_error";
  return Object.assign(new Error(`AI provider error: ${String(msg).slice(0, 300)}`), { status: 502, code, providerStatus: status });
}

// Pull {"fields": {...}} out of a model reply, tolerating code fences.
export function parseExtraction(reply, fields) {
  let s = String(reply || "").trim();
  const fence = s.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) s = fence[1];
  const start = s.indexOf("{");
  const end = s.lastIndexOf("}");
  let obj = null;
  if (start >= 0 && end > start) {
    try {
      obj = JSON.parse(s.slice(start, end + 1));
    } catch {
      obj = null;
    }
  }
  const got = (obj && typeof obj.fields === "object" && obj.fields) || obj || {};
  return fields.map((f) => {
    const v = got[f.name];
    if (v && typeof v === "object" && !Array.isArray(v) && ("value" in v || "confidence" in v)) {
      const c = typeof v.confidence === "number" ? v.confidence : Number(v.confidence);
      return { field: f.name, value: v.value ?? null, confidence: Number.isFinite(c) ? Math.min(1, Math.max(0, c)) : null };
    }
    return { field: f.name, value: v ?? null, confidence: null };
  });
}
