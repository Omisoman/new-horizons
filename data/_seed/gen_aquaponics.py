#!/usr/bin/env python3
"""Synthetic aquaponics farm telemetry — deterministic, dependency-free (stdlib only).

Usage: python gen_aquaponics.py [out_dir]
Produces units.csv, readings.csv, pump_events.csv, harvests.csv, alerts.csv
"""
import csv, math, random, sys, os
from datetime import datetime, timedelta

random.seed(2019)
OUT = sys.argv[1] if len(sys.argv) > 1 else "data"
os.makedirs(OUT, exist_ok=True)

START = datetime(2026, 6, 1)
DAYS = 90
STEP = timedelta(minutes=15)

UNITS = [
    ("AQ-01", "pepper", "greenhouse-A", 29.0, 21.0),
    ("AQ-02", "lettuce", "greenhouse-A", 18.0, 19.5),
    ("AQ-03", "tomato", "greenhouse-B", 24.0, 22.5),
    ("AQ-04", "basil", "rooftop", 12.0, 20.0),
]
# scripted incidents
PUMP_FAIL = ("AQ-03", START + timedelta(days=41), START + timedelta(days=47))   # water pump stuck off
DROPOUTS = [("AQ-02", START + timedelta(days=12, hours=3), timedelta(hours=9)),
            ("AQ-04", START + timedelta(days=66, hours=14), timedelta(hours=5))]
HEATWAVE = (START + timedelta(days=55), START + timedelta(days=60))

with open(f"{OUT}/units.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["unit_id", "plant", "location", "grow_bed_m2", "fish_count"])
    for u, plant, loc, m2, _ in UNITS:
        w.writerow([u, plant, loc, m2, int(m2 * 1.2)])

readings = open(f"{OUT}/readings.csv", "w", newline=""); rw = csv.writer(readings)
rw.writerow(["ts", "unit_id", "air_temp_c", "humidity_pct", "water_temp_c", "ph", "dissolved_o2_mg_l", "water_level_cm"])
pumps = open(f"{OUT}/pump_events.csv", "w", newline=""); pw = csv.writer(pumps)
pw.writerow(["ts", "unit_id", "pump", "action", "duration_s", "trigger"])
alerts = open(f"{OUT}/alerts.csv", "w", newline=""); aw = csv.writer(alerts)
aw.writerow(["ts", "unit_id", "type", "value", "threshold", "resolved_ts"])

state = {u[0]: {"ph": 6.8 + random.uniform(-0.1, 0.1), "level": 24.0, "air_on": False, "open_alert": {}} for u in UNITS}
daily_stress = {u[0]: [0.0] * DAYS for u in UNITS}

t = START
n = int(DAYS * 24 * 4)
for i in range(n):
    day = (t - START).days
    hour = t.hour + t.minute / 60
    outdoor = 2.0 if HEATWAVE[0] <= t < HEATWAVE[1] else 0.0
    for u, plant, loc, m2, base_temp in UNITS:
        s = state[u]
        if any(u == d[0] and d[1] <= t < d[1] + d[2] for d in DROPOUTS):
            continue  # sensor offline → gap in data
        loc_bias = 2.5 if loc == "rooftop" else 0.0
        air = base_temp + loc_bias + outdoor + 4.5 * math.sin((hour - 9) / 24 * 2 * math.pi) + random.gauss(0, 0.4)
        hum = 62 - 1.2 * (air - base_temp) + random.gauss(0, 2)
        wtemp = base_temp - 1.0 + 1.2 * math.sin((hour - 12) / 24 * 2 * math.pi) + 0.6 * outdoor + random.gauss(0, 0.15)
        # pH drifts down slowly (nitrification), corrected on Mondays
        s["ph"] += -0.0004 + random.gauss(0, 0.002)
        if t.weekday() == 0 and t.hour == 8 and t.minute == 0:
            s["ph"] = min(s["ph"] + 0.3, 7.1); pw.writerow([t, u, "dosing", "ph_up", 60, "weekly_maintenance"])
        do = 7.6 - 0.38 * (wtemp - 20) + random.gauss(0, 0.1)
        # water level: evaporation/drain + pump refill
        s["level"] = max(0.0, s["level"] - (0.06 + 0.02 * max(0, air - 24) / 4))
        pump_broken = u == PUMP_FAIL[0] and PUMP_FAIL[1] <= t < PUMP_FAIL[2]
        if s["level"] < 21.0 and not pump_broken:
            dur = int(random.uniform(90, 150)); s["level"] += 3.2
            pw.writerow([t, u, "water", "on", dur, "low_level"])
        # air pump duty cycle tied to DO
        if do < 6.5 and not s["air_on"]:
            s["air_on"] = True; pw.writerow([t, u, "air", "on", 0, "low_do"])
        elif do >= 7.0 and s["air_on"]:
            s["air_on"] = False; pw.writerow([t, u, "air", "off", 0, "do_recovered"])
        # alerts
        checks = {"low_water_level": (s["level"], 18.0, s["level"] < 18.0),
                  "high_air_temp": (air, 32.0, air > 32.0),
                  "low_ph": (s["ph"], 6.2, s["ph"] < 6.2),
                  "low_dissolved_o2": (do, 5.5, do < 5.5)}
        for typ, (val, thr, cond) in checks.items():
            if cond and typ not in s["open_alert"]:
                s["open_alert"][typ] = (t, val, thr)
            elif not cond and typ in s["open_alert"]:
                t0, v0, th = s["open_alert"].pop(typ)
                aw.writerow([t0, u, typ, round(v0, 2), th, t])
        stress = max(0, air - 30) + max(0, 6.3 - s["ph"]) * 3 + max(0, 19 - s["level"]) * 0.5
        daily_stress[u][day] += stress / 96
        rw.writerow([t.isoformat(), u, round(air, 2), round(hum, 1), round(wtemp, 2), round(s["ph"], 2), round(do, 2), round(s["level"], 1)])
    t += STEP

for u, s in state.items():
    for typ, (t0, v0, th) in s["open_alert"].items():
        aw.writerow([t0, u, typ, round(v0, 2), th, ""])
readings.close(); pumps.close(); alerts.close()

# weekly harvests: yield per m² depends on plant and accumulated stress
yield_per_m2_week = {"pepper": 0.55, "lettuce": 0.9, "tomato": 0.7, "basil": 0.4}
with open(f"{OUT}/harvests.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["date", "unit_id", "plant", "kg", "notes"])
    for u, plant, loc, m2, _ in UNITS:
        for wk in range(2, DAYS // 7):
            d = START + timedelta(days=wk * 7)
            stress = sum(daily_stress[u][wk * 7 - 7: wk * 7])
            kg = m2 * yield_per_m2_week[plant] * max(0.35, 1 - 0.08 * stress) * random.uniform(0.92, 1.08)
            note = "reduced — pump outage" if u == PUMP_FAIL[0] and PUMP_FAIL[1] <= d <= PUMP_FAIL[2] + timedelta(days=7) else ""
            w.writerow([d.date(), u, plant, round(kg, 2), note])
print("ok", OUT)
