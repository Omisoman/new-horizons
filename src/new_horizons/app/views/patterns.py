"""Patterns — who touches which grow unit, with what outcome, and the records
that stop adding up when you look at the person behind them."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr
WEEKDAY_AR = {"Monday": "الاثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء",
              "Thursday": "الخميس", "Friday": "الجمعة", "Saturday": "السبت", "Sunday": "الأحد"}
ALERT = {"low_water_level": tr("low water level", "انخفاض مستوى المياه"),
         "low_dissolved_o2": tr("low dissolved oxygen", "انخفاض الأكسجين المذاب"),
         "high_water_temp": tr("high water temperature", "ارتفاع حرارة المياه"),
         "high_air_temp": tr("high air temperature", "ارتفاع حرارة الهواء"),
         "low_ph": tr("low pH", "انخفاض الحموضة"), "high_ph": tr("high pH", "ارتفاع الحموضة")}

data = U.load_json(U.AN_DIR / "patterns.json")
if not data:
    with st.spinner(tr("scanning patterns…", "جارٍ فحص الأنماط…")):
        from new_horizons.app.analytics.patterns import run as patterns_run
        data = patterns_run()
recon = U.load_json(U.AN_DIR / "recon.json", {}) or {}
ghost_eur = {e["ref"]: e["eur"] for e in recon.get("exceptions", []) if e["class"] == "harvest_not_shipped"}

loops, late, drops = data.get("ghost_loops", []), data.get("late_responses", []), data.get("dropouts", [])
sop = data.get("sop_hours", 2)
U.page_header(
    tr("Patterns.", "الأنماط."),
    tr("Who touches which grow unit, with what outcome — and the records that stop adding up "
       "when you look at the person behind them.",
       "من يعمل على أي وحدة وبأي نتيجة — والسجلات التي لا تتطابق حين ننظر إلى الشخص الذي وراءها."),
    [U.chip(tr("Synthetic data", "بيانات تركيبية")),
     U.chip(tr(f"{len(loops)} ghost loop{'' if len(loops) == 1 else 's'}",
               f"حلقات حصاد وهمي: {len(loops)}"), "red" if loops else "strong"),
     U.chip(tr(f"{len(late)} late response{'' if len(late) == 1 else 's'}",
               f"استجابات متأخرة: {len(late)}"), "red" if late else "strong")])

ghost_n = sum(lp["count"] for lp in loops)
ghost_kg = sum(lp["kg"] for lp in loops)
ghost_money = sum(ghost_eur.get(h["harvest_no"], 0) for lp in loops for h in lp["harvests"])
worst = max((r["response_hours"] or 0 for r in late), default=0)
U.stat_cards([
    (tr("Harvests never shipped", "حصاد لم يُشحن"), f"{ghost_n}",
     tr(f"{ghost_kg:,.2f} kg · {U.money(ghost_money, 2)}", f"{ghost_kg:,.2f} كغ · {U.money(ghost_money, 2)}"),
     ghost_n > 0),
    (tr("Never countersigned", "بلا توقيع ثانٍ"), f"{sum(lp['uncountersigned'] for lp in loops)}",
     tr("a second person signs every harvest", "يوقّع شخص ثانٍ على كل حصاد"), bool(loops)),
    (tr("Late responses", "استجابات متأخرة"), f"{len(late)}",
     tr(f"worst {worst:.1f} h against the SOP's {sop:g} h", f"الأسوأ {worst:.1f} ساعة مقابل {sop:g} في الإجراءات"),
     bool(late)),
    (tr("Sensor dropouts", "انقطاعات الحساسات"), f"{len(drops)}",
     tr(f"{sum(g['hours'] for g in drops):g} hours · each followed by a work order",
        f"{sum(g['hours'] for g in drops):g} ساعة · تلا كلاً منها أمر عمل")
     if all(g.get("work_order_no") for g in drops) else
     tr("one without a work order", "أحدها بلا أمر عمل"), False),
])

for lp in loops:
    where, excerpt = U.rule_excerpt("harvest_countersign", 260)
    ship_where, _ = U.rule_excerpt("harvest_shipment_match", 60)
    days = sorted({h["weekday"] for h in lp["harvests"]})
    days_txt = tr(", ".join(days), "، ".join(WEEKDAY_AR.get(d, d) for d in days))
    units = ", ".join(lp["units"])
    money = U.money(sum(ghost_eur.get(h["harvest_no"], 0) for h in lp["harvests"]), 2)
    U.alert(tr(f"{lp['technician_code']} ({lp['name']}) logged {lp['count']} harvests nobody shipped — "
               f"{lp['kg']:,.2f} kg, {money}",
               f"سجّل {lp['technician_code']} عدد {lp['count']} عمليات حصاد لم يشحنها أحد — "
               f"{lp['kg']:,.2f} كغ، {money}"),
            "<p>" + tr(f"On {units}, every one on a {days_txt} — no scheduled harvest day — and none "
                       f"countersigned. {lp['share']:.0%} of this technician's harvests never left; no other "
                       f"technician has one ({lp['others_max_share']:.0%}).",
                       f"على الوحدات {units}، وكلها يوم {days_txt} — وهو ليس يوم حصاد مجدولاً — ولم يوقّع "
                       f"عليها أحد. {lp['share']:.0%} من حصاد هذا الفني لم يخرج من المزرعة، ولا يوجد ذلك لدى "
                       f"أي فني آخر ({lp['others_max_share']:.0%}).")
            + f"</p><p><b>{tr('Control.', 'الضابط.')}</b> {excerpt}</p>"
            f"<p class='cite'>{where} · {ship_where}</p>")

# ---- the graph: technician ↔ grow unit -------------------------------------------------
# identity by node kind (series 1 units, series 2 technicians); red marks only the
# loop edges — the one place colour means "discrepancy"
U.section(tr("Who works where", "من يعمل أين"),
          tr("technician ↔ grow unit · work orders and harvest logs", "فني ↔ وحدة زراعة · أوامر العمل وسجلات الحصاد"))
g = data["graph"]
pos = {n["id"]: n for n in g["nodes"]}
traces = []
for flagged in (False, True):
    xs, ys = [], []
    for e in g["edges"]:
        if bool(e.get("loop")) != flagged:
            continue
        a, b = pos[e["a"]], pos[e["b"]]
        xs += [a["x"], b["x"], None]
        ys += [a["y"], b["y"], None]
    traces.append(go.Scatter(x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=True,
                             name=tr("Unshipped harvests", "حصاد غير مشحون") if flagged
                             else tr("Work orders and harvests", "أوامر عمل وحصاد"),
                             opacity=1 if flagged else 0.45,
                             line=dict(width=3 if flagged else 0.9,
                                       color=U.C["red"] if flagged else U.C["borderStrong"])))
for kind, color, name in (("unit", U.SERIES[0], tr("Grow unit", "وحدة زراعة")),
                          ("technician", U.SERIES[1], tr("Technician", "فني"))):
    nodes = [n for n in g["nodes"] if n["kind"] == kind]
    traces.append(go.Scatter(
        x=[n["x"] for n in nodes], y=[n["y"] for n in nodes], mode="markers+text", name=name,
        marker=dict(size=16 if kind == "unit" else 12, color=color, line=dict(width=2, color=U.C["bg"])),
        text=[n["id"] for n in nodes], textposition="top center",
        textfont=dict(color=U.C["fgMuted"], size=11),
        hovertext=[n["label"] for n in nodes], hovertemplate="%{hovertext}<extra></extra>"))
with U.card("patterns-1"):
    fig = go.Figure(traces)
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False),
                      margin=dict(t=40, b=8, l=8, r=8), hovermode="closest")
    U.chart(fig, 460)

U.section(tr("Technicians", "الفنيون"), tr("work orders and harvest logs", "أوامر العمل وسجلات الحصاد"))
techs = pd.DataFrame(data.get("technicians", []))
if not techs.empty:
    techs = techs.drop(columns=["units", "no_fault_found"], errors="ignore")
    st.dataframe(techs, hide_index=True, column_config={
        "technician_code": tr("Code", "الرمز"), "name": tr("Name", "الاسم"), "role": tr("Role", "الدور"),
        "work_orders": st.column_config.NumberColumn(tr("Work orders", "أوامر العمل"), format="%d"),
        "closed": st.column_config.NumberColumn(tr("Closed", "مغلقة"), format="%d"),
        "harvests_logged": st.column_config.NumberColumn(tr("Harvests logged", "حصاد مسجّل"), format="%d"),
        "harvests_unshipped": st.column_config.NumberColumn(tr("Never shipped", "لم يُشحن"), format="%d"),
        "harvests_uncountersigned": st.column_config.NumberColumn(tr("Not countersigned", "بلا توقيع ثانٍ"),
                                                                   format="%d"),
        "unshipped_share": st.column_config.NumberColumn(tr("Unshipped share", "حصة غير المشحون"),
                                                         format="percent")})

# ---- response to alerts against the SOP ------------------------------------------------
where, excerpt = U.rule_excerpt("pump_response", 220)
U.section(tr("Alert response", "الاستجابة للتنبيهات"),
          tr(f"alert to work order · SOP {sop:g} hours for live-stock alerts",
             f"من التنبيه إلى أمر العمل · {sop:g} ساعة في الإجراءات لتنبيهات الكائنات الحية"))
rows = [(r["alert_no"], r["unit_id"], ALERT.get(r["type"], r["type"]), r["opened"].replace("T", " "),
         f"{(r['ack_minutes'] or 0) / 60:.1f} h", r["work_order_no"] or "—", r["technician_code"] or "—",
         ("html", U.chip(f"{r['response_hours']:.1f} h", "red" if r["late"] else "strong")))
        for r in data.get("response", [])]
if late:
    U.alert(tr(f"{len(late)} live-stock alert answered after the SOP's {sop:g} hours",
               f"{len(late)} تنبيه يمس الكائنات الحية جرت الاستجابة له بعد {sop:g} ساعة"),
            f"<p>{excerpt}</p><p class='cite'>{where}</p>", pill=tr("Late", "متأخر"))
st.markdown(U.html_table([tr("Alert", "التنبيه"), tr("Unit", "الوحدة"), tr("Type", "النوع"),
                          tr("Opened", "فُتح"), tr("Acknowledged after", "أُقرّ بعد"),
                          tr("Work order", "أمر العمل"), tr("Technician", "الفني"),
                          tr("Response", "الاستجابة")], rows), unsafe_allow_html=True)

# ---- dropout clusters --------------------------------------------------------------------
where, excerpt = U.rule_excerpt("sensor_dropout", 200)
U.section(tr("Sensor dropouts", "انقطاعات الحساسات"),
          tr("gaps in the readings, never zeros", "فجوات في القراءات وليست أصفاراً"))
rows = [(g["unit_id"], g["start"].replace("T", " "), g["end"].replace("T", " "), f"{g['hours']:g} h",
         f"{g['missing_readings']}", g.get("work_order_no") or "—") for g in drops]
st.markdown(U.html_table([tr("Unit", "الوحدة"), tr("From", "من"), tr("To", "إلى"),
                          tr("Duration", "المدة"), tr("Missing readings", "القراءات المفقودة"),
                          tr("Work order", "أمر العمل")], rows), unsafe_allow_html=True)
st.markdown(f"<p class='ac-subtle'>{excerpt} <span class='cite'>{where}</span></p>",
            unsafe_allow_html=True)
