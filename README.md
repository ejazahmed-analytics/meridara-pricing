# From Fare Buckets to Continuous Pricing

Pricing the Europe to Asia corridor at a hub carrier.

> **Illustrative case study using fictitious and simulated data.** Meridara is a fictional airline. All bookings, fares, seat volumes, revenue figures, forecasts and results in this project are synthetically generated and do not represent the commercial performance, data, systems or practices of any real airline, airport, agency or data provider. Public figures used for calibration are cited in the README. Methods follow published revenue management literature. This project is a personal portfolio piece created to demonstrate analytical and data science capability, and is not affiliated with or endorsed by any employer, past or present.

## Status: work in progress

This README is a placeholder. The full version is written in Phase 6.

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Setup | Done |
| 2 | Data | Done |
| 3 | Forecast | Done |
| 4 | Sensitivity and simulation | Done |
| 5 | App | Built, in review (redesign) |
| 6 | Publish | Not started |

## Data plan

The generator produces 36 months of synthetic departures (March 2023 to February 2026) with a fixed random seed. The first 30 months (March 2023 to August 2025) are used to train the models and the last 6 months (September 2025 to February 2026) are held out for testing.

The window ends in February 2026 and does not model events from March 2026 onward. Berlin launches on 26 October 2025, inside the held-out window.

## Run the app locally

```bash
pip install -r requirements.txt
python src/generate_data.py
python src/forecast.py
python src/sensitivity.py
python src/pricing_sim.py
python src/build_app_data.py
streamlit run app/app.py
```

The generated data and results are already in `data/`, so `streamlit run app/app.py` works straight after installing.

## Limitations

- The test window (September 2025 to February 2026) covers winter only. It has no summer peak, no Easter and no Eid, so the reported forecast accuracy reflects those conditions and may not hold in other seasons.
- The window ends in February 2026 and does not model events from March 2026 onward.

- **Constrained demand.** Bookings cannot exceed seats. Demand that was turned away on full flights is not recorded, as in real booking data, so booked volumes understate true demand on full flights.
- **Departure-month FX.** Fares are stored in the sales currency and converted to other currencies at the European Central Bank monthly average rate for the month each flight leg departs. AED is derived from the USD peg (3.6725 AED per USD).
- **Station revenue is point-of-sale revenue.** About half of total leg revenue is sold at the HUB (31%) or beyond-hub cities (18%), because journeys that start there are mostly sold there. A Station view therefore shows only the share of its routes' revenue sold at its own point of sale.
- **Journeys.** Bookings are journeys with one or two flight legs. A one-way fare is always 60% of the return fare, a stated simplification.

More limitations are added in Phase 6.

## Version 2 ideas (out of scope for this version)

- A stronger directional imbalance (for example one-way VFR traffic concentrated toward the home direction) so the Network view shows a clearer directional story. Today, 70 to 92% return travel keeps every route balanced to within about 3% by month.
- Let the replayed policies price by fare product (for example a flexible product for Business and a saver product for Leisure and VFR, each with its own price). Today both offer one base price per booking period, so neither can match the as-flown fares, which are set customer by customer.
- Unconstrain demand on full flights so the pricing replay is not conservative on sold-out departures.
- Use the stored sales channel (direct, NDC, GDS, OTA) in a separate NDC offer and pricing project.
- Reprice return journeys as a whole in the pricing replay (today the replay prices the outbound leg only).
- Bid-price control with network (origin and destination) optimisation instead of leg-level control.
- Model the beyond-hub flights explicitly instead of treating them as connecting origins and destinations.

## Environment

The project was built and tested on Python 3.11. Python 3.15 was too new at the time: some packages (for example pyarrow) had no prebuilt wheels for it. Create a virtual environment on Python 3.11 and run `pip install -r requirements.txt`.

## Data sources

Monthly average exchange rates: European Central Bank euro foreign exchange reference rates (ECB Data Portal, series EXR.M.USD.EUR.SP00.A, EXR.M.GBP.EUR.SP00.A and EXR.M.AUD.EUR.SP00.A). Reuse of ECB statistics is permitted with acknowledgement of the source. Other calibration sources are added in Phase 6.

## About the author

Ejaz Ahmed, GitHub: [ejazahmed-analytics](https://github.com/ejazahmed-analytics)
