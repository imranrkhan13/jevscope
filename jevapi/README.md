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
- Not published to npm or PyPI yet.

MIT licensed. Part of [JevScope](https://github.com/imranrkhan13/jevscope).

## Running on Jev

Jev is TypeSafe's decision model (https://docs.typesafe.ai). It never writes text; it answers typed questions with probabilities. JevAPI uses it as the judge: for each field, Jev is asked "does the document give X as the invoice number?" (a Noul), or picks from a fixed list (a Choice, with a "not_stated" option). Jev's probability becomes the field's confidence, and JevAPI decides fill or review.

```js
import { checkFields, decideAll } from "jevapi";
const { items } = await checkFields({ document: text, key: process.env.TYPESAFE_API_KEY,
  fields: [{ name: "invoice_number", value: "INV-2231" }, { name: "currency", options: ["INR", "USD"] }] });
const { decisions } = decideAll(profile, items); // profile: calibrate() on your own labelled Jev answers
```

```python
from jevapi import check_fields, decide_all
items = check_fields(text, [{"name": "invoice_number", "value": "INV-2231"}], key=os.environ["TYPESAFE_API_KEY"])
```

No field list? Pass no fields (`fields: null` / `None`). JevAPI finds every labelled field in the text ("Invoice No: ...", "Total 48,200") and Jev checks each one. That finder is simple pattern matching; for free-form documents use the hosted `/api/v1/extract` without `fields`, which asks your AI for every field, with `"judge": "jev"`.

Hosted: `POST /api/v1/verify` with header `X-Jev-Key`, or `POST /api/v1/extract` with `"judge": "jev"`.

What is Jev and what is not:

| Part | Where it comes from |
| --- | --- |
| The per-field probability | Jev itself, called with your own TypeSafe key |
| Turning Jev's noul/choice/score answers into one certainty | `jevapi/python/jevapi/certainty.py` is jevscope's own `reposcope/calibration/certainty.py`, unchanged (a test fails if they differ). `jevapi/js/src/certainty.js` is a line-for-line port, checked against the Python original's outputs |
| Calibration and the cost bar | JevAPI's own code, written for this package, using the same methods as the Calibration Lab |
| Field finding, question wording, HTTP client, API routes, demo | New glue code |

Jev's probabilities are raw until you calibrate them on your own labelled documents. The sample data in this repo is synthetic.
