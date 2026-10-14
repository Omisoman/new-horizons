"""Drift — water temperature, pH and dissolved oxygen per grow unit, each month
against the reference month (June), plus the aeration duty the controller ran.

One verdict, one set of bins. PSI on the reference month's deciles and a
two-sample Kolmogorov–Smirnov test are the evidence; the verdict is practical,
because n ≈ 2,900 readings a month makes any KS p-value tiny and pH's narrow,
weekly-reset distribution moves PSI past 0.2 on a 0.06 wander. Drift = the share
of readings outside the SOP band grew by at least BAND_PP points, or the mean
moved by the measure's practical threshold. A distribution PSI calls different
but that stays inside its band is "watch", not drift. The histogram behind each
verdict ships with it, so the screen shows the evidence.

Gaps are gaps (sensor-calibration §4): a sensor dropout leaves readings missing,
never zeros, so it shrinks the sample and cannot fake a shift. A flagged pH is
then classified — a probe that drifted, or water whose chemistry changed —
from what the readings alone cannot fake: the decline between weekly doses, the
dosing the unit needed, and a step at a calibration (sensor-calibration §3).

Artifacts: data/analytics/drift.json (every window), daily.json (the series the
screens chart) — consumed by the Drift page, the Overview and drift_report.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from new_horizons.app.analytics.dataio import OUT, cite, frames, period

MEASURES = {  # column -> (label, unit, practical shift threshold, SOP band low, high)
    "water_temp_c": ("Water temperature", "°C", 1.0, 18.0, 23.0),      # water-quality-sop §4
    "ph": ("pH", "", 0.15, 6.6, 7.2),                                  # §2
    "dissolved_o2_mg_l": ("Dissolved oxygen", "mg/L", 0.4, 6.0, None),  # §3
}
BAND_PP = 3.0                            # points of readings newly outside the band
DUTY_LIMIT = 0.5                         # pump-maintenance-sop §5: air pump on > 50% of a day
STEP = pd.Timedelta(minutes=15)


def _psi(ref: np.ndarray, cur: np.ndarray, edges: np.ndarray) -> float:
    e = edges.copy()
    e[0], e[-1] = -np.inf, np.inf
    r, _ = np.histogram(ref, e)
    c, _ = np.histogram(cur, e)
    r = np.clip(r / r.sum(), 1e-4, None)
    c = np.clip(c / c.sum(), 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


def _months(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [str(p) for p in pd.period_range(start, end - pd.Timedelta(days=1), freq="M")]


def _window(month: str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    p = pd.Period(month, freq="M")
    return max(p.start_time, start), min(p.end_time + pd.Timedelta(microseconds=1), end)


def _outside(x: np.ndarray, low: float | None, high: float | None) -> float:
    out = np.zeros(len(x), dtype=bool)
    if low is not None:
        out |= x < low
    if high is not None:
        out |= x > high
    return float(100 * out.mean()) if len(x) else 0.0


def compare(ref: pd.Series, cur: pd.Series, threshold: float, low: float | None = None,
            high: float | None = None) -> dict:
    """Reference vs current readings of one measure. Missing readings are dropped —
    a gap is not a value (sensor-calibration §4)."""
    from scipy.stats import ks_2samp
    ref, cur = ref.dropna().to_numpy(float), cur.dropna().to_numpy(float)
    edges = np.quantile(ref, np.linspace(0, 1, 11))
    psi = _psi(ref, cur, edges)
    ks = ks_2samp(ref, cur)
    shift = float(cur.mean() - ref.mean())
    out_ref, out_cur = _outside(ref, low, high), _outside(cur, low, high)
    band = out_cur - out_ref >= BAND_PP
    level = "alert" if band or abs(shift) >= threshold else "watch" if psi > 0.2 else "none"
    triggers = []
    if band:
        triggers.append(f"{out_cur:.1f}% of readings outside the band (reference {out_ref:.1f}%)")
    if abs(shift) >= threshold:
        triggers.append(f"mean shift {shift:+.2f} ≥ {threshold:g}")
    if level == "watch":
        triggers.append(f"PSI {psi:.3f} > 0.2 but inside the band — a wander, not drift")
    hist_edges = edges.copy()
    hist_edges[0], hist_edges[-1] = min(ref.min(), cur.min()), max(ref.max(), cur.max())
    rh, _ = np.histogram(ref, hist_edges)
    ch, _ = np.histogram(cur, hist_edges)
    return {"n_ref": int(len(ref)), "n_cur": int(len(cur)),
            "ref_mean": round(float(ref.mean()), 3), "cur_mean": round(float(cur.mean()), 3),
            "shift": round(shift, 3), "psi": round(psi, 4), "ks_stat": round(float(ks.statistic), 4),
            "ks_pvalue": float(ks.pvalue), "outside_ref_pct": round(out_ref, 2),
            "outside_cur_pct": round(out_cur, 2), "band": [low, high], "level": level,
            "trigger": " · ".join(triggers) or "no test above threshold",
            "distribution": {"edges": [round(float(x), 3) for x in hist_edges],
                             "reference_pct": [round(float(v) / len(ref), 4) for v in rh],
                             "current_pct": [round(float(v) / len(cur), 4) for v in ch]}}


def gaps(readings: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """Runs of missing 15-minute readings per unit (a dropout), oldest first."""
    out = []
    for unit, rs in readings.groupby("unit_id"):
        ts = rs.ts.sort_values().reset_index(drop=True)
        prev = ts.shift(1)
        for a, b in zip(prev[1:], ts[1:]):
            if b - a > STEP:
                missing = int((b - a) / STEP) - 1
                out.append({"unit_id": unit, "start": (a + STEP).isoformat(timespec="minutes"),
                            "end": b.isoformat(timespec="minutes"),
                            "hours": round(missing * 0.25, 2), "missing_readings": missing})
    return sorted(out, key=lambda g: g["start"])


def air_duty(commands: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Daily share of the day each unit's air pump was on, from the on/off commands."""
    days = pd.date_range(start, end - pd.Timedelta(days=1), freq="D")
    rows = []
    air = commands[commands.actuator == "air_pump"].sort_values("ts")
    for unit in sorted(commands.unit_id.unique()):
        on_secs = pd.Series(0.0, index=days)
        cur_on = None
        for r in air[air.unit_id == unit].itertuples():
            if r.action == "on" and cur_on is None:
                cur_on = r.ts
            elif r.action == "off" and cur_on is not None:
                _add_span(on_secs, cur_on, r.ts)
                cur_on = None
        if cur_on is not None:
            _add_span(on_secs, cur_on, end)
        for d, secs in on_secs.items():
            rows.append({"date": d, "unit_id": unit, "duty": round(secs / 86400, 4)})
    return pd.DataFrame(rows)


