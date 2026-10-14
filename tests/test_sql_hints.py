"""SQL hints — the code mistakes a small model repeats, explained from the schema.

`shared.db.introspect.sql_hint` reads a failed or empty query against the live
code formats (here a fixed map) and says what the values actually look like.
A hint only ever rides on an error or an empty result: a query that returns rows
is never touched, and an empty result becomes an error only when the schema
shows it could never have returned anything.
"""

import os

import pytest

from new_horizons.shared.db.introspect import sql_hint

COLUMNS = {
    "technician_code": {"tables": ["maintenance.technicians"], "shapes": {"TEC-NN"}},
    "unit_id": {"tables": ["telemetry.units", "telemetry.readings", "harvest.harvests"],
                "shapes": {"AQ-NN"}},
    "supplier_ref": {"tables": ["supplies.suppliers", "supplies.purchases"], "shapes": {"SUP-NNN"}},
    "item_code": {"tables": ["supplies.items", "supplies.purchases"],
                  "shapes": {"FEED-NN", "NUT-NN", "PART-NN"}},
    "work_order_no": {"tables": ["maintenance.work_orders"], "shapes": {"WO-NNNN-NNNN"}},
}


def test_a_code_compared_with_a_numeric_id_points_at_the_code_column():
    hint = sql_hint("SELECT count(*) FROM maintenance.work_orders WHERE technician_id = 'TEC-06'",
                    'invalid input syntax for type integer: "TEC-06"', COLUMNS)
    assert "technician_code in maintenance.technicians" in hint and "technician_code = 'TEC-06'" in hint


def test_the_unit_id_is_a_code_not_a_numeric_id():
    """unit_id ends in _id but holds AQ-NN: comparing it with a code is right."""
    assert sql_hint("SELECT count(*) FROM telemetry.readings WHERE unit_id = 'AQ-03'", None, COLUMNS) is None
    hint = sql_hint("SELECT 1 FROM telemetry.readings WHERE unit_id = 'AQ-3'", None, COLUMNS)
    assert hint == "unit_id values look like AQ-NN; 'AQ-3' never matches"


def test_a_join_of_two_code_formats_that_never_match_says_so():
    hint = sql_hint("SELECT * FROM supplies.purchases p JOIN supplies.items i "
                    "ON p.supplier_ref = i.item_code", None, COLUMNS)
    assert "supplier_ref and item_code never hold the same values" in hint


TABLES = {
    "harvest.harvests": ["harvest_id", "harvest_no", "date", "unit_id", "plant", "kg", "logged_by"],
    "harvest.shipments": ["shipment_id", "shipment_ref", "date", "unit_id", "harvest_no", "kg",
                          "customer_ref", "eur"],
    "telemetry.units": ["unit_id", "plant", "grow_bed_m2", "fish_count"],
}


def test_a_missing_column_names_its_table_and_the_join_key():
    hint = sql_hint("SELECT sum(eur) FROM harvest.harvests WHERE plant = 'basil'",
                    'column "eur" does not exist', COLUMNS, TABLES)
    assert "eur is a column of harvest.shipments — join it on harvest_no, unit_id" in hint
    nowhere = sql_hint("SELECT sum(revenue) FROM harvest.harvests", "column h.revenue does not exist",
                       COLUMNS, TABLES)
    assert "harvest.harvests has no revenue; its columns are harvest_id" in nowhere


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM maintenance.work_orders w JOIN maintenance.technicians t "
    "USING (technician_id) WHERE t.technician_code = 'TEC-06'",
    "SELECT * FROM supplies.purchases WHERE item_code = 'FEED-01'",
    "SELECT count(*) FROM controller.alerts WHERE status = 'open'",
])
def test_a_correct_query_gets_no_hint(sql):
    assert sql_hint(sql, None, COLUMNS) is None


def _db_up() -> bool:
    try:
        import psycopg
        psycopg.connect(os.environ.get("DATABASE_URL_RO",
                                       "postgresql://farm_ro:farm-ro@localhost:5432/horizons"),
                        connect_timeout=3).close()
        return True
    except Exception:
        return False


@pytest.mark.domain
@pytest.mark.skipif(not _db_up(), reason="postgres not running")
def test_sql_query_carries_the_hint_on_the_live_database():
    from new_horizons.shared.db.introspect import code_columns
    from new_horizons.shared.harness.tools import sql_query
    code_columns.cache_clear()
    failed = sql_query("SELECT count(*) FROM maintenance.work_orders WHERE technician_id = 'TEC-06'")
    assert "error" in failed and "technician_code = 'TEC-06'" in failed["error"]
    fixed = sql_query("SELECT count(*) FROM maintenance.work_orders w JOIN maintenance.technicians t "
                      "USING (technician_id) WHERE t.technician_code = 'TEC-06'")
    assert "error" not in fixed and int(fixed["rows"][0][0]) > 0
    nothing = sql_query("SELECT count(*) FROM telemetry.readings WHERE unit_id = 'AQ-03' "
                        "AND ph < 5")
    assert nothing["rows"] == [["0"]]              # a real zero stays a result
    read_only = sql_query("DELETE FROM telemetry.readings")
    assert "SELECT/WITH queries only" in read_only["error"]
