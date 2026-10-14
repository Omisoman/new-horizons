"""Every planted scenario surfaces exactly, by name — 5/5, plus the probe drift
and the benign weekly dosing.

Ground truth: data/mock_meta.json (written by `make mock`). Artifacts:
data/analytics/{recon,drift,patterns}.json (written by the analytics run()s).
"""

import json

import numpy as np
import pandas as pd
import pytest

from new_horizons.paths import DATA

AN = DATA / "analytics"
META = DATA / "mock_meta.json"

pytestmark = [pytest.mark.domain, pytest.mark.skipif(
    not META.exists() or not all((AN / f).exists() for f in ("recon.json", "drift.json", "patterns.json")),
    reason="mock data / analytics artifacts not built (make mock)")]


def _meta():
    return json.loads(META.read_text())


def _json(name):
    return json.loads((AN / name).read_text())


def test_volumes_and_seed():
    m = _meta()
    c = m["counts"]
    assert m["seed"] == 2019 and m["period"] == ["2026-06-01", "2026-08-29"]
    assert c["telemetry.units"] == 4
    # 4 units × 90 days × 96 readings, minus the two dropouts (36 + 20 missing)
    assert c["telemetry.readings"] == 4 * 90 * 96 - 36 - 20 == m["readings"]["rows"]
    assert c["harvest.harvests"] == c["harvest.shipments"] + 6
    assert m["farm"] == {"units": 4, "fish": 97, "fish_species": "European perch", "grow_bed_m2": 83.0,
                         "plants": {"AQ-01": "pepper", "AQ-02": "lettuce", "AQ-03": "tomato",
                                    "AQ-04": "basil"}}


def test_scenario_1_pump_failure_commanded_never_observed():
    truth = _meta()["scenarios"]["pump_failure"]
    recon = _json("recon.json")
    [e] = [e for e in recon["exceptions"] if e["class"] == "commanded_not_observed"]
    assert e["unit_id"] == truth["unit_id"] == "AQ-03"
    assert e["first_command"][:10] == "2026-07-12" and e["last_command"][:10] == "2026-07-17"
    # each run is judged against the next 30 minutes: the last runs before the repair see it
    assert truth["commands_unobserved"] - 3 <= e["commands"] <= truth["commands_unobserved"]
    assert (e["alert_no"], e["work_order_no"]) == (truth["alert_no"], truth["work_order_no"])
    assert e["response_hours"] == truth["response_hours"] > 100      # the SOP says 2
    assert (e["harvest_no"], e["kg_actual"], e["kg_expected"]) == \
        (truth["harvest_no"], truth["kg_actual"], truth["kg_expected"])
    assert e["kg"] == truth["kg_lost"] and e["eur"] == truth["eur_lost"]
    # the harvest collapses the next week and recovers the week after
    assert truth["kg_actual"] < 0.5 * truth["kg_expected"]
    late = _json("patterns.json")["late_responses"]
    assert [x["alert_no"] for x in late] == [truth["alert_no"]]


