"""Overview — the four grow units, the five farm systems behind them, and what
this period's analytics found, priced."""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from new_horizons.app import ui_common as U

tr = U.tr

SYSTEMS = [  # schema, name, what it holds, primary table, unit
    ("telemetry", tr("Telemetry", "القياسات"),
     tr("Water, air, pH and oxygen readings from every unit, every 15 minutes.",
        "قراءات المياه والهواء والحموضة والأكسجين من كل وحدة كل 15 دقيقة."),
     "readings", tr("readings", "قراءة")),
    ("controller", tr("Controller", "وحدة التحكم"),
     tr("What the pumps, feeders and dosing were told to do, and the alerts raised.",
        "ما أُمرت به المضخات والمعالِف والجرعات، والتنبيهات الصادرة."),
     "commands", tr("commands", "أمر")),
    ("maintenance", tr("Maintenance", "الصيانة"),
     tr("Technicians and the work orders they opened and closed.",
        "الفنيون وأوامر العمل التي فتحوها وأغلقوها."),
     "work_orders", tr("work orders", "أمر عمل")),
    ("harvest", tr("Harvest & shipping", "الحصاد والشحن"),
     tr("What each unit yielded, and what left the building to customers.",
        "ما أنتجته كل وحدة، وما خرج من المزرعة إلى العملاء."),
     "harvests", tr("harvests", "حصاد")),
    ("supplies", tr("Supplies", "المستلزمات"),
     tr("Feed, nutrients and parts bought, and what each unit consumed.",
        "العلف والمغذيات والقطع المشتراة، وما استهلكته كل وحدة."),
     "purchases", tr("purchases", "عملية شراء")),
]
PLANT = {"pepper": tr("Pepper", "فلفل"), "lettuce": tr("Lettuce", "خس"),
         "tomato": tr("Tomato", "طماطم"), "basil": tr("Basil", "ريحان")}
PLACE = {"greenhouse-A": tr("Greenhouse A", "البيت المحمي أ"),
         "greenhouse-B": tr("Greenhouse B", "البيت المحمي ب"), "rooftop": tr("Rooftop", "السطح")}
CLASSES = {  # recon class -> label, in the running language
    "commanded_not_observed": tr("Pump commanded, level never rose", "أُمرت المضخة ولم يرتفع المستوى"),
    "harvest_not_shipped": tr("Harvests never shipped", "حصاد لم يُشحن"),
    "consumed_not_purchased": tr("Feed consumed, never bought", "علف استُهلك ولم يُشترَ"),
}

meta = U.mock_meta()
if not meta:
    U.page_header(tr("Farm overview.", "نظرة عامة على المزرعة."),
                  tr("No synthetic farm data loaded yet.", "لم تُحمَّل بيانات المزرعة التركيبية بعد."),
                  [U.chip(tr("Synthetic data", "بيانات تركيبية"))])
    st.info(tr("Run `make mock` to generate the five databases.",
               "شغّل `make mock` لإنشاء قواعد البيانات الخمس."))
    st.stop()

start, end = (date.fromisoformat(d) for d in meta["period"])
week_start = end - timedelta(days=6)


@st.cache_data(ttl=600)
def table_counts() -> dict:
    rows = U.q("SELECT table_schema, table_name FROM information_schema.tables "
               "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
               ([s[0] for s in SYSTEMS],))
    out: dict = {}
    for schema, table in rows:
        n, = U.q(f'SELECT count(*) FROM "{schema}"."{table}"')[0]  # names from catalog
        out.setdefault(schema, {})[table] = n
    return out


@st.cache_data(ttl=600)
def units() -> pd.DataFrame:
    rows = U.q("SELECT unit_id, plant, location, grow_bed_m2, fish_count, fish_species "
               "FROM telemetry.units ORDER BY unit_id")
    return pd.DataFrame(rows, columns=["unit_id", "plant", "location", "m2", "fish", "species"])


@st.cache_data(ttl=600)
def kpis() -> dict:
    kg, n = U.q("SELECT coalesce(sum(kg), 0), count(*) FROM harvest.harvests "
                "WHERE date BETWEEN %s AND %s", (week_start, end))[0]
    open_, raised = U.q("SELECT count(*) FILTER (WHERE status = 'open'), count(*) "
                        "FROM controller.alerts")[0]
    return {"kg_week": float(kg), "harvests_week": n, "open": open_, "raised": raised}


@st.cache_data(ttl=600)
def weekly_harvest() -> pd.DataFrame:
    rows = U.q("SELECT date_trunc('week', date)::date, unit_id, sum(kg) FROM harvest.harvests "
               "GROUP BY 1, 2 ORDER BY 1, 2")
    return pd.DataFrame(rows, columns=["week", "unit_id", "kg"]).astype({"kg": float})


