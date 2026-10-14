"""Synthetic aquaponics farm — five source systems, seeded, generic.

`make mock` drops + recreates the five schemas of shared/db/farm_schema.sql and
COPY-loads them. Scale, period, units, scenario dates and seed come from
app/profile.yaml; nothing here names a real farm, company or person.

The physics is data/_seed/gen_aquaponics.py's, unchanged: 15-minute readings,
diurnal air and water temperature, slow nitrification pulling pH down, the
Monday dosing correction, dissolved oxygen falling with water temperature,
evaporation and the refill pump, stress-driven weekly yields. Around it:

  telemetry    units · readings (15-min, 90 days; a sensor dropout is a gap)
  controller   commands (refill, aeration, dosing, feeding) · alerts
  maintenance  technicians · work_orders (routine schedule + one per alert)
  harvest      customers · harvests (weekly, Mondays) · shipments
  supplies     suppliers · items · purchases (orders) · consumption (daily)

Planted, exactly detectable scenarios (ground truth -> data/mock_meta.json, the
question set's figures -> ingest/validation/expected-results.json):
  1 pump failure AQ-03 12-18 Jul   commanded, never observed; an open alert answered
                                   days late; the next harvest collapses
  2 heatwave 26-30 Jul             AQ-03's air pump runs most of the day
  3 ghost harvests                 six harvests with no shipment, one technician
  4 unmetered feed                 AQ-02 eats a feed nobody bought (August)
  5 sensor dropouts                gaps, not zeros — drift must not flag them
  + AQ-04 pH probe drift (August, fixed by a calibration) and the benign weekly dosing
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from new_horizons.paths import APP, DATA, PACKAGE, ROOT

load_dotenv(ROOT / ".env")

PROFILE = yaml.safe_load((APP / "profile.yaml").read_text(encoding="utf-8"))
SCHEMA_SQL = PACKAGE / "shared" / "db" / "farm_schema.sql"
META_PATH = DATA / "mock_meta.json"
EXPECTED_PATH = APP / "ingest" / "validation" / "expected-results.json"

SEED = int(PROFILE["seed"])
CUR = PROFILE["market"]["currency"]
START = datetime.fromisoformat(str(PROFILE["period"]["start"]))
DAYS = int(PROFILE["period"]["days"])
END = START + timedelta(days=DAYS)
STEP = timedelta(minutes=15)
UNITS = [tuple(u) for u in PROFILE["units"]]           # unit, plant, location, m², base °C
SC, DI = PROFILE["scenarios"], PROFILE["document_intake"]
FISH_SPECIES = "European perch"


def T(x) -> datetime:
    return x if isinstance(x, datetime) else datetime.fromisoformat(str(x))


def D(x) -> date:
    return x if isinstance(x, date) and not isinstance(x, datetime) else date.fromisoformat(str(x)[:10])


PUMP = SC["pump_failure"]
PUMP_UNIT, PUMP_START, PUMP_END = PUMP["unit"], T(PUMP["start"]), T(PUMP["end"])
HEAT_START, HEAT_END = T(SC["heatwave"]["start"]), T(SC["heatwave"]["end"])
HEAT_C = float(SC["heatwave"]["outdoor_c"])
DROPOUTS = [(d["unit"], T(d["start"]), timedelta(hours=d["hours"])) for d in SC["sensor_dropouts"]]
DRIFT = SC["ph_probe_drift"]
DRIFT_UNIT, DRIFT_START, DRIFT_FIX = DRIFT["unit"], T(DRIFT["start"]), T(DRIFT["calibrated"])
DRIFT_MAX = float(DRIFT["max_offset"])
FEED_SWITCH = SC["unmetered_feed"]

# The Farm's operating rules (knowledge base: water-quality-sop, pump-maintenance-sop,
# feeding-schedule) — the controller and the alert thresholds follow them.
REFILL_BELOW, REFILL_CM, LOW_LEVEL = 21.0, 3.2, 18.0
AIR_ON, AIR_OFF = 6.5, 7.0
DOSE_PH, DOSE_CAP, DOSE_KG = 0.3, 7.1, 0.04
RATION_KG = 0.012                      # per fish per day, three feeds
FEED_TIMES = (7, 12, 17)
HEAT_DAY_C, HEAT_CUT = 23.0, 0.75
# type -> (value key, open when, threshold, closes when)
ALERTS = {
    "low_water_level": ("level", lambda v: v < 18.0, 18.0, lambda v: v >= 19.0),
    "low_dissolved_o2": ("do", lambda v: v < 6.0, 6.0, lambda v: v >= 6.2),
    "high_water_temp": ("wtemp", lambda v: v > 23.5, 23.5, lambda v: v <= 23.3),
    "high_air_temp": ("air", lambda v: v > 30.0, 30.0, lambda v: v <= 29.5),
    "low_ph": ("ph", lambda v: v < 6.4, 6.4, lambda v: v >= 6.5),
    "high_ph": ("ph", lambda v: v > 7.4, 7.4, lambda v: v <= 7.3),
}
YIELD_PER_M2_WEEK = {"pepper": 0.55, "lettuce": 0.9, "tomato": 0.7, "basil": 0.4}
PRICE = {k: float(v) for k, v in PROFILE["prices"].items()}            # per kg shipped
FEED_OF = {"AQ-01": "FEED-01", "AQ-02": "FEED-01", "AQ-03": "FEED-02", "AQ-04": "FEED-01"}
ITEMS = [  # code, name, category, unit, list price
    ("FEED-01", "Floating fish feed 3 mm", "feed", "kg", 2.40),
    ("FEED-02", "Floating fish feed 4.5 mm", "feed", "kg", 2.20),
    ("FEED-03", "Grower pellets 6 mm", "feed", "kg", 1.90),
    ("NUT-01", "Potassium hydroxide (pH up)", "nutrient", "kg", 6.50),
    ("NUT-02", "Chelated iron DTPA 11 %", "nutrient", "kg", 14.00),
    ("PART-01", "Water pump impeller", "part", "pcs", 38.00),
    ("PART-02", "Air stone 50 mm", "part", "pcs", 6.50),
    ("PART-03", "pH probe, double junction", "part", "pcs", 79.00),
    ("PART-04", "Filter sock 200 micron", "part", "pcs", 4.20),
]
PRICE_OF = {code: price for code, *_rest, price in ITEMS}
SUPPLIER_OF = {"FEED-01": "SUP-001", "FEED-02": "SUP-001", "NUT-01": "SUP-004",
               "NUT-02": "SUP-004", "PART-01": "SUP-002", "PART-02": "SUP-002",
               "PART-03": "SUP-005", "PART-04": "SUP-003"}
UNAPPROVED = {"SUP-007"}
HOME = {"TEC-01": ["AQ-01"], "TEC-02": ["AQ-02"], "TEC-03": ["AQ-03"], "TEC-04": ["AQ-04"],
        "TEC-05": ["AQ-01", "AQ-02"], "TEC-06": ["AQ-02", "AQ-04"], "TEC-07": ["AQ-03", "AQ-04"],
        "TEC-08": []}
DUTY = ["TEC-01", "TEC-02", "TEC-03", "TEC-04", "TEC-05", "TEC-07"]   # rotates day by day
SENIOR = "TEC-08"


def duty(t: datetime) -> str:
    return DUTY[t.toordinal() % len(DUTY)]


def in_dropout(unit: str, t: datetime) -> bool:
    return any(unit == u and s <= t < s + span for u, s, span in DROPOUTS)


def probe_offset(unit: str, t: datetime) -> float:
    """The AQ-04 pH probe reads high: a ramp from the drift start to the calibration."""
    if unit != DRIFT_UNIT or not DRIFT_START <= t < DRIFT_FIX:
        return 0.0
    return DRIFT_MAX * (t - DRIFT_START) / (DRIFT_FIX - DRIFT_START)


# ---- the simulation (the seed's physics, step for step) -------------------------

def simulate(rng: random.Random) -> dict:
    readings, commands, alerts = [], [], []
    state = {u[0]: {"ph": 6.8 + rng.uniform(-0.1, 0.1), "level": 24.0, "air_on": False,
                    "open": {}, "air_ticks": 0} for u in UNITS}
    daily_stress = {u[0]: [0.0] * DAYS for u in UNITS}
    air_ticks = {u[0]: [0] * DAYS for u in UNITS}         # 15-min ticks with the air pump on
    seen_ticks = {u[0]: [0] * DAYS for u in UNITS}
    wmax = {u[0]: [0.0] * DAYS for u in UNITS}            # daily max water temperature
    true_ph: dict[tuple[str, datetime], float] = {}
    feed_kg = defaultdict(float)                           # (unit, day) -> kg dispensed
    unobserved = 0
    t = START
    while t < END:
        day = (t - START).days
        hour = t.hour + t.minute / 60
        outdoor = HEAT_C if HEAT_START <= t < HEAT_END else 0.0
        for u, plant, loc, m2, base in UNITS:
            s = state[u]
            if in_dropout(u, t):
                continue                       # sensor offline → a gap; the controller is blind too
            loc_bias = 2.5 if loc == "rooftop" else 0.0
            air = base + loc_bias + outdoor + 4.5 * math.sin((hour - 9) / 24 * 2 * math.pi) + rng.gauss(0, 0.4)
            hum = 62 - 1.2 * (air - base) + rng.gauss(0, 2)
            wtemp = base - 1.0 + 1.2 * math.sin((hour - 12) / 24 * 2 * math.pi) + 0.6 * outdoor + rng.gauss(0, 0.15)
            wmax[u][day] = max(wmax[u][day], wtemp)
            # pH drifts down slowly (nitrification), corrected on Mondays
            s["ph"] += -0.0004 + rng.gauss(0, 0.002)
            if t.weekday() == 0 and t.hour == 8 and t.minute == 0:
                s["ph"] = min(s["ph"] + DOSE_PH, DOSE_CAP)
                commands.append([t, u, "dosing_pump", "dose_ph_up", 60, DOSE_KG, "weekly_dosing", "controller"])
            do = 7.6 - 0.38 * (wtemp - 20) + rng.gauss(0, 0.1)
            # water level: evaporation/drain + pump refill (a broken pump is still commanded)
            s["level"] = max(0.0, s["level"] - (0.06 + 0.02 * max(0, air - 24) / 4))
            pump_broken = u == PUMP_UNIT and PUMP_START <= t < PUMP_END
            if s["level"] < REFILL_BELOW:
                dur = int(rng.uniform(90, 150))
                commands.append([t, u, "water_pump", "on", dur, None, "low_level", "controller"])
                if pump_broken:
                    unobserved += 1
                else:
                    s["level"] += REFILL_CM
            # air pump duty cycle tied to DO
            if do < AIR_ON and not s["air_on"]:
                s["air_on"] = True
                commands.append([t, u, "air_pump", "on", 0, None, "low_do", "controller"])
            elif do >= AIR_OFF and s["air_on"]:
                s["air_on"] = False
                commands.append([t, u, "air_pump", "off", 0, None, "do_recovered", "controller"])
            air_ticks[u][day] += s["air_on"]
            seen_ticks[u][day] += 1
            # feeding: three feeds a day, a quarter less the day after the water passed 23 °C
            if t.minute == 0 and t.hour in FEED_TIMES:
                fish = int(m2 * 1.2)
                cut = HEAT_CUT if day and wmax[u][day - 1] > HEAT_DAY_C else 1.0
                kg = round(fish * RATION_KG / len(FEED_TIMES) * cut, 3)
                commands.append([t, u, "feeder", "feed", 20, kg, "feeding_schedule", "controller"])
                feed_kg[(u, day)] += kg
            measured_ph = s["ph"] + probe_offset(u, t)
            true_ph[(u, t)] = s["ph"]
            values = {"level": s["level"], "do": do, "wtemp": wtemp, "air": air, "ph": measured_ph}
            for typ, (key, opens, thr, closes) in ALERTS.items():
                v = round(values[key], 2)              # the controller compares what it displays
                if typ not in s["open"] and opens(v):
                    s["open"][typ] = {"unit_id": u, "type": typ, "value": round(v, 2),
                                      "threshold": thr, "opened_ts": t, "resolved_ts": None}
                elif typ in s["open"] and closes(v):
                    a = s["open"].pop(typ)
                    a["resolved_ts"] = t
                    alerts.append(a)
            stress = max(0, air - 30) + max(0, 6.3 - s["ph"]) * 3 + max(0, 19 - s["level"]) * 0.5
            daily_stress[u][day] += stress / 96
            readings.append([t, u, round(air, 2), round(hum, 1), round(wtemp, 2), round(measured_ph, 2),
                             round(do, 2), round(s["level"], 1)])
        t += STEP
    for s in state.values():
        alerts.extend(s["open"].values())
    alerts.sort(key=lambda a: (a["opened_ts"], a["unit_id"]))
    return {"readings": readings, "commands": commands, "alerts": alerts,
            "daily_stress": daily_stress, "air_ticks": air_ticks, "seen_ticks": seen_ticks,
            "wmax": wmax, "true_ph": true_ph, "feed_kg": feed_kg, "unobserved": unobserved}


# ---- people and companies ---------------------------------------------------------

def people(rng: random.Random) -> dict:
    from faker import Faker
    fake = Faker(PROFILE["market"]["faker_locale"])
    fake.seed_instance(SEED)
    techs = []
    for i in range(1, int(PROFILE["scale"]["technicians"]) + 1):
        code = f"TEC-{i:02d}"
        techs.append([i, code, fake.name(), "senior technician" if code == SENIOR else "technician",
                      date(2024, 1, 8) + timedelta(days=rng.randint(0, 600))])
    segments = ["restaurant", "grocer", "market"]
    customers = [[f"CUS-{i:02d}", fake.company(), segments[i % 3]]
                 for i in range(1, int(PROFILE["scale"]["customers"]) + 1)]
    suppliers = [[f"SUP-{i:03d}", fake.company(), f"SUP-{i:03d}" not in UNAPPROVED,
                  fake.numerify("+1-###-###-####")]
                 for i in range(1, int(PROFILE["scale"]["suppliers"]) + 1)]
    return {"technicians": techs, "customers": customers, "suppliers": suppliers}


# ---- maintenance ------------------------------------------------------------------

def work_orders(rng: random.Random, sim: dict, techs: list) -> tuple[list, dict]:
    tid = {code: i for i, code, *_ in techs}
    wos: list[dict] = []

    def add(opened: datetime, unit: str, tech: str, typ: str, minutes: int, outcome: str,
            alert_no=None, part=None, notes="", closed=None):
        wos.append({"opened_ts": opened, "unit_id": unit, "technician": tech, "type": typ,
                    "alert_no": alert_no, "closed_ts": closed or opened + timedelta(minutes=minutes),
                    "outcome": outcome, "part": part, "notes": notes})

    def home_tech(unit: str) -> str:
        owners = [c for c, units in HOME.items() if unit in units]
        return rng.choice(owners) if rng.random() < 0.8 else rng.choice([c for c in HOME if c != SENIOR])

    for d in range(DAYS):
        day = START + timedelta(days=d)
        for u, *_ in UNITS:
            if day.weekday() == 2:                                   # Wednesday filters
                add(day.replace(hour=9) + timedelta(minutes=rng.randint(0, 50)), u, home_tech(u),
                    "filter_clean", rng.randint(30, 50), "done", part="PART-04")
            if day.weekday() == 0:                                   # Monday dosing check
                add(day.replace(hour=9) + timedelta(minutes=rng.randint(0, 40)), u, duty(day),
                    "dosing_check", rng.randint(10, 20), "done")
            if day.weekday() == 1 and day.day <= 7:                  # first Tuesday: probes
                add(day.replace(hour=10) + timedelta(minutes=rng.randint(0, 60)), u, SENIOR,
                    "sensor_calibration", rng.randint(35, 55), "done")
            if day.weekday() == 3 and 8 <= day.day <= 14:            # second Thursday: pumps
                part = "PART-02" if day.month == 7 else None         # quarterly air stones
                add(day.replace(hour=13) + timedelta(minutes=rng.randint(0, 60)), u,
                    rng.choice(["TEC-03", "TEC-07"]), "pump_service", rng.randint(45, 80), "done",
                    part=part)
    # every alert gets a work order; the pump failure's comes days late
    alert_rows = []
    for n, a in enumerate(sim["alerts"], 1):
        no = f"AL-2026-{n:04d}"
        opened = a["opened_ts"]
        if a["type"] == "low_water_level" and a["unit_id"] == PUMP_UNIT and PUMP_START <= opened < PUMP_END:
            ack, by = T(PUMP["acknowledged"]), PUMP["by"]
            add(ack + timedelta(minutes=15), a["unit_id"], by, "pump_repair", 0, "part_replaced",
                alert_no=no, part="PART-01", closed=PUMP_END + timedelta(minutes=10),
                notes="water pump impeller seized; replaced")
        else:
            ack = opened + timedelta(minutes=rng.randint(3, 14))
            by = duty(opened)
            if a["type"] in ("low_ph", "high_ph"):
                typ, outcome, notes = "sensor_check", "no_fault_found", "dosing tank and pump checked; nothing found"
            else:
                typ, outcome, notes = "alert_response", "fixed", {
                    "low_dissolved_o2": "air stones cleaned; spare blower on",
                    "high_water_temp": "shade cloth drawn; top-up with cool water",
                    "high_air_temp": "vents opened; misting on",
                    "low_water_level": "float valve freed; level restored"}[a["type"]]
            resolved = a["resolved_ts"] or END
            add(ack + timedelta(minutes=rng.randint(5, 25)), a["unit_id"], by, typ, 0, outcome,
                alert_no=no, notes=notes,
                closed=min(resolved, ack + timedelta(minutes=rng.randint(60, 180))))
        alert_rows.append({**a, "alert_no": no, "acknowledged_ts": ack, "acknowledged_by": by})
    # the probe drift: found by a lab sample, fixed by an unscheduled calibration
    add(DRIFT_FIX, DRIFT_UNIT, SENIOR, "sensor_calibration", 40, "fixed",
        notes=f"pH probe read {probe_offset(DRIFT_UNIT, T(DI['lab']['sampled'])):.1f} high against "
              f"the lab sample; recalibrated (two-point)")
    # a dropout longer than 4 hours gets a sensor check
    for u, s, span in DROPOUTS:
        add(s + span + timedelta(minutes=rng.randint(10, 40)), u, duty(s + span), "sensor_check",
            rng.randint(30, 60), "fixed", notes="sensor hub restarted; loose connector reseated")
    wos.sort(key=lambda w: (w["opened_ts"], w["unit_id"]))
    rows = []
    for n, w in enumerate(wos, 1):
        w["work_order_no"] = f"WO-2026-{n:04d}"
        rows.append([n, w["work_order_no"], w["opened_ts"], w["unit_id"], tid[w["technician"]], w["type"],
                     w["alert_no"], w["closed_ts"], w["outcome"], w["part"], w["notes"]])
    return rows, {"wos": wos, "alerts": alert_rows}


# ---- harvest ----------------------------------------------------------------------

def harvests(rng: random.Random, sim: dict, customers: list) -> dict:
    rows, ships, genuine = [], [], []
    loggers = ["TEC-01", "TEC-02", "TEC-03", "TEC-04", "TEC-05", "TEC-06"]
    by_segment = defaultdict(list)
    for ref, _name, seg in customers:
        by_segment[seg].append(ref)
    buyer_segment = {"pepper": "restaurant", "lettuce": "grocer", "tomato": "market", "basil": "restaurant"}
    for u, plant, loc, m2, _base in UNITS:
        for wk in range(2, DAYS // 7 + 1):           # Mondays 15 Jun … 24 Aug
            d = (START + timedelta(days=wk * 7)).date()
            stress = sum(sim["daily_stress"][u][wk * 7 - 7: wk * 7])
            kg = m2 * YIELD_PER_M2_WEEK[plant] * max(0.35, 1 - 0.08 * stress) * rng.uniform(0.92, 1.08)
            note = ("reduced — pump outage" if u == PUMP_UNIT and PUMP_START.date() <= d
                    <= PUMP_END.date() + timedelta(days=7) else "")
            logger = loggers[(wk + int(u[-1])) % len(loggers)]
            signer = SENIOR if rng.random() < 0.75 else "TEC-07"
            genuine.append({"date": d, "unit_id": u, "plant": plant, "kg": round(kg, 2),
                            "logged_by": logger, "countersigned_by": signer, "notes": note})
    ghost = SC["ghost_harvests"]
    plants = {u: p for u, p, *_ in UNITS}
    beds = {u: m2 for u, _p, _l, m2, _b in UNITS}
    ghosts = []
    for i, d in enumerate(ghost["dates"]):
        u = ghost["units"][i % len(ghost["units"])]
        kg = beds[u] * YIELD_PER_M2_WEEK[plants[u]] * rng.uniform(0.35, 0.5)
        ghosts.append({"date": D(d), "unit_id": u, "plant": plants[u], "kg": round(kg, 2),
                       "logged_by": ghost["technician"], "countersigned_by": None, "notes": ""})
    allh = sorted(genuine + ghosts, key=lambda h: (h["date"], h["unit_id"]))
    for n, h in enumerate(allh, 1):
        h["harvest_no"] = f"HV-2026-{n:04d}"
        rows.append([n, h["harvest_no"], h["date"], h["unit_id"], h["plant"], h["kg"], h["logged_by"],
                     h["countersigned_by"], h["notes"]])
    for h in sorted(genuine, key=lambda h: (h["date"], h["unit_id"])):
        kg = round(h["kg"] * rng.uniform(0.965, 0.995), 2)
        cust = rng.choice(by_segment[buyer_segment[h["plant"]]])
        eur = round(kg * PRICE[h["plant"]] * rng.uniform(0.95, 1.0), 2)
        ships.append([h["date"] + timedelta(days=rng.choice([0, 0, 1])), h["unit_id"], h["harvest_no"],
                      kg, cust, eur])
    ships.sort(key=lambda s: (s[0], s[1]))
    ship_rows = [[n, f"SHP-2026-{n:04d}", *s] for n, s in enumerate(ships, 1)]
    return {"rows": rows, "shipments": ship_rows, "genuine": genuine, "ghosts": ghosts}


# ---- supplies ---------------------------------------------------------------------

def supplies(rng: random.Random, sim: dict, wo_rows: list) -> dict:
    switch_unit, switch_item = FEED_SWITCH["unit"], FEED_SWITCH["item"]
    switch_day = (T(FEED_SWITCH["start"]) - START).days
    consumption = []                      # date, unit, item, qty, source
    for (u, day), kg in sorted(sim["feed_kg"].items()):
        item = switch_item if u == switch_unit and day >= switch_day else FEED_OF[u]
        consumption.append([(START + timedelta(days=day)).date(), u, item, round(kg, 3), "feeder"])
    for c in sim["commands"]:
        if c[3] == "dose_ph_up":
            consumption.append([c[0].date(), c[1], "NUT-01", DOSE_KG, "dosing"])
    for w in wo_rows:
        if w[9]:
            qty = 4 if w[9] == "PART-02" else 1
            consumption.append([w[2].date(), w[3], w[9], qty, "work_order"])
    consumption.sort(key=lambda c: (c[0], c[1], c[2]))

    # orders: what the week ahead needs, bought on Monday and received the same day;
    # the unmetered feed is never ordered
    need = defaultdict(float)               # (item, week) -> qty
    for d, _u, item, qty, _src in consumption:
        need[(item, (d - START.date()).days // 7)] += float(qty)
    orders = []                             # ordered, received, supplier, item, qty, unit price
    for (item, wk), qty in sorted(need.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if item == switch_item:
            continue
        monday = START.date() + timedelta(days=wk * 7)
        cat = next(c for code, _n, c, *_r in ITEMS if code == item)
        if cat == "feed":
            q = math.ceil((qty * 1.1) / 5) * 5                     # 5 kg bags, 10 % buffer
        elif item == "NUT-01":
            if wk % 4:
                continue                                           # monthly
            q = 1.0
        elif item == "PART-04":
            if wk % 4:
                continue
            q = 20
        else:
            q = qty
        when = monday - timedelta(days=3) if item in ("PART-01",) else monday
        if item == "PART-01":                                      # the repair part, bought on the day
            when = T(PUMP["acknowledged"]).date()
        price = round(PRICE_OF[item] * rng.uniform(0.98, 1.02), 2)
        orders.append([when, when, SUPPLIER_OF[item], item, q, price])
    # the two orders the sample invoices are printed against (awaiting their invoice)
    planted = {}
    for key in ("clean", "held"):
        p = DI[key]
        o = [D(p["ordered"]), D(p["ordered"]) + timedelta(days=1), p["supplier_ref"], p["item"],
             float(p["qty"]), PRICE_OF[p["item"]]]
        orders.append(o)
        planted[p["po_no"]] = o
    orders.sort(key=lambda o: (o[0], o[3]))
    fixed = {p: o for p, o in planted.items()}
    used = {int(p.rsplit("-", 1)[1]) for p in fixed}
    numbers = (n for n in range(1, 10_000) if n not in used)
    invoice_pool = [n for n in range(101, 400) if n not in (397, 418)]
    rng.shuffle(invoice_pool)
    rows = []
    for o in orders:
        po = next((p for p, f in fixed.items() if f is o), None) or f"PO-2026-{next(numbers):04d}"
        planted_order = po in fixed
        eur = round(o[4] * o[5], 2)
        invoice = None if planted_order else f"INV-2026-{invoice_pool.pop():04d}"
        rows.append([po, *o, eur, invoice, "awaiting_invoice" if planted_order else "invoiced"])
    rows.sort(key=lambda r: r[0])
    purchase_rows = [[n, *r] for n, r in enumerate(rows, 1)]
    cons_rows = [[n, *c] for n, c in enumerate(consumption, 1)]
    return {"purchases": purchase_rows, "consumption": cons_rows}


# ---- ground truth -----------------------------------------------------------------

def _plain(v):
    """A profile value as JSON: dates as ISO text, numbers and mappings as they are."""
    return v if isinstance(v, (int, float, dict, list)) and not isinstance(v, bool) else str(v)


def truth(sim: dict, people_: dict, maint: dict, harv: dict, sup: dict, wo_rows: list) -> dict:
    names = {code: name for _i, code, name, *_ in people_["technicians"]}
    plants = {u: p for u, p, *_ in UNITS}
    # 1 pump failure
    pump_alert = next(a for a in maint["alerts"] if a["unit_id"] == PUMP_UNIT
                      and a["type"] == "low_water_level" and PUMP_START <= a["opened_ts"] < PUMP_END)
    pump_wo = next(w for w in maint["wos"] if w["alert_no"] == pump_alert["alert_no"])
    weeks = [h for h in harv["genuine"] if h["unit_id"] == PUMP_UNIT]
    after = next(h for h in weeks if h["date"] > PUMP_END.date())
    normal = [h["kg"] for h in weeks if h is not after]
    expected = round(statistics.mean(normal), 2)
    lost = round(expected - after["kg"], 2)
    # 2 heatwave: AQ-03's air-pump duty
    heat_days = list(range((HEAT_START - START).days, (HEAT_END - START).days))
    duty_of = lambda u, d: sim["air_ticks"][u][d] / sim["seen_ticks"][u][d] if sim["seen_ticks"][u][d] else 0.0  # noqa: E731
    june = range(0, 30)
    heat = {u: round(100 * statistics.mean(duty_of(u, d) for d in heat_days), 1) for u, *_ in UNITS}
    base = {u: round(100 * statistics.mean(duty_of(u, d) for d in june), 1) for u, *_ in UNITS}
    over50 = {u: [str((START + timedelta(days=d)).date()) for d in range(DAYS) if duty_of(u, d) > 0.5]
              for u, *_ in UNITS}
    # 3 ghost harvests
    ghosts = harv["ghosts"]
    ghost_kg = round(sum(h["kg"] for h in ghosts), 2)
    ghost_eur = round(sum(h["kg"] * PRICE[h["plant"]] for h in ghosts), 2)
    # 4 unmetered feed
    item = FEED_SWITCH["item"]
    feed_rows = [c for c in sup["consumption"] if c[3] == item]
    feed_qty = round(sum(float(c[4]) for c in feed_rows), 3)
    # 5 dropouts
    expected_ticks = DAYS * 96
    drop = []
    for u, s, span in DROPOUTS:
        missing = int(span / STEP)
        drop.append({"unit_id": u, "start": s.isoformat(timespec="minutes"),
                     "end": (s + span).isoformat(timespec="minutes"),
                     "hours": span.total_seconds() / 3600, "missing_readings": missing})
    # + probe drift (lab sample vs probe)
    lab = DI["lab"]
    sampled = T(lab["sampled"])
    lab_true = round(sim["true_ph"][(lab["unit"], sampled)], 2)
    lab_probe = round(lab_true + probe_offset(lab["unit"], sampled), 2)
    # alerts, harvest & sales, work orders, recon
    alerts = maint["alerts"]
    open_alerts = [a for a in alerts if a["resolved_ts"] is None]
    by_type = defaultdict(int)
    for a in alerts:
        by_type[a["type"]] += 1
    aug = [h for h in harv["genuine"] + harv["ghosts"] if h["date"].month == 8]
    aug_ship = [s for s in harv["shipments"] if s[2].month == 8]
    wos_by_tech = defaultdict(lambda: {"closed": 0, "no_fault_found": 0})
    for w in maint["wos"]:
        wos_by_tech[w["technician"]]["closed"] += w["closed_ts"] is not None
        wos_by_tech[w["technician"]]["no_fault_found"] += w["outcome"] == "no_fault_found"
    top = max(wos_by_tech, key=lambda c: (wos_by_tech[c]["closed"], c))
    pump_eur = round(lost * PRICE[plants[PUMP_UNIT]], 2)
    feed_eur = round(feed_qty * PRICE_OF[item], 2)
    readings = len(sim["readings"])
    counts = {
        "telemetry.units": len(UNITS), "telemetry.readings": readings,
        "controller.commands": len(sim["commands"]), "controller.alerts": len(alerts),
        "maintenance.technicians": len(people_["technicians"]), "maintenance.work_orders": len(wo_rows),
        "harvest.customers": len(people_["customers"]), "harvest.harvests": len(harv["rows"]),
        "harvest.shipments": len(harv["shipments"]), "supplies.suppliers": len(people_["suppliers"]),
        "supplies.items": len(ITEMS), "supplies.purchases": len(sup["purchases"]),
        "supplies.consumption": len(sup["consumption"]),
    }
    held = DI["held"]
    clean_po = next(p for p in sup["purchases"] if p[1] == DI["clean"]["po_no"])
    held_po = next(p for p in sup["purchases"] if p[1] == held["po_no"])
    return {
        "seed": SEED, "currency": CUR, "period": [str(START.date()), str((END - timedelta(days=1)).date())],
        "counts": counts, "rows_total": sum(counts.values()),
        "farm": {"units": len(UNITS), "fish": sum(int(m2 * 1.2) for _u, _p, _l, m2, _b in UNITS),
                 "fish_species": FISH_SPECIES,
                 "grow_bed_m2": round(sum(m2 for _u, _p, _l, m2, _b in UNITS), 1),
                 "plants": {u: p for u, p, *_ in UNITS}},
        "readings": {"rows": readings, "expected": expected_ticks * len(UNITS),
                     "uptime_pct": round(100 * readings / (expected_ticks * len(UNITS)), 2)},
        "scenarios": {
            "pump_failure": {
                "unit_id": PUMP_UNIT, "start": PUMP_START.isoformat(timespec="minutes"),
                "end": PUMP_END.isoformat(timespec="minutes"),
                "commands_unobserved": sim["unobserved"], "alert_no": pump_alert["alert_no"],
                "alert_opened": pump_alert["opened_ts"].isoformat(timespec="minutes"),
                "acknowledged": pump_alert["acknowledged_ts"].isoformat(timespec="minutes"),
                "acknowledged_by": pump_alert["acknowledged_by"],
                "work_order_no": pump_wo["work_order_no"],
                "work_order_opened": pump_wo["opened_ts"].isoformat(timespec="minutes"),
                "response_hours": round((pump_wo["opened_ts"] - pump_alert["opened_ts"]).total_seconds() / 3600, 1),
                "sop_hours": 2, "harvest_no": next(r[1] for r in harv["rows"]
                                                   if r[3] == PUMP_UNIT and r[2] == after["date"]),
                "harvest_date": str(after["date"]), "kg_actual": after["kg"], "kg_expected": expected,
                "kg_lost": lost, "eur_lost": pump_eur, "price_per_kg": PRICE[plants[PUMP_UNIT]]},
            "heatwave": {"unit_id": PUMP_UNIT, "start": HEAT_START.isoformat(timespec="minutes"),
                         "end": HEAT_END.isoformat(timespec="minutes"),
                         "duty_heatwave_pct": heat[PUMP_UNIT], "duty_june_pct": base[PUMP_UNIT],
                         "duty_heatwave_by_unit": heat, "duty_june_by_unit": base,
                         "days_over_50": over50},
            "ghost_harvests": {"technician_code": SC["ghost_harvests"]["technician"],
                               "technician": names[SC["ghost_harvests"]["technician"]],
                               "harvest_nos": [next(r[1] for r in harv["rows"] if r[2] == h["date"]
                                                    and r[3] == h["unit_id"] and r[8] == "" and r[7] is None)
                                               for h in ghosts],
                               "count": len(ghosts), "kg": ghost_kg, "eur": ghost_eur},
            "unmetered_feed": {"unit_id": FEED_SWITCH["unit"], "item_code": item,
                               "first": str(feed_rows[0][1]), "last": str(feed_rows[-1][1]),
                               "days": len(feed_rows), "qty_kg": feed_qty, "eur": feed_eur,
                               "list_price": PRICE_OF[item]},
            "sensor_dropouts": drop,
            "ph_probe_drift": {"unit_id": DRIFT_UNIT, "start": DRIFT_START.isoformat(timespec="minutes"),
                               "calibrated": DRIFT_FIX.isoformat(timespec="minutes"),
                               "max_offset": DRIFT_MAX,
                               "lab_report_no": lab["report_no"], "lab_sampled": lab["sampled"],
                               "lab_ph": lab_true, "probe_ph": lab_probe},
            "weekly_dosing": {"events": sum(1 for c in sim["commands"] if c[3] == "dose_ph_up"),
                              "per_unit": sum(1 for c in sim["commands"] if c[3] == "dose_ph_up") // len(UNITS),
                              "ph_step": DOSE_PH, "cap": DOSE_CAP},
        },
        "alerts": {"raised": len(alerts), "open": len(open_alerts), "by_type": dict(sorted(by_type.items()))},
        "harvest_august": {"kg_harvested": round(sum(h["kg"] for h in aug), 2),
                           "kg_shipped": round(sum(float(s[5]) for s in aug_ship), 2),
                           "eur": round(sum(float(s[7]) for s in aug_ship), 2),
                           "shipments": len(aug_ship)},
        "work_orders": {"total": len(maint["wos"]),
                        "top_technician": top, "top_technician_name": names[top],
                        "top_closed": wos_by_tech[top]["closed"],
                        "no_fault_found": sum(v["no_fault_found"] for v in wos_by_tech.values())},
        "recon": {"eur": {"commanded_not_observed": pump_eur, "harvest_not_shipped": ghost_eur,
                          "consumed_not_purchased": feed_eur},
                  "kg": {"commanded_not_observed": lost, "harvest_not_shipped": ghost_kg,
                         "consumed_not_purchased": feed_qty},
                  "eur_total": round(pump_eur + ghost_eur + feed_eur, 2)},
        "document_intake": {
            "held": {**{k: _plain(v) for k, v in held.items()}, "agreed_unit_price": float(held_po[7]),
                     "received": str(held_po[3]), "qty": float(held_po[6]),
                     "invoice_total": round(float(held["qty"]) * float(held["invoice_unit_price"]), 2),
                     "po_total": float(held_po[8])},
            "clean": {**{k: _plain(v) for k, v in DI["clean"].items()}, "unit_price": float(clean_po[7]),
                      "received": str(clean_po[3]), "qty": float(clean_po[6]), "po_total": float(clean_po[8])},
            "lab": {**{k: _plain(v) for k, v in lab.items()}, "lab_ph": lab_true, "probe_ph": lab_probe},
        },
    }


# ---- load ---------------------------------------------------------------------------

def load_pg(tables: dict) -> None:
    import psycopg
    dsn = os.environ.get("DATABASE_URL", "postgresql://horizons:horizons@localhost:5432/horizons")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
            for table, (cols, rows) in tables.items():
                with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
                    for r in rows:
                        cp.write_row(r)
                print(f"  {table}: {len(rows):,} rows")
        conn.commit()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("ANALYZE")


def build() -> dict:
    t0 = time.time()
    rng = random.Random(SEED)
    sim = simulate(rng)
    ppl = people(random.Random(SEED + 1))
    wo_rows, maint = work_orders(random.Random(SEED + 2), sim, ppl["technicians"])
    harv = harvests(random.Random(SEED + 3), sim, ppl["customers"])
    sup = supplies(random.Random(SEED + 4), sim, wo_rows)
    alert_rows = [[n, a["alert_no"], a["unit_id"], a["type"], a["value"], a["threshold"], a["opened_ts"],
                   a["acknowledged_ts"], a["acknowledged_by"], a["resolved_ts"],
                   "open" if a["resolved_ts"] is None else "resolved"]
                  for n, a in enumerate(maint["alerts"], 1)]
    units = [[u, p, loc, m2, FISH_SPECIES, int(m2 * 1.2), date(2025, 3, 1)] for u, p, loc, m2, _b in UNITS]
    readings = [[n, *r] for n, r in enumerate(sim["readings"], 1)]
    commands = [[n, *c] for n, c in enumerate(sorted(sim["commands"], key=lambda c: (c[0], c[1], c[2])), 1)]
    tables = {
        "telemetry.units": (["unit_id", "plant", "location", "grow_bed_m2", "fish_species", "fish_count",
                             "commissioned"], units),
        "telemetry.readings": (["reading_id", "ts", "unit_id", "air_temp_c", "humidity_pct", "water_temp_c",
                                "ph", "dissolved_o2_mg_l", "water_level_cm"], readings),
        "controller.commands": (["command_id", "ts", "unit_id", "actuator", "action", "duration_s", "qty",
                                 "trigger", "issued_by"], commands),
        "controller.alerts": (["alert_id", "alert_no", "unit_id", "type", "value", "threshold", "opened_ts",
                               "acknowledged_ts", "acknowledged_by", "resolved_ts", "status"], alert_rows),
        "maintenance.technicians": (["technician_id", "technician_code", "name", "role", "started"],
                                    ppl["technicians"]),
        "maintenance.work_orders": (["work_order_id", "work_order_no", "opened_ts", "unit_id", "technician_id",
                                     "type", "alert_no", "closed_ts", "outcome", "part_item_code", "notes"],
                                    wo_rows),
        "harvest.customers": (["customer_ref", "name", "segment"], ppl["customers"]),
        "harvest.harvests": (["harvest_id", "harvest_no", "date", "unit_id", "plant", "kg", "logged_by",
                              "countersigned_by", "notes"], harv["rows"]),
        "harvest.shipments": (["shipment_id", "shipment_ref", "date", "unit_id", "harvest_no", "kg",
                               "customer_ref", "eur"], harv["shipments"]),
        "supplies.suppliers": (["supplier_ref", "name", "approved", "phone"], ppl["suppliers"]),
        "supplies.items": (["item_code", "name", "category", "unit", "list_price_eur"], [list(i) for i in ITEMS]),
        "supplies.purchases": (["purchase_id", "po_no", "ordered", "received", "supplier_ref", "item_code",
                                "qty", "unit_price_eur", "eur", "invoice_no", "status"], sup["purchases"]),
        "supplies.consumption": (["consumption_id", "date", "unit_id", "item_code", "qty", "source"],
                                 sup["consumption"]),
    }
    meta = truth(sim, ppl, maint, harv, sup, wo_rows)
    meta["generated_s"] = round(time.time() - t0, 1)
    return {"tables": tables, "meta": meta}


def expected_results(meta: dict) -> dict:
    """The figures the question set and tests/test_validation.py pin — written by the
    generator from its own ground truth, never typed by hand."""
    sc = meta["scenarios"]
    return {
        "_note": "GENERATED by `make mock` (app/mock/generate.py) — do not edit by hand.",
        "seed": meta["seed"], "currency": meta["currency"], "period": meta["period"],
        "farm": meta["farm"], "readings": meta["readings"], "alerts": meta["alerts"],
        "pump_failure": sc["pump_failure"], "heatwave": {k: v for k, v in sc["heatwave"].items()
                                                         if k not in ("duty_heatwave_by_unit", "duty_june_by_unit")},
        "ghost_harvests": sc["ghost_harvests"], "unmetered_feed": sc["unmetered_feed"],
        "sensor_dropouts": sc["sensor_dropouts"], "ph_probe_drift": sc["ph_probe_drift"],
        "weekly_dosing": sc["weekly_dosing"], "harvest_august": meta["harvest_august"],
        "work_orders": meta["work_orders"], "recon": meta["recon"],
        "document_intake": meta["document_intake"],
    }


def main() -> None:
    t0 = time.time()
    data = build()
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(data["meta"], ensure_ascii=False, indent=2, default=str))
    EXPECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPECTED_PATH.write_text(json.dumps(expected_results(data["meta"]), ensure_ascii=False, indent=2,
                                        default=str) + "\n")
    load_pg(data["tables"])
    m = data["meta"]
    print(f"mock data loaded in {time.time() - t0:.1f}s (seed={SEED}, {m['rows_total']:,} rows); "
          f"ground truth -> {META_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
