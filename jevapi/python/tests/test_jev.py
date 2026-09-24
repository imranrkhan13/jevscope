import io
import json
import pathlib

import pytest

import jevapi
from jevapi import answers_to_items, build_questions, check_fields, decide_all, discover_fields, normalize, correctness_probability

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = json.loads((ROOT / "jevapi/spec/jev_certainty.json").read_text())


def test_certainty_is_jevscopes_own_file_unchanged():
    original = ROOT / "reposcope/calibration/certainty.py"
    shipped = pathlib.Path(jevapi.__file__).with_name("certainty.py")
    if not original.exists():
        pytest.skip("not running inside the jevscope repo")
    assert shipped.read_bytes() == original.read_bytes()


@pytest.mark.parametrize("case", SPEC["cases"])
def test_certainty_matches_spec(case):
    n = normalize(case["answer"])
    e = case["expected"]
    assert n.answer_type == e["answerType"]
    assert n.prediction == e["prediction"]
    assert n.certainty == pytest.approx(e["certainty"])
    assert correctness_probability(n) == pytest.approx(e["correctness"])


FIELDS = [
    {"name": "invoice_number", "value": "INV-2231"},
    {"name": "total", "value": 1200.5, "description": "amount due"},
    {"name": "currency", "options": ["USD", "INR", "EUR"]},
    {"name": "po_number", "value": ""},
]
ANSWERS = {
    "f0": {"type": "noul", "noul": 0.97},
    "f1": {"type": "noul", "noul": 0.08},
    "f2": {"type": "choice", "choice": "INR", "confidence": 0.9,
           "probabilities": {"USD": 0.01, "INR": 0.98, "EUR": 0.0, "not_stated": 0.01}},
}


def test_questions_match_js():
    q = build_questions(FIELDS)
    assert list(q) == ["f0", "f1", "f2"]
    assert q["f0"]["instructions"] == 'Does the document give "INV-2231" as the invoice_number?'
    assert q["f1"]["instructions"] == 'Does the document give "1200.5" as the total (amount due)?'
    assert list(q["f2"]["criteria"]) == ["USD", "INR", "EUR", "not_stated"]


def test_items_and_decisions():
    items = answers_to_items(FIELDS, ANSWERS)
    assert [(i["field"], i["value"], i["confidence"]) for i in items] == [
        ("invoice_number", "INV-2231", 0.97), ("total", 1200.5, 0.08), ("currency", "INR", 0.98), ("po_number", "", None)]
    assert [d["action"] for d in decide_all(None, items)["decisions"]] == ["fill", "review", "fill", "review"]


def test_discover_matches_js():
    f = discover_fields("ACME LTD\nInvoice No: INV-2231\nDue date: 2026-10-15\nSub total 21,450\nGST 18% 3,861\nThank you!\nInvoice No: X-2")
    assert [(x["name"], x["value"]) for x in f] == [
        ("invoice_no", "INV-2231"), ("due_date", "2026-10-15"), ("sub_total", "21,450"), ("gst_18", "3,861"), ("invoice_no_2", "X-2")]
    assert discover_fields("") == []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_fields_posts_typesafe_shape():
    seen = []

    def opener(req, timeout):
        seen.append(req)
        return _Resp(json.dumps({"answers": ANSWERS}).encode())

    items = check_fields("Invoice INV-2231", FIELDS, key="k1", opener=opener)
    req = seen[0]
    assert req.full_url == "https://api.typesafe.ai/v1/systemone"
    assert req.get_header("Authorization") == "Bearer k1"
    body = json.loads(req.data)
    assert body["model"] == "jev-latest" and body["state"] == "Invoice INV-2231"
    assert items[2]["value"] == "INR"


def test_check_fields_discovers_when_no_list():
    def opener(req, timeout):
        return _Resp(json.dumps({"answers": {"f0": {"type": "noul", "noul": 0.99}}}).encode())

    items = check_fields("Invoice No: INV-2231", None, key="k", opener=opener)
    assert items == [{"field": "invoice_no", "label": "Invoice No", "value": "INV-2231", "confidence": 0.99,
                      "jev": {"type": "noul", "noul": 0.99, "certainty": pytest.approx(0.98)}}]


def test_key_required():
    with pytest.raises(ValueError):
        jevapi.ask_jev("d", {}, key="")