def test_scenario_2_heatwave_aeration_and_water_temperature():
    truth = _meta()["scenarios"]["heatwave"]
    july = _json("drift.json")["windows"]["2026-07"]
    assert july["duty"]["AQ-03"]["days_over_limit"] == truth["days_over_50"]["AQ-03"] == \
        ["2026-07-26", "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
    assert all(not truth["days_over_50"][u] for u in ("AQ-01", "AQ-02", "AQ-04"))
    assert truth["duty_heatwave_pct"] > 50 > truth["duty_june_pct"]
    flagged = {(f["unit_id"], f["measure"]) for f in july["flags"]}
    assert flagged == {("AQ-03", "air_duty"), ("AQ-03", "water_temp_c")}


def test_scenario_3_ghost_harvests_one_technician():
    truth = _meta()["scenarios"]["ghost_harvests"]
    recon = _json("recon.json")
    unshipped = sorted(e["ref"] for e in recon["exceptions"] if e["class"] == "harvest_not_shipped")
    assert unshipped == sorted(truth["harvest_nos"]) and truth["count"] == 6
    [loop] = _json("patterns.json")["ghost_loops"]
    assert loop["technician_code"] == truth["technician_code"] == "TEC-06"
    assert loop["count"] == 6 and loop["uncountersigned"] == 6 and loop["others_max_share"] == 0.0
    assert abs(loop["kg"] - sum(e["kg"] for e in recon["exceptions"] if e["class"] == "harvest_not_shipped")) < 1e-6


def test_scenario_4_unmetered_feed():
    truth = _meta()["scenarios"]["unmetered_feed"]
    [e] = [e for e in _json("recon.json")["exceptions"] if e["class"] == "consumed_not_purchased"]
    assert (e["unit_id"], e["item_code"]) == (truth["unit_id"], truth["item_code"]) == ("AQ-02", "FEED-03")
    assert (e["first"], e["last"], e["days"]) == (truth["first"], truth["last"], truth["days"])
    assert abs(e["qty"] - truth["qty_kg"]) < 1e-6 and e["eur"] == truth["eur"]


def test_scenario_5_dropouts_are_gaps_and_raise_no_drift():
    truth = _meta()["scenarios"]["sensor_dropouts"]
    drift = _json("drift.json")
    assert [(g["unit_id"], g["start"], g["missing_readings"]) for g in drift["gaps"]] == \
        [(t["unit_id"], t["start"], t["missing_readings"]) for t in truth]
    # AQ-04's August window holds its dropout: its temperature and oxygen do not flag
    aug = drift["windows"]["2026-08"]
    assert not [f for f in aug["flags"] if f["unit_id"] == "AQ-04" and f["measure"] != "ph"]
    assert aug["units"]["AQ-04"]["water_temp_c"]["n_cur"] == 29 * 96 - 20
    for g in _json("patterns.json")["dropouts"]:
        assert g["needs_work_order"] and g["work_order_no"]


def test_zero_filling_a_dropout_would_have_faked_drift():
    """The negative test: the same comparison with the gap filled with zeros flags —
    which is why a gap is never a value (sensor-calibration §4)."""
    from new_horizons.app.analytics.drift import MEASURES, compare
    rng = np.random.default_rng(2019)
    ref = pd.Series(rng.normal(19.2, 0.9, 2880))
    cur = pd.Series(rng.normal(19.2, 0.9, 2784 - 20))
    label, _u, thr, low, high = MEASURES["water_temp_c"]
    assert compare(ref, cur, thr, low, high)["level"] == "none"
    zero_filled = pd.concat([cur, pd.Series([0.0] * 120)])          # a 30-hour gap as zeros
    faked = compare(ref, zero_filled, thr, low, high)
    assert faked["level"] == "alert" and "outside the band" in faked["trigger"]


def test_ph_probe_drift_is_a_sensor_not_the_water():
    truth = _meta()["scenarios"]["ph_probe_drift"]
    aug = _json("drift.json")["windows"]["2026-08"]
    assert [(f["unit_id"], f["measure"]) for f in aug["flags"]] == [("AQ-04", "ph")]
    cause = aug["ph_cause"]["AQ-04"]
    assert cause["cause"] == "sensor"
    assert cause["calibration"]["at"] == truth["calibrated"] and cause["calibration"]["step"] < -0.3
    doses = cause["doses_per_week"]                                  # one Monday dose a week
    assert 0.9 <= doses["current"] <= 1.2 and 0.9 <= doses["reference"] <= 1.2
    assert truth["probe_ph"] - truth["lab_ph"] > 0.2                 # the lab report shows it


def test_weekly_dosing_is_benign():
    truth = _meta()["scenarios"]["weekly_dosing"]
    assert truth["events"] == 52 and truth["per_unit"] == 13
    drift = _json("drift.json")
    flagged = {(f["unit_id"], f["measure"]) for w in drift["windows"].values() for f in w["flags"]}
    assert {(u, "ph") for u in ("AQ-01", "AQ-02", "AQ-03")}.isdisjoint(flagged)


def test_exposure_is_ranked_by_money():
    recon = _json("recon.json")
    eur = [e["eur"] for e in recon["exceptions"]]
    assert eur == sorted(eur, reverse=True)
    truth = _meta()["recon"]
    assert recon["exposure"] == truth["eur"] and recon["exposure_total"] == truth["eur_total"]