counts = table_counts()
total = sum(sum(t.values()) for t in counts.values())
farm = units()
k = kpis()
recon = U.load_json(U.AN_DIR / "recon.json", {}) or {}
exposure, n_exc = recon.get("exposure", {}), sum((recon.get("counts") or {}).values())

U.page_header(
    tr("Farm overview.", "نظرة عامة على المزرعة."),
    tr(f"Four grow units, five farm systems, one agent — {start:%d %b} to {end:%d %b %Y}.",
       f"أربع وحدات زراعة، وخمسة أنظمة، ووكيل واحد — من {start:%Y/%m/%d} إلى {end:%Y/%m/%d}."),
    [U.chip(tr("Synthetic data", "بيانات تركيبية")),
     U.chip(tr(f"{len(SYSTEMS)} databases", f"{len(SYSTEMS)} قواعد بيانات")),
     U.chip(tr(f"{total:,} records", f"{total:,} سجل"), "strong")])


# ---- what this period found ---------------------------------------------------------
def findings() -> list[dict]:
    """Every reconciliation class with an exception, priced, biggest first. The
    action line is the governing rule's own wording — never ours."""
    classes = recon.get("classes") or {}
    out = []
    for cls, eur in exposure.items():
        n = (recon.get("counts") or {}).get(cls, 0)
        if not n:
            continue
        kg = (recon.get("exposure_kg") or {}).get(cls, 0)
        out.append({"what": CLASSES.get(cls, cls), "amount": eur,
                    "detail": tr(f"{n} exception{'s' if n != 1 else ''} · {kg:,.2f} kg at risk",
                                 f"{n} استثناء · {kg:,.2f} كغ معرّضة للخطر"),
                    "cite": (classes.get(cls) or {}).get("cite")})
    return sorted(out, key=lambda f: -f["amount"])[:3]


found = findings()
if found:
    U.section(tr("What the reconciliation found", "ما وجدته المطابقة"),
              tr(f"highest money at risk first · every figure in {U.CURRENCY}",
                 f"الأعلى مالاً أولاً · جميع المبالغ بـ {U.CURRENCY}"))
    cards = []
    for f in found:
        where, excerpt = U.rule_excerpt(f["cite"], 220) if f["cite"] else ("", "")
        action = (excerpt.split(". ")[0].rstrip(".") + "." if excerpt else "")
        cards.append(
            f"<div class='ac-card flag'><div class='ac-label'>{f['what']}</div>"
            f"<div class='v'>{U.money(f['amount'], 2)}</div>"
            f"<div class='s'>{f['detail']}</div>"
            f"<p style='margin-top:.7rem;font-size:13.5px'>{action}</p>"
            f"<p class='cite' style='margin-top:.4rem'>{where}</p></div>")
    st.markdown(f"<div class='ac-grid' style='grid-template-columns:repeat({len(cards)},"
                f"minmax(0,1fr))'>{''.join(cards)}</div>", unsafe_allow_html=True)

# ---- the grow units ----------------------------------------------------------------
U.section(tr("Grow units", "وحدات الزراعة"),
          tr("fish tanks feeding plant beds · one controller", "أحواض أسماك تغذّي أحواض الزراعة · وحدة تحكم واحدة"))
cards = []
for u in farm.itertuples():
    cards.append(
        f"<div class='ac-card'><div class='ac-label'>{u.unit_id}</div>"
        f"<div class='v'>{PLANT.get(u.plant, u.plant)}</div>"
        f"<div class='s'>{PLACE.get(u.location, u.location)} · {float(u.m2):.1f} m² · "
        + tr(f"{u.fish} fish", f"{u.fish} سمكة") + "</div></div>")
st.markdown(f"<div class='ac-grid' style='grid-template-columns:repeat({max(len(cards), 1)},"
            f"minmax(0,1fr))'>{''.join(cards)}</div>", unsafe_allow_html=True)

