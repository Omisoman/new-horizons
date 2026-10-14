"""Drift — water temperature, pH and dissolved oxygen per grow unit against the
reference month, the aeration duty, and for a drifting pH whether the probe or
the water moved. The page is one fragment: changing the month or the unit reruns
the page, not the app."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
MONTHS_AR = ("كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب",
             "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول")
LABEL = {"water_temp_c": tr("Water temperature", "حرارة المياه"), "ph": tr("pH", "الحموضة"),
         "dissolved_o2_mg_l": tr("Dissolved oxygen", "الأكسجين المذاب"),
         "air_duty": tr("Aeration duty", "تشغيل التهوية")}
RULE = {"water_temp_c": "water_temp_band", "ph": "water_ph_band",
        "dissolved_o2_mg_l": "do_minimum", "air_duty": "aeration_duty"}


def month_label(m: str) -> str:
    y, mo = m.split("-")
    return tr(f"{MONTHS_EN[int(mo) - 1]} {y}", f"{MONTHS_AR[int(mo) - 1]} {y}")


drift = U.load_json(U.AN_DIR / "drift.json")
if not drift:
    with st.spinner(tr("computing drift…", "جارٍ حساب الانحراف…")):
        from new_horizons.app.analytics.drift import run as drift_run
        drift = drift_run()
daily = pd.DataFrame(U.load_json(U.AN_DIR / "daily.json", []) or [])


def _fmt(v, unit: str = "", digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}{(' ' + unit) if unit else ''}"


@st.fragment
def page() -> None:
    months = drift["months"]
    names = {m: month_label(m) for m in months}      # labels fixed in this run's language
    head, pick_m, pick_u = st.columns([3.2, 1, 1], vertical_alignment="bottom")
    with pick_m:
        month = st.selectbox(tr("Month under test", "الشهر قيد الاختبار"), months,
                             index=months.index(drift["default_window"]), format_func=names.get,
                             help=tr(f"Compared with the reference month, {month_label(drift['reference'])}.",
                                     f"مقارنةً بشهر الأساس، {month_label(drift['reference'])}."))
    win = drift["windows"][month]
    units = sorted(win["units"])
    flagged = [f["unit_id"] for f in win["flags"]]
    with pick_u:
        unit = st.selectbox(tr("Grow unit", "وحدة الزراعة"), units,
                            index=units.index(flagged[0]) if flagged else 0)
    flags = win["flags"]
    with head:
        U.page_header(tr("Water drift.", "انحراف المياه."),
                      tr("Water temperature, pH and dissolved oxygen per grow unit against the "
                         "reference month — the share outside the SOP band decides; PSI and "
                         "Kolmogorov–Smirnov are the evidence.",
                         "حرارة المياه والحموضة والأكسجين المذاب لكل وحدة مقارنةً بشهر الأساس — "
                         "تحسم الحصةُ خارج نطاق الإجراءات، ومؤشر PSI واختبار كولموغوروف–سميرنوف دليل."),
                      [U.chip(tr("Synthetic data", "بيانات تركيبية")),
                       U.chip(tr(f"{len(flags)} drift flag{'' if len(flags) == 1 else 's'}", f"إنذارات انحراف: {len(flags)}")
                              if flags else tr("Stable", "مستقر"), "red" if flags else "strong")])

    stats = win["units"][unit]
    measures = drift["measures"]
    duty = win["duty"].get(unit, {})
    cards = []
    for col, spec in measures.items():
        s = stats[col]
        band = spec["band"]
        band_txt = f"{band[0]:g}–{band[1]:g}" if band[0] is not None and band[1] is not None else \
            (f"≥ {band[0]:g}" if band[0] is not None else f"≤ {band[1]:g}")
        cards.append((LABEL.get(col, spec["label"]), _fmt(s["cur_mean"], spec["unit"]),
                      tr(f"reference {_fmt(s['ref_mean'], spec['unit'])} · {s['outside_cur_pct']:.1f}% "
                         f"outside {band_txt}",
                         f"الأساس {_fmt(s['ref_mean'], spec['unit'])} · {s['outside_cur_pct']:.1f}% "
                         f"خارج {band_txt}"),
                      s["level"] == "alert"))
    limit = drift.get("duty_limit", 0.5)
    over = duty.get("days_over_limit", [])
    cards.append((LABEL["air_duty"], f"{duty.get('current_pct', 0):.1f}%",
                  tr(f"reference {duty.get('reference_pct', 0):.1f}% · {len(over)} days over {limit:.0%}",
                     f"الأساس {duty.get('reference_pct', 0):.1f}% · {len(over)} أيام فوق {limit:.0%}"),
                  bool(over)))
    U.stat_cards(cards)

    verdicts = {"alert": (tr("Drift", "انحراف"), "red"), "watch": (tr("Watch", "مراقبة"), "amber"),
                "none": (tr("Stable", "مستقر"), "strong")}
    rows = []
    for col, spec in measures.items():
        s = stats[col]
        text, kind = verdicts.get(s["level"], (s["level"], ""))
        rows.append((LABEL.get(col, spec["label"]), _fmt(s["ref_mean"]), _fmt(s["cur_mean"]),
                     f"{s['outside_ref_pct']:.1f}% → {s['outside_cur_pct']:.1f}%",
                     f"{s['psi']:.3f}", f"{s['ks_stat']:.3f} · p = {s['ks_pvalue']:.1e}",
                     ("html", U.chip(text, kind))))
    U.section(tr(f"{unit} in {month_label(month)}", f"{unit} في {month_label(month)}"),
              tr(f"{stats['ph']['n_cur']:,} readings against {stats['ph']['n_ref']:,} in the reference month",
                 f"{stats['ph']['n_cur']:,} قراءة مقابل {stats['ph']['n_ref']:,} في شهر الأساس"))
    st.markdown(U.html_table([tr("Measure", "القياس"), tr("Reference mean", "متوسط الأساس"),
                              tr("Current mean", "المتوسط الحالي"), tr("Outside band", "خارج النطاق"),
                              "PSI", "KS", tr("Verdict", "الحكم")], rows), unsafe_allow_html=True)

    # ---- the flags of the month, each with the rule it is measured against ----------
    for f in flags:
        where, excerpt = U.rule_excerpt(RULE.get(f["measure"], ""), 260)
        label = LABEL.get(f["measure"], f["label"])
        U.alert(tr(f"{f['unit_id']} · {label} in {month_label(month)}",
                   f"{f['unit_id']} · {label} في {month_label(month)}"),
                f"<p>{f['trigger']}</p><p><b>{tr('Rule.', 'القاعدة.')}</b> {excerpt}</p>"
                f"<p class='cite'>{where}</p>", pill=tr("Drift", "انحراف"))

    # ---- a drifting pH: the probe or the water? ----------------------------------------
    cause = win.get("ph_cause", {}).get(unit)
    if cause:
        sensor = cause["cause"] == "sensor"
        where, excerpt = U.rule_excerpt("sensor_vs_chemistry", 320)
        dec, doses, cal = cause["decline_per_day"], cause["doses_per_week"], cause.get("calibration")
        evidence = [
            tr(f"Decline between doses: {_fmt(dec['current'], digits=4)} pH/day against "
               f"{_fmt(dec['reference'], digits=4)} in the reference month.",
               f"الانخفاض بين الجرعات: {_fmt(dec['current'], digits=4)} يومياً مقابل "
               f"{_fmt(dec['reference'], digits=4)} في شهر الأساس."),
            tr(f"Doses per week: {doses['current']:.2f} against {doses['reference']:.2f}.",
               f"الجرعات أسبوعياً: {doses['current']:.2f} مقابل {doses['reference']:.2f}."),
        ]
        if cal:
            evidence.append(tr(f"Calibration {cal['work_order_no']} on {cal['at'][:10]} stepped the "
                               f"reading {cal['step']:+.2f}.",
                               f"أعادت المعايرة {cal['work_order_no']} في {cal['at'][:10]} القراءة "
                               f"بمقدار {cal['step']:+.2f}."))
        U.alert(tr("Sensor drift — the reading moved, the water did not" if sensor
                   else "Chemistry drift — the water changed",
                   "انحراف المجس — تحركت القراءة ولم تتغير المياه" if sensor
                   else "انحراف كيميائي — تغيّرت المياه"),
                "<ul>" + "".join(f"<li>{e}</li>" for e in evidence) + "</ul>"
                f"<p><b>{tr('Rule.', 'القاعدة.')}</b> {excerpt}</p><p class='cite'>{where}</p>",
                pill=tr("Sensor", "المجس") if sensor else tr("Chemistry", "الكيمياء"),
                kind="amber" if sensor else "red")

    # ---- the evidence: the distribution behind the verdict ---------------------------
    measure = st.radio(tr("Distribution", "التوزيع"), list(measures), horizontal=True,
                       index=list(measures).index("ph"), format_func=lambda c: LABEL.get(c, c),
                       key="drift-measure")
    dist = stats[measure]["distribution"]
    edges = dist["edges"]
    labels = [f"{edges[i]:.2f}–{edges[i + 1]:.2f}" for i in range(len(edges) - 1)]
    U.section(tr(f"Distribution · {LABEL[measure]}", f"التوزيع · {LABEL[measure]}"),
              tr("reference-month deciles — the bins the PSI uses", "عُشيرات شهر الأساس — فئات مؤشر PSI"))
    with U.card("drift-1"):
        fig = go.Figure()
        fig.add_bar(x=labels, y=dist["reference_pct"], name=month_label(drift["reference"]))
        fig.add_bar(x=labels, y=dist["current_pct"], name=month_label(month))
        fig.update_layout(barmode="group", bargroupgap=0.08, hovermode="x unified",
                          yaxis_tickformat=".0%")
        U.chart(fig, 320)

    # ---- aeration duty: the controller's own record of the heat ---------------------
    if not daily.empty:
        where, excerpt = U.rule_excerpt("aeration_duty", 240)
        U.section(tr("Aeration duty", "تشغيل التهوية"),
                  tr(f"share of the day each air pump ran · limit {limit:.0%}",
                     f"حصة اليوم التي عملت فيها كل مضخة هواء · الحد {limit:.0%}"))
        with U.card("drift-2"):
            fig = go.Figure()
            for u in sorted(daily.unit_id.unique()):
                part = daily[daily.unit_id == u]
                fig.add_scatter(x=part.date, y=part.duty, mode="lines", name=u, line=dict(width=2))
            fig.add_hline(y=limit, line_dash="dot", line_color=U.C["red"],
                          annotation_text=f"{limit:.0%}", annotation_font_color=U.C["red"])
            rng = win["range"]
            fig.add_vrect(x0=rng[0], x1=rng[1], fillcolor=U.C["fg"], opacity=0.05, line_width=0,
                          annotation_text=month_label(month), annotation_position="top left",
                          annotation_font_color=U.C["fgMuted"])
            fig.update_layout(hovermode="x unified", yaxis_tickformat=".0%")
            U.chart(fig, 300)
        st.markdown(f"<p class='ac-subtle'>{excerpt} <span class='cite'>{where}</span></p>",
                    unsafe_allow_html=True)

    # ---- gaps are gaps ---------------------------------------------------------------
    gaps = drift.get("gaps", [])
    where, excerpt = U.rule_excerpt("sensor_dropout", 200)
    listed = "; ".join(f"{g['unit_id']} {g['start'][:16].replace('T', ' ')} · {g['hours']:g} h · "
                       + tr(f"{g['missing_readings']} readings", f"{g['missing_readings']} قراءة")
                       for g in gaps) or tr("none", "لا يوجد")
    st.markdown("<p class='ac-subtle'>" + tr(
        f"Sensor dropouts are left out of every test, never filled with zeros: {listed}.",
        f"تُستبعد انقطاعات الحساسات من كل اختبار ولا تُملأ بأصفار أبداً: {listed}.")
        + f" <span class='cite'>{where}</span></p>", unsafe_allow_html=True)


page()
