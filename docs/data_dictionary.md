# Data dictionary

Illustrative case study using fictitious and simulated data. Meridara is a fictional airline. All values are synthetic. Assumptions behind the numbers are in `assumptions.md`.

Database: `data/meridara.db` (SQLite). Model outputs are in `data/results.db` (see the end of this file). Small tables are also saved as CSV in `data/`. The bookings table is not saved as CSV; run `python src/generate_data.py` to rebuild it (same seed, same result).

## Lookup tables

| Table | Key | Rows | Meaning |
| --- | --- | --- | --- |
| segments | segment_id | 3 | 1 Business, 2 Leisure, 3 VFR |
| cabins | cabin_id | 2 | 1 Economy, 2 Business |
| trip_types | trip_type_id | 2 | 1 OW (one way), 2 RT (return) |
| channels | channel_id | 4 | 1 Airline direct, 2 NDC, 3 GDS, 4 OTA. Placeholder mix, not analysed in Project 1. |
| stations | station_id | 11 | The ten cities plus HUB, with region, role and sales currency (HUB sells in AED). |
| beyond_hub_cities | beyond_city_id | 4 | Bangkok, Sydney, Nairobi, Mumbai, linked to stations. |

## Network and schedule

| Table | One row per | Columns |
| --- | --- | --- |
| routes | Directional route (12) | route_id; station_id (European station); direction (`to_hub` = station to HUB, `from_hub` = HUB to station); distance_band; aircraft_type; seats_business; seats_economy; weekly_frequency (per direction); price_index (Frankfurt = 1.00). |
| events | Dated event | event_id; event_name; start_date; end_date. School holidays are per country. Christmas 2022 exists only to feed the unstored burn-in period. |
| flights | Departure in the window (8,632) | flight_id; route_id; departure_date; weekday (0 = Monday); season (low, shoulder, summer, christmas); event_id (main event, may be empty); capacity_business; capacity_economy; berlin_launch_flag; promo_discount_pct (random promotion, 0 if none); is_test (1 from 2025-09-01). |

## Pricing reference

| Table | One row per | Columns |
| --- | --- | --- |
| fare_buckets | Route, cabin, ladder and class | route_id; cabin_id; ladder (`low` for January, February, November; `standard` otherwise, 1.18 times the low ladder); class_rank (1 cheapest to 10); class_code; price_point_eur (ONE-WAY price). |
| competitor_index | Route and week | route_id; week_start (Monday); index_value (100 = Meridara's level). |
| fx_rates | Month and currency | month; currency (EUR, GBP, USD, AUD, AED); rate_to_eur (EUR per unit); source. |
| proration_factors | Route, beyond-hub city and cabin | factor = share of a connecting through fare attributed to the European leg. |
| displacement_costs | Beyond-hub city, season, cabin | cost_eur_per_pax = chance the seat sells to someone else x average local fare on that leg. Assumption approved by the owner. |
| revenue_targets | European station and month | target_revenue_eur: synthetic target for revenue sold at that station's point of sale. |

## Bookings (one row per flight leg of a booking)

Stored in flight order (`WITHOUT ROWID`, key `flight_id, booking_id`).

| Column | Meaning |
| --- | --- |
| booking_id | Unique id, assigned in flight order. |
| flight_id | The flight of this leg. |
| journey_id | Links the legs of one journey. A one-way journey has one leg; a return journey has an outbound leg (leg_seq 1) and an inbound leg (leg_seq 2). |
| trip_type | 1 OW, 2 RT. A return journey whose second leg falls outside the window keeps trip_type 2 with one row. |
| leg_seq | 1 outbound, 2 inbound. Only leg_seq 1 responds to the promotion on its own flight. |
| days_before | Days between booking and departure. Inbound legs are booked with the outbound leg, so their value is larger. |
| segment_id, cabin_id | Passenger segment and cabin. |
| pos_station_id | Point of sale, assigned per journey (origin, destination or a third station, by segment). |
| channel_id | Sales channel (placeholder mix). |
| class_rank | Booking class (1 to 10) used when the journey was priced. |
| pax | Passengers in the party. |
| through_fare | Fare per passenger per leg, whole units of the sales currency. For a return journey it is half the return fare, so both legs carry the same amount. One-way fare is 60% of the return fare (simplification). |
| beyond_city_id | Empty for local passengers; the beyond-hub city for connecting passengers. |

### View `v_bookings_with_leg_fare`

Adds derived fields to every booking row:

| Column | Meaning |
| --- | --- |
| booking_date | departure_date minus days_before. |
| sales_currency | Currency of the point of sale. |
| traffic_type | `local` or `connecting`. |
| trip_type | 'OW' or 'RT' (name, not code). |
| leg_fare | through_fare x proration factor (factor 1 for local). Convert to EUR with the fx_rates row for the departure month and sales currency. |
| journey_fare | through_fare x 2 for return journeys, otherwise through_fare. |
| journey_origin_station_id | Station where the whole journey started (Europe, HUB or a beyond-hub city). |
| sold_at_origin | 1 if the point of sale is the journey origin. |
| route_station_id, direction | Station and direction of the flight's route. |

## Derived conventions

- Fares convert to other currencies at the monthly average rate for the month each leg departs.
- Load factor = passengers on the flight / seats.
- Bookings cannot exceed seats. Demand turned away on full flights is not recorded (constrained demand).
- Train = departures on or before 2025-08-31. Test = departures from 2025-09-01 to 2026-02-28.

## Model output tables (`data/results.db`)

Written by `src/forecast.py`, `src/sensitivity.py` and `src/pricing_sim.py`. Column lists are in `sql/results_schema.sql`. They are kept in a separate file so the 34 MB data file does not change between phases and the git history stays small.
