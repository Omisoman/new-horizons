"""Agent tools — pure functions behind the JSON tool protocol.

Every tool returns a JSON-serializable dict. The graph audits calls; tools
stay side-effect-free (sql_query runs on the READ-ONLY role).

This module holds the tools any toolset can use: read-only SQL, the knowledge
base and the audit trail. A domain adds its own with `register()` — the farm
app registers its analytics tools from app/analytics/agent_tools.py — so the
harness never imports an app.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

from new_horizons.paths import data_path

MAX_ROWS = 200


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- tools ------------------------------------------------------------------

def sql_query(sql: str) -> dict:
    """Read-only SQL against the five schemas (role farm_ro)."""
    import psycopg
    stmt = sql.strip().rstrip(";")
    if ";" in stmt:
        return {"error": "one statement only"}
    if not re.match(r"^(select|with)\b", stmt, re.I):
        return {"error": "SELECT/WITH queries only (read-only role)"}
    dsn = os.environ.get("DATABASE_URL_RO",
                         "postgresql://farm_ro:farm-ro@localhost:5432/horizons")
    try:
        with psycopg.connect(dsn, options="-c statement_timeout=10000") as conn, \
                conn.cursor() as cur:
            cur.execute(stmt)
            cols = [d.name for d in cur.description]
            rows = cur.fetchmany(MAX_ROWS)
        out = {"columns": cols,
               "rows": [[None if v is None else str(v) for v in r] for r in rows],
               "row_count": len(rows), "truncated": len(rows) == MAX_ROWS}
        hint = None if rows else _sql_hint(stmt)
        if hint:
            # an empty result the schema says was impossible is a broken query, not
            # "no data" — as an error the model retries (a note was read past: "no
            # record found" for a code that exists in another format)
            return {"error": f"the query returned no rows and cannot return any — hint: {hint}"}
        return out
    except Exception as exc:
        hint = _sql_hint(stmt, str(exc))
        return {"error": f"{exc}".strip() + (f" — hint: {hint}" if hint else "")}


def _sql_hint(sql: str, error: str | None = None) -> str | None:
    """A schema-derived explanation for an error or an empty result (observed:
    a code compared with a numeric id three times over, and two code columns
    joined that never hold the same values). Never raises, never blocks."""
    try:
        from new_horizons.shared.db.introspect import sql_hint
        return sql_hint(sql, error)
    except Exception:
        return None


def kb_search(query: str, k: int = 6, synthetic: bool | None = None) -> dict:
    """Semantic search over the knowledge base (the Farm's procedures)."""
    return kb_search_in(data_path(os.environ.get("KB_DIR"), "kb"), query, k, synthetic)


def kb_search_in(kb_dir: str | Path, query: str, k: int = 6,
                 synthetic: bool | None = None) -> dict:
    """kb_search against an explicit KB directory — how host tenants get
    their own KB. Deliberately not in REGISTRY: the path is never model-chosen."""
    from new_horizons.shared.kb.store import KB
    where = {"synthetic": synthetic} if synthetic is not None else None
    hits = KB(str(kb_dir)).search(query, k=int(k), where=where)
    return {"hits": [{
        "source": h["meta"]["source"], "section": str(h["meta"].get("section", "")),
        "heading": h["meta"].get("heading", ""), "page": h["meta"].get("page"),
        "synthetic": h["meta"].get("synthetic", True),
        "text": h["text"][:700],
    } for h in hits]}


def audit_trail(subject: str = "", limit: int = 20) -> dict:
    """Who did what to one finding, from the hash-chained audit log. With no
    subject: the most recent human decisions across all findings — which items
    were held, escalated or approved, and by whom."""
    from new_horizons.shared.audit.audit import decisions, events
    subject = (subject or "").strip()
    if not subject:
        # Test rows stay in the chain (it is append-only) but never in the
        # operational view: the suite writes decisions as pytest-* actors.
        recent = sorted(((k, v) for k, v in decisions().items()
                         if not str(v.get("approver", "")).startswith("pytest")),
                        key=lambda kv: kv[1]["ts"], reverse=True)
        return {"recent_decisions": [
            {"subject": k, "decision": v["decision"], "approver": v["approver"],
             "ts": v["ts"].isoformat(timespec="seconds"), "rule": v["rule"],
             "detail": v.get("subject_label")} for k, v in recent[:int(limit)]],
            "total": len(recent)}
    rows = events(limit=int(limit), contains=subject)
    out = []
    for e in rows:
        p = e.get("payload") or {}
        out.append({"ts": e["ts"].isoformat(timespec="seconds"), "actor": e["actor"],
                    "action": e["event_type"], "decision": p.get("decision"),
                    "rule": p.get("rule"), "detail": p.get("detail") or p.get("subject_label"),
                    "hash": e["hash"][:12]})
    # the decision is looked up directly, not hoped for inside the recent window
    d = decisions(subject).get(subject)
    decided = ({"decision": d["decision"], "approver": d["approver"], "rule": d["rule"],
                "ts": d["ts"].isoformat(timespec="seconds")} if d else None)
    return {"subject": subject, "events": out, "total": len(out),
            "latest_decision": decided,
            "note": "append-only, hash-chained; each row carries the head of its own hash"}


def _schemas() -> str:
    from new_horizons.shared.db.introspect import SCHEMAS
    return ", ".join(SCHEMAS)


REGISTRY: dict[str, dict] = {
    "sql_query": {
        "fn": sql_query,
        "description": "Run ONE read-only SQL query (SELECT/WITH) over the five farm "
                       f"schemas ({_schemas()}); the tables and columns are listed "
                       "under Databases. Synthetic data; systems join on unit_id and "
                       "the other business keys listed there.",
        "args": {"sql": "string (a single SELECT)"},
    },
    "kb_search": {
        "fn": kb_search,
        "description": "Semantic search over the Farm's knowledge base: water-quality "
                       "and feeding SOPs, pump and aeration maintenance, sensor "
                       "calibration, harvest and shipping, biosecurity, alert "
                       "escalation, supplier invoice controls, data dictionary. Cite "
                       "hits as source + section.",
        "args": {"query": "string", "k": "int (default 6)"},
    },
    "audit_trail": {
        "fn": audit_trail,
        "description": "Who approved, escalated or rejected a finding, when, and under "
                       "which rule — plus the agent's own model/tool calls for it, and "
                       "the deploys sojourner shipped. Reads the hash-chained "
                       "audit log. Use for 'who approved that hold?'.",
        "args": {"subject": 'string|empty — unit, work order, shipment or rule, e.g. '
                            '"AQ-03"; empty = the most recent decisions',
                 "limit": "int (default 20)"},
    },
}


def register(name: str, fn, description: str, args: dict) -> None:
    """Add a domain tool to the registry (idempotent: re-registering replaces)."""
    REGISTRY[name] = {"fn": fn, "description": description, "args": args}


def run_tool(name: str, args: dict) -> dict:
    if name not in REGISTRY:
        return {"error": f"unknown tool '{name}'. Available: {list(REGISTRY)}"}
    try:
        return REGISTRY[name]["fn"](**args)
    except TypeError as exc:
        return {"error": f"bad args for {name}: {exc}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
