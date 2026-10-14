"""Reconcile — commanded vs observed, harvested vs shipped, consumed vs purchased,
each exception next to the rule it breaks and ranked by the money at risk. The
exception panel is a fragment: picking a class or a row reruns it, not the app."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr

CLASSES = {  # recon class -> label, in the running language
    "commanded_not_observed": tr("Pump commanded, level never rose", "أُمرت المضخة ولم يرتفع المستوى"),
    "harvest_not_shipped": tr("Harvest never shipped", "حصاد لم يُشحن"),
    "consumed_not_purchased": tr("Consumed, never bought", "استُهلك ولم يُشترَ"),
}

recon = U.load_json(U.AN_DIR / "recon.json")
if not recon:
    with st.spinner(tr("reconciling the five systems…", "جارٍ مطابقة الأنظمة الخمسة…")):
        from new_horizons.app.analytics.recon import run as recon_run
        recon = recon_run()

counts = recon.get("counts", {})
exposure, exposure_kg = recon.get("exposure", {}), recon.get("exposure_kg", {})
at_risk, at_risk_kg = recon.get("exposure_total", 0), recon.get("exposure_kg_total", 0)
n_exc = sum(counts.values())
U.page_header(
    tr("Reconciliation.", "المطابقة بين الأنظمة."),
    tr("Three pairs of systems matched every night — the controller against the sensors, "
       "harvests against shipments, consumption against purchases.",
       "ثلاثة أزواج من الأنظمة تُطابَق كل ليلة — وحدة التحكم مقابل الحساسات، والحصاد مقابل "
       "الشحنات، والاستهلاك مقابل المشتريات."),
    [U.chip(tr("Synthetic data", "بيانات تركيبية")),
     U.chip(tr(f"{n_exc} exceptions", f"{n_exc} استثناءات"), "red" if n_exc else "strong"),
     U.chip(tr(f"{U.money(at_risk, 2)} at risk", f"{U.money(at_risk, 2)} معرّضة للخطر"),
            "red" if at_risk else "strong")])

# ---- the three matches ---------------------------------------------------------------
m = recon.get("match", {})
cmd, hv, su = m.get("commands", {}), m.get("harvest", {}), m.get("supplies", {})
U.section(tr("Three matches", "المطابقات الثلاث"),
          tr("controller ↔ sensors · harvest ↔ shipments · consumption ↔ purchases",
             "وحدة التحكم ↔ الحساسات · الحصاد ↔ الشحنات · الاستهلاك ↔ المشتريات"))
U.stat_cards([
    (tr("Pump runs observed", "تشغيلات المضخة المرصودة"), f"{cmd.get('rate', 0):.1%}",
     tr(f"{cmd.get('observed', 0):,} of {cmd.get('commanded', 0):,} runs raised the level",
        f"{cmd.get('observed', 0):,} من {cmd.get('commanded', 0):,} تشغيلاً رفعت المستوى"),
     cmd.get("rate", 1) < 1),
    (tr("Harvest shipped", "الحصاد المشحون"), f"{hv.get('rate', 0):.1%}",
     tr(f"{hv.get('kg_shipped', 0):,.2f} of {hv.get('kg_harvested', 0):,.2f} kg · "
        f"{hv.get('shipped', 0)} of {hv.get('harvests', 0)} harvests",
        f"{hv.get('kg_shipped', 0):,.2f} من {hv.get('kg_harvested', 0):,.2f} كغ · "
        f"{hv.get('shipped', 0)} من {hv.get('harvests', 0)} عملية حصاد"),
     hv.get("shipped", 0) < hv.get("harvests", 0)),
    (tr("Consumption covered", "الاستهلاك المغطّى"), f"{su.get('rate', 0):.1%}",
     tr(f"{su.get('covered', 0):,.2f} of {su.get('consumed', 0):,.2f} units bought before use",
        f"{su.get('covered', 0):,.2f} من {su.get('consumed', 0):,.2f} وحدة اشتُريت قبل استخدامها"),
     su.get("rate", 1) < 1),
    (tr("At risk", "المعرّض للخطر"), U.money(at_risk, 2),
     tr(f"{at_risk_kg:,.2f} kg across {n_exc} exceptions", f"{at_risk_kg:,.2f} كغ عبر {n_exc} استثناءات"),
     at_risk > 0),
])


# ---- the exceptions ---------------------------------------------------------------------
@st.fragment
def exceptions() -> None:
    exc = pd.DataFrame(recon.get("exceptions", []))
    classes = recon.get("classes") or {}
    # Ranked by money, not by count: one pump incident can outweigh six records.
    order = sorted((c for c in CLASSES if counts.get(c)), key=lambda c: exposure.get(c, 0),
                   reverse=True)
    if not order:
        U.alert(tr("Every match closed", "أُغلقت كل المطابقات"),
                "<p>" + tr("No reconciliation exception this period.",
                           "لا يوجد استثناء مطابقة في هذه الفترة.") + "</p>",
                pill=tr("Reconciled", "مطابَق"), kind="ok")
        return
    left, right = st.columns([1.05, 1], gap="large")
    with left, U.card("reconcile-1"):
        fig = go.Figure(go.Bar(
            y=[CLASSES[c] for c in order], x=[exposure.get(c, 0) for c in order],
            orientation="h", marker_color=U.C["red"],          # red = money at risk
            text=[f"{U.money(exposure.get(c, 0), 2)} · {exposure_kg.get(c, 0):,.2f} kg · {counts[c]}"
                  for c in order],
            textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: %{x:,.2f}<extra></extra>"))
        fig.update_layout(showlegend=False, yaxis=dict(autorange="reversed"),
                          margin=dict(l=230, t=12, r=210), xaxis=dict(visible=False))
        U.chart(fig, 260)
    with right:
        cls = st.selectbox(
            tr("Exception class", "فئة الاستثناء"), order,
            format_func=lambda c: f"{CLASSES[c]} · {counts.get(c, 0)} · {U.money(exposure.get(c, 0), 2)}")
        key = (classes.get(cls) or {}).get("cite")
        where, excerpt = U.rule_excerpt(key, 360) if key else ("", "")
        label, amount, items = CLASSES[cls], U.money(exposure.get(cls, 0), 2), counts.get(cls, 0)
        U.alert(tr(f"{label} — {amount} across {items} items", f"{label} — {amount} عبر {items} بنود"),
                f"<p>{excerpt}</p><p class='cite'>{where}</p>",
                pill=tr("Governing rule", "القاعدة الحاكمة"), kind="ok")
    if exc.empty:
        return
    picked = exc[exc["class"] == cls].sort_values("eur", ascending=False).reset_index(drop=True)
    cols = [c for c in ("unit_id", "ref", "kg", "eur", "expected", "found", "detail", "date")
            if c in picked.columns]
    rows = picked[cols].copy()
    rows["date"] = rows["date"].astype(str).str[:10]
    event = st.dataframe(
        rows, hide_index=True, height=min(420, 38 + 35 * len(rows)),
        selection_mode="single-row", on_select="rerun", key=f"exc-{cls}",
        column_config={
            "unit_id": tr("Unit", "الوحدة"), "ref": tr("Reference", "المرجع"),
            "kg": st.column_config.NumberColumn(tr("kg at risk", "كغ معرّضة"), format="%.2f"),
            "eur": st.column_config.NumberColumn(tr(f"At risk ({U.CURRENCY})", f"معرّض ({U.CURRENCY})"),
                                                 format="%.2f"),
            "expected": tr("System expects", "المتوقع في النظام"), "found": tr("Found", "الموجود"),
            "detail": tr("Detail", "التفاصيل"), "date": tr("Date", "التاريخ")})
    # Select a row to decide on it: every exception is a finding someone must
    # approve, escalate or reject, and the decision is audited.
    chosen = (event.selection.rows or [None])[0] if hasattr(event, "selection") else None
    if chosen is None:
        st.caption(tr("Select a row to approve, escalate or reject it.",
                      "اختر صفاً لاعتماده أو تصعيده أو رفضه."))
        return
    item = picked.iloc[chosen]
    subject = str(item["ref"])
    cite_of = item.get("citation") if isinstance(item.get("citation"), dict) else {}
    rule = U.cite(cite_of.get("source", ""), cite_of.get("section")) if cite_of else where
    U.approval_bar(subject,
                   f"{CLASSES[cls]} · {U.money(float(item.get('eur') or 0), 2)}",
                   rule=rule, detail=str(item.get("detail") or ""), key_suffix=f"-recon-{cls}")
    U.audit_link(subject, tr("Audit trail for this item", "سجل التدقيق لهذا البند"),
                 key_suffix=f"-recon-{cls}")


U.section(tr("Exceptions", "الاستثناءات"),
          tr("ranked by money at risk · the rule each one breaks", "مرتبة حسب المال المعرّض · والقاعدة التي يخالفها كل منها"))
exceptions()