def _add_span(acc: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> None:
    d = a.normalize()
    while d < b:
        nxt = d + pd.Timedelta(days=1)
        lo, hi = max(a, d), min(b, nxt)
        if d in acc.index and hi > lo:
            acc[d] += (hi - lo).total_seconds()
        d = nxt


def ph_cause(readings: pd.DataFrame, commands: pd.DataFrame, work_orders: pd.DataFrame,
             unit: str, ref: tuple, cur: tuple) -> dict:
    """Sensor or chemistry, for a unit whose pH drifted (sensor-calibration §3)."""
    def slope(win: tuple) -> float | None:
        rs = readings[(readings.unit_id == unit) & (readings.ts >= win[0]) & (readings.ts < win[1])]
        doses = commands[(commands.unit_id == unit) & (commands.action == "dose_ph_up")].ts.sort_values()
        slopes = []
        bounds = [win[0], *[d for d in doses if win[0] < d < win[1]], win[1]]
        for a, b in zip(bounds, bounds[1:]):
            seg = rs[(rs.ts >= a) & (rs.ts < b)]
            if len(seg) < 96:                       # a day at least between doses
                continue
            x = (seg.ts - seg.ts.iloc[0]).dt.total_seconds() / 86400
            slopes.append(float(np.polyfit(x, seg.ph.astype(float), 1)[0]))
        return round(float(np.median(slopes)), 4) if slopes else None

    def doses_per_week(win: tuple) -> float:
        n = int(((commands.unit_id == unit) & (commands.action == "dose_ph_up")
                 & (commands.ts >= win[0]) & (commands.ts < win[1])).sum())
        return round(n / ((win[1] - win[0]).days / 7), 2)

    ref_slope, cur_slope = slope(ref), slope(cur)
    ref_dose, cur_dose = doses_per_week(ref), doses_per_week(cur)
    cal = work_orders[(work_orders.unit_id == unit) & (work_orders.type == "sensor_calibration")
                      & (work_orders.opened_ts >= cur[0]) & (work_orders.opened_ts < cur[1])
                      & (work_orders.outcome == "fixed")].sort_values("opened_ts")
    step = None
    if len(cal):
        t = cal.iloc[0].opened_ts
        rs = readings[readings.unit_id == unit]
        before = rs[(rs.ts >= t - pd.Timedelta(hours=4)) & (rs.ts < t)].ph.astype(float).mean()
        after = rs[(rs.ts >= t + pd.Timedelta(hours=1)) & (rs.ts < t + pd.Timedelta(hours=5))].ph.astype(float).mean()
        step = {"work_order_no": cal.iloc[0].work_order_no, "at": t.isoformat(timespec="minutes"),
                "notes": cal.iloc[0].notes, "step": round(float(after - before), 3)}
    steeper = (ref_slope is not None and cur_slope is not None and ref_slope < 0
               and cur_slope < ref_slope * 1.3)
    more_dosing = cur_dose > ref_dose * 1.3
    cause = "chemistry" if steeper or more_dosing else "sensor"
    why = ("the decline between doses steepened or the unit needed more dosing — the water changed"
           if cause == "chemistry" else
           "the decline between doses did not steepen and the dosing did not change — the reading "
           "moved, the water did not" + (f"; calibration {step['work_order_no']} stepped it "
                                         f"{step['step']:+.2f}" if step else ""))
    return {"unit_id": unit, "cause": cause, "why": why,
            "decline_per_day": {"reference": ref_slope, "current": cur_slope},
            "doses_per_week": {"reference": ref_dose, "current": cur_dose},
            "calibration": step, "citation": cite("sensor_vs_chemistry")}


def run(write: bool = True) -> dict:
    data = frames(["readings", "commands", "work_orders", "units"])
    rd, cmd, wo = data["readings"], data["commands"], data["work_orders"]
    start, end = period()
    months = _months(start, end)
    ref_win = _window(months[0], start, end)
    ref = rd[(rd.ts >= ref_win[0]) & (rd.ts < ref_win[1])]
    duty = air_duty(cmd, start, end)
    units = sorted(rd.unit_id.unique())
    windows = {}
    for month in months[1:]:
        win = _window(month, start, end)
        cur = rd[(rd.ts >= win[0]) & (rd.ts < win[1])]
        per_unit, flags = {}, []
        for unit in units:
            per_unit[unit] = {}
            for col, (label, _u, thr, low, high) in MEASURES.items():
                c = compare(ref[ref.unit_id == unit][col], cur[cur.unit_id == unit][col], thr, low, high)
                per_unit[unit][col] = c
                if c["level"] == "alert":
                    flags.append({"unit_id": unit, "measure": col, "label": label, "level": c["level"],
                                  "shift": c["shift"], "psi": c["psi"], "trigger": c["trigger"]})
        d = duty[(duty.date >= win[0]) & (duty.date < win[1])]
        d_ref = duty[(duty.date >= ref_win[0]) & (duty.date < ref_win[1])]
        over = d[d.duty > DUTY_LIMIT]
        duty_summary = {u: {"reference_pct": round(100 * float(d_ref[d_ref.unit_id == u].duty.mean()), 1),
                            "current_pct": round(100 * float(d[d.unit_id == u].duty.mean()), 1),
                            "days_over_limit": [str(x.date()) for x in over[over.unit_id == u].date]}
                        for u in units}
        for u, s in duty_summary.items():
            if s["days_over_limit"]:
                flags.append({"unit_id": u, "measure": "air_duty", "label": "Aeration duty",
                              "level": "alert", "shift": None, "psi": None,
                              "trigger": f"air pump on > {DUTY_LIMIT:.0%} of the day on "
                                         f"{len(s['days_over_limit'])} days "
                                         f"({s['days_over_limit'][0]} … {s['days_over_limit'][-1]})"})
        causes = {f["unit_id"]: ph_cause(rd, cmd, wo, f["unit_id"], ref_win, win)
                  for f in flags if f["measure"] == "ph" and f["level"] == "alert"}
        windows[month] = {
            "range": [str(win[0].date()), str((win[1] - pd.Timedelta(days=1)).date())],
            "units": per_unit, "flags": flags, "duty": duty_summary, "ph_cause": causes,
            "gaps": [g for g in gaps(rd, start, end) if win[0].isoformat() <= g["start"] < win[1].isoformat()],
        }
    result = {
        "reference": months[0], "reference_range": [str(ref_win[0].date()),
                                                    str((ref_win[1] - pd.Timedelta(days=1)).date())],
        "months": months[1:], "default_window": months[-1],
        "measures": {k: {"label": v[0], "unit": v[1], "threshold": v[2], "band": [v[3], v[4]]}
                     for k, v in MEASURES.items()},
        "band_pp": BAND_PP,
        "duty_limit": DUTY_LIMIT, "windows": windows, "gaps": gaps(rd, start, end),
        "reference_gaps": [g for g in gaps(rd, start, end) if g["start"] < ref_win[1].isoformat()],
        "citations": {"duty": cite("aeration_duty"), "gaps": cite("sensor_dropout"),
                      "ph": cite("sensor_vs_chemistry")},
    }
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "drift.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
        _daily(rd, cmd, duty).to_json(OUT / "daily.json", orient="records", date_format="iso")
    return result


def _daily(rd: pd.DataFrame, cmd: pd.DataFrame, duty: pd.DataFrame) -> pd.DataFrame:
    rd = rd.assign(date=rd.ts.dt.normalize())
    for c in ("water_temp_c", "ph", "dissolved_o2_mg_l", "water_level_cm", "air_temp_c"):
        rd[c] = rd[c].astype(float)
    day = rd.groupby(["date", "unit_id"]).agg(
        readings=("ts", "count"), water_temp_c=("water_temp_c", "mean"),
        water_temp_max=("water_temp_c", "max"), ph=("ph", "mean"),
        do_mg_l=("dissolved_o2_mg_l", "mean"), do_min=("dissolved_o2_mg_l", "min"),
        level_min=("water_level_cm", "min"), air_temp_max=("air_temp_c", "max")).reset_index()
    feed = cmd[cmd.action == "feed"].assign(date=lambda d: d.ts.dt.normalize()) \
        .groupby(["date", "unit_id"]).qty.sum().rename("feed_kg").reset_index()
    out = day.merge(duty, on=["date", "unit_id"], how="left").merge(feed, on=["date", "unit_id"], how="left")
    out["date"] = out.date.dt.strftime("%Y-%m-%d")
    return out.round(3)


if __name__ == "__main__":
    r = run()
    for m, w in r["windows"].items():
        print(m, [(f["unit_id"], f["measure"], f["level"], f["trigger"]) for f in w["flags"]])
        print("  ph causes:", {u: (c["cause"], c["decline_per_day"], c["calibration"]) for u, c in w["ph_cause"].items()})
    print("gaps:", r["gaps"])
