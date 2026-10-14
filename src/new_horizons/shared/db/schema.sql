-- new-horizons Postgres bootstrap — loaded by initdb on a fresh volume only.
--
-- The five synthetic farm systems (telemetry, controller, maintenance,
-- harvest, supplies) are NOT created here: `make mock` applies
-- shared/db/farm_schema.sql (drop + recreate) and COPY-loads them from
-- profile.yaml. This file holds only what must survive a data regeneration:
-- the audit chain (shared with sojourner, which writes its deploy
-- events into it) and the read-only role the agent's sql_query tool connects as.

-- Hash-chained append-only audit (mirrored to JSONL by shared/audit).
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

-- Read-only role for the sql_query tool (schema grants: farm_schema.sql).
CREATE ROLE farm_ro LOGIN PASSWORD 'farm-ro';
GRANT CONNECT ON DATABASE horizons TO farm_ro;
GRANT USAGE ON SCHEMA public TO farm_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO farm_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO farm_ro;
