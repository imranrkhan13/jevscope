// Line-for-line JavaScript port of jevscope's reposcope/calibration/certainty.py
// (Imran Khan's Jev answer normaliser). Kept in step by a parity test against
// outputs produced by the Python original: jevapi/spec/jev_certainty.json.
//
// Jev returns three answer shapes and they do not carry certainty the same way:
//   noul    a single probability in [0,1]; no confidence field. 0.5 is maximal
//           uncertainty and both tails are confident.
//   choice  a selected option, a distribution, and a confidence scalar.
//   score   a probability-weighted score, a legend, a distribution, and confidence.
// This maps all three onto one axis: certainty in [0,1].

function normalizedEntropy(probs) {
  const clean = probs.filter((p) => p > 0);
  if (clean.length <= 1) return 0;
  const entropy = -clean.reduce((s, p) => s + p * Math.log(p), 0);
  return Math.min(1, entropy / Math.log(probs.length));
}

function margin(probs) {
  if (probs.length < 2) return 1;
  const [top, second] = [...probs].sort((a, b) => b - a);
  return top - second;
}

// Python's round() is banker's rounding; match it for score levels.
function pyRound(x) {
  const f = Math.floor(x);
  const d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/** normalize(answer) -> { answerType, prediction, certainty, reportedConfidence, distributionCertainty, raw } */
export function normalize(answer) {
  const kind = answer && answer.type;
  if (kind === "noul") {
    const p = Number(answer.noul);
    return {
      answerType: "noul",
      prediction: p >= 0.5 ? "true" : "false",
      certainty: Math.abs(p - 0.5) * 2,
      reportedConfidence: null,
      distributionCertainty: 1 - normalizedEntropy([p, 1 - p]),
      raw: answer,
    };
  }
  if (kind === "choice" || kind === "score") {
    const probs = Object.values(answer.probabilities || {}).map(Number);
    const reported = answer.confidence;
    const dist = probs.length ? margin(probs) : null;
    const hasRep = reported !== undefined && reported !== null;
    return {
      answerType: kind,
      prediction: kind === "choice" ? String(answer.choice) : String(pyRound(Number(answer.score))),
      certainty: hasRep ? Number(reported) : dist || 0,
      reportedConfidence: hasRep ? Number(reported) : null,
      distributionCertainty: dist,
      raw: answer,
    };
  }
  throw new Error(`Unknown Jev answer type: ${JSON.stringify(kind)}`);
}

/** The model's implied probability that its own prediction is right. */
export function correctnessProbability(norm) {
  if (norm.answerType === "noul") {
    const p = Number(norm.raw.noul);
    return norm.prediction === "true" ? p : 1 - p;
  }
  const probs = norm.raw.probabilities || {};
  if (Object.keys(probs).length) {
    return norm.prediction in probs ? Number(probs[norm.prediction]) : norm.certainty;
  }
  return norm.certainty;
}
