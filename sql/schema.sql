-- n8n-circuit-breaker-pack -- Postgres schema
--
-- Run once against the database your n8n Postgres credential points at.
-- You can point it at n8n's own database or (preferred) a separate one, so a
-- breaker read never competes with n8n's execution writes.
--
--   psql "$DATABASE_URL" -f sql/schema.sql
--
-- Everything here is IF NOT EXISTS / idempotent: re-running it is safe.

BEGIN;

-- ---------------------------------------------------------------- spend cap
-- One row per (workflow_key, window). The window is a date_trunc unit:
-- 'hour', 'day', 'week', 'month'. The module writes date_trunc(<unit>, now()).
CREATE TABLE IF NOT EXISTS spend_counter (
    id            bigserial     PRIMARY KEY,
    workflow_key  text          NOT NULL,
    window_start  timestamptz   NOT NULL,
    cost_usd      numeric(14,6) NOT NULL DEFAULT 0,
    call_count    integer       NOT NULL DEFAULT 0,
    updated_at    timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT spend_counter_window_uniq UNIQUE (workflow_key, window_start),
    CONSTRAINT spend_counter_cost_nonneg CHECK (cost_usd >= 0)
);

-- The upsert hits the unique index; this one serves "show me recent spend".
CREATE INDEX IF NOT EXISTS spend_counter_key_window_desc_idx
    ON spend_counter (workflow_key, window_start DESC);

-- ------------------------------------------------------------ breaker state
-- One row per protected workflow. 'open' means: do not start new work.
-- Reset is deliberately manual (see README) -- there is no auto half-open.
CREATE TABLE IF NOT EXISTS breaker_state (
    workflow_key text        PRIMARY KEY,
    state        text        NOT NULL DEFAULT 'closed',
    reason       text,
    tripped_at   timestamptz,
    reset_at     timestamptz,
    tripped_by   text,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT breaker_state_state_chk CHECK (state IN ('closed', 'open'))
);

-- "Which breakers are currently open?" on a dashboard / morning check.
CREATE INDEX IF NOT EXISTS breaker_state_open_idx
    ON breaker_state (tripped_at DESC)
    WHERE state = 'open';

-- -------------------------------------------------------------- kill switch
-- scope = 'global' stops everything. scope = <workflow_key> stops one workflow.
-- Both are checked on every entry; either one engaged means stop.
CREATE TABLE IF NOT EXISTS kill_switch (
    scope       text        PRIMARY KEY,
    engaged     boolean     NOT NULL DEFAULT false,
    reason      text,
    engaged_at  timestamptz,
    engaged_by  text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO kill_switch (scope, engaged, reason)
VALUES ('global', false, 'initial seed')
ON CONFLICT (scope) DO NOTHING;

-- ------------------------------------------------------------ execution log
-- Rolling window feed for the error-rate breaker. One row per protected run.
CREATE TABLE IF NOT EXISTS execution_log (
    id            bigserial   PRIMARY KEY,
    workflow_key  text        NOT NULL,
    execution_id  text,
    status        text        NOT NULL,
    error_message text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT execution_log_status_chk CHECK (status IN ('success', 'error'))
);

-- The window query is: WHERE workflow_key = $1 ORDER BY created_at DESC LIMIT $2
CREATE INDEX IF NOT EXISTS execution_log_key_time_desc_idx
    ON execution_log (workflow_key, created_at DESC, id DESC);

-- --------------------------------------------------------- iteration budget
-- One row per (workflow_key, run_key). run_key is usually the n8n execution id,
-- so a single agent run has one counter no matter how many loop turns it takes.
CREATE TABLE IF NOT EXISTS iteration_counter (
    workflow_key text        NOT NULL,
    run_key      text        NOT NULL,
    iterations   integer     NOT NULL DEFAULT 0,
    started_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workflow_key, run_key)
);

-- Used by the housekeeping delete below.
CREATE INDEX IF NOT EXISTS iteration_counter_started_idx
    ON iteration_counter (started_at);

COMMIT;

-- ------------------------------------------------------------- housekeeping
-- These tables grow. Run something like this on a schedule (pg_cron, or an
-- n8n schedule workflow). Keep enough execution_log rows to cover your window.
--
--   DELETE FROM execution_log      WHERE created_at < now() - interval '30 days';
--   DELETE FROM iteration_counter  WHERE started_at < now() - interval '7 days';
--   DELETE FROM spend_counter      WHERE window_start < now() - interval '365 days';

-- --------------------------------------------------------------- manual ops
-- Reset a tripped breaker (deliberately a human action):
--   UPDATE breaker_state
--      SET state = 'closed', reset_at = now(), updated_at = now()
--    WHERE workflow_key = 'your-workflow-key';
--
-- Engage / release the global kill switch from psql:
--   UPDATE kill_switch
--      SET engaged = true, reason = 'runaway agent', engaged_at = now(),
--          engaged_by = 'you', updated_at = now()
--    WHERE scope = 'global';
--
-- See today's spend:
--   SELECT workflow_key, window_start, cost_usd, call_count
--     FROM spend_counter
--    WHERE window_start >= date_trunc('day', now())
--    ORDER BY cost_usd DESC;
