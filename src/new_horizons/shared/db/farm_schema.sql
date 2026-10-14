-- The five farm systems — dropped and recreated by `make mock`
-- (app/mock/generate.py), COPY-loaded from profile.yaml. One schema per system.
-- Systems join only on business keys (unit_id, technician_code, item_code,
-- alert_no, harvest_no, po_no, invoice_no, supplier_ref, customer_ref) — never on
-- another system's numeric id. Foreign keys exist only inside a system.

DROP SCHEMA IF EXISTS telemetry, controller, maintenance, harvest, supplies CASCADE;

-- ---- telemetry: what actually happened -------------------------------------------
CREATE SCHEMA telemetry;

CREATE TABLE telemetry.units (
    unit_id        text PRIMARY KEY,               -- AQ-01 … AQ-04
    plant          text NOT NULL,                  -- pepper | lettuce | tomato | basil
    location       text NOT NULL,                  -- greenhouse-A | greenhouse-B | rooftop
    grow_bed_m2    numeric(6, 1) NOT NULL,
    fish_species   text NOT NULL,
    fish_count     integer NOT NULL,
    commissioned   date NOT NULL
);

CREATE TABLE telemetry.readings (                  -- every 15 minutes; a sensor dropout is a gap
    reading_id         bigint PRIMARY KEY,
    ts                 timestamp NOT NULL,
    unit_id            text NOT NULL REFERENCES telemetry.units,
    air_temp_c         numeric(5, 2),
    humidity_pct       numeric(5, 1),
    water_temp_c       numeric(5, 2),
    ph                 numeric(4, 2),
    dissolved_o2_mg_l  numeric(5, 2),
    water_level_cm     numeric(5, 1)
);
CREATE INDEX ON telemetry.readings (unit_id, ts);

-- ---- controller: what the system was told to do ----------------------------------
CREATE SCHEMA controller;

CREATE TABLE controller.commands (
    command_id   bigint PRIMARY KEY,
    ts           timestamp NOT NULL,
    unit_id      text NOT NULL,
    actuator     text NOT NULL,                    -- water_pump | air_pump | dosing_pump | feeder
    action       text NOT NULL,                    -- on | off | dose_ph_up | feed
    duration_s   integer NOT NULL,                 -- run time; 0 for a state change
    qty          numeric(8, 3),                    -- kg dispensed (feeder, dosing pump)
    trigger      text NOT NULL,                    -- low_level | low_do | do_recovered | weekly_dosing | feeding_schedule
    issued_by    text NOT NULL                     -- 'controller' or a technician_code
);
CREATE INDEX ON controller.commands (unit_id, ts);

CREATE TABLE controller.alerts (
    alert_id         integer PRIMARY KEY,
    alert_no         text NOT NULL UNIQUE,         -- AL-2026-NNNN
    unit_id          text NOT NULL,
    type             text NOT NULL,                -- low_water_level | low_dissolved_o2 | high_water_temp | high_air_temp | low_ph | high_ph
    value            numeric(6, 2) NOT NULL,       -- the reading that opened it
    threshold        numeric(6, 2) NOT NULL,
    opened_ts        timestamp NOT NULL,
    acknowledged_ts  timestamp,
    acknowledged_by  text,                         -- technician_code
    resolved_ts      timestamp,
    status           text NOT NULL                 -- open | resolved
);

-- ---- maintenance: who touched what -----------------------------------------------
CREATE SCHEMA maintenance;

CREATE TABLE maintenance.technicians (
    technician_id    integer PRIMARY KEY,
    technician_code  text NOT NULL UNIQUE,         -- TEC-01 … TEC-08
    name             text NOT NULL,
    role             text NOT NULL,                -- technician | senior technician
    started          date NOT NULL
);

