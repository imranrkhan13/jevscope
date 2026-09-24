// Shared parsing for the endpoints that call Jev. The caller's Jev key is used
// for one request and never stored or logged by this code.
import { JEV_PROVIDERS, JevError } from "../../jevapi/js/src/index.js";
import { badRequest } from "./http.js";

export function jevKey(req) {
  return String((req.headers || {})["x-jev-key"] || "").trim();
}

export function jevConfig(body) {
  const provider = body.jevProvider == null ? "typesafe" : body.jevProvider;
  if (!(provider in JEV_PROVIDERS)) throw badRequest(`jevProvider must be one of ${Object.keys(JEV_PROVIDERS).join(", ")}`);
  if (body.jevModel != null && (typeof body.jevModel !== "string" || !/^[\w.\-:/@~]{1,100}$/.test(body.jevModel))) throw badRequest("jevModel must be a Jev model id, e.g. jev-latest");
  return { provider, model: body.jevModel || undefined };
}

export function jevFailure(e) {
  if (e instanceof JevError) {
    const code = e.status === 401 || e.status === 403 ? "jev_auth" : e.status === 429 ? "jev_rate_limited" : e.status === 504 ? "jev_timeout" : "jev_error";
    return Object.assign(new Error(e.message), { status: e.status === 504 ? 504 : 502, code });
  }
  return e;
}
