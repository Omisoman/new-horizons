"""LangGraph Postgres checkpointer keyed by session (thread_id)."""

from __future__ import annotations

import os

_saver = None


def checkpointer():
    """Singleton PostgresSaver; tables created on first use."""
    global _saver
    if _saver is None:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection
        from psycopg.rows import dict_row
        dsn = os.environ.get("DATABASE_URL",
                             "postgresql://horizons:horizons@localhost:5432/horizons")
        conn = Connection.connect(dsn, autocommit=True, row_factory=dict_row,
                                  prepare_threshold=None)
        saver = PostgresSaver(conn)
        saver.setup()
        _saver = saver
    return _saver