CREATE TABLE maintenance.work_orders (
    work_order_id   integer PRIMARY KEY,
    work_order_no   text NOT NULL UNIQUE,          -- WO-2026-NNNN
    opened_ts       timestamp NOT NULL,
    unit_id         text NOT NULL,
    technician_id   integer NOT NULL REFERENCES maintenance.technicians,
    type            text NOT NULL,                 -- filter_clean | pump_service | sensor_calibration | dosing_check | pump_repair | alert_response | sensor_check
    alert_no        text,                          -- the controller alert it answers, if any
    closed_ts       timestamp,
    outcome         text NOT NULL,                 -- done | fixed | part_replaced | no_fault_found
    part_item_code  text,                          -- a supplies item fitted on the job
    notes           text NOT NULL DEFAULT ''
);

-- ---- harvest: what left the building ---------------------------------------------
CREATE SCHEMA harvest;

CREATE TABLE harvest.customers (
    customer_ref  text PRIMARY KEY,                -- CUS-01 …
    name          text NOT NULL,
    segment       text NOT NULL                    -- restaurant | grocer | market
);

CREATE TABLE harvest.harvests (
    harvest_id        integer PRIMARY KEY,
    harvest_no        text NOT NULL UNIQUE,        -- HV-2026-NNNN
    date              date NOT NULL,
    unit_id           text NOT NULL,
    plant             text NOT NULL,
    kg                numeric(8, 2) NOT NULL,
    logged_by         text NOT NULL,               -- technician_code
    countersigned_by  text,                        -- technician_code of the second signatory
    notes             text NOT NULL DEFAULT ''
);

CREATE TABLE harvest.shipments (
    shipment_id    integer PRIMARY KEY,
    shipment_ref   text NOT NULL UNIQUE,           -- SHP-2026-NNNN
    date           date NOT NULL,
    unit_id        text NOT NULL,
    harvest_no     text NOT NULL,
    kg             numeric(8, 2) NOT NULL,
    customer_ref   text NOT NULL REFERENCES harvest.customers,
    eur            numeric(10, 2) NOT NULL
);

-- ---- supplies: what was bought vs used -------------------------------------------
CREATE SCHEMA supplies;

CREATE TABLE supplies.suppliers (
    supplier_ref  text PRIMARY KEY,                -- SUP-001 …
    name          text NOT NULL,
    approved      boolean NOT NULL,                -- on the approved supplier list
    phone         text NOT NULL
);

CREATE TABLE supplies.items (
    item_code       text PRIMARY KEY,              -- FEED-01, NUT-01, PART-01 …
    name            text NOT NULL,
    category        text NOT NULL,                 -- feed | nutrient | part
    unit            text NOT NULL,                 -- kg | pcs
    list_price_eur  numeric(8, 2) NOT NULL
);

CREATE TABLE supplies.purchases (
    purchase_id     integer PRIMARY KEY,
    po_no           text NOT NULL UNIQUE,          -- PO-2026-NNNN
    ordered         date NOT NULL,
    received        date,
    supplier_ref    text NOT NULL REFERENCES supplies.suppliers,
    item_code       text NOT NULL REFERENCES supplies.items,
    qty             numeric(8, 2) NOT NULL,
    unit_price_eur  numeric(8, 2) NOT NULL,        -- the agreed price on the order
    eur             numeric(10, 2) NOT NULL,
    invoice_no      text,                          -- the supplier's invoice, once matched
    status          text NOT NULL                  -- invoiced | awaiting_invoice
);

CREATE TABLE supplies.consumption (
    consumption_id  integer PRIMARY KEY,
    date            date NOT NULL,
    unit_id         text NOT NULL,
    item_code       text NOT NULL REFERENCES supplies.items,
    qty             numeric(8, 3) NOT NULL,
    source          text NOT NULL                  -- feeder | dosing | work_order
);

-- ---- read-only role for the agent's sql_query tool -------------------------------
GRANT USAGE ON SCHEMA telemetry, controller, maintenance, harvest, supplies TO farm_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA telemetry, controller, maintenance, harvest, supplies TO farm_ro;
