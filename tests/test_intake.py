"""Document intake: extraction verified against the OCR text, the alert built by
rules with the model's words only, and end to end on the printed scans.

Static tests run anywhere; the end-to-end ones need `make db-up mock kb` and
Tesseract (and Ollama for the composed alert — the template stands in without it).
"""

import json
import os
import shutil

import pytest

from new_horizons.app.intake import extract as X
from new_horizons.app.intake import pipeline as P
from new_horizons.paths import DATA

SAMPLES = DATA / "samples"
META = DATA / "mock_meta.json"

INVOICE_TEXT = """Martinez LLC
Aquaculture feed, nutrients and spare parts
Supplier ref. SUP-007 - Tel. +1-954-699-7156
INVOICE
Invoice No. INV-2026-0418 Bill to the Farm
Invoice Date 2026-08-27 Your order PO-2026-0031
Item Description Qty Unit price Amount (EUR)
FEED-01 Floating fish feed 3 mm 50 2.95 147.50
TOTAL DUE 147.50 EUR
"""
LAB_TEXT = """Contract Water Laboratory
WATER ANALYSIS REPORT
Report No. LAB-2026-0019 Client the Farm
Grow unit AQ-04 Sampled 2026-08-19 09:00
pH 6.89 — electrode, 25 °C
Ammonia (TAN) 0.12 mg/L salicylate
Nitrite 0.08 mg/L diazotisation
Nitrate 42 mg/L cadmium reduction
lron 2.4 mg/L phenanthroline
"""


def test_regex_reads_an_invoice():
    f = X.regex_invoice(INVOICE_TEXT)
    assert X.kind_of(INVOICE_TEXT) == "invoice"
    assert (f["invoice_no"], f["po_no"], f["supplier_ref"], f["item_code"]) == \
        ("INV-2026-0418", "PO-2026-0031", "SUP-007", "FEED-01")
    assert (f["qty"], f["unit_price"], f["total"], f["invoice_date"]) == (50.0, 2.95, 147.5, "2026-08-27")


def test_a_misread_price_is_dropped_not_trusted():
    """OCR lost the decimal point (2.95 → 205): the row no longer adds up, so the
    price is dropped and the reconciliation derives it from total ÷ quantity."""
    f = X.regex_invoice(INVOICE_TEXT.replace("50 2.95 147.50", "50 205 147.50"))
    assert f["qty"] == 50.0 and f["unit_price"] is None and f["total"] == 147.5


def test_regex_reads_a_lab_report_and_never_a_stray_number():
    f = X.regex_lab(LAB_TEXT + "\nols! od 583\n")
    assert X.kind_of(LAB_TEXT) == "lab"
    assert (f["report_no"], f["unit_id"], f["sampled"]) == ("LAB-2026-0019", "AQ-04", "2026-08-19T09:00")
    assert (f["ph"], f["ammonia_mg_l"], f["nitrite_mg_l"], f["nitrate_mg_l"], f["iron_mg_l"]) == \
        (6.89, 0.12, 0.08, 42.0, 2.4)


def test_verify_requires_presence_in_the_ocr_text():
    assert X.verify("total", 147.5, INVOICE_TEXT) and not X.verify("total", 151.0, INVOICE_TEXT)
    assert X.verify("po_no", "PO 2026 0031", INVOICE_TEXT)
    assert not X.verify("supplier_ref", "SUP-001", INVOICE_TEXT)


def test_merge_never_trusts_an_unverifiable_model_value():
    rx = X.regex_invoice(INVOICE_TEXT)
    fields, checks = X.merge("invoice", INVOICE_TEXT, {**rx, "supplier_ref": "SUP-001", "total": 120.0}, rx)
    assert fields["supplier_ref"] == "SUP-007" and fields["total"] == 147.5
    by = {c["field"]: c for c in checks}
    assert by["supplier_ref"]["source"] == "regex" and by["total"]["verified"]


