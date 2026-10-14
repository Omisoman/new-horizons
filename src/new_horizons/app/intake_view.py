"""Document-intake views shared by the Documents and Chat pages.

The pipeline (intake/pipeline.py) does the work — OCR, field extraction, the
reconciliation call against the farm systems, KB terms, the alert. This
module only renders it: live step progress, extracted fields, the check
list and the alert card, and posts the alert into Chat. What the pipeline
writes (step details, check labels, the composed alert) keeps its own language;
what this module words follows the application language.
"""

from __future__ import annotations

import hashlib
import time
from html import escape
from pathlib import Path

import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr

STEPS = [  # pipeline step key -> label, hint
    ("read", "Read document", "OCR on-device"),
    ("extract", "Extract fields", "vision model, every figure verified against the OCR text"),
    ("reconcile", "Reconcile", "purchase order · supplier master · probes · SOP bands"),
    ("terms", "Check terms", "knowledge base"),
    ("compose", "Compose alert", "grounded in the retrieved terms"),
]
STEPS_AR = {
    "read": ("قراءة المستند", "تعرّف ضوئي على الجهاز"),
    "extract": ("استخراج الحقول", "نموذج الرؤية، مع التحقق من كل رقم مقابل نص التعرف الضوئي"),
    "reconcile": ("المطابقة", "أمر الشراء · سجل الموردين · المجسات · نطاقات الإجراءات"),
    "terms": ("فحص البنود", "قاعدة المعرفة"),
    "compose": ("صياغة التنبيه", "مستند إلى البنود المسترجعة"),
}
FIELD_LABELS = {
    "invoice_no": "Invoice no", "po_no": "Purchase order", "invoice_date": "Invoice date",
    "supplier_ref": "Supplier ref", "supplier_name": "Supplier", "item_code": "Item",
    "qty": "Quantity", "unit_price": "Unit price", "total": "Total due", "currency": "Currency",
    "report_no": "Report no", "unit_id": "Grow unit", "sampled": "Sampled", "ph": "pH",
    "ammonia_mg_l": "Ammonia (mg/L)", "nitrite_mg_l": "Nitrite (mg/L)",
    "nitrate_mg_l": "Nitrate (mg/L)", "iron_mg_l": "Iron (mg/L)", "lab_name": "Laboratory",
}
FIELD_LABELS_AR = {
    "invoice_no": "رقم الفاتورة", "po_no": "أمر الشراء", "invoice_date": "تاريخ الفاتورة",
    "supplier_ref": "رمز المورد", "supplier_name": "المورد", "item_code": "الصنف",
    "qty": "الكمية", "unit_price": "سعر الوحدة", "total": "المبلغ المستحق", "currency": "العملة",
    "report_no": "رقم التقرير", "unit_id": "الوحدة", "sampled": "وقت العينة", "ph": "الحموضة",
    "ammonia_mg_l": "الأمونيا (ملغ/لتر)", "nitrite_mg_l": "النتريت (ملغ/لتر)",
    "nitrate_mg_l": "النترات (ملغ/لتر)", "iron_mg_l": "الحديد (ملغ/لتر)", "lab_name": "المختبر",
}
DB_LABELS = {"supplies": "Supplies", "telemetry": "Telemetry"}
DB_LABELS_AR = {"supplies": "المستلزمات", "telemetry": "القياسات"}
SAMPLE_LABELS = {"invoice-held": ("Invoice · held", "فاتورة · موقوفة"),
                 "invoice-clean": ("Invoice · clean", "فاتورة · مطابقة"),
                 "lab-report": ("Lab report", "تقرير مختبر")}


def save_upload(name: str, data: bytes) -> Path:
    U.UPLOADS.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:10]
    path = U.UPLOADS / f"{digest}-{Path(name).name}"
    path.write_bytes(data)
    return path


def samples() -> list[tuple[str, str, Path]]:
    """(key, label, path) of the generated sample scans that exist."""
    out = []
    for key, (en, ar) in SAMPLE_LABELS.items():
        p = U.SAMPLES / f"{key}.pdf"
        if p.exists():
            out.append((key, tr(en, ar), p))
    return out


