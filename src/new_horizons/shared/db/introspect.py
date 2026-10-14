"""The schema section of the analytics prompt, generated from the database.

information_schema gives tables and columns; pg_catalog gives foreign keys
(readable by the read-only role, unlike information_schema's constraint views).
Low-cardinality text columns list their values, so the model never guesses
`status = 'in force'`; date columns carry their range; business keys shared
across systems are derived from column names, not typed. Cached per process —
the demo schema does not change while the app runs.
"""

from __future__ import annotations

import functools
import os
import re

SCHEMAS = ("telemetry", "controller", "maintenance", "harvest", "supplies")
MAX_VALUES = 12          # enumerate a text column with at most this many values, each repeated
LOOKUP_ROWS = 1000       # a unique *_code in a table this small is a record code users name
_TEXT = ("text", "character varying", "character")
_DATE = ("date", "timestamp without time zone", "timestamp with time zone")
_CODE_SUFFIXES = ("_no", "_ref", "_code")
# text codes whose name ends in _id: the grow unit (AQ-01) is the farm-wide key
_CODE_COLUMNS = ("unit_id",)


def _dsn() -> str:
    return os.environ.get("DATABASE_URL_RO", "postgresql://farm_ro:farm-ro@localhost:5432/horizons")


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _is_code(column: str) -> bool:
    return column.endswith(_CODE_SUFFIXES) or column in _CODE_COLUMNS


def _business_key(column: str) -> str | None:
    return column if _is_code(column) else None


@functools.lru_cache(maxsize=4)
def schema_digest(dsn: str | None = None, schemas: tuple[str, ...] = SCHEMAS) -> str:
    """Markdown for the system prompt. Raises if the database is unreachable —
    callers decide whether to run without it."""
    import psycopg
    with psycopg.connect(dsn or _dsn(), connect_timeout=5,
                         options="-c statement_timeout=20000") as conn, conn.cursor() as cur:
        cur.execute("""SELECT table_schema, table_name, column_name, data_type
                       FROM information_schema.columns WHERE table_schema = ANY(%s)
                       ORDER BY table_schema, table_name, ordinal_position""", (list(schemas),))
        tables: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for s, t, c, dt in cur.fetchall():
            tables.setdefault((s, t), []).append((c, dt))
        cur.execute("""
            SELECT cn.nspname, c.relname, a.attname, fn.nspname, f.relname, fa.attname
            FROM pg_constraint k
            JOIN pg_class c ON c.oid = k.conrelid
            JOIN pg_namespace cn ON cn.oid = c.relnamespace
            JOIN pg_class f ON f.oid = k.confrelid
            JOIN pg_namespace fn ON fn.oid = f.relnamespace
            JOIN LATERAL unnest(k.conkey, k.confkey) AS u(ck, fk) ON true
            JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.ck
            JOIN pg_attribute fa ON fa.attrelid = k.confrelid AND fa.attnum = u.fk
            WHERE k.contype = 'f' AND cn.nspname = ANY(%s)""", (list(schemas),))
        fks = {(s, t, c): (fs, ft, fc) for s, t, c, fs, ft, fc in cur.fetchall()}

        annotations: dict[tuple[str, str, str], str] = {}
        lookup_keys: set[str] = set()
        for (s, t), cols in tables.items():
            texts = [c for c, dt in cols if dt in _TEXT]
            dates = [c for c, dt in cols if dt in _DATE]
            exprs = (["count(*)"] + [f"count(DISTINCT {_q(c)})" for c in texts]
                     + [f"min({_q(c)})::date::text, max({_q(c)})::date::text" for c in dates])
            cur.execute(f"SELECT {', '.join(exprs)} FROM {_q(s)}.{_q(t)}")
            row = cur.fetchone()
            n_rows, distinct = row[0], dict(zip(texts, row[1:1 + len(texts)]))
            bounds = row[1 + len(texts):]
            for i, c in enumerate(dates):
                lo, hi = bounds[2 * i], bounds[2 * i + 1]
                if lo:
                    annotations[(s, t, c)] = f"[{lo}..{hi}]"
            # a category repeats: work_orders.outcome (4 values, 600 rows) is one,
            # technicians.name (8 values, 8 rows) is not
            enum = [c for c in texts if 0 < distinct[c] <= MAX_VALUES and distinct[c] * 2 <= n_rows]
            if enum:
                cur.execute("SELECT " + ", ".join(
                    f"array_agg(DISTINCT {_q(c)} ORDER BY {_q(c)})" for c in enum)
                    + f" FROM {_q(s)}.{_q(t)}")
                for c, values in zip(enum, cur.fetchone()):
                    annotations[(s, t, c)] = "{" + "|".join(v for v in values if v is not None) + "}"
            # code columns carry their format, so "unit 3" can become AQ-03 in SQL
            for c in texts:
                if c in enum or not c.endswith(_CODE_SUFFIXES):
                    continue
                cur.execute(f"SELECT regexp_replace({_q(c)}, '[0-9]', 'N', 'g'), min({_q(c)}), "
                            f"max({_q(c)}) FROM {_q(s)}.{_q(t)} WHERE {_q(c)} IS NOT NULL "
                            "GROUP BY 1 ORDER BY count(*) DESC LIMIT 5")
                shapes = cur.fetchall()
                if len(shapes) == 1:
                    annotations[(s, t, c)] = f"<{shapes[0][1]}..{shapes[0][2]}>"
                elif 1 < len(shapes) <= 4:
                    annotations[(s, t, c)] = "<" + "|".join(x[0] for x in shapes) + ">"
                if c.endswith("_code") and n_rows <= LOOKUP_ROWS and distinct[c] == n_rows:
                    lookup_keys.add(c)

    key_schemas: dict[str, set[str]] = {}
    for (s, _t), cols in tables.items():
        for c, _dt in cols:
            k = _business_key(c)
            if k:
                key_schemas.setdefault(k, set()).add(s)
    shared = sorted({k for k, ss in key_schemas.items() if len(ss) > 1} | lookup_keys)

    lines = ["## Databases (generated from the live schema)",
             "Read-only Postgres, SYNTHETIC data. `{a|b}` = every value the column holds; "
             "`<first..last>` or `<FORMAT|FORMAT>` = a code column's values (N = digit); "
             "`[from..to]` = its date range; `→` = foreign key within a system. "
             f"Systems join only on business keys: {', '.join(shared)}."]
    for (s, t), cols in tables.items():
        parts = []
        for c, _dt in cols:
            fk = fks.get((s, t, c))
            ref = f"→{fk[1]}" if fk and fk[0] == s else ""
            parts.append(f"{c}{ref}{annotations.get((s, t, c), '')}")
        lines.append(f"- {s}.{t}: {', '.join(parts)}")
    return "\n".join(lines)


