import io
import json
import pathlib

import pytest

import jevapi
from jevapi import CURRENCY_HINTS, answers_to_items, build_questions, check_fields, core_fields, decide_all, discover_fields, normalize, correctness_probability, vendor_candidates

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
    assert [(x["name"], x.get("value", x.get("options", [])[:3])) for x in f] == [
        ("vendor", ["ACME LTD"]), ("currency", ["INR", "USD", "EUR"]),
        ("invoice_no", "INV-2231"), ("due_date", "2026-10-15"), ("sub_total", "21,450"), ("gst_18", "3,861"), ("invoice_no_2", "X-2")]
    assert discover_fields("") == []
    assert len(discover_fields("\n".join(f"Field {i}: v" for i in range(80)))) == 50


def test_vendor_and_currency_always_asked_on_invoices():
    f = discover_fields("NORTH STAR LOGISTICS PVT LTD\n12 Dock Road\nInvoice\nFreight Mumbai -> Delhi\nT0TAL $25,311")
    assert next(x for x in f if x["name"] == "vendor")["options"] == ["NORTH STAR LOGISTICS PVT LTD", "12 Dock Road"]
    assert next(x for x in f if x["name"] == "currency")["options"][0] == "USD"
    assert vendor_candidates("Invoice\nRemit to:\nWTHI\nBilling Address:\nJohn Roach")[0] == "WTHI"
    labelled = discover_fields("Invoice\nVendor: Acme\nCurrency: INR")
    assert [x["name"] for x in labelled] == ["vendor", "currency"] and labelled[0]["value"] == "Acme"
    assert core_fields("Name: Imran\nSkills: Python") == []


def test_real_invoices_always_get_vendor_and_currency():
    from pathlib import Path
    fx = json.loads((Path(__file__).resolve().parents[2] / "spec" / "real_invoices.json").read_text())
    for d in fx["invoices"]:
        f = discover_fields(d["text"])
        v = next(x for x in f if x["name"] == "vendor")
        assert any(w in o.lower() for o in v["options"] for w in d["vendor_any"]), d["id"]
        assert next(x for x in f if x["name"] == "currency")["options"][0] == "USD"


def test_resume_mode_matches_hand_labels():
    from pathlib import Path
    from jevapi import is_resume, join_wrapped
    fx = json.loads((Path(__file__).resolve().parents[2] / "spec" / "resumes.json").read_text(encoding="utf-8"))
    for r in fx["resumes"]:
        assert is_resume(r["text"])
        assert {f["name"]: f["value"] for f in discover_fields(r["text"])} == r["gold"], r["id"]
    assert join_wrapped("availability-aware schedul-", "  ing and booking") == "availability-aware scheduling and booking"
    assert join_wrapped("resume uploads, job-", "  description parsing") == "resume uploads, job-description parsing"
    assert join_wrapped("GitHub Actions, NGINX,", "Azure, GCP") == "GitHub Actions, NGINX, Azure, GCP"
    assert not is_resume("ACME LTD\nInvoice No: 1\nTotal: 5")


def test_resume_layouts():
    from jevapi import resume_fields
    get = lambda t: {f["name"]: f["value"] for f in resume_fields(t)}
    a = get("A B\na@b.co\n\nExperience\nAcme Corp                              Pune, India\nBackend Engineer                       Jan 2020 – Mar 2021\n• Built X.\n• Built Y.\n  and Z\nA B · Résumé    2\n\nEducation\nBSc in Physics    2019\nUniversity of Pune")
    assert (a["job_1_company"], a["job_1_title"], a["job_1_location"], a["job_1_dates"]) == ("Acme Corp", "Backend Engineer", "Pune, India", "Jan 2020 – Mar 2021")
    assert (a["job_1_highlight_1"], a["job_1_highlight_2"], a["education_1_school"]) == ("Built X.", "Built Y. and Z", "University of Pune")
    assert not any("Résumé" in v for v in a.values())
    b = get("A B\na@b.co\n\nExperience\nNexus AI, Co-Founder & CTO                      San Francisco, CA\n • Built it                                  June 2023 – present\n                                                  2 years 10 months\n\nSkills\nGo")
    assert (b["job_1_company"], b["job_1_title"], b["job_1_dates"], b["job_1_highlight_1"]) == ("Nexus AI", "Co-Founder & CTO", "June 2023 – present", "Built it")
    assert not any("months" in v for v in b.values())
    f = next(f for f in resume_fields("A B\na@b.co\n\nExperience\nEngineer    2020\nAcme, Pune\n\nSkills\nGo") if f["name"] == "job_1_company")
    assert '"Engineer" job' in f["description"]

