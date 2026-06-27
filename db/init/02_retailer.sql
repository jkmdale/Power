-- ===========================================================================
-- Power — retailer (Genesis) usage import + cost + appliance ESTIMATOR
-- Track B: extract value from the whole-house data you already have.
--
-- The Genesis "My Daily Usage" export is DAILY (one row per day: kWh + actual $).
-- Daily data is whole-house only and even coarser than hourly, so it CANNOT be
-- split into spa/heat pump/oven. The appliance figures here are ESTIMATES from
-- your own inputs. Accurate per-appliance numbers need CT-clamp hardware —
-- see docs/hardware-install.md.
-- ===========================================================================

-- --- Daily whole-house usage (matches the Genesis "My Daily Usage" CSV) ------
CREATE TABLE IF NOT EXISTS meter_daily_usage (
    day     DATE             NOT NULL,
    kwh     DOUBLE PRECISION NOT NULL,
    dollars NUMERIC,                          -- actual $ from Genesis (incl GST)
    type    TEXT,                             -- 'actual', 'powerShout', 'estimate', ...
    source  TEXT             NOT NULL DEFAULT 'genesis',
    PRIMARY KEY (day, source)
);

-- --- Optional: sub-daily/interval export, if your account can produce one -----
CREATE TABLE IF NOT EXISTS meter_hourly (
    ts     TIMESTAMPTZ      NOT NULL,         -- interval start, UTC
    kwh    DOUBLE PRECISION NOT NULL,
    source TEXT             NOT NULL DEFAULT 'genesis',
    PRIMARY KEY (ts, source)
);
SELECT create_hypertable('meter_hourly', 'ts', if_not_exists => TRUE);

-- --- Appliance profiles: YOUR estimate inputs (nameplate / measured-by-test) -
CREATE TABLE IF NOT EXISTS appliance_profiles (
    appliance     TEXT    PRIMARY KEY,
    rated_w       NUMERIC NOT NULL,           -- typical running power
    hours_per_day NUMERIC NOT NULL,           -- typical runtime per day
    window_start  TIME,                       -- when it usually runs (optional)
    window_end    TIME
);
-- Example seeds — edit to your appliances, or clear and add your own.
INSERT INTO appliance_profiles (appliance, rated_w, hours_per_day, window_start, window_end) VALUES
    ('Spa Pool',         3000, 3.0, '22:00', '06:00'),
    ('Ducted Heat Pump', 1800, 6.0, '06:00', '22:00'),
    ('Oven',             2400, 0.5, '17:00', '20:00')
ON CONFLICT (appliance) DO NOTHING;

-- --- Views the Whole House dashboard reads ----------------------------------

-- Average usage + cost by day-of-week (when does your week get expensive?).
CREATE OR REPLACE VIEW usage_by_dow AS
SELECT extract(isodow FROM day)::int     AS dow_n,
       trim(to_char(day, 'Day'))         AS weekday,
       round(avg(kwh)::numeric, 2)               AS avg_kwh,
       round(avg(coalesce(dollars, 0))::numeric, 2) AS avg_dollars
FROM meter_daily_usage
GROUP BY dow_n, weekday;

-- Appliance ESTIMATE: modelled kWh/day from profiles. NOT measured.
CREATE OR REPLACE VIEW appliance_estimate AS
SELECT appliance,
       round((rated_w / 1000.0 * hours_per_day)::numeric, 2) AS est_kwh_per_day
FROM appliance_profiles;
