-- ===========================================================================
-- Power — TimescaleDB schema for home energy monitoring
-- Runs automatically on first start of the timescaledb container
-- (mounted into /docker-entrypoint-initdb.d). Safe to re-run by hand.
-- ===========================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- --- Raw readings (one row per channel per sample) --------------------------
CREATE TABLE IF NOT EXISTS readings (
    ts         TIMESTAMPTZ      NOT NULL,
    device_id  TEXT             NOT NULL,   -- e.g. 'sim-board', 'shelly-mains'
    channel    SMALLINT         NOT NULL,   -- CT clamp index within the device
    power_w    DOUBLE PRECISION NOT NULL,   -- instantaneous real power (W)
    voltage_v  DOUBLE PRECISION,
    current_a  DOUBLE PRECISION,
    pf         REAL,                        -- power factor
    energy_wh  DOUBLE PRECISION             -- cumulative meter counter (Wh), if available
);

SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS readings_dev_chan_ts
    ON readings (device_id, channel, ts DESC);

-- --- Channel -> appliance mapping (what makes the dashboard human-readable) --
-- role = 'mains' is the whole-house incomer; 'appliance' are the itemised loads.
-- "Rest of house" is then derived as mains - sum(appliances).
CREATE TABLE IF NOT EXISTS channels (
    device_id  TEXT     NOT NULL,
    channel    SMALLINT NOT NULL,
    appliance  TEXT     NOT NULL,
    role       TEXT     NOT NULL DEFAULT 'appliance',  -- 'mains' | 'appliance'
    PRIMARY KEY (device_id, channel)
);

-- Seed the simulator's channel map so the stack is meaningful out of the box.
-- Replace / add rows to match your real CT placement after install.
INSERT INTO channels (device_id, channel, appliance, role) VALUES
    ('sim-board', 0, 'Mains (whole house)', 'mains'),
    ('sim-board', 1, 'Spa Pool',            'appliance'),
    ('sim-board', 2, 'Ducted Heat Pump',    'appliance'),
    ('sim-board', 3, 'Oven',                'appliance')
ON CONFLICT (device_id, channel) DO NOTHING;

-- --- 1-minute continuous aggregate (keeps dashboards fast over years) --------
-- Stores avg/max power plus first/last cumulative energy so true energy can be
-- derived downstream as (energy_last - energy_first). Kept as separate columns
-- for maximum compatibility (no expressions-on-aggregates required).
CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1m
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', ts) AS bucket,
       device_id,
       channel,
       avg(power_w)        AS avg_w,
       max(power_w)        AS max_w,
       first(energy_wh, ts) AS energy_first,
       last(energy_wh, ts)  AS energy_last
FROM readings
GROUP BY bucket, device_id, channel
WITH NO DATA;

-- Real-time aggregation ON: queries union materialized buckets with the latest raw
-- rows, so the dashboard shows the current (still-filling) minute immediately.
-- (Recent TimescaleDB defaults new aggregates to materialized_only = true.)
ALTER MATERIALIZED VIEW readings_1m SET (timescaledb.materialized_only = false);

-- Refresh recent buckets every minute (background worker keeps history compacted).
SELECT add_continuous_aggregate_policy('readings_1m',
    start_offset      => INTERVAL '2 hours',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => TRUE);

-- --- Daily rollup for long-horizon trend charts -----------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS readings_1d
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 day', ts) AS bucket,
       device_id,
       channel,
       avg(power_w)        AS avg_w,
       max(power_w)        AS max_w,
       first(energy_wh, ts) AS energy_first,
       last(energy_wh, ts)  AS energy_last
FROM readings
GROUP BY bucket, device_id, channel
WITH NO DATA;

ALTER MATERIALIZED VIEW readings_1d SET (timescaledb.materialized_only = false);

SELECT add_continuous_aggregate_policy('readings_1d',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);

-- --- Convenience view: whole-house total + derived "rest of house" -----------
-- Used directly by the Grafana dashboard.
CREATE OR REPLACE VIEW house_power_1m AS
WITH agg AS (
    SELECT r.bucket,
           sum(r.avg_w) FILTER (WHERE c.role = 'mains')     AS house_w,
           sum(r.avg_w) FILTER (WHERE c.role = 'appliance') AS metered_w
    FROM readings_1m r
    JOIN channels c USING (device_id, channel)
    GROUP BY r.bucket
)
SELECT bucket,
       house_w,
       metered_w,
       greatest(coalesce(house_w, 0) - coalesce(metered_w, 0), 0) AS rest_of_house_w
FROM agg;

-- --- Storage hygiene: compression + retention -------------------------------
-- Compress raw rows older than 7 days (typically 10-20x smaller).
ALTER TABLE readings SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, channel',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('readings', INTERVAL '7 days', if_not_exists => TRUE);

-- Drop raw rows older than 90 days. The 1m / 1d aggregates are tiny and kept
-- indefinitely, so multi-year trends survive even after raw data is gone.
SELECT add_retention_policy('readings', INTERVAL '90 days', if_not_exists => TRUE);
