# JevAPI

**Should this field be filled automatically, or should a person check it?**

Apps that pull data out of documents (invoices, resumes, IDs, insurance forms)
get a value and a confidence for every field. The confidence is a claim, and
models are often wrong about it. On JevScope's real public-repo study, one
classifier claimed about 98% confidence and was right 68.5% of the time.

JevAPI measures the claim on your own labelled examples and turns it into a
decision you can defend:

```js
import { calibrate, decide } from "jevapi";

const profile = calibrate(labelledExamples, {
  costError: 20,                          // a wrong fill costs as much as 20 human checks
  fields: { total_amount: { costError: 100 }, due_date: { maxRisk: 0.05 } },
});

decide(profile, { field: "total_amount", value: "₹48,200", confidence: 0.97 });
// { action: "review", confidence: 0.78, lower: 0.73, threshold: 0.99,
//   reason: "Stated 97%; measured on this field's 200 examples, values like this
//            are right about 78% of the time (at least 73%). Below the 99% bar,
//            so a person should check it." }
```

```python
from jevapi import calibrate, decide

profile = calibrate(labelled_examples, {"costError": 20})
decide(profile, {"field": "invoice_number", "value": "INV-2231", "confidence": 0.99})
```

Same maths, same JSON profile format, same answers in JavaScript and Python
(both are tested against one shared spec file). Zero dependencies. Runs on your
machine or in the browser; nothing is sent anywhere.

## How it decides

1. **Calibrate.** For each field, isotonic regression maps "the extractor said
   0.97" to "on your examples, values like this were right X% of the time".
   Fields with fewer than 30 examples borrow the pooled calibration, and say so.
2. **Be careful with small samples.** By default it decides on a 90% lower
   bound (Wilson), not the point estimate, so 10 lucky examples cannot unlock
   auto-fill.
3. **Apply your costs.** Fill when the expected cost of a wrong fill is lower
   than a human check: `p > reviewAccuracy - costReview / costError`. Add
   `maxRisk` to set a hard ceiling on the chance of a wrong fill.
4. **Explain.** Every decision carries a plain-English reason.

Empty values, missing or broken confidences, and values that fail your own
`validate` function always go to review.

## Check it before you trust it

```js
import { evaluate } from "jevapi";
evaluate(labelledExamples, options, 5);
// held-out (5-fold) coverage, auto-fill error rate, ECE before/after, savings vs checking everything
```

## Labelled examples

One row per extracted field you have checked by hand:

```json
{ "field": "total_amount", "confidence": 0.97, "correct": false }
```

A few hundred rows per important field is a good start. The numbers only mean
something for documents like the ones you labelled.

## Honest limits

- The sample data in `spec/examples.json` is **synthetic**. It exists to test
  the maths. It says nothing about any real model.
- Calibration fitted on one kind of document does not transfer to another.
- On npm: `npm i jevapi`. Not on PyPI yet.

MIT licensed. Part of [JevScope](https://github.com/imranrkhan13/jevscope).
