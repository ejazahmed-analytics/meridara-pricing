-- Meridara pricing database schema (SQLite).
-- Illustrative case study using fictitious and simulated data.
--
-- Reading guide:
--   PRIMARY KEY  = the column that identifies one row uniquely.
--   REFERENCES   = a link to a row in another table (a foreign key).
--   Small whole-number codes (1, 2, 3) are used in the big bookings table
--   to keep the database file small. Lookup tables translate the codes.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- Lookup tables (tiny, translate codes into names)
-- ---------------------------------------------------------------------

-- Passenger segments: 1 Business, 2 Leisure, 3 VFR.
CREATE TABLE segments (
    segment_id   INTEGER PRIMARY KEY,
    segment_name TEXT NOT NULL
);

-- Cabins: 1 Economy, 2 Business.
CREATE TABLE cabins (
    cabin_id   INTEGER PRIMARY KEY,
    cabin_name TEXT NOT NULL
);

-- Trip types: 1 OW (one way), 2 RT (return).
CREATE TABLE trip_types (
    trip_type_id   INTEGER PRIMARY KEY,
    trip_type_name TEXT NOT NULL
);

-- Sales channels: 1 Airline direct, 2 NDC, 3 GDS, 4 OTA.
-- Stored for reuse in a later NDC project; Project 1 does not analyse it.
CREATE TABLE channels (
    channel_id   INTEGER PRIMARY KEY,
    channel_name TEXT NOT NULL
);

-- Every city in the story, including the hub.
-- sales_currency is the currency tickets are sold in at that point of sale.
-- The hub is labelled HUB. It sells in AED (a simplification: AED is pegged
-- to USD), so journeys that start at the hub have a point of sale.
CREATE TABLE stations (
    station_id     INTEGER PRIMARY KEY,
    station_name   TEXT NOT NULL,          -- 'Frankfurt', 'HUB', ...
    region         TEXT NOT NULL,          -- 'Europe', 'Asia', 'Hub', ...
    role           TEXT NOT NULL,          -- 'featured', 'core', 'beyond hub', 'hub'
    sales_currency TEXT NOT NULL           -- 'EUR', 'GBP', 'USD', 'AUD', 'AED'
);

-- The four beyond-hub cities a connecting passenger can travel to or from.
-- Each one links to a row in stations.
CREATE TABLE beyond_hub_cities (
    beyond_city_id INTEGER PRIMARY KEY,
    station_id     INTEGER NOT NULL REFERENCES stations (station_id)
);

-- ---------------------------------------------------------------------
-- Network and schedule
-- ---------------------------------------------------------------------

-- One row per directional route: 6 European stations x 2 directions = 12.
-- direction 'to_hub' means station -> HUB; 'from_hub' means HUB -> station.
CREATE TABLE routes (
    route_id         INTEGER PRIMARY KEY,
    station_id       INTEGER NOT NULL REFERENCES stations (station_id),
    direction        TEXT NOT NULL CHECK (direction IN ('to_hub', 'from_hub')),
    distance_band    TEXT NOT NULL,
    aircraft_type    TEXT NOT NULL,
    seats_business   INTEGER NOT NULL,
    seats_economy    INTEGER NOT NULL,
    weekly_frequency INTEGER NOT NULL,     -- departures per week on this direction
    price_index      REAL NOT NULL         -- route price level vs Frankfurt = 1.00
);

-- Dated events (Easter, Eid, Diwali, Christmas, school holidays...).
-- Keeping dates in a table means a wrong date is a one-row fix.
CREATE TABLE events (
    event_id   INTEGER PRIMARY KEY,
    event_name TEXT NOT NULL,
    start_date TEXT NOT NULL,              -- ISO date, 'YYYY-MM-DD'
    end_date   TEXT NOT NULL
);