def test_company_first_layout():
    from jevapi import resume_fields
    a = {f["name"]: f["value"] for f in resume_fields("A B\na@b.co\nProfile\nBuilds APIs.\nExperience\nAcme Labs   Jan 2024 – Present\nBackend Developer   ShipIt\nTracking for small shops\n• Shipped more than\n60 features, fixes, and reports.\n• Used Go, Rust, and\nZig.\nOrbit Co   2022 – 2023\nEngineer   Pune, India\n1\nSelected Projects | Backend\nQueueLens   |   Queue viewer | Python, Redis\n• Shows stuck jobs.\nAdditional Engineering Projects\nShelfScan   – Reads barcodes.\nTinyForms   – Form builder.\n2")}
    assert a["summary"] == "Builds APIs."
    assert (a["job_1_company"], a["job_1_title"], a["job_1_product"], a["job_1_about"]) == ("Acme Labs", "Backend Developer", "ShipIt", "Tracking for small shops")
    assert "job_1_location" not in a and "job_3_title" not in a
    assert a["job_1_highlight_1"] == "Shipped more than 60 features, fixes, and reports."
    assert a["job_1_highlight_2"] == "Used Go, Rust, and Zig."
    assert a["job_2_location"] == "Pune, India" and "job_2_product" not in a
    assert (a["project_1_name"], a["project_1_summary"], a["project_1_tech"]) == ("QueueLens", "Queue viewer", "Python, Redis")
    assert (a["project_2_name"], a["project_2_summary"], a["project_3_name"]) == ("ShelfScan", "Reads barcodes.", "TinyForms")
    assert not any(k.startswith("education") for k in a) and "1" not in a.values() and "2" not in a.values()


def test_jev_reason_wording():
    r = decide_all(None, [{"field": "a", "value": "x", "confidence": 0.99, "jev": {"type": "noul", "noul": 0.99}},
                          {"field": "b", "value": "y", "confidence": 0.99}])
    assert "Jev's raw 99%" in r["decisions"][0]["reason"]
    assert "extractor's own 99%" in r["decisions"][1]["reason"]


def test_choice_option_keys_map_back():
    fields = [{"name": "vendor", "options": ["ACME LTD", "Kiran Traders"]}, {"name": "currency", "options": ["INR", "USD"], "hints": CURRENCY_HINTS}]
    q = build_questions(fields)
    assert list(q["f0"]["criteria"]) == ["o0", "o1", "not_stated"]
    assert '"ACME LTD" as the vendor' in q["f0"]["criteria"]["o0"]
    assert "US dollars" in q["f1"]["criteria"]["USD"]
    items = answers_to_items(fields, {"f0": {"type": "choice", "choice": "o0", "probabilities": {"o0": 0.9, "o1": 0.05, "not_stated": 0.05}},
                                      "f1": {"type": "choice", "choice": "not_stated", "probabilities": {"INR": 0.2, "USD": 0.1, "not_stated": 0.7}}})
    assert [(i["value"], i["jev"]["choice"], i["confidence"]) for i in items] == [("ACME LTD", "ACME LTD", 0.9), (None, "not_stated", 0.7)]


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
        return _Resp(json.dumps({"answers": {"f0": {"type": "choice", "choice": "not_stated", "probabilities": {"not_stated": 0.8}},
                                             "f1": {"type": "noul", "noul": 0.99}}}).encode())

    items = check_fields("Invoice No: INV-2231", None, key="k", opener=opener)
    assert items[0]["field"] == "currency" and items[0]["value"] is None and items[0]["confidence"] == 0.8
    assert items[1:] == [{"field": "invoice_no", "label": "Invoice No", "value": "INV-2231", "confidence": 0.99,
                      "jev": {"type": "noul", "noul": 0.99, "certainty": pytest.approx(0.98)}}]


def test_key_required():
    with pytest.raises(ValueError):
        jevapi.ask_jev("d", {}, key="")


# ---- Receipts, bank statements, forms (real public datasets; see spec/*.json for source and license) ----

def _spec(name):
    return json.loads((pathlib.Path(__file__).resolve().parents[2] / "spec" / name).read_text())


