"""Governance layer: decisions, the kill switch and the drawer's reader are
audit events — recorded in the chain, never in UI state or a side table."""

import os
import uuid
from pathlib import Path

import pytest

try:
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parents[1] / ".env")
    psycopg.connect(os.environ.get("DATABASE_URL",
                                   "postgresql://horizons:horizons@localhost:5432/horizons"),
                    connect_timeout=3).close()
    _DB = True
except Exception:
    _DB = False

pytestmark = pytest.mark.skipif(not _DB, reason="postgres not running")


def test_decision_is_recorded_with_who_when_and_rule():
    from new_horizons.shared.audit.audit import decisions, record_decision
    subject = f"AQ-TEST-{uuid.uuid4().hex[:8]}"
    record_decision(subject, "escalate", "pytest-approver",
                    rule="supplier-invoice-controls.md §2", detail="price above tolerance",
                    subject_label="invoice.pdf")
    d = decisions(subject)[subject]
    assert d["decision"] == "escalate"
    assert d["approver"] == "pytest-approver"
    assert d["rule"] == "supplier-invoice-controls.md §2"
    assert d["ts"] is not None


def test_latest_decision_wins():
    from new_horizons.shared.audit.audit import decisions, record_decision
    subject = f"AQ-TEST-{uuid.uuid4().hex[:8]}"
    for decision in ("reject", "approve"):
        record_decision(subject, decision, "pytest-approver")
    assert decisions(subject)[subject]["decision"] == "approve"


def test_unknown_decision_is_refused():
    from new_horizons.shared.audit.audit import record_decision
    with pytest.raises(ValueError):
        record_decision("AQ-TEST-x", "shred", "pytest-approver")


def test_kill_switch_state_round_trips():
    from new_horizons.shared.audit.audit import agent_state, set_agent_state
    try:
        set_agent_state(False, "pytest-operator", reason="test pause")
        s = agent_state()
        assert s["active"] is False and s["actor"] == "pytest-operator"
        assert s["reason"] == "test pause"
    finally:
        set_agent_state(True, "pytest-operator")     # never leave the agent paused
    assert agent_state()["active"] is True


def test_drawer_filter_finds_the_subject_and_nothing_else():
    from new_horizons.shared.audit.audit import events, record_decision
    subject = f"AQ-TEST-{uuid.uuid4().hex[:8]}"
    record_decision(subject, "approve", "pytest-approver", rule="harvest-shipping-procedure.md §3")
    rows = events(limit=50, contains=subject)
    assert rows and all(subject in str(r["payload"]) for r in rows)
    assert rows[0]["event_type"] == "decision" and rows[0]["hash"]


def test_governance_document_is_generic_and_renders_placeholders():
    """The handoff names the farm only through profile.yaml."""
    doc = (Path(__file__).parents[1] / "src" / "new_horizons" / "app" / "agents" / "analytics"
           / "GOVERNANCE.md").read_text(encoding="utf-8")
    for placeholder in ("{{farm}}", "{{date}}", "{{operator}}"):
        assert placeholder in doc
    assert "never writes to a farm system" in doc.lower().replace("**", "")
    assert "never actuates equipment" in doc.lower().replace("**", "")