-- One row per departure inside the data window.
-- is_test = 1 for departures on or after 2025-09-01 (the held-out window).
-- promo_discount_pct is the randomised promotion (0 if none); it is unrelated
-- to demand and lets Phase 4 estimate price sensitivity cleanly.
CREATE TABLE flights (
    flight_id          INTEGER PRIMARY KEY,
    route_id           INTEGER NOT NULL REFERENCES routes (route_id),
    departure_date     TEXT NOT NULL,      -- ISO date
    weekday            INTEGER NOT NULL,   -- 0 = Monday ... 6 = Sunday
    season             TEXT NOT NULL CHECK (season IN ('low', 'shoulder', 'summer', 'christmas')),
    event_id           INTEGER REFERENCES events (event_id),   -- main event, may be empty
    capacity_business  INTEGER NOT NULL,
    capacity_economy   INTEGER NOT NULL,
    berlin_launch_flag INTEGER NOT NULL DEFAULT 0,             -- 1 = Berlin launch period flight
    promo_discount_pct REAL NOT NULL DEFAULT 0,
    is_test            INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------
-- Pricing reference tables
-- ---------------------------------------------------------------------

-- About 10 fixed ONE-WAY price points per route, cabin and ladder.
-- class_rank 1 = cheapest class, 10 = most expensive. Prices are in EUR
-- equivalent; they are converted to the sales currency using fx_rates.
-- Two ladders exist: 'low' (used for January, February and November
-- departures) and 'standard' (the low ladder scaled by 1.18, used for all
-- other departures). A return fare is the one-way price divided by 0.6.
CREATE TABLE fare_buckets (
    route_id        INTEGER NOT NULL REFERENCES routes (route_id),
    cabin_id        INTEGER NOT NULL REFERENCES cabins (cabin_id),
    ladder          TEXT NOT NULL CHECK (ladder IN ('low', 'standard')),
    class_rank      INTEGER NOT NULL,
    class_code      TEXT NOT NULL,          -- a booking class letter
    price_point_eur REAL NOT NULL,
    PRIMARY KEY (route_id, cabin_id, ladder, class_rank)
);

-- Market fare trend by month (1.00 at September 2024). The fare ladders in fare_buckets are at that
-- price level; the price actually offered on a flight is the ladder price times this index.
CREATE TABLE fare_trend (
    month       TEXT PRIMARY KEY,      -- 'YYYY-MM'
    trend_index REAL NOT NULL
);

-- A competing-hub price index per route and week (no real airline named).
-- 100 = same price level as Meridara; 110 = competitor is 10% dearer.
CREATE TABLE competitor_index (
    route_id    INTEGER NOT NULL REFERENCES routes (route_id),
    week_start  TEXT NOT NULL,              -- ISO date of the Monday
    index_value REAL NOT NULL,
    PRIMARY KEY (route_id, week_start)
);

-- Monthly exchange rates: how many EUR one unit of the currency is worth.
-- source says where each rate comes from.
CREATE TABLE fx_rates (
    month       TEXT NOT NULL,              -- 'YYYY-MM'
    currency    TEXT NOT NULL,              -- 'EUR', 'GBP', 'USD', 'AUD', 'AED'
    rate_to_eur REAL NOT NULL,
    source      TEXT NOT NULL,
    PRIMARY KEY (month, currency)
);

-- Share of a connecting through fare attributed to the European leg.
-- leg_fare = through_fare x factor. One row per route, beyond-hub city, cabin.
CREATE TABLE proration_factors (
    route_id       INTEGER NOT NULL REFERENCES routes (route_id),
    beyond_city_id INTEGER NOT NULL REFERENCES beyond_hub_cities (beyond_city_id),
    cabin_id       INTEGER NOT NULL REFERENCES cabins (cabin_id),
    factor         REAL NOT NULL,
    PRIMARY KEY (route_id, beyond_city_id, cabin_id)
);

-- Estimated cost of the seat a connecting passenger takes on the beyond-hub
-- leg. Used only for network contribution = through_fare - displacement cost.
-- Filled after the owner has reviewed the values (Phase 2, checkpoint 3).
CREATE TABLE displacement_costs (
    beyond_city_id    INTEGER NOT NULL REFERENCES beyond_hub_cities (beyond_city_id),
    season            TEXT NOT NULL CHECK (season IN ('low', 'shoulder', 'summer', 'christmas')),
    cabin_id          INTEGER NOT NULL REFERENCES cabins (cabin_id),
    cost_eur_per_pax  REAL NOT NULL,
    PRIMARY KEY (beyond_city_id, season, cabin_id)
);

-- Monthly revenue target per European station, in EUR, for the Station view.
-- Synthetic budgets set in advance (financial year April to March): same month last year
-- times a station growth factor, a planned seasonal curve in the first year, and a launch
-- plan for Berlin. No target uses the actual revenue of its own month. Station revenue means revenue SOLD AT
-- that station's point of sale (all routes), counted in the month each leg
-- departs, converted at that month's rate.
CREATE TABLE revenue_targets (
    station_id         INTEGER NOT NULL REFERENCES stations (station_id),
    month              TEXT NOT NULL,       -- 'YYYY-MM'
    target_revenue_eur REAL NOT NULL,
    PRIMARY KEY (station_id, month)
);

-- ---------------------------------------------------------------------
-- Bookings (the big table, about one million rows)
-- ---------------------------------------------------------------------

-- One row per flight leg of a booking (a party of 1 or more passengers).
-- A booking is a journey: one-way journeys have one leg, return journeys
-- have an outbound leg (leg_seq 1) and an inbound leg (leg_seq 2) that share
-- a journey_id. Returns after the end of the window have no inbound row, and
-- inbound legs of journeys that left before the window have no outbound row.
-- Only essentials are stored to keep the file small:
--   * booking date is not stored; the view below works it out
--   * sales currency is not stored; it comes from the point of sale
--   * local or connecting is not stored; beyond_city_id empty = local
-- through_fare is per passenger, per leg, in the sales currency, whole units.
-- For a return journey it is half the return fare, so the two legs carry the
-- same amount. For a one-way journey it is the one-way fare.
-- The table is stored in flight order (WITHOUT ROWID, key flight_id then
-- booking_id), which makes a separate flight index unnecessary.
CREATE TABLE bookings (
    booking_id     INTEGER NOT NULL,
    flight_id      INTEGER NOT NULL REFERENCES flights (flight_id),
    journey_id     INTEGER NOT NULL,
    trip_type      INTEGER NOT NULL REFERENCES trip_types (trip_type_id),
    leg_seq        INTEGER NOT NULL CHECK (leg_seq IN (1, 2)),
    days_before    INTEGER NOT NULL,        -- days between booking and departure
    segment_id     INTEGER NOT NULL REFERENCES segments (segment_id),
    cabin_id       INTEGER NOT NULL REFERENCES cabins (cabin_id),
    pos_station_id INTEGER NOT NULL REFERENCES stations (station_id),   -- point of sale
    channel_id     INTEGER NOT NULL REFERENCES channels (channel_id),   -- not used in Project 1
    class_rank     INTEGER NOT NULL,        -- booking class used (1 to 10)
    pax            INTEGER NOT NULL,        -- passengers in the party
    through_fare   INTEGER NOT NULL,        -- fare per passenger per leg, sales currency
    beyond_city_id INTEGER REFERENCES beyond_hub_cities (beyond_city_id),  -- empty = local
    PRIMARY KEY (flight_id, booking_id)
) WITHOUT ROWID;

CREATE INDEX idx_flights_route_date ON flights (route_id, departure_date);

-- ---------------------------------------------------------------------
-- Convenience view: bookings with the derived fields filled in
-- ---------------------------------------------------------------------

-- Adds booking_date, sales_currency, traffic_type, trip type name, leg_fare,
-- journey_fare and the journey origin station.
-- For local bookings there is no proration row, so COALESCE uses a factor of 1.
-- journey_origin_station_id: the station where the whole journey started.
--   Outbound legs going to the hub, and inbound legs coming from it, belong to
--   journeys that started in Europe. Otherwise the journey started at the HUB
--   (local) or in the beyond-hub city (connecting). Station 11 is the HUB.
-- sold_at_origin is 1 when the point of sale is the journey origin.
CREATE VIEW v_bookings_with_leg_fare AS
SELECT *,
       CASE WHEN pos_station_id = journey_origin_station_id THEN 1 ELSE 0 END AS sold_at_origin
FROM (
    SELECT
        b.booking_id,
        b.flight_id,
        f.route_id,
        r.station_id AS route_station_id,
        r.direction,
        f.departure_date,
        date(f.departure_date, '-' || b.days_before || ' days') AS booking_date,
        b.days_before,
        b.journey_id,
        tt.trip_type_name AS trip_type,
        b.leg_seq,
        b.segment_id,
        b.cabin_id,
        b.pos_station_id,
        b.channel_id,
        s.sales_currency,
        b.class_rank,
        b.pax,
        b.through_fare,
        CASE WHEN b.beyond_city_id IS NULL THEN 'local' ELSE 'connecting' END AS traffic_type,
        b.beyond_city_id,
        ROUND(b.through_fare * COALESCE(p.factor, 1.0), 2) AS leg_fare,
        b.through_fare * CASE WHEN b.trip_type = 2 THEN 2 ELSE 1 END AS journey_fare,
        CASE
            WHEN (b.leg_seq = 1 AND r.direction = 'to_hub')
              OR (b.leg_seq = 2 AND r.direction = 'from_hub') THEN r.station_id
            WHEN b.beyond_city_id IS NULL THEN 11
            ELSE h.station_id
        END AS journey_origin_station_id
    FROM bookings AS b
    JOIN flights    AS f  ON f.flight_id  = b.flight_id
    JOIN routes     AS r  ON r.route_id   = f.route_id
    JOIN stations   AS s  ON s.station_id = b.pos_station_id
    JOIN trip_types AS tt ON tt.trip_type_id = b.trip_type
    LEFT JOIN beyond_hub_cities AS h ON h.beyond_city_id = b.beyond_city_id
    LEFT JOIN proration_factors AS p
           ON p.route_id       = f.route_id
          AND p.beyond_city_id = b.beyond_city_id
          AND p.cabin_id       = b.cabin_id
);
