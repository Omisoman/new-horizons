"""The five analysis pages render from the live artifacts in both languages, and
show what the artifacts hold. Needs `make db-up mock` (and `make kb` for the
rule excerpts)."""

import json
import os
import shutil

import pytest

from new_horizons.paths import DATA

AN = DATA / "analytics"
PAGES = ("overview", "reconcile", "drift", "patterns", "changes")


def _db_up() -> bool:
    try:
        import psycopg
        psycopg.connect(os.environ.get("DATABASE_URL",
                                       "postgresql://horizons:horizons@localhost:5432/horizons"),
                        connect_timeout=2).close()
        return True
    except Exception:
        return False


pytestmark = [pytest.mark.domain, pytest.mark.skipif(
    not _db_up() or not all((AN / f).exists() for f in ("recon.json", "drift.json", "patterns.json",
                                                        "daily.json")),
    reason="needs make db-up mock")]


@pytest.fixture(params=["en", "ar"])
def app(request, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from new_horizons.app import ui_common as U
    settings = tmp_path / "ui_settings.json"
    settings.write_text(json.dumps({"lang": request.param}))
    monkeypatch.setattr(U, "SETTINGS_FILE", settings)    # never the real data/ui_settings.json
    at = AppTest.from_file(str(U.APP / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception
    at.lang = request.param
    return at


def _open(at, key: str):
    from new_horizons.app import ui_common as U
    path = next(p for k, _l, _i, p in U.NAV if k == key)
    at.switch_page(str(U.APP / path)).run()
    assert not at.exception, [e.message for e in at.exception]
    return " ".join(m.value for m in at.markdown)


@pytest.mark.parametrize("key", PAGES)
def test_every_analysis_page_renders(app, key):
    md = _open(app, key)
    assert "ac-header" in md and "ac-chip" in md


def test_reconcile_shows_the_money_at_risk(app):
    total = json.loads((AN / "recon.json").read_text())["exposure_total"]
    assert f"{total:,.2f}" in _open(app, "reconcile")


def test_drift_names_the_flagged_ph_as_the_probe(app):
    md = _open(app, "drift")                       # default window: the latest month
    drift = json.loads((AN / "drift.json").read_text())
    if drift["windows"][drift["default_window"]]["ph_cause"]:
        assert ("Sensor drift" in md) if app.lang == "en" else ("انحراف المجس" in md)


def test_patterns_shows_the_ghost_loop(app):
    loop = json.loads((AN / "patterns.json").read_text())["ghost_loops"][0]
    md = _open(app, "patterns")
    assert loop["technician_code"] in md and f"{loop['kg']:,.2f}" in md


def test_changes_shows_the_deploys_or_explains_the_loop(app):
    from new_horizons.shared.audit.audit import deploys
    md = _open(app, "changes")
    if deploys(1):
        assert deploys(1)[0]["payload"]["ref"][:12] in " ".join(
            str(v) for df in app.dataframe for v in df.value.values.ravel())
    else:
        assert ("No deploys yet" in md) if app.lang == "en" else ("لا عمليات نشر بعد" in md)
        assert ("without a recorded approval" in md) if app.lang == "en" else ("دون اعتماد مسجّل" in md)


@pytest.mark.parametrize("key", ("documents", "chat"))
def test_the_document_and_chat_pages_render(app, key):
    md = _open(app, key)
    assert "ac-header" in md


@pytest.mark.skipif(not (DATA / "samples" / "lab-report.pdf").exists() or not shutil.which("tesseract"),
                    reason="needs the printed samples and tesseract")
def test_a_sample_runs_through_intake_and_raises_the_alert(app, monkeypatch):
    """The Documents page's sample button: read → extract → reconcile → terms →
    compose, the alert card on the page and the alert waiting in Chat."""
    from new_horizons.app.intake import pipeline as P
    monkeypatch.setenv("INTAKE_VLM", "0")
    monkeypatch.setattr(P, "compose_llm", lambda *a, **k: None)    # the rule template, no model
    _open(app, "documents")
    app.button(key="sample-lab-report").click().run()
    assert not app.exception, [e.message for e in app.exception]
    md = " ".join(m.value for m in app.markdown)
    assert "LAB-2026-0019" in md and "ac-alert" in md
    log = app.session_state["chat_log"]
    assert log[-1]["kind"] == "intake" and log[-1]["result"]["alert"]["verdict"] == "discrepancy"
