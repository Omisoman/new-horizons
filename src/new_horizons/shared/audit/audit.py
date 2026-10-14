"""Hash-chained append-only audit — Postgres rows + JSONL mirror.

hash_n = sha256(prev_hash + canonical(ts, actor, event_type, payload)).
UPDATE/DELETE are revoked on the table; verify_chain() recomputes the chain.
Used by every model call, tool call and A2A state transition in both demos.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from new_horizons.paths import data_path

_lock = threading.Lock()
GENESIS = "genesis"
AUDIT_LOCK_KEY = 0x6A1C0A0D17  # pg advisory lock id for the audit chain


def _dsn() -> str:
    return os.environ.get("DATABASE_URL",
                          "postgresql://horizons:horizons@localhost:5432/horizons")


def _jsonl_path() -> Path:
    p = data_path(os.environ.get("AUDIT_JSONL"), "audit/audit.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _canonical(actor: str, event_type: str, payload: dict) -> str:
    # ts stays out of the hash basis: timestamptz round-trips are not
    # byte-stable across sessions; order + content is what the chain protects.
    return json.dumps({"actor": actor, "event_type": event_type,
                       "payload": payload},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def audit(actor: str, event_type: str, payload: dict) -> str:
    """Append one event; returns its hash."""
    import psycopg
    ts = datetime.now(timezone.utc).isoformat()
    with _lock, psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        # _lock only serializes threads of THIS process; the Streamlit app, the
        # intake pipeline and the host write from separate processes, so the
        # read-last-hash → insert pair is serialized in Postgres (released at commit).
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
        cur.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        prev = row[0] if row else GENESIS
        h = hashlib.sha256(
            (prev + _canonical(actor, event_type, payload)).encode()).hexdigest()
        cur.execute(
            "INSERT INTO audit_log (ts, actor, event_type, payload, prev_hash, hash)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (ts, actor, event_type, json.dumps(payload, ensure_ascii=False), prev, h))
        conn.commit()
    with _jsonl_path().open("a") as f:
        f.write(json.dumps({"ts": ts, "actor": actor, "event_type": event_type,
                            "payload": payload, "prev_hash": prev, "hash": h},
                           ensure_ascii=False) + "\n")
    return h


# ---- governance: human decisions, agent state, and the reader behind the drawer ----
# Decisions and pause/resume are AUDIT EVENTS, not rows in some side table: the
# state of a finding is its latest decision event, so nothing can be changed
# without breaking the chain.

DECISIONS = ("approve", "escalate", "reject")


def record_decision(subject: str, decision: str, approver: str, rule: str | None = None,
                    detail: str | None = None, subject_label: str | None = None) -> str:
    """A human decision on one finding. `subject` is its stable id (unit, work
    transfer ref, exception id); `rule` is the KB citation it rests on."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    return audit(approver, "decision", {"subject": subject, "subject_label": subject_label,
                                        "decision": decision, "rule": rule, "detail": detail})


def set_agent_state(active: bool, actor: str, reason: str | None = None) -> str:
    """The kill switch. Paused means no automated action runs until resumed."""
    return audit(actor, "agent_state", {"active": bool(active), "reason": reason})


# ---- deploys: what sojourner shipped to this app ---------------------------
# One chain: tier-2 writes each approved deploy here, the app's Changes page reads it.

DEPLOY_SOURCE = "sojourner"


def record_deploy(ref: str, approved_by: str, task_id: str, actor: str = "sojourner-tier2",
                  **detail) -> str:
    """One approved deploy: the commit `ref` that reached staging, the person who
    approved it and the A2A task it came from; `detail` adds summary, files, the
    evaluation and the staging URL."""
    return audit(actor, "deploy", {"source": DEPLOY_SOURCE, "kind": "deploy", "ref": ref,
                                   "approved_by": approved_by, "task_id": task_id, **detail})


def deploys(limit: int = 100) -> list[dict]:
    """Newest-first deploy events written by sojourner (payload source = sojourner)."""
    return _rows("SELECT id, ts, actor, payload, hash FROM audit_log WHERE event_type = 'deploy'"
                 " AND payload->>'source' = %s ORDER BY id DESC LIMIT %s", (DEPLOY_SOURCE, int(limit)))


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    import psycopg
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


