import { calibrate, evaluate } from "../../jevapi/js/src/index.js";
import { endpoint, LIMITS, RATE } from "../_lib/http.js";
import { cleanOptions, listOf } from "../_lib/validate.js";

export default endpoint({ bucket: "math", rate: RATE.math }, async (body) => {
  const examples = listOf(body.examples, "examples", LIMITS.examples);
  const options = cleanOptions(body.options);
  const profile = calibrate(examples, options);
  const out = { profile };
  if (body.evaluate) out.evaluation = evaluate(examples, options, 5);
  return [200, out];
});
