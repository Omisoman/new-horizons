"""Audit chain — append events, verify, prove tamper detection.

Needs the demo Postgres (make db-up); skipped otherwise.
"""

import os

import pytest

try:
    import psycopg
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parents[1] / ".env")
    _conn = psycopg.connect(os.environ.get(
        "DATABASE_URL", "postgresql://horizons:horizons@localhost:5432/horizons"),
        connect_timeout=3)
    _conn.close()
    _DB = True
except Exception:
    _DB = False

pytestmark = pytest.mark.skipif(not _DB, reason="postgres not running")


def test_chain_appends_and_verifies():
    from new_horizons.shared.audit.audit import audit, verify_chain
    audit("pytest", "test_event", {"n": 1})
    audit("pytest", "test_event", {"n": 2, "arabic": "تدقيق"})
    result = verify_chain()
    assert result["ok"] is True
    assert result["rows"] >= 2


def test_concurrent_writers_keep_one_chain():
    """Separate processes (Streamlit, intake pipeline, host, sojourner) append at the
    same time; the advisory lock must keep every row chained to its predecessor."""
    import subprocess
    import sys
    dsn = os.environ.get("DATABASE_URL", "postgresql://horizons:horizons@localhost:5432/horizons")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) FROM audit_log")
        start, = cur.fetchone()
    code = ("import sys; sys.path.insert(0, '.'); from new_horizons.shared.audit.audit import audit\n"
            "for i in range(15): audit('pytest-concurrency', 'race', {'w': sys.argv[1], 'i': i})")
    root = Path(__file__).parents[1]
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w)], cwd=root) for w in range(4)]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT prev_hash, hash FROM audit_log WHERE id >= %s ORDER BY id",
                    (max(start, 1),))
        rows = cur.fetchall()
    assert len(rows) >= 60
    for (_, prev_h), (prev_of_next, _) in zip(rows, rows[1:]):
        assert prev_of_next == prev_h, "two writers chained off the same predecessor"


def test_tamper_detected_and_rolled_back():
    import psycopg
    from new_horizons.shared.audit.audit import audit, verify_chain
    audit("pytest", "tamper_target", {"v": "original"})
    dsn = os.environ.get("DATABASE_URL",
                         "postgresql://horizons:horizons@localhost:5432/horizons")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # UPDATE is revoked for normal roles; the owner can — simulate an
        # attacker with table ownership, then restore.
        cur.execute("SELECT id, payload FROM audit_log WHERE event_type='tamper_target' ORDER BY id DESC LIMIT 1")
        row_id, payload = cur.fetchone()
        cur.execute("UPDATE audit_log SET payload='{\"v\": \"forged\"}' WHERE id=%s", (row_id,))
        conn.commit()
        assert verify_chain()["ok"] is False, "tampering must break the chain"
        cur.execute("UPDATE audit_log SET payload=%s::jsonb WHERE id=%s",
                    (__import__("json").dumps(payload), row_id))
        conn.commit()
    assert verify_chain()["ok"] is True


def test_carried_state_folds_into_decisions():
    """A rotation carries the latest decision per finding into the new chain as one
    `chain_carried` event; the readers fold it in with its ARCHIVE timestamp, and a
    later live decision wins (T8.6)."""
    import uuid
    from datetime import datetime, timezone
    from new_horizons.shared.audit.audit import audit, decisions, record_decision
    subject = f"PYTEST-CARRY-{uuid.uuid4()}"
    then = datetime(2026, 9, 1, 8, 30, tzinfo=timezone.utc)
    audit("pytest-carry", "chain_carried", {
        "from_table": "pytest", "skipped": [], "counts": {"decision": 1, "agent_state": 0},
        "carried": [{"archive_id": 1, "archive_hash": "0" * 64, "self_consistent": True,
                     "ts": then.isoformat(), "actor": "pytest-carry", "event_type": "decision",
                     "payload": {"subject": subject, "decision": "escalate", "rule": "pump-maintenance-sop.md §3",
                                 "detail": None, "subject_label": None}}]})
    carried = decisions(subject)[subject]
    assert carried["decision"] == "escalate" and carried["approver"] == "pytest-carry"
    assert carried["ts"] == then
    record_decision(subject, "approve", "pytest-carry")
    live = decisions(subject)[subject]
    assert live["decision"] == "approve" and live["ts"] > then


