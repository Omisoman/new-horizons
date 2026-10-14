"""Rotate the demo-1 audit chain: archive it intact, start a new one anchored to it.

    uv run python -m new_horizons.shared.audit.rotate --reason "<why>"      (make audit-rotate REASON=…)
    uv run python -m new_horizons.shared.audit.rotate --carry-only --from-table audit_log_archive_<YYYYMMDD>

An audit chain that can be reset is not an audit chain. A broken chain (BLOCKERS
27: two writers before the advisory lock) is therefore never repaired, truncated
or dropped: the table is RENAMED to audit_log_archive_<YYYYMMDD> — DDL, not
UPDATE/DELETE, so it keeps every row, its grants and the REVOKE — a fresh
audit_log is created with the exact schema.sql DDL, the JSONL mirror is rotated
beside it, and the first event of the new chain records the archive: its table,
row count, head hash, verify result and the reason. Its prev_hash is GENESIS;
the anchor is the payload.

A rotation is a checkpoint, not amnesia. Right after the anchor, the current
state — the latest `decision` per subject and the latest `agent_state` (the kill
switch), the suite's `pytest*` rows excluded — is carried into the new chain as
ONE `chain_carried` event. Every carried entry names its archive row (id, hash)
and was checked against its OWN stored prev_hash (the link at a break may be
wrong; a row's content is not), so an auditor can accept the snapshot; a row
that fails the check is listed under `skipped`, never carried. The readers
(`audit._typed`) fold carried entries in; the archive stays the evidence.
`--carry-only` adds that event to the live chain for an existing archive (once
per archive) without rotating.

Rotations compose (T8.7): the selection reads the source table the way the
screens read the live one — plain rows AND the entries of its own
`chain_carried` rows — so state carried in by an earlier rotation is carried
again. Provenance never collapses: an entry keeps its ORIGINAL archive_table,
archive_id and archive_hash, and gains one `via` hop ({table, id} of the
chain_carried row that transported it) per rotation it crossed.

One chain: DATABASE_URL (default the `horizons` database), which
sojourner also writes its deploy events into. No pytest runs this — it
would rotate the dev chain on every run; tests/test_audit_chain.py, run with the
DB up, is the proof.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from new_horizons.paths import ROOT

# the DSN lives in the repo's .env (audit._dsn reads the environment)
load_dotenv(ROOT / ".env")

import hashlib  # noqa: E402
import re  # noqa: E402

from new_horizons.shared.audit.audit import (AUDIT_LOCK_KEY, _TABLE, _canonical, _dsn, _rows, _typed,  # noqa: E402
                                audit, verify_chain)

ARCHIVE_NAME = re.compile(r"^audit_log_archive_\d{8}$")

# exactly shared/db/schema.sql's audit_log (plus the grant the read-only role has)
DDL = """
CREATE TABLE audit_log (
    id         bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    actor      text NOT NULL,                  -- agent/tool/user id
    event_type text NOT NULL,                  -- model_call | tool_call | state | ...
    payload    jsonb NOT NULL,
    prev_hash  text NOT NULL,
    hash       text NOT NULL
);
REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;
GRANT SELECT ON audit_log TO farm_ro;
"""


def _self_consistent(row: dict) -> bool:
    """A row's content against its OWN stored prev_hash: a broken link elsewhere does not matter."""
    expect = hashlib.sha256((row["prev_hash"] + _canonical(row["actor"], row["event_type"],
                                                           row["payload"])).encode()).hexdigest()
    return row["hash"] == expect


def carried_state(table: str) -> tuple[list[dict], list[dict]]:
    """(entries, skipped) — the current state in `table`, ready to carry.

    Selected through `_typed(..., table=table)`, so plain rows and the entries inside
    the table's own `chain_carried` rows count alike, in chain order (id, seq): the
    latest `decision` per subject and the latest `agent_state`. `pytest*` actors are
    excluded, whether they wrote the row or the carrier. A plain row is accepted when
    its own hash checks; a carried entry when its carrier row's hash checks (the row's
    hash covers the entries)."""
    if not _TABLE.match(table):
        raise ValueError(f"not an audit table: {table!r}")
    pytest_carriers = {r["id"] for r in _rows(
        f"SELECT id FROM {table} WHERE event_type = 'chain_carried' AND actor LIKE 'pytest%%'")}
    latest: dict[tuple, tuple[int, int]] = {}
    for etype in ("decision", "agent_state"):
        for rid, seq, _ts, actor, payload in _typed(etype, table=table):
            if (actor or "").startswith("pytest") or rid in pytest_carriers:
                continue
            key = (etype, payload.get("subject")) if etype == "decision" else (etype,)
            latest[key] = (rid, seq)
    ids = sorted({rid for rid, _seq in latest.values()})
    rows = {r["id"]: r for r in _rows(
        f"SELECT id, ts, actor, event_type, payload, prev_hash, hash FROM {table}"
        " WHERE id = ANY(%s)", (ids,))} if ids else {}

    entries, skipped = [], []
    for rid, seq in sorted(latest.values()):
        row = rows[rid]
        ok = _self_consistent(row)
        if row["event_type"] == "chain_carried":
            e = row["payload"]["carried"][seq]
            first = e.get("archive_table") or row["payload"].get("from_table")
            via = list(e.get("via") or []) + [{"table": table, "id": rid}]
            if not ok:
                skipped.append({"archive_table": first, "archive_id": e.get("archive_id"), "via": via,
                                "reason": "carrier hash does not match content"})
                continue
            entries.append({"archive_table": first, "archive_id": e["archive_id"],
                            "archive_hash": e["archive_hash"],
                            "self_consistent": e.get("self_consistent", True), "ts": e["ts"],
                            "actor": e["actor"], "event_type": e["event_type"],
                            "payload": e["payload"], "via": via})
            continue
        if not ok:
            skipped.append({"archive_table": table, "archive_id": rid,
                            "reason": "hash does not match content"})
            continue
        entries.append({"archive_table": table, "archive_id": rid, "archive_hash": row["hash"],
                        "self_consistent": True, "ts": row["ts"].isoformat(), "actor": row["actor"],
                        "event_type": row["event_type"], "payload": row["payload"], "via": []})
    return entries, skipped


