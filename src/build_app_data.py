"""Build the small summary tables the app reads (written to data/results.db).

Illustrative case study using fictitious and simulated data.

The bookings table has about one million rows. The app only needs summaries, so
they are computed once here, in EUR at the departure-month exchange rate. The
app converts to the selected currency by month. Run after generate_data.py:

    python src/build_app_data.py
"""
import sqlite3

import numpy as np
import pandas as pd

from results_db import DATA_DB, RESULTS_DB

LEADS = [330, 300, 270, 240, 210, 180, 150, 120, 105, 90, 75, 60, 45, 30, 21, 14, 10, 7, 5, 3, 2, 1, 0]
LAUNCH = "2025-10-26"
WINDOWS = "CASE WHEN days_before >= 181 THEN 1 WHEN days_before >= 91 THEN 2 WHEN days_before >= 61 THEN 3 " \
          "WHEN days_before >= 31 THEN 4 WHEN days_before >= 15 THEN 5 WHEN days_before >= 8 THEN 6 ELSE 7 END"


def main():
    con = sqlite3.connect(DATA_DB)
    # One row per booking leg with EUR values at the departure-month rate.
    con.execute("""
        CREATE TEMP VIEW L AS
        SELECT v.*, substr(v.departure_date, 1, 7) AS month, f.season, f.is_test,
               v.leg_fare * x.rate_to_eur AS leg_eur,
               v.through_fare * x.rate_to_eur AS through_eur,
               COALESCE(d.cost_eur_per_pax, 0) AS disp_eur
        FROM v_bookings_with_leg_fare v
        JOIN flights f ON f.flight_id = v.flight_id
        JOIN fx_rates x ON x.month = substr(v.departure_date, 1, 7) AND x.currency = v.sales_currency
        LEFT JOIN displacement_costs d ON d.beyond_city_id = v.beyond_city_id AND d.season = f.season
                                      AND d.cabin_id = v.cabin_id""")
    out = {}

    out["agg_pos_month"] = pd.read_sql("""
        SELECT pos_station_id, month, segment_id, trip_type, sold_at_origin,
               SUM(pax) AS pax, SUM(pax * leg_eur) AS rev_eur
        FROM L GROUP BY 1, 2, 3, 4, 5""", con)

    out["agg_route_month"] = pd.read_sql("""
        SELECT route_station_id AS station_id, direction, month, traffic_type, segment_id, cabin_id,
               trip_type, leg_seq, SUM(pax) AS pax, SUM(pax * leg_eur) AS rev_eur
        FROM L GROUP BY 1, 2, 3, 4, 5, 6, 7, 8""", con)

    out["agg_flights_month"] = pd.read_sql("""
        SELECT r.station_id, r.direction, substr(f.departure_date, 1, 7) AS month,
               COUNT(*) AS flights, SUM(f.capacity_business + f.capacity_economy) AS seats,
               SUM(COALESCE(p.pax, 0)) AS pax
        FROM flights f JOIN routes r ON r.route_id = f.route_id
        LEFT JOIN (SELECT flight_id, SUM(pax) AS pax FROM bookings GROUP BY flight_id) p
               ON p.flight_id = f.flight_id
        GROUP BY 1, 2, 3""", con)

    out["agg_contribution"] = pd.read_sql("""
        SELECT route_station_id AS station_id, direction, month, season, cabin_id,
               COALESCE(beyond_city_id, 0) AS beyond_city_id, SUM(pax) AS pax,
               SUM(pax * leg_eur) AS leg_eur, SUM(pax * through_eur) AS through_eur,
               SUM(pax * disp_eur) AS displacement_eur
        FROM L GROUP BY 1, 2, 3, 4, 5, 6""", con)

    out["agg_trip_pricing"] = pd.read_sql(f"""
        SELECT route_station_id AS station_id, month, segment_id, cabin_id, trip_type,
               {WINDOWS} AS window, SUM(pax) AS pax, SUM(pax * leg_eur) AS leg_eur,
               SUM(pax * leg_eur * CASE WHEN trip_type = 'RT' THEN 2 ELSE 1 END) AS journey_eur
        FROM L WHERE leg_seq = 1 GROUP BY 1, 2, 3, 4, 5, 6""", con)

    out["agg_origin_test"] = pd.read_sql("""
        SELECT segment_id, cabin_id, route_station_id AS station_id, traffic_type, month,
               SUM(pax) AS pax, SUM(pax * leg_eur) AS leg_eur, SUM(pax * through_eur) AS through_eur,
               SUM(pax * disp_eur) AS displacement_eur
        FROM L WHERE is_test = 1 AND leg_seq = 1 GROUP BY 1, 2, 3, 4, 5""", con)

    # Weekly launch comparison: Berlin and Frankfurt from the Berlin launch date.
    out["agg_launch_week"] = pd.read_sql(f"""
        SELECT r.station_id, CAST((julianday(f.departure_date) - julianday('{LAUNCH}')) / 7 AS INTEGER) AS week,
               MIN(substr(f.departure_date, 1, 7)) AS month, COUNT(*) AS flights,
               SUM(f.capacity_business + f.capacity_economy) AS seats, SUM(COALESCE(p.pax, 0)) AS pax,
               SUM(COALESCE(p.rev_eur, 0)) AS rev_eur
        FROM flights f JOIN routes r ON r.route_id = f.route_id
        LEFT JOIN (SELECT flight_id, SUM(pax) AS pax, SUM(pax * leg_eur) AS rev_eur FROM L GROUP BY flight_id) p
               ON p.flight_id = f.flight_id
        WHERE r.station_id IN (1, 2) AND f.departure_date >= '{LAUNCH}'
        GROUP BY 1, 2""", con)

    # Booking pace of the held-out flights: passengers booked at each look-ahead point.
    test = pd.read_sql("""SELECT b.flight_id, b.segment_id, b.days_before, b.pax FROM bookings b
                          JOIN flights f ON f.flight_id = b.flight_id WHERE f.is_test = 1""", con)
    parts = []
    for lead in LEADS:
        g = test[test.days_before >= lead].groupby(["flight_id", "segment_id"]).pax.sum().reset_index()
        g["lead"] = lead
        parts.append(g)
    pace = pd.concat(parts)
    out["flight_pace"] = pace
    con.close()

    rc = sqlite3.connect(RESULTS_DB)
    for name, df in out.items():
        df.round(2).to_sql(name, rc, if_exists="replace", index=False)
        print(f"{name}: {len(df):,} rows")
    rc.execute("CREATE INDEX IF NOT EXISTS idx_pace ON flight_pace (flight_id)")
    rc.commit()
    rc.close()


if __name__ == "__main__":
    main()