# ---- SQL hints: the mistakes an 8B model repeats, answered from the live formats --

_LITERAL_CODE = re.compile(r"\b(\w+)\s*=\s*'([A-Za-z]{1,5}(?:-[A-Za-z0-9]+)+)'")
_COLUMN_EQ = re.compile(r"\b(?:\w+\.)?(\w+)\s*=\s*(?:\w+\.)?(\w+)\b")
_MISSING_COLUMN = re.compile(r'column "?(?:\w+\.)?(\w+)"? does not exist', re.I)
_TABLES_IN = re.compile(r"\b(?:from|join)\s+(\w+\.\w+)", re.I)


@functools.lru_cache(maxsize=4)
def table_columns(dsn: str | None = None, schemas: tuple[str, ...] = SCHEMAS) -> dict[str, list[str]]:
    """{"schema.table": [columns]} from information_schema."""
    import psycopg
    out: dict[str, list[str]] = {}
    with psycopg.connect(dsn or _dsn(), connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("""SELECT table_schema, table_name, column_name FROM information_schema.columns
                       WHERE table_schema = ANY(%s) ORDER BY table_schema, table_name, ordinal_position""",
                    (list(schemas),))
        for s, t, c in cur.fetchall():
            out.setdefault(f"{s}.{t}", []).append(c)
    return out


def _missing_column_hint(sql: str, error: str, tables: dict[str, list[str]]) -> list[str]:
    """`column "kg" does not exist` on harvest.shipments → where kg lives and
    the key that joins it (within a system an _id, across systems a business key)."""
    m = _MISSING_COLUMN.search(error or "")
    if not m:
        return []
    col, used = m.group(1), [t for t in _TABLES_IN.findall(sql) if t in tables]
    owners = [t for t, cs in tables.items() if col in cs and t not in used]
    hints = []
    for owner in owners[:2]:
        keys = sorted({c for u in used for c in tables[u] if c in tables[owner] and (
            _is_code(c) or (c.endswith("_id") and u.split(".")[0] == owner.split(".")[0]))})
        hints.append(f"{col} is a column of {owner}" + (f" — join it on {', '.join(keys)}" if keys else ""))
    if not owners and used:
        hints.append(f"{used[0]} has no {col}; its columns are {', '.join(tables[used[0]])}")
    return hints


def _shape(value: str) -> str:
    return re.sub(r"[0-9]", "N", value)


@functools.lru_cache(maxsize=4)
def code_columns(dsn: str | None = None, schemas: tuple[str, ...] = SCHEMAS) -> dict[str, dict]:
    """{column: {"tables": [...], "shapes": {...}}} for every *_code / *_no / *_ref
    text column (and unit_id) whose values take at most four shapes (N = digit)."""
    import psycopg
    out: dict[str, dict] = {}
    with psycopg.connect(dsn or _dsn(), connect_timeout=5,
                         options="-c statement_timeout=20000") as conn, conn.cursor() as cur:
        cur.execute("""SELECT table_schema, table_name, column_name FROM information_schema.columns
                       WHERE table_schema = ANY(%s) AND data_type = ANY(%s)
                       ORDER BY table_schema, table_name, ordinal_position""",
                    (list(schemas), list(_TEXT)))
        for s, t, c in cur.fetchall():
            if not _is_code(c):
                continue
            cur.execute(f"SELECT regexp_replace({_q(c)}, '[0-9]', 'N', 'g') FROM {_q(s)}.{_q(t)} "
                        f"WHERE {_q(c)} IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 5")
            shapes = [r[0] for r in cur.fetchall()]
            if 0 < len(shapes) <= 4:
                entry = out.setdefault(c, {"tables": [], "shapes": set()})
                entry["tables"].append(f"{s}.{t}")
                entry["shapes"].update(shapes)
    return out


def sql_hint(sql: str, error: str | None = None, columns: dict | None = None,
             tables: dict | None = None) -> str | None:
    """What went wrong with a query that errored or returned no rows, when it is
    one of the code mistakes the schema can explain:
    - a code compared with a numeric id: `technician_id = 'TEC-07'`
    - a literal in the wrong format for its column: `unit_id = 'AQ-3'`
    - a join of two code columns that never hold the same values:
      `supplier_ref = item_code` (SUP-NNN vs FEED-NNN)
    Returns None when nothing applies — a hint never blocks a query."""
    hints: list[str] = []
    if error and _MISSING_COLUMN.search(error):
        hints += _missing_column_hint(sql, error, table_columns() if tables is None else tables)
    cols = code_columns() if columns is None else columns
    owners: dict[str, tuple[str, str]] = {}
    for name, entry in cols.items():
        for shape in entry["shapes"]:
            owners.setdefault(shape, (name, entry["tables"][0]))
    for col, value in _LITERAL_CODE.findall(sql):
        shape = _shape(value)
        if col.endswith("_id") and col not in cols:      # unit_id is a text code, not an id
            if shape in owners:
                name, table = owners[shape]
                hints.append(f"{col} holds numeric ids; '{value}' is a {name} in {table} — join "
                             f"{table} and filter {name} = '{value}'")
        elif col in cols and shape not in cols[col]["shapes"]:
            wider = sorted(s for s in cols[col]["shapes"] if s.endswith(shape))
            if wider:
                hints.append(f"{col} values look like {wider[0]}, not {shape} — try {col} = "
                             f"'{wider[0][:-len(shape)]}{value}'")
            else:
                hints.append(f"{col} values look like {'|'.join(sorted(cols[col]['shapes']))}; "
                             f"'{value}' never matches")
    for a, b in _COLUMN_EQ.findall(sql):
        if a == b or a not in cols or b not in cols or cols[a]["shapes"] & cols[b]["shapes"]:
            continue
        for x, y in ((a, b), (b, a)):
            wider = sorted(sy for sy in cols[y]["shapes"] for sx in cols[x]["shapes"]
                           if sy.endswith(sx) and sy != sx)
            narrow = next((sx for sx in sorted(cols[x]["shapes"]) if wider and wider[0].endswith(sx)), None)
            if wider and narrow:
                hints.append(f"{x} values look like {narrow} but {y} values look like {wider[0]}, "
                             f"so they never match — compare {y} = "
                             f"'{wider[0][:-len(narrow)]}' || {x}")
                break
        else:
            hints.append(f"{a} and {b} never hold the same values "
                         f"({'|'.join(sorted(cols[a]['shapes']))} vs "
                         f"{'|'.join(sorted(cols[b]['shapes']))})")
    return "; ".join(dict.fromkeys(hints)) or None