def carry(archive: str) -> tuple[str, dict]:
    """Append the `chain_carried` event for `archive` to the live chain; returns (hash, payload)."""
    carried, skipped = carried_state(archive)
    payload = {"from_table": archive, "carried": carried, "skipped": skipped,
               "counts": {"decision": sum(e["event_type"] == "decision" for e in carried),
                          "agent_state": sum(e["event_type"] == "agent_state" for e in carried)}}
    return audit("system", "chain_carried", payload), payload


def _report_carry(h: str, p: dict) -> None:
    print(f"carried    chain_carried  hash {h}  from {p['from_table']}")
    print(f"           {p['counts']['decision']} decisions · {p['counts']['agent_state']} agent_state"
          f" · {len(p['skipped'])} skipped")
    for e in p["carried"]:
        hops = "".join(f" <- {h['table']}#{h['id']}" for h in e.get("via") or [])
        print(f"           {e['archive_table']}#{e['archive_id']}{hops} {e['event_type']:<11}"
              f" {e['actor']:<12} {e['ts'][:19]}  {json_brief(e['payload'])}")
    for e in p["skipped"]:
        print(f"           SKIPPED {e.get('archive_table', '')}#{e['archive_id']}: {e['reason']}")


def json_brief(p: dict) -> str:
    keys = ("subject", "decision", "rule", "active")
    return " ".join(f"{k}={p[k]}" for k in keys if k in p)


def carry_only(archive: str) -> int:
    import psycopg
    if not ARCHIVE_NAME.match(archive):
        print(f"rotate: {archive!r} is not an archive name (audit_log_archive_YYYYMMDD)", file=sys.stderr)
        return 2
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (archive,))
        if cur.fetchone()[0] is None:
            print(f"rotate: {archive} does not exist", file=sys.stderr)
            return 2
        cur.execute("SELECT id FROM audit_log WHERE event_type = 'chain_carried'"
                    " AND payload->>'from_table' = %s", (archive,))
        if cur.fetchone():
            print(f"rotate: refusing — the live chain already carries state from {archive}", file=sys.stderr)
            return 2
    h, p = carry(archive)
    _report_carry(h, p)
    after = verify_chain()
    print(f"live chain ok {after['ok']}, rows {after['rows']}")
    return 0 if after["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reason", help="why the chain is rotated (recorded in the anchor)")
    ap.add_argument("--carry-only", action="store_true",
                    help="append the carried state of --from-table to the live chain; no rotation")
    ap.add_argument("--from-table", help="the archive to carry from (with --carry-only)")
    a = ap.parse_args(argv)
    dsn = _dsn()
    if a.carry_only:
        if not a.from_table:
            print("rotate: --carry-only needs --from-table audit_log_archive_<YYYYMMDD>", file=sys.stderr)
            return 2
        return carry_only(a.from_table)
    reason = (a.reason or "").strip()
    if not reason:
        print("rotate: --reason must say why", file=sys.stderr)
        return 2

    import psycopg

    v = verify_chain()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d")
    archive = f"audit_log_archive_{suffix}"
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # the same lock audit() takes: no write can land between the head read and the rename
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
        cur.execute("SELECT to_regclass(%s)", (archive,))
        if cur.fetchone()[0] is not None:
            print(f"rotate: refusing — {archive} already exists (one rotation per UTC day)", file=sys.stderr)
            return 2
        cur.execute("SELECT count(*) FROM audit_log")
        n = cur.fetchone()[0]
        cur.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        head = row[0] if row else None
        cur.execute(f"ALTER TABLE audit_log RENAME TO {archive}")
        # its sequence and key index move with it, so the new table's are plainly named
        cur.execute(f"ALTER SEQUENCE IF EXISTS audit_log_id_seq RENAME TO {archive}_id_seq")
        cur.execute(f"ALTER INDEX IF EXISTS audit_log_pkey RENAME TO {archive}_pkey")
        cur.execute(DDL)
        conn.commit()

    mirror = Path(os.environ.get("AUDIT_JSONL", "data/audit/audit.jsonl"))
    mirror_archive = mirror.with_name(f"audit-archive-{suffix}.jsonl")
    if mirror.exists():
        mirror.rename(mirror_archive)

    anchor = audit("system", "chain_rotated", {
        "archived_table": archive, "archived_rows": n, "archived_head_hash": head,
        "archived_verify": v, "reason": reason,
        "archived_mirror": str(mirror_archive) if mirror_archive.exists() else None,
    })
    carried_hash, carried = carry(archive)
    after = verify_chain()
    print(f"archived   {archive}  rows {n}  head {head}")
    print(f"archived verify  {v}")
    print(f"mirror     {mirror_archive if mirror_archive.exists() else '(none)'}")
    print(f"anchor     chain_rotated  hash {anchor}")
    _report_carry(carried_hash, carried)
    print(f"new chain  ok {after['ok']}, rows {after['rows']}")
    return 0 if after["ok"] and after["rows"] == 2 else 1


if __name__ == "__main__":
    sys.exit(main())