def _steps_html(state: dict) -> str:
    rows = []
    for key, label, hint in STEPS:
        label, hint = tr(label, STEPS_AR[key][0]), tr(hint, STEPS_AR[key][1])
        s = state.get(key, {})
        status = s.get("status", "pending")
        icon = {"done": U.check_icon("pass"), "failed": U.check_icon("fail"),
                "running": "<span class='ac-check warn'>…</span>"}.get(status, U.check_icon("skip"))
        ms = f"{s['ms'] / 1000:.1f}s" if s.get("ms") and status == "done" else ""
        detail = escape(s.get("detail") or hint)
        rows.append(
            f"<tr class='{'fail' if status == 'failed' else ''}'><td style='width:28px'>{icon}</td>"
            f"<td><b style='color:var(--ac-fg);font-weight:600'>{label}</b>"
            f"<div class='ac-subtle'>{detail}</div></td>"
            f"<td style='text-align:end;width:56px' class='ac-subtle'>{ms}</td></tr>")
    return f"<table class='ac-table'>{''.join(rows)}</table>"


def run(path: Path, model: str, box=None) -> dict | None:
    """Run the intake pipeline with live progress in `box` (a placeholder)."""
    from new_horizons.app.intake.pipeline import process
    box = box or st.empty()
    state: dict = {}

    def on_step(step: dict) -> None:
        state[step["key"]] = step
        box.markdown(_steps_html(state), unsafe_allow_html=True)

    paused, who, _ = U.agent_paused()
    if paused:                       # the kill switch stops automated actions
        box.markdown("", unsafe_allow_html=True)
        st.warning(tr(f"Agent paused by {who or 'an operator'} — automated document analysis "
                      "is stopped. Resume the agent in Settings to run it.",
                      f"أوقف {who or 'أحد المشغّلين'} الوكيل مؤقتاً — تحليل المستندات الآلي "
                      "متوقف. استأنف الوكيل من الإعدادات لتشغيله."), icon=":material/pause:")
        return None
    box.markdown(_steps_html(state), unsafe_allow_html=True)
    try:
        result = process(path, model, on_step=on_step)
    except Exception as exc:  # the demo keeps going; the error is shown, not raised
        st.error(tr(f"Intake failed: {type(exc).__name__}: {exc}",
                    f"تعذّر الاستلام: {type(exc).__name__}: {exc}"))
        return None
    for key, *_ in STEPS:      # cached results arrive without step callbacks
        state.setdefault(key, {"status": "done", "detail": tr("cached", "من الذاكرة المؤقتة")})
    box.markdown(_steps_html(state), unsafe_allow_html=True)
    return result


def steps_done(result: dict) -> str:
    """Completed step list for a finished result (re-render without re-running)."""
    timing = result.get("timings", {})
    return _steps_html({k: {"status": "done", "ms": timing.get(k)} for k, *_ in STEPS})


def fields_table(result: dict) -> str:
    checks = {c["field"]: c for c in result.get("field_checks", [])}
    rows, classes = [], []
    for key, label in FIELD_LABELS.items():
        v = result.get("fields", {}).get(key)
        if v in (None, ""):
            continue
        if key in ("total", "unit_price"):
            v = f"{float(v):,.2f}"
        c = checks.get(key)
        # True = found in the OCR text, False = not found (manual keying),
        # None = not a figure/identifier, so not subject to verification
        v_ok = c.get("verified") if c else None
        mark = U.check_icon({True: "pass", False: "warn"}.get(v_ok, "skip"))
        rows.append((tr(label, FIELD_LABELS_AR[key]), v, ("html", mark)))
        classes.append("")
    return U.html_table([tr("Field", "الحقل"), tr("Read from document", "المقروء من المستند"),
                         tr("In OCR text", "في نص التعرف الضوئي")], rows, row_class=classes)


def checks_table(result: dict) -> str:
    rows, classes = [], []
    for c in result.get("recon", {}).get("checks", []):
        db = c.get("db") or ""
        rows.append((("html", U.check_icon(c["status"])), c.get("label", c["id"]),
                     c.get("expected") if c.get("expected") is not None else "—",
                     c.get("found") if c.get("found") is not None else "—",
                     tr(DB_LABELS.get(db, db), DB_LABELS_AR.get(db, db))))
        classes.append("fail" if c["status"] == "fail" else "")
    return U.html_table(["", tr("Check", "الفحص"), tr("System of record", "نظام السجل"),
                         tr("Document", "المستند"), tr("Database", "قاعدة البيانات")], rows,
                        row_class=classes)


