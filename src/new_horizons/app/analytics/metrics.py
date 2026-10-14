"""Metrics layer — deterministic answers to the questions the room asks.

`agents/analytics/intents.yaml` names the known questions. `Metrics.match`
embeds a question with bge-m3 and compares it with every paraphrase; a close,
unambiguous match is resolved here into figures plus an English and an Arabic
template. Answers are the resolver's template by default (model phrasing is
opt-in and kept only if every figure survives — shared/harness/graph.py).
Figures come from what the screens read — data/analytics/*.json,
data/mock_meta.json — the read-only database and the audit log, so chat,
screens and tests/test_validation.py cannot disagree.

Resolvers are pure reads. Each returns
    {"figures": {name: text}, "template_en": str, "template_ar": str,
     "citation": {source, section}, "citations": [...]}
or None when the question is not really theirs (a slot they cannot answer).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from new_horizons.paths import APP, DATA
from new_horizons.shared.text.lang import IDENT, identifiers

AN = DATA / "analytics"
META = DATA / "mock_meta.json"
INTENTS = APP / "agents" / "analytics" / "intents.yaml"
CITATIONS = APP / "ingest" / "kb_synthetic" / "citations.yaml"
CACHE = DATA / "intents"

EN_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
# Levantine month names (the KB's); other Arabic markets say يونيو، يوليو، أغسطس
AR_MONTHS = ("كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب",
             "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول")
AR_MONTH_ALIASES = {6: ("حزيران", "يونيو", "يونيه"), 7: ("تموز", "يوليو", "يوليه"),
                    8: ("آب", "أغسطس", "اغسطس")}
AR_CURRENCY = {"EUR": "يورو"}
PLANT_AR = {"pepper": "الفلفل", "lettuce": "الخس", "tomato": "الطماطم", "basil": "الريحان"}
ALERT_EN = {"low_water_level": "low water level", "low_dissolved_o2": "low dissolved oxygen",
            "high_water_temp": "high water temperature", "high_air_temp": "high air temperature",
            "low_ph": "low pH", "high_ph": "high pH"}
CLASS_EN = {"commanded_not_observed": "pump commanded, level never rose",
            "harvest_not_shipped": "harvests never shipped",
            "consumed_not_purchased": "feed consumed, never bought"}
CLASS_AR = {"commanded_not_observed": "مضخة أُمرت ولم يرتفع المستوى",
            "harvest_not_shipped": "محاصيل لم تُشحن",
            "consumed_not_purchased": "علف استُهلك ولم يُشترَ"}


# ---- formatting ---------------------------------------------------------------

def _int(v) -> str:
    return f"{int(v):,}"


def _money(v) -> str:
    return f"{float(v):,.2f}"


def _kg(v) -> str:
    return f"{float(v):,.2f}"


def _d(v) -> date:
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])


def _day_en(v) -> str:
    d = _d(v)
    return f"{d.day} {EN_MONTHS[d.month - 1]}"


def _day_ar(v) -> str:
    d = _d(v)
    return f"{d.day} {AR_MONTHS[d.month - 1]}"


def _hm(v) -> str:
    return str(v)[11:16]


def _and_en(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _and_ar(items: list[str]) -> str:
    return "، و".join(items)


# ---- sources ------------------------------------------------------------------

def _json(name: str):
    return json.loads((AN / name).read_text(encoding="utf-8"))


def _meta() -> dict:
    return json.loads(META.read_text(encoding="utf-8"))


def _currency() -> tuple[str, str]:
    cur = _meta().get("currency", "EUR")
    return cur, AR_CURRENCY.get(cur, cur)


def _cite(key: str) -> dict:
    reg = yaml.safe_load(CITATIONS.read_text(encoding="utf-8"))
    return {"source": reg[key]["source"], "section": str(reg[key]["section"])}


def _rows(sql: str, params: tuple = ()) -> list[tuple]:
    import psycopg
    dsn = os.environ.get("DATABASE_URL_RO", "postgresql://farm_ro:farm-ro@localhost:5432/horizons")
    with psycopg.connect(dsn, connect_timeout=5, options="-c statement_timeout=10000") as conn, \
            conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _payload(figures: dict, en: str, ar: str, cite: str, *extra: dict) -> dict:
    primary = _cite(cite)
    return {"figures": figures, "template_en": en, "template_ar": ar,
            "citation": primary, "citations": [primary, *[c for c in extra if c != primary]]}


def _exceptions(cls: str) -> list[dict]:
    return [e for e in _json("recon.json")["exceptions"] if e["class"] == cls]


# ---- resolvers: the farm ------------------------------------------------------

def farm_overview(question: str = "") -> dict:
    units = _rows("SELECT unit_id, plant, location, grow_bed_m2, fish_count, fish_species "
                  "FROM telemetry.units ORDER BY unit_id")
    fish = sum(int(u[4]) for u in units)
    beds = sum(float(u[3]) for u in units)
    readings = _rows("SELECT count(*) FROM telemetry.readings")[0][0]
    species = units[0][5] if units else ""
    crops_en = _and_en([f"{u[0]} {u[1]}" for u in units])
    crops_ar = _and_ar([f"{u[0]} {PLANT_AR.get(u[1], u[1])}" for u in units])
    return _payload(
        {"units": _int(len(units)), "fish": _int(fish), "beds": f"{beds:.1f}", "readings": _int(readings)},
        f"The Farm runs {_int(len(units))} grow units — {crops_en} — with {_int(fish)} fish "
        f"({species}) under {beds:.1f} m² of grow beds. One controller reads every unit every 15 "
        f"minutes: {_int(readings)} readings so far (telemetry.readings).",
        f"تشغّل المزرعة {_int(len(units))} وحدات زراعة — {crops_ar} — فيها {_int(fish)} سمكة "
        f"(فرخ أوروبي) على {beds:.1f} م² من أحواض الزراعة. تقرأ وحدة تحكم واحدة كل وحدة كل 15 "
        f"دقيقة: {_int(readings)} قراءة حتى الآن (telemetry.readings).",
        "data_joins")


def _pump_incident() -> dict:
    return _exceptions("commanded_not_observed")[0]


def pump_failure(question: str = "") -> dict:
    e = _pump_incident()
    return _payload(
        {"commands": _int(e["commands"]), "response": f"{e['response_hours']:.1f}"},
        f"{e['unit_id']}'s water pump failed from {_day_en(e['first_command'])} to "
        f"{_day_en(e['last_command'])}: the controller commanded it {_int(e['commands'])} times and "
        f"the level never rose (controller.commands against telemetry.readings). Alert "
        f"{e['alert_no']} opened on {_day_en(e['alert_opened'])} at {_hm(e['alert_opened'])}; the "
        f"repair, {e['work_order_no']}, came {e['response_hours']:.1f} hours later.",
        f"تعطلت مضخة المياه في الوحدة {e['unit_id']} من {_day_ar(e['first_command'])} إلى "
        f"{_day_ar(e['last_command'])}: أمرتها وحدة التحكم {_int(e['commands'])} مرة ولم يرتفع "
        f"المستوى (controller.commands مقابل telemetry.readings). فُتح التنبيه {e['alert_no']} في "
        f"{_day_ar(e['alert_opened'])} الساعة {_hm(e['alert_opened'])}، وجاء أمر الإصلاح "
        f"{e['work_order_no']} بعد {e['response_hours']:.1f} ساعة.",
        "pump_command_check", _cite("pump_response"))


def pump_failure_loss(question: str = "") -> dict:
    e = _pump_incident()
    cur, cur_ar = _currency()
    plant = _meta()["farm"]["plants"][e["unit_id"]]
    return _payload(
        {"kg_lost": _kg(e["kg"]), "kg_actual": _kg(e["kg_actual"]),
         "kg_expected": _kg(e["kg_expected"]), "eur": _money(e["eur"]), "sop": "2",
         "response": f"{e['response_hours']:.1f}"},
        f"{e['unit_id']} lost {_kg(e['kg'])} kg of {plant} in the week after the pump failure: "
        f"harvest {e['harvest_no']} on {_day_en(e['harvest_date'])} came in at "
        f"{_kg(e['kg_actual'])} kg against its usual {_kg(e['kg_expected'])} kg (harvest.harvests), "
        f"{_money(e['eur'])} {cur} at the price list. The pump maintenance SOP says a water-pump "
        f"failure alert is answered on site within 2 hours; alert {e['alert_no']} "
        f"(controller.alerts) waited {e['response_hours']:.1f} hours for its work order.",
        f"خسرت الوحدة {e['unit_id']} {_kg(e['kg'])} كغ من {PLANT_AR.get(plant, plant)} في الأسبوع "
        "التالي لتعطل المضخة: "
        f"جاء الحصاد {e['harvest_no']} في {_day_ar(e['harvest_date'])} بوزن {_kg(e['kg_actual'])} كغ "
        f"مقابل {_kg(e['kg_expected'])} كغ في العادة (harvest.harvests)، أي {_money(e['eur'])} "
        f"{cur_ar} بسعر القائمة. تنص إجراءات صيانة المضخات على الاستجابة لتنبيه تعطل مضخة المياه في "
        f"الموقع خلال ساعتين؛ وقد انتظر التنبيه {e['alert_no']} (controller.alerts) "
        f"{e['response_hours']:.1f} ساعة حتى صدر أمر العمل.",
        "pump_response", _cite("pump_command_check"))


def open_alerts(question: str = "") -> dict:
    by_type = dict(_rows("SELECT type, count(*) FROM controller.alerts GROUP BY 1 ORDER BY 2 DESC"))
    still = _rows("SELECT count(*) FROM controller.alerts WHERE status = 'open'")[0][0]
    late = _json("patterns.json")["late_responses"]
    total = sum(by_type.values())
    kinds_en = _and_en([f"{n} {ALERT_EN.get(t, t.replace('_', ' '))}" for t, n in by_type.items()])
    kinds_ar = _and_ar([f"{n} من نوع `{t}`" for t, n in by_type.items()])
    late_en = (f" One was answered late: {late[0]['alert_no']} on {late[0]['unit_id']}, "
               f"{late[0]['response_hours']:.1f} hours to its work order against the SOP's 2."
               if late else " Every one was answered within the SOP's 2 hours.")
    late_ar = (f" وتأخرت الاستجابة لتنبيه واحد: {late[0]['alert_no']} على الوحدة {late[0]['unit_id']}، "
               f"{late[0]['response_hours']:.1f} ساعة حتى أمر العمل مقابل ساعتين في الإجراءات."
               if late else " وجرت الاستجابة لكل التنبيهات خلال الساعتين المحددتين.")
    return _payload(
        {"open": _int(still), "raised": _int(total), "late": _int(len(late))},
        f"{_int(still)} alerts are open now; {_int(total)} were raised this period — {kinds_en} "
        f"(controller.alerts).{late_en}",
        f"عدد التنبيهات المفتوحة الآن {_int(still)}؛ وقد صدر {_int(total)} تنبيهاً في هذه الفترة: "
        f"{kinds_ar} (controller.alerts).{late_ar}",
        "escalation_matrix", _cite("escalation_timing"))


def recon_exposure(question: str = "") -> dict:
    r = _json("recon.json")
    cur, cur_ar = _currency()
    order = sorted(r["exposure"], key=lambda k: -r["exposure"][k])
    figures = {k: _money(r["exposure"][k]) for k in order}
    figures |= {"total": _money(r["exposure_total"]), "kg": _kg(r["exposure_kg_total"])}
    parts_en = _and_en([f"{CLASS_EN[k]} {_money(r['exposure'][k])} {cur} ({r['counts'][k]})"
                        for k in order])
    parts_ar = _and_ar([f"{CLASS_AR[k]} {_money(r['exposure'][k])} {cur_ar} ({r['counts'][k]})"
                        for k in order])
    n = sum(r["counts"].values())
    return _payload(
        figures,
        f"{_money(r['exposure_total'])} {cur} and {_kg(r['exposure_kg_total'])} kg are at risk across "
        f"{n} reconciliation exceptions: {parts_en}. Ranked by money, not by count.",
        f"المعرّض للخطر {_money(r['exposure_total'])} {cur_ar} و{_kg(r['exposure_kg_total'])} كغ عبر "
        f"{n} استثناءات مطابقة: {parts_ar}. مرتبة حسب المال لا حسب العدد.",
        "figure_provenance")


def ghost_harvests(question: str = "") -> dict:
    loops = _json("patterns.json")["ghost_loops"]
    if not loops:
        return _payload({"count": "0"}, "Every harvest was shipped within 48 hours.",
                        "شُحن كل حصاد خلال 48 ساعة.", "harvest_shipment_match")
    lp = loops[0]
    exc = {e["ref"]: e for e in _exceptions("harvest_not_shipped")}
    eur = sum(exc[h["harvest_no"]]["eur"] for h in lp["harvests"] if h["harvest_no"] in exc)
    cur, cur_ar = _currency()
    nos = [h["harvest_no"] for h in lp["harvests"]]
    return _payload(
        {"count": _int(lp["count"]), "kg": _kg(lp["kg"]), "eur": _money(eur)},
        f"{_int(lp['count'])} harvests were never shipped — {_and_en(nos)}: {_kg(lp['kg'])} kg, "
        f"{_money(eur)} {cur} at the price list. All were logged by {lp['technician_code']} "
        f"({lp['name']}), none was countersigned, and all fall on days with no scheduled harvest "
        "(harvest.harvests against harvest.shipments). No other technician has an unshipped harvest.",
        f"{_int(lp['count'])} عمليات حصاد لم تُشحن أبداً — {_and_ar(nos)}: {_kg(lp['kg'])} كغ، أي "
        f"{_money(eur)} {cur_ar} بسعر القائمة. سجّلها كلها {lp['technician_code']} ولم يوقّع عليها "
        "أحد توقيعاً ثانياً، وكلها في أيام لا حصاد مجدولاً فيها (harvest.harvests مقابل "
        "harvest.shipments). لا يوجد لدى أي فني آخر حصاد غير مشحون.",
        "harvest_countersign", _cite("harvest_shipment_match"))


def unmetered_feed(question: str = "") -> dict:
    rows = _exceptions("consumed_not_purchased")
    cur, cur_ar = _currency()
    if not rows:
        return _payload({}, "Every item consumed is covered by a recorded purchase.",
                        "كل صنف مستهلك تغطيه عملية شراء مسجلة.", "stock_unmetered")
    e = rows[0]
    return _payload(
        {"qty": f"{e['qty']:g}", "eur": _money(e["eur"]), "days": _int(e["days"])},
        f"Yes: {e['unit_id']} was fed {e['qty']:g} kg of {e['item_code']} ({e['item']}) on "
        f"{_int(e['days'])} days from {_day_en(e['first'])} to {_day_en(e['last'])}, and no "
        f"purchase of {e['item_code']} exists (supplies.consumption against supplies.purchases) — "
        f"{_money(e['eur'])} {cur} at its list price. Unmetered consumption is investigated within "
        "2 working days and the stock count corrected.",
        f"نعم: أُطعمت الوحدة {e['unit_id']} {e['qty']:g} كغ من الصنف {e['item_code']} خلال "
        f"{_int(e['days'])} يوماً من {_day_ar(e['first'])} إلى {_day_ar(e['last'])}، ولا توجد أي "
        f"عملية شراء للصنف {e['item_code']} (supplies.consumption مقابل supplies.purchases) — أي "
        f"{_money(e['eur'])} {cur_ar} بسعر القائمة. يُحقق في الاستهلاك غير المقيس خلال يومي عمل "
        "ويُصحَّح جرد المخزون.",
        "stock_unmetered", _cite("feed_source"))


def feed_biosecurity(question: str = "") -> dict:
    return _payload(
        {},
        "Yes. Only feed from an approved supplier, through a recorded purchase, may enter a unit. "
        "Feed of unknown origin is a biosecurity incident: quarantine the bag, stop feeding it, and "
        "inform the owner.",
        "نعم. لا يدخل أي وحدة إلا علف من مورد معتمد وبعملية شراء مسجلة. العلف مجهول المصدر حادثة "
        "أمن حيوي: يُعزل الكيس ويُوقف استخدامه ويُبلَّغ المالك.",
        "feed_source", _cite("feed_change"))


def heatwave_aeration(question: str = "") -> dict:
    hw = _meta()["scenarios"]["heatwave"]
    drift = _json("drift.json")
    july = drift["windows"].get("2026-07", {})
    duty = july.get("duty", {}).get("AQ-03", {})
    days = duty.get("days_over_limit", [])
    temp = july.get("units", {}).get("AQ-03", {}).get("water_temp_c", {})
    return _payload(
        {"heat": f"{hw['duty_heatwave_pct']:.1f}%", "june": f"{hw['duty_june_pct']:.1f}%",
         "days": _int(len(days)), "outside": f"{temp.get('outside_cur_pct', 0):.1f}%"},
        f"During the heatwave ({_day_en(hw['start'])}–{_day_en(days[-1] if days else hw['end'])}) AQ-03's "
        f"air pump ran {hw['duty_heatwave_pct']:.1f}% of the day against {hw['duty_june_pct']:.1f}% "
        f"in June, above the SOP's 50% on {_int(len(days))} days (controller.commands). The tomato "
        f"tank's water left the perch band on {temp.get('outside_cur_pct', 0):.1f}% of July's readings.",
        f"خلال موجة الحر ({_day_ar(hw['start'])} – {_day_ar(days[-1] if days else hw['end'])}) عملت مضخة "
        f"الهواء في الوحدة AQ-03 بنسبة {hw['duty_heatwave_pct']:.1f}% من اليوم مقابل "
        f"{hw['duty_june_pct']:.1f}% في حزيران، فوق حد 50% في الإجراءات خلال {_int(len(days))} أيام "
        f"(controller.commands). وخرجت مياه حوض الطماطم عن نطاق سمك الفرخ في "
        f"{temp.get('outside_cur_pct', 0):.1f}% من قراءات تموز.",
        "aeration_duty", _cite("do_minimum"))


def ph_drift_cause(question: str = "") -> dict:
    drift = _json("drift.json")
    aug = drift["windows"].get("2026-08", {})
    c = aug.get("ph_cause", {}).get("AQ-04")
    lab = _meta()["scenarios"]["ph_probe_drift"]
    if not c:
        return _payload({}, "No unit's pH drifted in August.", "لم تنحرف حموضة أي وحدة في آب.",
                        "sensor_vs_chemistry")
    cal = c.get("calibration") or {}
    outside = aug["units"]["AQ-04"]["ph"]["outside_cur_pct"]
    return _payload(
        {"outside": f"{outside:.1f}%", "lab": f"{lab['lab_ph']:.2f}", "probe": f"{lab['probe_ph']:.2f}",
         "step": f"{cal.get('step', 0):+.2f}"},
        f"A sensor problem. AQ-04's pH reading left the 6.6–7.2 band on {outside:.1f}% of August's "
        f"readings, but the decline between weekly doses did not steepen and the unit needed no "
        f"extra dosing. Lab report {lab['lab_report_no']} measured pH {lab['lab_ph']:.2f} when the "
        f"probe read {lab['probe_ph']:.2f}; calibration {cal.get('work_order_no', '—')} on "
        f"{_day_en(cal.get('at', lab['calibrated']))} stepped the reading {cal.get('step', 0):+.2f} "
        "(telemetry.readings, maintenance.work_orders).",
        f"مشكلة في المجس. خرجت قراءة الحموضة في الوحدة AQ-04 عن النطاق 6.6–7.2 في {outside:.1f}% من "
        "قراءات آب، لكن الانخفاض بين الجرعات الأسبوعية لم يشتد ولم تحتج الوحدة جرعات إضافية. قاس "
        f"تقرير المختبر {lab['lab_report_no']} حموضة {lab['lab_ph']:.2f} حين كان المجس يقرأ "
        f"{lab['probe_ph']:.2f}؛ وأعادت المعايرة {cal.get('work_order_no', '—')} في "
        f"{_day_ar(cal.get('at', lab['calibrated']))} القراءة بمقدار {cal.get('step', 0):+.2f} "
        "(telemetry.readings، maintenance.work_orders).",
        "sensor_vs_chemistry", _cite("calibration_interval"))


def sensor_dropouts(question: str = "") -> dict:
    gaps = _json("patterns.json")["dropouts"]
    parts_en = _and_en([f"{g['unit_id']} on {_day_en(g['start'])} for {g['hours']:g} hours "
                        f"({_int(g['missing_readings'])} readings, followed by {g['work_order_no']})"
                        for g in gaps])
    parts_ar = _and_ar([f"{g['unit_id']} في {_day_ar(g['start'])} لمدة {g['hours']:g} ساعات "
                        f"({_int(g['missing_readings'])} قراءة، تلاه أمر العمل {g['work_order_no']})"
                        for g in gaps])
    return _payload(
        {"dropouts": _int(len(gaps)), "missing": _int(sum(g["missing_readings"] for g in gaps))},
        f"{_int(len(gaps))} sensor dropouts: {parts_en}. They are gaps, not zeros — the drift tests "
        "leave the missing readings out, so neither dropout raised a drift flag.",
        f"{_int(len(gaps))} انقطاعات في الحساسات: {parts_ar}. وهي فجوات لا أصفار — تستبعد اختبارات "
        "الانحراف القراءات المفقودة، فلم يرفع أي انقطاع منها إنذار انحراف.",
        "sensor_dropout")


def _month_in(question: str) -> int | None:
    q = question or ""
    for i, name in enumerate(EN_MONTHS, 1):
        if re.search(rf"\b{name}\b", q, re.I):
            return i
    for m, names in AR_MONTH_ALIASES.items():
        if any(n in q for n in names):
            return m
    return None


def harvest_and_sales(question: str = "") -> dict:
    month = _month_in(question)
    where_h = "WHERE extract(month FROM date) = %s" if month else ""
    params = (month,) if month else ()
    kg_h, n_h = _rows(f"SELECT coalesce(sum(kg), 0), count(*) FROM harvest.harvests {where_h}", params)[0]
    kg_s, eur, n_s = _rows(f"SELECT coalesce(sum(kg), 0), coalesce(sum(eur), 0), count(*) "
                           f"FROM harvest.shipments {where_h}", params)[0]
    cur, cur_ar = _currency()
    when_en = f"in {EN_MONTHS[month - 1]}" if month else "over the whole period"
    when_ar = f"في {AR_MONTHS[month - 1]}" if month else "خلال الفترة كلها"
    return _payload(
        {"kg_harvested": _kg(kg_h), "kg_shipped": _kg(kg_s), "eur": _money(eur),
         "harvests": _int(n_h), "shipments": _int(n_s)},
        f"{when_en[0].upper() + when_en[1:]} the Farm logged {_kg(kg_h)} kg in {_int(n_h)} harvests and shipped "
        f"{_kg(kg_s)} kg in {_int(n_s)} shipments for {_money(eur)} {cur} (harvest.harvests, "
        "harvest.shipments). The gap is trim loss plus any harvest that never shipped.",
        f"{when_ar} سجّلت المزرعة {_kg(kg_h)} كغ في {_int(n_h)} عملية حصاد، وشحنت {_kg(kg_s)} كغ في "
        f"{_int(n_s)} شحنة بقيمة {_money(eur)} {cur_ar} (harvest.harvests، harvest.shipments). الفرق "
        "فاقد التشذيب وأي حصاد لم يُشحن.",
        "price_list", _cite("harvest_shipment_match"))


def technician_workload(question: str = "") -> dict:
    rows = _rows("""SELECT t.technician_code, t.name, count(*) FILTER (WHERE w.closed_ts IS NOT NULL),
                           count(*)
                    FROM maintenance.work_orders w JOIN maintenance.technicians t USING (technician_id)
                    GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT 3""")
    total = _rows("SELECT count(*) FROM maintenance.work_orders")[0][0]
    top = rows[0]
    rest_en = _and_en([f"{r[0]} ({_int(r[2])})" for r in rows[1:]])
    rest_ar = _and_ar([f"{r[0]} ({_int(r[2])})" for r in rows[1:]])
    return _payload(
        {"top": _int(top[2]), "total": _int(total)},
        f"{top[0]} ({top[1]}) closed the most work orders: {_int(top[2])} of {_int(total)} "
        f"(maintenance.work_orders). Next: {rest_en}.",
        f"أغلق {top[0]} أكبر عدد من أوامر العمل: {_int(top[2])} من أصل {_int(total)} "
        f"(maintenance.work_orders). يليه: {rest_ar}.",
        "preventive_service")


def dosing_schedule(question: str = "") -> dict:
    events = _rows("SELECT count(*) FROM controller.commands WHERE action = 'dose_ph_up'")[0][0]
    units = _rows("SELECT count(DISTINCT unit_id) FROM controller.commands WHERE action = 'dose_ph_up'")[0][0]
    return _payload(
        {"events": _int(events), "per_unit": _int(events // max(units, 1))},
        "Every Monday at 08:00 the controller doses potassium hydroxide (pH up) into each unit, "
        "raising the pH by 0.3 and never above 7.1; nitrification lowers it slowly between doses, so "
        f"the weekly sawtooth is normal, not drift. {_int(events)} doses this period, "
        f"{_int(events // max(units, 1))} per unit (controller.commands).",
        "كل يوم اثنين الساعة 08:00 تضيف وحدة التحكم هيدروكسيد البوتاسيوم (رافع الحموضة) إلى كل "
        "وحدة، فترفع الحموضة 0.3 ولا تتجاوز بها 7.1؛ ويخفضها التأزت ببطء بين الجرعات، لذا فالنمط "
        f"الأسبوعي المسنّن طبيعي وليس انحرافاً. {_int(events)} جرعة في هذه الفترة، "
        f"{_int(events // max(units, 1))} لكل وحدة (controller.commands).",
        "ph_dosing")


def held_invoice(question: str = "") -> dict | None:
    d = _meta()["document_intake"]["held"]
    known = {d["invoice_no"], d["po_no"], d["supplier_ref"], d["invoice_supplier_ref"], d["item"]}
    if any(i not in known for i in identifiers(question)):
        return None                       # a different document: the free agent's question
    cur, cur_ar = _currency()
    agreed, billed = float(d["agreed_unit_price"]), float(d["invoice_unit_price"])
    over = billed / agreed - 1
    extra_eur = (billed - agreed) * float(d["qty"])
    return _payload(
        {"price": _money(billed), "agreed": _money(agreed), "over": f"{over:+.1%}",
         "extra": _money(extra_eur)},
        f"{d['invoice_no']} is held for two reasons. It bills {d['item']} at {_money(billed)} {cur}/kg "
        f"against the order's {_money(agreed)} ({over:+.1%}, beyond the 5% tolerance) — "
        f"{_money(extra_eur)} {cur} more on {float(d['qty']):g} kg. And it comes from "
        f"{d['invoice_supplier_ref']}, not {d['supplier_ref']} who took purchase order {d['po_no']}, "
        f"and {d['invoice_supplier_ref']} is not on the approved supplier list. Verify by the phone "
        "number on file before anything is paid.",
        f"الفاتورة {d['invoice_no']} موقوفة لسببين: تحتسب الصنف {d['item']} بسعر {_money(billed)} "
        f"{cur_ar}/كغ مقابل {_money(agreed)} في أمر الشراء ({over:+.1%}، أي خارج هامش 5%) — أي "
        f"{_money(extra_eur)} {cur_ar} زيادة على {float(d['qty']):g} كغ. وهي صادرة عن "
        f"{d['invoice_supplier_ref']} لا عن {d['supplier_ref']} الذي استلم أمر الشراء {d['po_no']}، "
        f"و{d['invoice_supplier_ref']} ليس على قائمة الموردين المعتمدين. يُتحقق بالاتصال على رقم الهاتف "
        "المسجل قبل دفع أي مبلغ.",
        "invoice_tolerance", _cite("supplier_master"))


EN_DECISION = {"approve": "approved", "escalate": "escalated to the owner", "reject": "rejected"}
AR_DECISION = {"approve": "اعتُمد", "escalate": "صُعِّد إلى المالك", "reject": "رُفض"}
_RULE = re.compile(r"([a-z0-9-]+\.md)\s*§\s*([\d.]+)")


def decision_on_finding(question: str = "") -> dict:
    from new_horizons.shared.audit.audit import decisions, events
    human = {k: v for k, v in decisions().items()
             if not str(v.get("approver", "")).startswith("pytest")}
    asked = identifiers(question)
    if asked:
        subject = next((k for k in human if any(a in k for a in asked)), None) or asked[0]
    elif human:
        subject = max(human, key=lambda k: human[k]["ts"])
    else:
        return _payload({}, "No human decision has been recorded in the audit log yet.",
                        "لم يُسجَّل أي قرار بشري في سجل التدقيق بعد.", "decision_record")
    d = human.get(subject)
    if d is None:
        return _payload({}, f"No decision is recorded for {subject} in the audit log yet.",
                        f"لا يوجد قرار مسجل بشأن {subject} في سجل التدقيق بعد.", "decision_record")
    ts = d["ts"] if isinstance(d["ts"], datetime) else datetime.fromisoformat(str(d["ts"]))
    ts = ts.astimezone(timezone.utc)
    n_events = len(events(limit=1000, contains=subject))
    rule = d.get("rule") or "—"
    m = _RULE.search(rule)
    extra = [{"source": m.group(1), "section": m.group(2)}] if m else []
    hhmm = ts.strftime("%H:%M")
    return _payload(
        {},
        f"{subject} was {EN_DECISION.get(d['decision'], d['decision'])} by `{d['approver']}` on "
        f"{_day_en(ts.date())} at {hhmm} UTC, under {rule}. The hash-chained audit log holds the "
        f"decision row with its hash and every model call, tool call and check that touched it "
        f"({n_events} events).",
        f"{subject}: {AR_DECISION.get(d['decision'], d['decision'])} من قِبل `{d['approver']}` "
        f"بتاريخ {_day_ar(ts.date())} الساعة {hhmm} (UTC)، بموجب {rule}. يحفظ سجل التدقيق المتسلسل "
        f"بالتجزئة صف القرار مع قيمة التجزئة وكل استدعاء للنموذج أو للأدوات وكل فحص يخصه "
        f"({n_events} حدثاً).",
        "decision_record", *extra)


RESOLVERS = {f.__name__: f for f in (
    farm_overview, pump_failure, pump_failure_loss, open_alerts, recon_exposure, ghost_harvests,
    unmetered_feed, feed_biosecurity, heatwave_aeration, ph_drift_cause, sensor_dropouts,
    harvest_and_sales, technician_workload, dosing_schedule, held_invoice, decision_on_finding)}


# ---- matching -------------------------------------------------------------------

# Arabic letters only (؟ and ، sit in the same Unicode block), with an attached و/ب/ف/ل
_AR_EDGE = r"(?<![\u0621-\u064A])(?:[وبفل])?{}(?![\u0621-\u064A])"
_QUARTERS = {"first": "1", "second": "2", "third": "3", "fourth": "4",
             "الأول": "1", "الثاني": "2", "الثالث": "3", "الرابع": "4"}
_PERIODS: list[tuple[re.Pattern, object]] = [
    (re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])"), lambda m: m.group()),
    (re.compile(r"(?i)(?<![a-z])q([1-4])(?![a-z0-9])"), lambda m: "q" + m.group(1)),
    (re.compile(r"(?i)\b(first|second|third|fourth) quarter\b"),
     lambda m: "q" + _QUARTERS[m.group(1).lower()]),
    (re.compile(r"الربع (الأول|الثاني|الثالث|الرابع)"), lambda m: "q" + _QUARTERS[m.group(1)]),
    (re.compile(r"(?i)\bthis year\b|هذا العام|هذه السنة|هالسنة|السنة الحالية|العام الحالي"),
     "this_year"),
    (re.compile(r"(?i)\blast year\b|العام الماضي|السنة الماضية"), "last_year"),
    (re.compile(r"(?i)\b(?:this|last|past|previous) (week|month|quarter)\b"),
     lambda m: "recent_" + m.group(1).lower()),
    (re.compile(r"الأسبوع الماضي|الاسبوع الماضي|هذا الأسبوع"), "recent_week"),
    (re.compile(r"الشهر الماضي|هذا الشهر|هالشهر"), "recent_month"),
    # not "May": "which supplier may we use?" names no month
    (re.compile(r"\b(?:January|February|March|April|June|July|August|September|October|"
                r"November|December)\b", re.I), "month"),
    (re.compile("|".join(_AR_EDGE.format(m) for m in (
        "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر",
        "أكتوبر", "نوفمبر", "ديسمبر", "كانون", "شباط", "آذار", "نيسان", "أيار", "حزيران",
        "تموز", "آب", "أيلول", "تشرين"))), "month"),
]


def periods(text: str) -> set[str]:
    """Canonical period mentions — a year, a quarter, a month, 'this week'.
    Identifiers are blanked first: WO-2026-0074 names a work order, not a year."""
    t = IDENT.sub(" ", text or "")
    out: set[str] = set()
    for pat, canon in _PERIODS:
        for m in pat.finditer(t):
            out.add(canon(m) if callable(canon) else canon)
    return out


# ---- aliases: "unit 3" → AQ-03 ------------------------------------------------------

_SOURCE = re.compile(r"^\w+\.\w+\.\w+$")


def _alias_rules(spec: dict, known: set[str]) -> list[tuple[re.Pattern, object]]:
    """The patterns for one `aliases:` entry and the substitution they share.
    A number becomes a code only when the code is in `known`."""
    prefix, width = spec["code"], int(spec.get("width", 3))
    num = rf"0*(?P<n>\d{{1,{width}}})(?!\d)"
    words = spec.get("words") or {}
    en = "|".join(re.escape(w) for w in words.get("en", []))
    ar = "|".join(re.escape(w) for w in words.get("ar", []))
    # a two-letter prefix is a code only in capitals ("aq 3" is not a unit)
    rules = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(prefix)}[ -]?{num}",
                        re.I if len(prefix) >= 3 else 0)]
    if en:
        rules.append(re.compile(rf"(?<![A-Za-z])(?P<word>(?:{en})(?:'s|s)?)\s*"
                                rf"(?:(?:no\.?|number|#)\s*)?{num}", re.I))
    if ar:   # optional و/ف/ب/ل and ال/لل in front: الوحدة، للوحدة، بالوحدة، ووحدة
        rules.append(re.compile(rf"(?<![؀-ۿ])(?P<word>(?:[وفب]?(?:ال|لل)|[وفبل])?"
                                rf"(?:{ar}))\s*(?:رقم\s*)?{num}"))

    def sub(m: re.Match) -> str:
        code = f"{prefix}-{int(m.group('n')):0{width}d}"
        if code not in known:
            return m.group(0)
        word = m.groupdict().get("word")
        return f"{word} {code}" if word else code

    return [(rule, sub) for rule in rules]


class Metrics:
    """intents.yaml + bge-m3 → match, nearest family, resolve."""

    periods = staticmethod(periods)

    def __init__(self, path: Path | str = INTENTS, embed=None, cache_dir: Path | str | None = CACHE):
        self.path = Path(path)
        spec = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.threshold = float(spec.get("threshold", 0.80))
        self.margin = float(spec.get("margin", 0.02))
        self.intents = {i["id"]: i for i in spec["intents"]}
        self._alias_spec = [a for a in spec.get("aliases") or [] if _SOURCE.match(a["source"])]
        self._aliases: list | None = None
        self._embed = embed
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._rows: list[tuple[str, str, object]] = []
        self._matrix = None
        texts = {iid: [p for group in ("paraphrases", "follow_ups")
                       for ps in (i.get(group) or {}).values() for p in ps]
                 for iid, i in self.intents.items()}
        self._periods = {iid: set().union(*map(periods, ts)) for iid, ts in texts.items()}
        self._idents = {iid: set().union(*map(identifiers, ts)) for iid, ts in texts.items()}

    # -- embeddings
    def _vectors(self, texts: list[str]):
        import numpy as np

        from new_horizons.shared.text.arabic import EASTERN_DIGITS, clean_arabic
        if self._embed is None:
            from new_horizons.shared.kb.store import embed_texts as embed
        else:
            embed = self._embed
        # Not the KB's index_normalize: bge-m3 knows correct spelling, and folding
        # ة→ه / أ→ا cost hits on the calibration set with no fewer false positives.
        m = np.asarray(embed([clean_arabic(t).translate(EASTERN_DIGITS) for t in texts]),
                       dtype="float32")
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    def _load(self) -> None:
        if self._matrix is not None:
            return
        import numpy as np
        self._rows = [(iid, p, None) for iid, i in self.intents.items()
                      for ps in i["paraphrases"].values() for p in ps]
        self._rows += [(iid, p, frozenset(i.get("after") or ())) for iid, i in self.intents.items()
                       for ps in (i.get("follow_ups") or {}).values() for p in ps]
        self._rows += [(iid, p, "not") for iid, i in self.intents.items()
                       for ps in (i.get("not") or {}).values() for p in ps]
        key = hashlib.sha256(self.path.read_bytes() + b"clean-v2"
                             + os.environ.get("EMBED_MODEL", "bge-m3").encode()).hexdigest()[:16]
        cache = (self._cache_dir / f"paraphrases-{key}.npy") if self._cache_dir and \
            self._embed is None else None
        if cache and cache.exists():
            self._matrix = np.load(cache)
            return
        self._matrix = self._vectors([p for _, p, _ in self._rows])
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(cache, self._matrix)

    def _eligible(self, iid: str, named: list[str]) -> bool:
        needs = self.intents[iid].get("requires") or []
        return all(any(re.match(rf"^(?:[A-Z]+-)?{re.escape(p)}-", i) for i in named) for p in needs)

    def _scores(self, question: str, previous: str | None):
        self._load()
        sims = self._matrix @ self._vectors([question])[0]
        named = identifiers(question)
        best: dict[str, tuple[float, str, bool]] = {}
        narrower: dict[str, tuple[float, str]] = {}
        for (iid, text, after), s in zip(self._rows, sims.tolist()):
            if not self._eligible(iid, named):
                continue
            if after == "not":
                if iid not in narrower or s > narrower[iid][0]:
                    narrower[iid] = (s, text)
                continue
            if after is not None and previous not in after:
                continue
            if iid not in best or s > best[iid][0]:
                best[iid] = (s, text, after is not None)
        ranked = sorted(((i, s, t, f) for i, (s, t, f) in best.items()), key=lambda x: -x[1])
        return ranked, narrower

    def ranked(self, question: str, previous: str | None = None) -> list[tuple[str, float, str, bool]]:
        """[(intent, best cosine, closest paraphrase, via a follow-up)], best first."""
        return self._scores(question, previous)[0]

    def match(self, question: str, guard: str | None = None, previous: str | None = None) -> dict:
        """{intent, score, second, family, matched, reason, paraphrase, follow_up}.
        `matched` only when the question is close, unambiguous, names no period the
        intent does not cover and no identifier it cannot answer. `guard` is the text
        the period and identifier checks read — the user's own words when `question`
        is a rewrite. `previous` is the intent that answered the last turn, which
        unlocks that intent's follow-ups."""
        guard = question if guard is None else guard
        ranked, narrower = self._scores(question, previous)
        (iid, score, para, follow_up) = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        intent = self.intents[iid]
        out = {"intent": iid, "score": round(score, 4), "second": round(second, 4),
               "runner_up": ranked[1][0] if len(ranked) > 1 else None,
               "family": intent.get("family", "data"), "paraphrase": para,
               "follow_up": follow_up, "matched": False, "reason": "ok"}
        if score < self.threshold:
            out["reason"] = "below threshold"
        elif score - second < self.margin:
            out["reason"] = f"ambiguous with {out['runner_up']}"
        elif iid in narrower and narrower[iid][0] >= score:
            out["reason"] = f"closer to a narrower question: {narrower[iid][1]}"
        elif not periods(guard) <= self._periods[iid]:
            out["reason"] = f"names a period the intent does not cover: {sorted(periods(guard))}"
        elif not intent.get("slots") and not set(identifiers(guard)) <= self._idents[iid]:
            out["reason"] = "names an identifier the intent does not answer"
        else:
            out["matched"] = True
        return out

    def canonical(self, text: str) -> str:
        """A record named by its number becomes its code, only when the code exists:
        "unit 3" → "unit AQ-03", "technician 6" → "technician TEC-06"."""
        if self._aliases is None:
            rules, complete = [], True
            for a in self._alias_spec:
                schema, table, column = a["source"].split(".")
                try:
                    known = {r[0] for r in _rows(
                        f'SELECT DISTINCT "{column}" FROM "{schema}"."{table}"')}
                except Exception:          # database down: no aliases, try again next time
                    known, complete = set(), False
                rules += _alias_rules(a, known)
            if not complete:
                return text
            self._aliases = rules
        for rule, sub in self._aliases:
            text = rule.sub(sub, text)
        return text

    def resolve(self, intent_id: str, question: str) -> dict | None:
        intent = self.intents[intent_id]
        payload = RESOLVERS[intent["resolver"]](question)
        if payload is None:
            return None
        return {**payload, "intent": intent_id, "screen": intent.get("screen"),
                "phrasing": intent.get("phrasing", "model")}


_DEFAULT: Metrics | None = None


def default() -> Metrics:
    """One matcher per process — the paraphrase matrix loads once."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Metrics()
    return _DEFAULT