def test_extract_falls_back_to_regex_when_vlm_is_off():
    out = X.extract_fields(LAB_TEXT, None, use_vlm=False)
    assert out["kind"] == "lab" and out["engine"] == "regex"
    assert all(c["verified"] is not False for c in out["field_checks"])


def _held_recon():
    return {"kind": "invoice", "verdict": "discrepancy", "ref": "INV-2026-0418", "po_no": "PO-2026-0031",
            "record": {"supplier_ref": "SUP-001", "unit_price_eur": 2.40, "qty": 50.0,
                       "item_code": "FEED-01", "item_unit": "kg"},
            "checks": [], "discrepancies": [
                {"id": "supplier_matches_order", "label": "Supplier matches the purchase order",
                 "status": "fail", "found": "SUP-007", "expected": "SUP-001", "cite": "supplier_master"},
                {"id": "supplier_approved", "label": "Supplier is on the approved supplier list",
                 "status": "fail", "found": "SUP-007 not on the list", "cite": "supplier_master"},
                {"id": "price_within_tolerance", "label": "Unit price within 5%", "status": "fail",
                 "found": "2.95", "expected": "≤ 2.52", "cite": "invoice_tolerance"}]}


FIELDS = {"invoice_no": "INV-2026-0418", "po_no": "PO-2026-0031", "supplier_ref": "SUP-007",
          "qty": 50.0, "total": 147.5}


def test_template_alert_covers_every_failed_check_with_a_real_citation():
    a = P.template_alert(_held_recon(), FIELDS)
    assert a["verdict"] == "discrepancy" and a["hold_payment"] is True
    cites = {(x["cite"]["source"], x["cite"]["section"]) for x in a["actions"]}
    assert cites == {("supplier-invoice-controls.md", "2"), ("supplier-invoice-controls.md", "3")}
    assert "27.50" in a["actions"][0]["text"] and "+22.9%" in a["summary"]


def test_validate_keeps_words_not_judgement():
    tmpl = P.template_alert(_held_recon(), FIELDS)
    terms = [{"source": "supplier-invoice-controls.md", "section": "2"},
             {"source": "supplier-invoice-controls.md", "section": "3"}]
    model = {"headline": "Pay it", "summary": "fine", "hold_payment": False, "actions": [
        {"text": "Hold the invoice; the price is outside tolerance — ask for a credit note",
         "cite": {"source": "supplier-invoice-controls.md", "section": "2"}},
        {"text": "Pay the supplier today", "cite": {"source": "supplier-invoice-controls.md", "section": "3"}},
        {"text": "Ignore it", "cite": {"source": "made-up.md", "section": "9"}}]}
    alert, mode = P.validate(model, tmpl, terms)
    assert alert["hold_payment"] is True                       # the rules decide the hold
    by = {(x["cite"]["source"], x["cite"]["section"]): x for x in alert["actions"]}
    assert by[("supplier-invoice-controls.md", "2")]["by"] == "model"
    assert by[("supplier-invoice-controls.md", "3")]["by"] == "rule"   # "pay" lacks call/verify
    assert not any(x["cite"]["source"] == "made-up.md" for x in alert["actions"]) and mode == "llm"


def test_clean_and_not_found_templates():
    clean = P.template_alert({"kind": "invoice", "verdict": "clean", "po_no": "PO-2026-0030",
                              "record": {"supplier_ref": "SUP-004", "item_code": "NUT-01", "item_unit": "kg",
                                         "unit_price_eur": 6.5}, "discrepancies": []},
                             {"invoice_no": "INV-2026-0397", "qty": 2.0})
    assert clean["hold_payment"] is False and clean["actions"][0]["cite"]["section"] == "5"
    missing = P.template_alert({"kind": "invoice", "verdict": "not_found", "po_no": "PO-2099-0001"},
                               {"invoice_no": "INV-2099-0001"})
    assert missing["hold_payment"] is True and missing["actions"][0]["cite"]["section"] == "6"
    lab = P.template_alert({"kind": "lab", "verdict": "discrepancy", "unit_id": "AQ-04", "discrepancies": [
        {"id": "ph_matches_probe", "expected": "probe 7.28 ± 0.2", "found": "lab 6.89", "cite": "sensor_vs_chemistry"}]},
        {"report_no": "LAB-2026-0019", "ph": 6.89})
    assert "Recalibrate" in lab["actions"][0]["text"] and lab["hold_payment"] is False


