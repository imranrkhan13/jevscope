import { decideAll, validateProfile } from "../../jevapi/js/src/index.js";
import { endpoint, LIMITS, RATE, badRequest } from "../_lib/http.js";
import { cleanOptions, listOf } from "../_lib/validate.js";

export default endpoint({ bucket: "math", rate: RATE.math }, async (body) => {
  const items = listOf(body.items, "items", LIMITS.items);
  let profile = null;
  if (body.profile != null) {
    try {
      profile = validateProfile(body.profile);
    } catch (e) {
      throw badRequest(`profile: ${e.message}`, "bad_profile");
    }
  }
  const out = decideAll(profile, items, cleanOptions(body.options));
  if (!profile) out.note = "No profile sent, so decisions use the raw confidence (not calibrated).";
  return [200, out];
});
