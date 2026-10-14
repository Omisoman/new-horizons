"""Admin center — governance and the audit trail. The handoff document this
deployment runs under (GOVERNANCE.md, or GOVERNANCE.ar.md in Arabic), rendered
with live facts from the running system (agent state, decisions, audit chain),
next to every event behind those facts."""

from datetime import date

import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr
DOC = U.APP / "agents" / "analytics" / tr("GOVERNANCE.md", "GOVERNANCE.ar.md")
FARM = U.PROFILE["farm"][tr("name_en", "name_ar")]

paused, who, ts = U.agent_paused()

U.page_header(
    tr("Admin center.", "مركز الإدارة."),
    tr("What the agent may do, who approves its findings, and the audit trail that "
       "proves it after the fact.",
       "ما يجوز للوكيل فعله، ومن يعتمد نتائجه، وسجل التدقيق الذي يثبت ذلك لاحقاً."),
    [U.chip(tr("Synthetic data", "بيانات تركيبية")),
     U.chip(tr("Read-only database role", "صلاحية قراءة فقط على قاعدة البيانات")),
     U.chip(tr("Agent paused", "الوكيل متوقف"), "red") if paused
     else U.chip(tr("Agent active", "الوكيل نشط"), "strong")])


@st.cache_data(ttl=10, show_spinner=False)
def facts() -> dict:
    from new_horizons.shared.audit.audit import events, verify_chain
    try:
        rows = events(limit=5000)
        chain = verify_chain()
    except Exception as exc:                       # governance must render regardless
        return {"error": str(exc)}
    decisions = [e for e in rows if e["event_type"] == "decision"]
    return {"events": len(rows), "decisions": len(decisions),
            "chain_ok": chain.get("ok"), "chain_rows": chain.get("rows"),
            "break_at": chain.get("break_at"),
            "last": decisions[0] if decisions else None}


tab_gov, tab_audit = st.tabs([tr("Governance", "الحوكمة"), tr("Audit trail", "سجل التدقيق")])

with tab_gov:
    f = facts()
    kb_docs = len(list((U.APP / "ingest" / "kb_synthetic").glob("*.md")))
    events = f"{f.get('events', 0):,}" + ("+" if f.get("events") == 5000 else "")
    rows, break_at = f.get("chain_rows", 0), f.get("break_at")
    U.stat_cards([
        (tr("Agent", "الوكيل"), tr("Paused", "متوقف") if paused else tr("Active", "نشط"),
         f"{who} · {ts:%d %b %H:%M}" if who else tr("no pause recorded", "لا يوجد إيقاف مسجل"),
         paused),
        (tr("Decisions recorded", "القرارات المسجلة"), f.get("decisions", "—"),
         tr("approve · escalate · reject", "اعتماد · تصعيد · رفض")),
        (tr("Audit events", "أحداث التدقيق"), events,
         tr("model, tool, intake, decision", "نموذج، أداة، استلام، قرار")),
        (tr("Hash chain", "سلسلة التجزئة"),
         tr("Verified", "سليمة") if f.get("chain_ok") else tr("Broken", "مكسورة"),
         tr(f"{rows:,} rows", f"{rows:,} صف") if f.get("chain_ok")
         else tr(f"breaks at row {break_at}", f"تنكسر عند الصف {break_at}"), not f.get("chain_ok")),
        (tr("Knowledge base", "قاعدة المعرفة"), kb_docs,
         tr("documents the agent may cite", "مستنداً يجوز للوكيل الاستشهاد به")),
    ])
    if f.get("error"):
        U.alert(tr("Audit log unreachable", "تعذّر الوصول إلى سجل التدقيق"),
                f"<p>{f['error']}</p>", pill=tr("Degraded", "أداء منخفض"), kind="amber")

    today = date.today()
    U.section(tr("Handoff document", "وثيقة التسليم"),
              f"{FARM} · " + tr(f"{today:%d %b %Y}", f"{today:%Y/%m/%d}"))
    doc = (DOC.read_text(encoding="utf-8")
           .replace("{{farm}}", FARM)
           .replace("{{date}}", tr(f"{today:%d %B %Y}", f"{today:%Y/%m/%d}"))
           .replace("{{operator}}", U.operator()))
    st.download_button(tr("Download this document", "تنزيل هذه الوثيقة"), doc,
                       file_name=tr("governance-handoff.md", "governance-handoff-ar.md"),
                       icon=":material/download:")
    with U.card("governance-doc"):
        st.markdown(doc)

with tab_audit:
    U.audit_trail(key="admin")