def test_rotation_selection_folds_carried_entries():
    """A second rotation must carry what the first carried: the selection reads the
    source table's own `chain_carried` entries too, and provenance never collapses —
    the entry keeps its first archive reference and gains one `via` hop (T8.7)."""
    import hashlib
    import json
    import uuid
    from new_horizons.shared.audit.audit import GENESIS, _canonical
    from new_horizons.shared.audit.rotate import carried_state

    dsn = os.environ.get("DATABASE_URL", "postgresql://horizons:horizons@localhost:5432/horizons")
    ddl = ("CREATE TABLE {t} (id bigserial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(),"
           " actor text NOT NULL, event_type text NOT NULL, payload jsonb NOT NULL,"
           " prev_hash text NOT NULL, hash text NOT NULL)")
    first_hash = "a" * 64
    carried_b = {"archive_table": "audit_log_archive_20000101", "archive_id": 7,
                 "archive_hash": first_hash, "self_consistent": True,
                 "ts": "2000-01-01T09:00:00+00:00", "actor": "approver-b", "event_type": "decision",
                 "payload": {"subject": "B", "decision": "escalate", "rule": "pump-maintenance-sop.md §3"},
                 "via": []}
    events = [("reviewer-a", "decision", {"subject": "A", "decision": "escalate"}),
              ("system", "chain_carried", {"from_table": "audit_log_archive_20000101",
                                           "carried": [carried_b], "skipped": [],
                                           "counts": {"decision": 1, "agent_state": 0}}),
              ("reviewer-a", "decision", {"subject": "A", "decision": "approve"})]

    def scratch(tamper_carrier: bool) -> tuple[str, list[int]]:
        table = f"pytest_archive_{uuid.uuid4().hex[:8]}"
        ids, prev = [], GENESIS
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(ddl.format(t=table))
            for actor, etype, payload in events:
                h = hashlib.sha256((prev + _canonical(actor, etype, payload)).encode()).hexdigest()
                if tamper_carrier and etype == "chain_carried":
                    h = "0" * 64
                cur.execute(f"INSERT INTO {table} (actor, event_type, payload, prev_hash, hash)"
                            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
                            (actor, etype, json.dumps(payload), prev, h))
                ids.append(cur.fetchone()[0])
                prev = h
            conn.commit()
        return table, ids

    tables = []
    try:
        table, (_i, carrier, latest_a) = scratch(tamper_carrier=False)
        tables.append(table)
        entries, skipped = carried_state(table)
        by = {e["payload"]["subject"]: e for e in entries}
        assert skipped == [] and set(by) == {"A", "B"}
        assert by["A"]["archive_table"] == table and by["A"]["archive_id"] == latest_a
        assert by["A"]["payload"]["decision"] == "approve" and by["A"]["via"] == []
        b = by["B"]
        assert (b["archive_table"], b["archive_id"], b["archive_hash"]) == \
            ("audit_log_archive_20000101", 7, first_hash)
        assert b["ts"] == "2000-01-01T09:00:00+00:00" and b["actor"] == "approver-b"
        assert b["via"] == [{"table": table, "id": carrier}]

        table, _ids = scratch(tamper_carrier=True)
        tables.append(table)
        entries, skipped = carried_state(table)
        assert {e["payload"]["subject"] for e in entries} == {"A"}
        assert [(s["archive_id"], s["reason"]) for s in skipped] == \
            [(7, "carrier hash does not match content")]
    finally:
        # scratch tables are not audit tables: the no-DROP rule is about audit_log*
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            for t in tables:
                assert t.startswith("pytest_archive_")
                cur.execute(f"DROP TABLE IF EXISTS {t}")
            conn.commit()