# ---- the printed scans ----------------------------------------------------------------

@pytest.mark.skipif(not (SAMPLES / "invoice-held.pdf").exists(), reason="samples not printed (make mock)")
def test_samples_are_image_only_scans():
    import pymupdf
    for name in ("invoice-held", "invoice-clean", "lab-report"):
        doc = pymupdf.open(SAMPLES / f"{name}.pdf")
        assert len(doc) == 1 and not doc[0].get_text().strip(), name
        assert (SAMPLES / f"{name}-preview.png").exists()


def _db_up() -> bool:
    try:
        import psycopg
        psycopg.connect(os.environ.get("DATABASE_URL_RO",
                                       "postgresql://farm_ro:farm-ro@localhost:5432/horizons"),
                        connect_timeout=2).close()
        return True
    except Exception:
        return False


E2E = pytest.mark.skipif(not META.exists() or not (SAMPLES / "invoice-held.pdf").exists() or not _db_up()
                         or not shutil.which("tesseract"), reason="needs make db-up mock and tesseract")


@pytest.mark.domain
@E2E
def test_e2e_the_held_invoice_is_held_with_cited_actions(monkeypatch):
    monkeypatch.setattr(P, "compose_llm", lambda *a, **k: None)      # the rule template, no model
    r = P.process(SAMPLES / "invoice-held.pdf", "qwen3:8b", use_cache=False, use_vlm=False)
    assert r["extract"]["kind"] == "invoice" and r["alert"]["verdict"] == "discrepancy"
    failed = sorted(c["id"] for c in r["recon"]["discrepancies"])
    assert failed == ["price_within_tolerance", "supplier_approved", "supplier_matches_order"]
    assert r["alert"]["hold_payment"] is True and all(a["cite"] for a in r["alert"]["actions"])
    meta = json.loads(META.read_text())["document_intake"]["held"]
    assert r["fields"]["invoice_no"] == meta["invoice_no"] and r["fields"]["total"] == meta["invoice_total"]


@pytest.mark.domain
@E2E
def test_e2e_the_clean_invoice_passes_and_a_repeat_is_cached(monkeypatch):
    first = P.process(SAMPLES / "invoice-clean.pdf", "qwen3:8b", use_cache=False, use_vlm=False)
    assert first["alert"]["verdict"] == "clean" and first["alert"]["hold_payment"] is False
    again = P.process(SAMPLES / "invoice-clean.pdf", "qwen3:8b", use_vlm=False)
    assert again["cached"] is True and again["alert"]["verdict"] == "clean"


@pytest.mark.domain
@E2E
def test_e2e_the_lab_report_catches_the_probe(monkeypatch):
    monkeypatch.setattr(P, "compose_llm", lambda *a, **k: None)
    r = P.process(SAMPLES / "lab-report.pdf", "qwen3:8b", use_cache=False, use_vlm=False)
    assert r["extract"]["kind"] == "lab" and r["alert"]["verdict"] == "discrepancy"
    assert [c["id"] for c in r["recon"]["discrepancies"]] == ["ph_matches_probe"]


def test_a_failed_step_returns_an_error_alert_instead_of_raising(tmp_path):
    bad = tmp_path / "not-a-document.pdf"
    bad.write_bytes(b"%PDF-1.4 broken")
    r = P.process(bad, "qwen3:8b", use_cache=False, use_vlm=False)
    assert r["alert"]["verdict"] == "error" and r["error"]["step"] == "read"