def governance_row(result: dict, key_suffix: str = "") -> None:
    """Approval bar + audit link under a document finding. A clean document needs
    no decision, so it only gets the audit link."""
    r, a = result.get("recon", {}), result.get("alert", {})
    subject = r.get("ref") or result["doc"]["name"]
    if a.get("verdict") != "clean":
        first = next((c for c in r.get("checks", []) if c["status"] == "fail"), None)
        cite = (result.get("terms") or [{}])[0]
        rule = (U.cite(cite.get("source", ""), cite.get("section")) if cite.get("source")
                else None)
        U.approval_bar(subject, f"{result['doc']['name']} · {a.get('headline', '')[:60]}",
                       rule=rule, detail=(first or {}).get("label"), key_suffix=key_suffix)
    U.audit_link(subject, tr("Audit trail for this document", "سجل التدقيق لهذا المستند"),
                 key_suffix=key_suffix)


def alert_card(result: dict) -> None:
    a = result.get("alert", {})
    verdict = a.get("verdict", "discrepancy")
    kind = {"discrepancy": "red", "clean": "ok", "not_found": "amber",
            "error": "amber"}.get(verdict, "red")
    pill = {"discrepancy": tr("Discrepancy", "تباين"), "clean": tr("Reconciled", "مطابَق"),
            "not_found": tr("No match", "لا تطابق"),
            "error": tr("Needs review", "بحاجة إلى مراجعة")}.get(verdict, verdict)
    actions = "".join(
        f"<li>{escape(x['text'])}"
        + (f" <span class='cite'>{escape(U.cite(x['cite']['source'], x['cite'].get('section')))}"
           f"</span>" if x.get("cite") else "") + "</li>"
        for x in a.get("actions", []))
    hold = U.chip(tr("Invoice on hold", "الفاتورة معلّقة"), "red") if a.get("hold_payment") else ""
    body = (f"<p>{escape(a.get('summary', ''))}</p>"
            + (f"<p class='ac-label' style='margin-top:.8rem'>"
               f"{tr('Suggested actions', 'الإجراءات المقترحة')}</p><ol>{actions}</ol>"
               if actions else "")
            + f"<div class='foot' style='display:flex;gap:.5rem;align-items:center;"
              f"margin-top:.8rem'>{hold}<span class='cite'>{escape(result['doc']['name'])} · "
              f"{tr('composed by', 'صاغه')} {escape(a.get('composer', ''))}</span></div>")
    U.alert(a.get("headline") or tr("Document reconciled", "تمت مطابقة المستند"), body,
            pill=pill, kind=kind)


def post_to_chat(result: dict) -> None:
    """Append the alert to the chat log (once per document) and flag it unread."""
    log = st.session_state.setdefault("chat_log", [])
    sha = result["doc"].get("sha256")
    if any(e.get("kind") == "intake" and e["result"]["doc"].get("sha256") == sha for e in log):
        return
    log.append({"role": "user", "kind": "attachment", "content": result["doc"]["name"]})
    log.append({"role": "assistant", "kind": "intake", "result": result, "ts": time.time()})
    unread = st.session_state.setdefault("unread_alerts", [])
    if result.get("alert", {}).get("verdict") != "clean":
        unread.append(sha)


def chat_context(result: dict) -> str:
    """One paragraph the chat agent receives about the latest document."""
    r, a = result.get("recon", {}), result.get("alert", {})
    fails = "; ".join(f"{c.get('label', c['id'])}: system {c.get('expected')} vs document "
                      f"{c.get('found')}" for c in r.get("checks", []) if c["status"] == "fail")
    cites = sorted({U.cite(x["cite"]["source"], x["cite"].get("section"))
                    for x in a.get("actions", []) if x.get("cite")})
    fails += f". Governing sections: {', '.join(cites)}" if cites else ""
    what = r.get("kind") or "document"
    return (f"[Latest document intake — {result['doc']['name']}: {what} {r.get('ref')}, "
            f"verdict {a.get('verdict')}. {fails or 'All checks passed.'} "
            f"Alert: {a.get('headline', '')}]")
