"""The farm's agent tools and known-question layer, registered with the harness.

Importing this module is what turns the shared harness into the Farm's analytics
agent: the five tools below join the generic ones in
`shared.harness.tools.REGISTRY`, and the metrics layer becomes the "analytics"
toolset's known questions. The harness never imports the app; the app plugs in.
Every tool returns a JSON-serializable dict and reads only — the computed
findings come from the analytics artifacts the screens read.
"""

from __future__ import annotations

import json
from pathlib import Path

from new_horizons.app.analytics import metrics, recon
from new_horizons.app.analytics.dataio import OUT, citations
from new_horizons.paths import ROOT
from new_horizons.shared.harness import graph, tools


def _artifact(name: str, build) -> dict:
    path = OUT / name
    return json.loads(path.read_text()) if path.exists() else build()


def _cited(entry: dict | None) -> dict | None:
    """Files and sections only — the model never sees registry keys."""
    return {"source": entry.get("source"), "section": entry.get("section")} if entry else None


def unit_status(unit_id: str) -> dict:
    """One grow unit across all five systems."""
    snap = recon.unit_snapshot(unit_id)
    return snap if snap is not None else {"error": f"no grow unit {unit_id!r}; units are AQ-01 … AQ-04"}


def recon_summary(exception_class: str | None = None) -> dict:
    data = _artifact("recon.json", lambda: recon.run(write=False))
    exc = data.get("exceptions", [])
    if exception_class:
        exc = [e for e in exc if e.get("class") == exception_class]
    sample = [{**{k: v for k, v in e.items() if k not in ("cite", "citation")},
               "citation": _cited(e.get("citation"))} for e in exc[:10]]
    return {"match": data.get("match"), "counts": data.get("counts"),
            # pre-computed: the model quotes these, it never re-adds them
            "at_risk_eur_by_class": data.get("exposure"), "at_risk_eur_total": data.get("exposure_total"),
            "at_risk_kg_by_class": data.get("exposure_kg"), "at_risk_kg_total": data.get("exposure_kg_total"),
            "currency": data.get("currency"), "sample": sample, "total": len(exc)}


def reconcile_document(**fields) -> dict:
    """The reconciliation call for a document's extracted fields."""
    r = recon.check_document({k: v for k, v in fields.items() if v is not None})
    reg = citations()
    checks = []
    for c in r.get("checks") or []:
        key = c.get("cite")
        c = {k: v for k, v in c.items() if k != "cite"}
        if key in reg:
            c["citation"] = {"source": reg[key]["source"], "section": str(reg[key]["section"])}
        checks.append(c)
    return {"kind": r.get("kind"), "ref": r.get("ref"), "verdict": r.get("verdict"),
            "checks": checks, "tolerance": r.get("tolerance")}


def drift_report(month: str | None = None) -> dict:
    from new_horizons.app.analytics import drift
    data = _artifact("drift.json", lambda: drift.run(write=False))
    month = month or data["default_window"]
    win = data["windows"].get(month)
    if win is None:
        return {"error": f"no drift window {month!r}; windows: {data['months']} against "
                         f"{data['reference']}"}
    units = {u: {m: {k: v for k, v in s.items() if k != "distribution"} for m, s in ms.items()}
             for u, ms in win["units"].items()}
    return {"month": month, "reference": data["reference"], "range": win["range"],
            "flags": win["flags"], "ph_cause": win["ph_cause"], "aeration_duty": win["duty"],
            "duty_limit": data["duty_limit"], "gaps": win["gaps"], "units": units,
            "note": "verdict = share of readings outside the SOP band or a practical mean shift; "
                    "PSI/KS are evidence; gaps are excluded, never zero-filled"}


def pattern_scan() -> dict:
    from new_horizons.app.analytics import patterns
    data = _artifact("patterns.json", lambda: patterns.run(write=False))
    return {"ghost_loops": data["ghost_loops"], "late_responses": data["late_responses"],
            "dropouts": data["dropouts"], "technicians": data["technicians"],
            "sop_hours": data["sop_hours"]}


def ocr_document(path: str, max_pages: int = 4) -> dict:
    """Read a PDF or image on disk (text layer or on-device OCR)."""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        return {"error": f"file not found: {path}"}
    from new_horizons.app.intake.read import read_document
    r = read_document(p)
    return {"engine": r.get("engine"), "pages": r.get("pages"), "text": (r.get("text") or "")[:4000]}


tools.register(
    "unit_status", unit_status,
    "One grow unit across all five systems: the unit, its latest reading and reading summary, "
    "alerts, controller commands, recent work orders, harvests with their shipments, consumption "
    "by month.",
    {"unit_id": 'string like "AQ-03"'})
tools.register(
    "recon_summary", recon_summary,
    "Cross-system reconciliation: match rates (commanded vs observed, harvested vs shipped, "
    "consumed vs purchased), exceptions (commanded_not_observed, harvest_not_shipped, "
    "consumed_not_purchased) and the money and kilograms at risk per class and in total "
    "(`at_risk_eur_by_class`, `at_risk_eur_total`, `at_risk_kg_total`). Quote those figures; never "
    "add them up yourself.",
    {"exception_class": "string|null — filter to one class"})
tools.register(
    "reconcile_document", reconcile_document,
    "Reconcile a document's fields against the systems of record. A supplier invoice: purchase "
    "order, supplier and approved list, item, quantity received, price tolerance, already "
    "invoiced. A water-lab report: the unit, the probe reading at the sample time, the bands.",
    {"invoice_no": "string|null", "po_no": "string|null", "supplier_ref": "string|null",
     "item_code": "string|null", "qty": "number|null", "unit_price": "number|null",
     "report_no": "string|null", "unit_id": "string|null", "sampled": "string|null (ISO time)",
     "ph": "number|null", "nitrate_mg_l": "number|null", "ammonia_mg_l": "number|null"})
tools.register(
    "drift_report", drift_report,
    "Drift per grow unit for a month against the June reference: water temperature, pH and "
    "dissolved oxygen (share outside the SOP band, mean shift, PSI, KS), the air-pump duty against "
    "the 50% limit, sensor gaps, and for a drifting pH whether the probe or the chemistry moved.",
    {"month": 'string: "2026-07" | "2026-08" (default the latest)'})
tools.register(
    "pattern_scan", pattern_scan,
    "People and records: harvests a technician logged that were never countersigned or shipped, "
    "alerts answered later than the SOP's 2 hours, sensor dropouts and their work orders, and "
    "each technician's work orders and harvest logs.",
    {})
tools.register(
    "ocr_document", ocr_document,
    "Read a PDF or image on disk (text layer or on-device OCR).",
    {"path": "string (file path)", "max_pages": "int (default 4)"})

graph.register_metrics("analytics", metrics.default)
