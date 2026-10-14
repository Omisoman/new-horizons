"""Shared data access for the analytics modules (read-only is enough).

The five farm systems live in their own Postgres schemas; `frames()` hands
them to pandas under short names. Citation keys resolve through
ingest/kb_synthetic/citations.yaml — the one contract with the KB corpus.
"""

from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache

import pandas as pd
import yaml

from new_horizons.paths import APP, DATA

OUT = DATA / "analytics"
META = DATA / "mock_meta.json"

TABLES = {
    "units": "telemetry.units", "readings": "telemetry.readings",
    "commands": "controller.commands", "alerts": "controller.alerts",
    "technicians": "maintenance.technicians", "work_orders": "maintenance.work_orders",
    "customers": "harvest.customers", "harvests": "harvest.harvests",
    "shipments": "harvest.shipments", "suppliers": "supplies.suppliers",
    "items": "supplies.items", "purchases": "supplies.purchases",
    "consumption": "supplies.consumption",
}
DATES = {
    "readings": ["ts"], "commands": ["ts"],
    "alerts": ["opened_ts", "acknowledged_ts", "resolved_ts"],
    "work_orders": ["opened_ts", "closed_ts"], "harvests": ["date"], "shipments": ["date"],
    "purchases": ["ordered", "received"], "consumption": ["date"],
}


def dsn() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://horizons:horizons@localhost:5432/horizons")


def dsn_ro() -> str:
    return os.environ.get("DATABASE_URL_RO", "postgresql://farm_ro:farm-ro@localhost:5432/horizons")


@lru_cache(maxsize=1)
def profile() -> dict:
    return yaml.safe_load((APP / "profile.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def citations() -> dict:
    return yaml.safe_load(
        (APP / "ingest" / "kb_synthetic" / "citations.yaml").read_text(encoding="utf-8"))


def cite(key: str | None, quote: str = "") -> dict | None:
    """Citation key -> {"key", "source", "section", "quote"} (None passes through)."""
    if not key:
        return None
    c = citations()[key]
    return {"key": key, "source": c["source"], "section": str(c["section"]), "quote": quote}


def currency() -> str:
    return profile()["market"]["currency"]


def period() -> tuple[pd.Timestamp, pd.Timestamp]:
    """[start, end) of the data period."""
    p = profile()["period"]
    start = pd.Timestamp(str(p["start"]))
    return start, start + pd.Timedelta(days=int(p["days"]))


def frames(names: list[str] | None = None) -> dict[str, pd.DataFrame]:
    import psycopg
    out: dict[str, pd.DataFrame] = {}
    with psycopg.connect(dsn_ro()) as conn, conn.cursor() as cur:
        for name in names or list(TABLES):
            cur.execute(f"SELECT * FROM {TABLES[name]}")  # noqa: S608 — fixed names
            cols = [d.name for d in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
            for c in DATES.get(name, []):
                df[c] = pd.to_datetime(df[c])
            for c in cols:
                first = df[c].dropna().iloc[0] if len(df) and df[c].notna().any() else None
                if isinstance(first, Decimal):
                    df[c] = df[c].astype(float)
            out[name] = df
    return out