def test_receipts_match_cord_labels():
    from jevapi import is_receipt
    for d in _spec("receipts.json")["receipts"]:
        assert is_receipt(d["text"]), d["id"]
        got = {f["name"]: f.get("value") for f in discover_fields(d["text"])}
        for k, v in d["gold"].items():
            assert got.get(k) == v, f"{d['id']} {k}: {got.get(k)!r} != {v!r}"


def test_bank_statements_match_labels():
    from jevapi import is_bank_statement
    for d in _spec("bank_statements.json")["bank_statements"]:
        assert is_bank_statement(d["text"]), d["id"]
        got = {f["name"]: f.get("value") for f in discover_fields(d["text"])}
        for k, v in d["gold"].items():
            assert got.get(k) == v, f"{d['id']} {k}: {got.get(k)!r} != {v!r}"


def test_forms_match_funsd_labels():
    from jevapi import is_form
    for d in _spec("forms.json")["forms"]:
        assert is_form(d["text"]), d["id"]
        got = {f["name"]: f.get("value") for f in discover_fields(d["text"])}
        for k, v in d["gold"].items():
            assert got.get(k) == v, f"{d['id']} {k}: {got.get(k)!r} != {v!r}"


def test_readers_do_not_fight_each_other():
    from jevapi import is_bank_statement, is_form, is_receipt
    for d in _spec("real_invoices.json")["invoices"]:
        assert not is_receipt(d["text"]) and not is_bank_statement(d["text"]) and not is_form(d["text"]), d["id"]
        assert any(f["name"] == "vendor" for f in discover_fields(d["text"])), d["id"]
    for r in _spec("resumes.json")["resumes"]:
        assert any(f["name"] == "name" for f in discover_fields(r["text"])), r["id"]
    scan = "1nvoice\nBlll To: Acme\nAM0UNT DUE: 700.00\nremit to\nreceipt of payment\nJAN 1 2 1999\n83443897"
    assert not is_receipt(scan) and not is_form(scan)
    assert not is_form(_spec("receipts.json")["receipts"][0]["text"])
    assert not is_receipt(_spec("forms.json")["forms"][2]["text"])
    stmt = _spec("bank_statements.json")["bank_statements"][0]["text"]
    assert not is_receipt(stmt) and not is_form(stmt)


def test_extract_candidate_spans_match_shared_spec():
    fx = json.loads((ROOT / "jevapi/spec/extract_candidates.json").read_text())
    for c in fx["cases"]:
        assert jevapi.candidate_spans(c["document"], c["field"]) == c["candidates"], c["id"]


def test_extract_by_verification_picks_jevs_best_and_abstains(monkeypatch):
    doc = "MART\n2x Tea 4.50 CHF 9.00\nTotal : CHF 54.50\nCash 100.00"
    probs = {"4.50": 0.05, "9.00": 0.2, "54.50": 0.97, "100.00": 0.4}

    def fake_ask(state, questions, key, **opts):
        answers = {}
        for k, q in questions.items():
            v = q["instructions"].split('give "')[1].split('"')[0]
            answers[k] = {"type": "noul", "noul": probs[v]}
        return {"answers": answers, "usage": {"input_tokens": 1}, "model": "mock"}

    monkeypatch.setattr("jevapi.extract.ask_jev", fake_ask)
    out = jevapi.extract_by_verification(doc, ["total"], key="k")
    assert out["items"][0]["value"] == "54.50"
    assert out["items"][0]["confidence"] == 0.97
    assert out["items"][0]["jev"]["candidates"] == 4

    def low_ask(state, questions, key, **opts):
        return {"answers": {k: {"type": "noul", "noul": 0.3} for k in questions}}

    monkeypatch.setattr("jevapi.extract.ask_jev", low_ask)
    low = jevapi.extract_by_verification(doc, ["total"], key="k")
    assert low["items"][0]["value"] is None
    assert low["items"][0]["jev"]["abstained"] is True

    # A confidently-wrong noul (0.02) must NOT beat a genuinely-right one.
    def trap_ask(state, questions, key, **opts):
        answers = {}
        for k, q in questions.items():
            v = q["instructions"].split('give "')[1].split('"')[0]
            answers[k] = {"type": "noul", "noul": 0.02 if v == "9.00" else 0.6 if v == "54.50" else 0.1}
        return {"answers": answers}

    monkeypatch.setattr("jevapi.extract.ask_jev", trap_ask)
    trap = jevapi.extract_by_verification(doc, ["total"], key="k")
    assert trap["items"][0]["value"] == "54.50"
