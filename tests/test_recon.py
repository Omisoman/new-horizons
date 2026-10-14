"""Reconciliation: the three matches, the document call for an invoice and a lab
report, and one unit across all five systems. Needs `make db-up mock`."""

import json
import os

import pytest

from new_horizons.paths import DATA

META = DATA / "mock_meta.json"


def _db_up() -> bool:
    try:
        import psycopg
        psycopg.connect(os.environ.get("DATABASE_URL_RO",
                                       "postgresql://farm_ro:farm-ro@localhost:5432/horizons"),
                        connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = [pytest.mark.domain,
              pytest.mark.skipif(not META.exists() or not _db_up(), reason="needs make db-up mock")]


def _di():
    return json.loads(META.read_text())["document_intake"]


def _fails(result):
    return sorted(c["id"] for c in result["checks"] if c["status"] == "fail")


def test_the_held_invoice_fails_on_price_and_supplier():
    from new_horizons.app.analytics.recon import check_document
    d = _di()["held"]
    r = check_document({"invoice_no": d["invoice_no"], "po_no": d["po_no"],
                        "supplier_ref": d["invoice_supplier_ref"], "item_code": d["item"],
                        "qty": float(d["qty"]), "unit_price": float(d["invoice_unit_price"])})
    assert r["kind"] == "invoice" and r["verdict"] == "discrepancy"
    assert _fails(r) == ["price_within_tolerance", "supplier_approved", "supplier_matches_order"]
    price = next(c for c in r["checks"] if c["id"] == "price_within_tolerance")
    assert "+22.9%" in price["found"] and price["cite"] == "invoice_tolerance"


def test_the_clean_invoice_reconciles():
    from new_horizons.app.analytics.recon import check_document
    d = _di()["clean"]
    r = check_document({"invoice_no": d["invoice_no"], "po_no": d["po_no"], "supplier_ref": d["supplier_ref"],
                        "item_code": d["item"], "qty": d["qty"], "unit_price": d["unit_price"]})
    assert r["verdict"] == "clean" and not _fails(r)


def test_an_invoiced_order_cannot_be_paid_twice_and_an_unknown_one_is_not_found():
    import psycopg

    from new_horizons.app.analytics.dataio import dsn_ro
    from new_horizons.app.analytics.recon import check_document
    with psycopg.connect(dsn_ro()) as conn:
        po, sup, item, qty, price = conn.execute(
            "SELECT po_no, supplier_ref, item_code, qty, unit_price_eur FROM supplies.purchases "
            "WHERE status = 'invoiced' ORDER BY po_no LIMIT 1").fetchone()
    r = check_document({"po_no": po, "supplier_ref": sup, "item_code": item, "qty": float(qty),
                        "unit_price": float(price)})
    assert _fails(r) == ["not_already_invoiced"]
    assert check_document({"po_no": "PO-2099-0001"})["verdict"] == "not_found"


def test_the_lab_report_catches_the_probe():
    from new_horizons.app.analytics.recon import check_document
    lab = _di()["lab"]
    r = check_document({"report_no": lab["report_no"], "unit_id": lab["unit"], "sampled": lab["sampled"],
                        "ph": lab["lab_ph"], "ammonia_mg_l": 0.12, "nitrite_mg_l": 0.08,
                        "nitrate_mg_l": 42.0, "iron_mg_l": 2.4})
    assert r["kind"] == "lab" and r["verdict"] == "discrepancy"
    assert _fails(r) == ["ph_matches_probe"]
    probe = next(c for c in r["checks"] if c["id"] == "ph_matches_probe")
    assert probe["cite"] == "sensor_vs_chemistry" and f"{lab['probe_ph']:.2f}" in probe["expected"]


def test_lab_bands_follow_the_sop():
    from new_horizons.app.analytics.recon import check_document
    lab = _di()["lab"]
    r = check_document({"report_no": lab["report_no"], "unit_id": "AQ-02", "sampled": "2026-08-19T09:00",
                        "ammonia_mg_l": 0.8, "nitrate_mg_l": 180.0, "iron_mg_l": 1.2})
    assert {"ammonia_mg_l", "nitrate_mg_l", "iron_mg_l"} <= set(_fails(r))


def test_unit_snapshot_spans_five_systems():
    from new_horizons.app.analytics.recon import unit_snapshot
    s = unit_snapshot("aq-03")
    assert s["unit"]["unit_id"] == "AQ-03" and s["unit"]["plant"] == "tomato"
    assert any(a["type"] == "low_water_level" for a in s["alerts"])
    assert s["work_orders"] and s["harvests"] and s["consumption_by_month"]
    assert unit_snapshot("AQ-09") is None


def test_match_rates_reflect_the_scenarios():
    from new_horizons.app.analytics.recon import run
    r = run(write=False)
    m = r["match"]
    assert m["commands"]["commanded"] - m["commands"]["observed"] == \
        next(e["commands"] for e in r["exceptions"] if e["class"] == "commanded_not_observed")
    assert m["harvest"]["harvests"] - m["harvest"]["shipped"] == 6
    assert 0.9 < m["supplies"]["rate"] < 1.0
