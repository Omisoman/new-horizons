"""Business truth: the figures the screens, the chat and the question set state
equal the generator's own ground truth (ingest/validation/expected-results.json,
written by `make mock` — never typed by hand)."""

import json
import os

import pytest

from new_horizons.paths import APP, DATA

EXPECTED = APP / "ingest" / "validation" / "expected-results.json"
META = DATA / "mock_meta.json"
AN = DATA / "analytics"

pytestmark = [pytest.mark.domain, pytest.mark.skipif(
    not META.exists() or not (AN / "recon.json").exists(), reason="needs make mock")]


def _expected():
    return json.loads(EXPECTED.read_text())


def _json(name):
    return json.loads((AN / name).read_text())


def test_expected_results_are_the_generators():
    """A regenerated dataset that moved a pinned figure shows up as a diff of the
    tracked expected-results.json — and fails here until it is committed."""
    from new_horizons.app.mock.generate import expected_results
    meta = json.loads(META.read_text())
    fresh = json.loads(json.dumps(expected_results(meta), default=str))
    assert fresh == _expected(), "run `make mock` and commit ingest/validation/expected-results.json"


def test_reconciliation_money_equals_ground_truth():
    e, r = _expected()["recon"], _json("recon.json")
    assert r["exposure"] == e["eur"] and r["exposure_total"] == e["eur_total"]
    assert {k: round(v, 3) for k, v in r["exposure_kg"].items()} == \
        {k: round(v, 3) for k, v in e["kg"].items()}


def _db_up() -> bool:
    try:
        import psycopg
        psycopg.connect(os.environ.get("DATABASE_URL_RO",
                                       "postgresql://farm_ro:farm-ro@localhost:5432/horizons"),
                        connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="the metrics read the farm database (make db-up)")
def test_metric_figures_equal_the_validation_set():
    from new_horizons.app.analytics import metrics as M
    e = _expected()
    pump = M.pump_failure_loss()["figures"]
    pf = e["pump_failure"]
    assert pump["kg_lost"] == f"{pf['kg_lost']:.2f}" and pump["eur"] == f"{pf['eur_lost']:.2f}"
    assert pump["kg_actual"] == f"{pf['kg_actual']:.2f}" and pump["kg_expected"] == f"{pf['kg_expected']:.2f}"
    assert pump["response"] == f"{pf['response_hours']:.1f}" and pump["sop"] == str(pf["sop_hours"])
    ghost = M.ghost_harvests()["figures"]
    assert ghost["count"] == str(e["ghost_harvests"]["count"])
    assert ghost["kg"] == f"{e['ghost_harvests']['kg']:.2f}"
    feed = M.unmetered_feed()["figures"]
    assert feed["eur"] == f"{e['unmetered_feed']['eur']:.2f}" and feed["days"] == str(e["unmetered_feed"]["days"])
    heat = M.heatwave_aeration()["figures"]
    assert heat["heat"] == f"{e['heatwave']['duty_heatwave_pct']:.1f}%"
    assert heat["days"] == str(len(e["heatwave"]["days_over_50"]["AQ-03"]))
    ph = M.ph_drift_cause()["figures"]
    assert (ph["lab"], ph["probe"]) == (f"{e['ph_probe_drift']['lab_ph']:.2f}",
                                        f"{e['ph_probe_drift']['probe_ph']:.2f}")
    farm = M.farm_overview()["figures"]
    assert (farm["units"], farm["fish"], farm["beds"]) == ("4", "97", "83.0")
    aug = M.harvest_and_sales("in August")["figures"]
    ha = e["harvest_august"]
    assert (aug["kg_harvested"], aug["kg_shipped"]) == (f"{ha['kg_harvested']:.2f}", f"{ha['kg_shipped']:.2f}")
    assert aug["eur"] == f"{ha['eur']:,.2f}"
    alerts = M.open_alerts()["figures"]
    assert (alerts["open"], alerts["raised"]) == (str(e["alerts"]["open"]), str(e["alerts"]["raised"]))
    work = M.technician_workload()["figures"]
    assert work["total"] == str(e["work_orders"]["total"]) and work["top"] == str(e["work_orders"]["top_closed"])
    held = M.held_invoice()["figures"]
    d = e["document_intake"]["held"]
    assert held["price"] == f"{float(d['invoice_unit_price']):.2f}"
    assert held["agreed"] == f"{d['agreed_unit_price']:.2f}"
    dosing = M.dosing_schedule()["figures"]
    assert dosing["events"] == str(e["weekly_dosing"]["events"])


@pytest.mark.skipif(not _db_up(), reason="the metrics read the farm database (make db-up)")
def test_the_question_set_states_ground_truth():
    """Every must-include figure in docs/question-set.yaml appears in its expected
    answer, and every intent question's figures are what its resolver says."""
    import yaml

    from new_horizons.app.analytics import metrics as M
    from new_horizons.paths import ROOT
    from new_horizons.shared.text.lang import figure_found
    qs = yaml.safe_load((ROOT / "docs" / "question-set.yaml").read_text(encoding="utf-8"))
    spec = {i["id"]: i for i in yaml.safe_load(M.INTENTS.read_text(encoding="utf-8"))["intents"]}
    for q in qs:
        for f in q.get("must_include") or []:
            assert figure_found(f, q["a"]), (q["id"], f)
        if q.get("intent") and q["intent"] != "decision_on_finding":
            p = M.RESOLVERS[spec[q["intent"]]["resolver"]](q["q"])
            text = p["template_en"] if q["lang"] == "en" else p["template_ar"]
            for f in q.get("must_include") or []:
                assert figure_found(f, text), (q["id"], f, text[:120])