# The live chain, a rotation's archive, or a test's scratch archive. Only rotate.py
# (and its test) pass `table`: the screens read the live chain and nothing else.
_TABLE = re.compile(r"^audit_log(_archive_\d{8})?$|^pytest_archive_[0-9a-f]{8}$")


def _typed(event_type: str, subject: str | None = None, table: str = "audit_log"):
    """(id, seq, ts, actor, payload) of one event type, in chain order: the table's own
    rows, and the entries of that type a rotation carried in (`chain_carried`,
    shared/audit/rotate.py). A carried entry sits at the carried row's id, `seq` = its
    index, and keeps the archive row's ts, actor and payload — so a decision carried
    across a rotation keeps its original time and approver."""
    if not _TABLE.match(table):
        raise ValueError(f"not an audit table: {table!r}")
    where = " AND payload->>'subject' = %s" if subject else ""
    rows = _rows(f"SELECT id, ts, actor, event_type, payload FROM {table}"
                 f" WHERE (event_type = %s{where}) OR event_type = 'chain_carried' ORDER BY id",
                 (event_type, subject) if subject else (event_type,))
    out = []
    for r in rows:
        if r["event_type"] != "chain_carried":
            out.append((r["id"], 0, r["ts"], r["actor"], r["payload"]))
            continue
        for seq, e in enumerate((r["payload"] or {}).get("carried") or []):
            p = e.get("payload") or {}
            if e.get("event_type") != event_type or (subject and p.get("subject") != subject):
                continue
            out.append((r["id"], seq, datetime.fromisoformat(e["ts"]), e.get("actor"), p))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def agent_state() -> dict:
    """{active, actor, ts, reason} — the latest kill-switch event (default active),
    carried state included."""
    rows = _typed("agent_state")
    if not rows:
        return {"active": True, "actor": None, "ts": None, "reason": None}
    _id, _seq, ts, actor, p = rows[-1]
    return {"active": bool(p.get("active", True)), "actor": actor, "ts": ts, "reason": p.get("reason")}


def decisions(subject: str | None = None) -> dict[str, dict]:
    """Latest decision per subject: {subject: {decision, approver, ts, rule, detail}} —
    carried decisions folded in chain order, a later live decision wins."""
    out: dict[str, dict] = {}
    for _id, _seq, ts, actor, p in _typed("decision", subject):
        out[p["subject"]] = {"decision": p["decision"], "approver": actor, "ts": ts,
                             "rule": p.get("rule"), "detail": p.get("detail"),
                             "subject_label": p.get("subject_label")}
    return out


def events(limit: int = 200, contains: str | None = None,
           event_types: tuple[str, ...] | None = None) -> list[dict]:
    """Newest-first audit events for the drawer. `contains` matches anywhere in
    the payload (unit, work order, shipment, rule), so one filter serves the UI."""
    where, params = ["1=1"], []
    if contains:
        where.append("payload::text ILIKE %s")
        params.append(f"%{contains}%")
    if event_types:
        where.append("event_type = ANY(%s)")
        params.append(list(event_types))
    return _rows(f"SELECT id, ts, actor, event_type, payload, hash FROM audit_log"
                 f" WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT {int(limit)}",
                 tuple(params))


def verify_chain() -> dict:
    """Recompute the whole chain; returns {ok, rows, break_at}."""
    import psycopg
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT actor, event_type, payload, prev_hash, hash"
                    " FROM audit_log ORDER BY id")
        prev, n = GENESIS, 0
        for n, (actor, etype, payload, prev_hash, h) in enumerate(cur, 1):
            if prev_hash != prev:
                return {"ok": False, "rows": n, "break_at": n, "reason": "prev_hash mismatch"}
            expect = hashlib.sha256(
                (prev + _canonical(actor, etype, payload)).encode()).hexdigest()
            if expect != h:
                return {"ok": False, "rows": n, "break_at": n, "reason": "hash mismatch"}
            prev = h
        return {"ok": True, "rows": n, "break_at": None}
