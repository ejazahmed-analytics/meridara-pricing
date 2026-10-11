-- Model output tables (data/results.db).
-- Illustrative case study using fictitious and simulated data.
-- Written by src/forecast.py, src/sensitivity.py and src/pricing_sim.py.
-- flight_id and route_id refer to data/meridara.db.

-- Phase 3: forecasts of final passengers per flight and segment, test flights only.
-- asof_days: how many days before departure the forecast is made.
CREATE TABLE IF NOT EXISTS forecast_results (
    flight_id         INTEGER NOT NULL,
    segment_id        INTEGER NOT NULL,
    asof_days         INTEGER NOT NULL,
    onhand_pax        REAL NOT NULL,      -- passengers booked at that point
    actual_final      REAL NOT NULL,      -- passengers booked at departure
    baseline_forecast REAL NOT NULL,      -- historical pickup (Berlin: borrowed ratios)
    gbm_forecast      REAL NOT NULL,      -- gradient boosting
    PRIMARY KEY (flight_id, segment_id, asof_days)
);

-- Accuracy tables. analysis names the question, model the method, scope the group of flights.
CREATE TABLE IF NOT EXISTS model_metrics (
    analysis  TEXT NOT NULL,
    model     TEXT NOT NULL,
    scope     TEXT NOT NULL,
    asof_days INTEGER,
    wape      REAL,        -- sum of absolute errors / sum of actuals
    mape      REAL,        -- mean absolute % error on rows with actual >= 10
    bias      REAL,        -- (sum forecast - sum actual) / sum actual
    n_rows    INTEGER
);

-- Phase 4: price sensitivity estimates by segment.
CREATE TABLE IF NOT EXISTS sensitivity_estimates (
    sample          TEXT NOT NULL,        -- 'all training flights' or 'low-season flights'
    segment_id      INTEGER NOT NULL,
    parameter       TEXT NOT NULL,        -- 'price' or 'competitor'
    estimate        REAL NOT NULL,
    ci_low          REAL NOT NULL,        -- 95% interval
    ci_high         REAL NOT NULL,
    std_err         REAL NOT NULL,
    n_obs           INTEGER NOT NULL,
    generator_input REAL                  -- the value the synthetic data was built with
);

-- Phase 4: pricing replay on the held-out flights.
-- Passengers and revenue are for originating passengers on their outbound leg.
CREATE TABLE IF NOT EXISTS simulation_results (
    scenario    TEXT NOT NULL,
    policy      TEXT NOT NULL,            -- 'buckets' or 'continuous'
    flight_id   INTEGER NOT NULL,
    cabin_id    INTEGER NOT NULL,
    segment_id  INTEGER NOT NULL,
    pax         INTEGER NOT NULL,
    revenue_eur REAL NOT NULL
);

-- Seats available to originating passengers (seats minus returning passengers already booked).
CREATE TABLE IF NOT EXISTS simulation_flights (
    flight_id     INTEGER NOT NULL,
    cabin_id      INTEGER NOT NULL,
    capacity      INTEGER NOT NULL,
    inbound_pax   INTEGER NOT NULL,
    PRIMARY KEY (flight_id, cabin_id)
);

-- Average price offered, by booking period (1 = 330-181 days out ... 7 = 7-0 days out).
CREATE TABLE IF NOT EXISTS simulation_price_paths (
    scenario      TEXT NOT NULL,
    policy        TEXT NOT NULL,
    period        INTEGER NOT NULL,
    avg_price_eur REAL NOT NULL,
    PRIMARY KEY (scenario, policy, period)
);

-- Price offered by each policy in the base scenario, per flight, cabin and booking period.
-- Used by the Pricing and Revenue Management view as the "recommended price".
CREATE TABLE IF NOT EXISTS simulation_prices (
    policy     TEXT NOT NULL,
    flight_id  INTEGER NOT NULL,
    cabin_id   INTEGER NOT NULL,
    period     INTEGER NOT NULL,
    price_eur  REAL NOT NULL,
    PRIMARY KEY (policy, flight_id, cabin_id, period)
);