uptime = (meta.get("readings") or {}).get("uptime_pct", 0.0)
U.stat_cards([
    (tr("Grow units", "وحدات الزراعة"), f"{len(farm)}",
     tr(f"{farm.m2.astype(float).sum():.1f} m² of grow beds", f"{farm.m2.astype(float).sum():.1f} م² من الأحواض")),
    (tr("Fish", "الأسماك"), f"{int(farm.fish.sum()):,}",
     tr("European perch", "فرخ أوروبي")),
    (tr("Harvested this week", "حصاد هذا الأسبوع"), f"{k['kg_week']:,.2f} kg",
     tr(f"{k['harvests_week']} harvests · {week_start:%d %b}–{end:%d %b}",
        f"{k['harvests_week']} عملية حصاد · {week_start:%m/%d}–{end:%m/%d}")),
    (tr("Open alerts", "التنبيهات المفتوحة"), f"{k['open']}",
     tr(f"{k['raised']} raised this period", f"{k['raised']} تنبيهاً في الفترة"), k["open"] > 0),
    (tr("Sensor uptime", "جاهزية الحساسات"), f"{uptime:.2f}%",
     tr("readings received / expected", "القراءات الواردة / المتوقعة")),
    (tr("Money at risk", "المال المعرّض للخطر"), U.money(recon.get("exposure_total", 0), 2),
     tr(f"{n_exc} reconciliation exceptions", f"{n_exc} استثناءات مطابقة"), n_exc > 0),
], cols=6)

# ---- the five databases -------------------------------------------------------------
U.section(tr("Farm systems", "أنظمة المزرعة"),
          tr("one database each · joined on business keys", "قاعدة بيانات لكل نظام · مربوطة بمفاتيح الأعمال"))
cards = []
for schema, name, desc, table, unit in SYSTEMS:
    n = counts.get(schema, {}).get(table, 0)
    cards.append(
        f"<div class='ac-card' title='{desc}'><div class='ac-label'>{name}</div>"
        f"<div class='v'>{n:,}</div><div class='s'>{unit} · "
        f"<span class='ac-mono'>{schema}</span></div></div>")
st.markdown(f"<div class='ac-grid' style='grid-template-columns:repeat(5,minmax(0,1fr))'>"
            f"{''.join(cards)}</div>", unsafe_allow_html=True)

# ---- trends -------------------------------------------------------------------------
daily = U.load_json(U.AN_DIR / "daily.json")
if not daily:
    st.info(tr("Run the analytics once (`make mock`) to build the daily trends.",
               "شغّل التحليلات مرة واحدة (`make mock`) لبناء الاتجاهات اليومية."))
    st.stop()
df = pd.DataFrame(daily)
unit_ids = sorted(df.unit_id.unique())
bands = (U.load_json(U.AN_DIR / "drift.json", {}) or {}).get("measures", {})
water_top = (bands.get("water_temp_c") or {}).get("band", [None, None])[1]
do_floor = (bands.get("dissolved_o2_mg_l") or {}).get("band", [None, None])[0]

U.section(tr("Trends", "الاتجاهات"), tr("per grow unit", "لكل وحدة زراعة"))
tab1, tab2, tab3 = st.tabs([tr("Harvest", "الحصاد"), tr("Water temperature", "حرارة المياه"),
                            tr("Dissolved oxygen", "الأكسجين المذاب")])
with tab1, U.card("overview-1"):
    wk = weekly_harvest()
    fig = go.Figure()
    for u in unit_ids:
        part = wk[wk.unit_id == u]
        fig.add_bar(x=part.week, y=part.kg, name=u)
    fig.update_layout(barmode="stack", hovermode="x unified",
                      yaxis_title=tr("kg harvested per week", "كغ محصودة في الأسبوع"))
    U.chart(fig, 360)
with tab2, U.card("overview-2"):
    fig = go.Figure()
    for u in unit_ids:
        part = df[df.unit_id == u]
        fig.add_scatter(x=part.date, y=part.water_temp_c, mode="lines", name=u, line=dict(width=2))
    if water_top is not None:                                           # the perch band's top
        fig.add_hline(y=water_top, line_dash="dot", line_color=U.C["red"],
                      annotation_text=tr(f"{water_top:g} °C perch band", f"{water_top:g} °م نطاق الفرخ"),
                      annotation_font_color=U.C["red"])
    fig.update_layout(hovermode="x unified", yaxis_title=tr("daily mean, °C", "المتوسط اليومي، °م"))
    U.chart(fig, 360)
with tab3, U.card("overview-3"):
    fig = go.Figure()
    for u in unit_ids:
        part = df[df.unit_id == u]
        fig.add_scatter(x=part.date, y=part.do_min, mode="lines", name=u, line=dict(width=2))
    if do_floor is not None:                                            # the fish minimum
        fig.add_hline(y=do_floor, line_dash="dot", line_color=U.C["red"],
                      annotation_text=tr(f"{do_floor:g} mg/L minimum", f"الحد الأدنى {do_floor:g} ملغ/لتر"),
                      annotation_font_color=U.C["red"])
    fig.update_layout(hovermode="x unified",
                      yaxis_title=tr("daily minimum, mg/L", "الحد الأدنى اليومي، ملغ/لتر"))
    U.chart(fig, 360)
