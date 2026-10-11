# From Fare Buckets to Continuous Pricing

Pricing the Europe to Asia corridor at a hub carrier.

> **Illustrative case study using fictitious and simulated data.** Meridara is a fictional airline. All bookings, fares, seat volumes, revenue figures, forecasts and results in this project are synthetically generated and do not represent the commercial performance, data, systems or practices of any real airline, airport, agency or data provider. Public figures used for calibration are cited in the README. Methods follow published revenue management literature. This project is a personal portfolio piece created to demonstrate analytical and data science capability, and is not affiliated with or endorsed by any employer, past or present.

## Status: work in progress

This README is a placeholder. The full version is written in Phase 6.

| Phase | Description | Status |
| --- | --- | --- |
| 1 | Setup | Done |
| 2 | Data | In progress |
| 3 | Forecast | Not started |
| 4 | Sensitivity and simulation | Not started |
| 5 | App | Not started |
| 6 | Publish | Not started |

## Data plan

The generator produces 36 months of synthetic departures (March 2023 to February 2026) with a fixed random seed. The first 30 months (March 2023 to August 2025) are used to train the models and the last 6 months (September 2025 to February 2026) are held out for testing.

The window ends in February 2026 and does not model events from March 2026 onward. Berlin launches on 26 October 2025, inside the held-out window.

## Limitations

- The test window (September 2025 to February 2026) covers winter only. It has no summer peak, no Easter and no Eid, so the reported forecast accuracy reflects those conditions and may not hold in other seasons.
- The window ends in February 2026 and does not model events from March 2026 onward.

- **Constrained demand.** Bookings cannot exceed seats. Demand that was turned away on full flights is not recorded, as in real booking data, so booked volumes understate true demand on full flights.
- **Departure-month FX.** Fares are stored in the sales currency and converted to other currencies at the European Central Bank monthly average rate for the month each flight leg departs. AED is derived from the USD peg (3.6725 AED per USD).
- **Journeys.** Bookings are journeys with one or two flight legs. A one-way fare is always 60% of the return fare, a stated simplification.

More limitations are added in Phase 6.

## Environment

The project was built and tested on Python 3.11. Python 3.15 was too new at the time: some packages (for example pyarrow) had no prebuilt wheels for it. Create a virtual environment on Python 3.11 and run `pip install -r requirements.txt`.

## Data sources

Monthly average exchange rates: European Central Bank euro foreign exchange reference rates (ECB Data Portal, series EXR.M.USD.EUR.SP00.A, EXR.M.GBP.EUR.SP00.A and EXR.M.AUD.EUR.SP00.A). Reuse of ECB statistics is permitted with acknowledgement of the source. Other calibration sources are added in Phase 6.

## About the author

Ejaz Ahmed, GitHub: [ejazahmed-analytics](https://github.com/ejazahmed-analytics)
