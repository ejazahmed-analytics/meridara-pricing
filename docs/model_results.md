# Model results (Phases 3 and 4)

Illustrative case study using fictitious and simulated data. Meridara is a fictional airline. Every number below comes from simulated data and from scripts in `src/`; rerun `python src/generate_data.py`, `src/forecast.py`, `src/sensitivity.py` and `src/pricing_sim.py` to reproduce them (fixed seeds).

Train: departures to 31 August 2025 (30 months). Test: 1 September 2025 to 28 February 2026 (6 months, 1,574 flights, winter only: no summer peak, Easter or Eid, so accuracy reflects those conditions).

## 1. Demand forecast (Phase 3)

Final passengers per flight and segment, forecast at five points before departure using only bookings made by then. The baseline is historical pickup (final divided by on-hand, by route, segment and look-ahead point). The model is gradient boosting (scikit-learn) trained on the remaining pickup. Berlin is excluded from the table below because it has no training history.

| Days before departure | Baseline WAPE % | Gradient boosting WAPE % | Improvement % | Baseline MAPE % | Gradient boosting MAPE % |
| --- | --- | --- | --- | --- | --- |
| 90 | 23.1 | 12.4 | 46.5 | 25.9 | 14.4 |
| 60 | 16.0 | 10.5 | 34.2 | 17.7 | 12.0 |
| 30 | 9.2 | 7.4 | 20.0 | 10.2 | 8.4 |
| 14 | 5.2 | 4.7 | 9.6 | 5.9 | 5.4 |
| 7 | 2.8 | 2.6 | 4.8 | 3.2 | 3.0 |
| All | 11.3 | 7.5 | 33.2 | 12.6 | 8.6 |

WAPE is the sum of absolute errors divided by the sum of actuals. MAPE is the mean absolute percentage error on flight-segments with at least 10 actual passengers. Bias is near zero for both methods (within 0.5%).

- The model beats the baseline at every look-ahead point and on every route and segment. The gain is largest early (46% at 90 days) and for Business (65% at 90 days), where late booking makes the pickup ratio unstable.
- The model uses no route identifier, only seats, frequency, price level, booking mix and calendar features, so it can score a route it has never seen.

### Berlin cold start

Berlin launched on 26 October 2025, inside the test window, with no history. WAPE %, all segments:

| Look-ahead | Period | Berlin pickup baseline (borrowed from Frankfurt, Paris, Milan) | Berlin gradient boosting | Frankfurt gradient boosting, same weeks |
| --- | --- | --- | --- | --- |
| 90 days | Weeks 1-4 | 33.5 | 27.1 | 11.9 |
| 90 days | Weeks 5-8 | 27.9 | 22.6 | 11.6 |
| 90 days | Weeks 9-12 | 26.8 | 20.4 | 11.1 |
| 90 days | Weeks 13-18 | 21.9 | 11.8 | 11.4 |
| 30 days | Weeks 1-4 | 13.8 | 18.4 | 7.6 |
| 30 days | Weeks 5-8 | 10.2 | 13.3 | 7.0 |
| 30 days | Weeks 9-12 | 12.0 | 11.3 | 6.2 |
| 30 days | Weeks 13-18 | 10.2 | 8.1 | 7.7 |

- At 90 days out Berlin's error is more than double Frankfurt's for the first 12 weeks (27% vs 12%) and converges by weeks 13-18 (11.8% vs 11.4%).
- At 30 days out the borrowed pickup baseline beats the model for the first eight weeks (13.8% vs 18.4%). Close to departure, the borrowed pickup ratio is a safer guide than a model that has not seen the route. By weeks 13-18 the model is ahead (8.1% vs 10.2%).
- Switching the baseline to Berlin's own history (after 30 departed flight-segments per route) did not help within the test window.

## 2. Price sensitivity (Phase 4a)

Elasticity of originating demand to price, estimated from the random promotions (Poisson regression, route, month, weekday and event controls, errors clustered by week). 95% ranges.

| Segment | All training flights | Low-season flights | Value used to build the data |
| --- | --- | --- | --- |
| Business | -0.32 (-0.45 to -0.20) | -0.53 (-0.81 to -0.24) | -0.50 |
| Leisure | -1.32 (-1.45 to -1.19) | -1.32 (-1.65 to -1.00) | -1.60 |
| VFR | -1.11 (-1.27 to -0.94) | -1.13 (-1.59 to -0.67) | -1.30 |

- Ordering is right in both samples: Business is the least price sensitive, Leisure the most.
- The all-flights estimates are pulled toward zero because full flights cap the extra demand a promotion creates. Low-season flights rarely fill, and their ranges contain the true values. The low-season sample was chosen by season (a known capacity argument), not by outcome. The pricing replay uses the low-season estimates and their ranges.
- Competitor price effect (all flights): Business 0.29, Leisure 0.43, VFR 0.44 (true 0.2, 0.5, 0.5).

## 3. Fare buckets vs continuous pricing (Phase 4b)

The held-out flights replayed under two policies facing identical simulated customers. Revenue is for originating passengers on their outbound leg, in millions of EUR in one-way-fare terms. Both policies see the Phase 3 forecast at 90 days (not the truth) and rescale from actual sales.

- **Buckets:** 10 fixed one-way price points opened and closed by EMSR-b.
- **Continuous:** a price anywhere between the lowest and highest bucket price, re-chosen each booking period to maximise expected revenue.
- **Fence:** Business-segment customers can only buy the 6th price point or above, in both policies. Without a fence, every customer could buy down and buckets would look unfairly weak.

### Base scenario

| Policy | Revenue (m EUR) | Passengers | Average fare (EUR) | Load factor % |
| --- | --- | --- | --- | --- |
| Observed (as flown) | 79.19 | 153,040 | 517 | 76.9 |
| Buckets | 76.79 | 213,783 | 359 | 93.4 |
| Continuous | 84.70 | 131,280 | 645 | 70.9 |

**Continuous pricing earns 10.3% more revenue than buckets**, with a higher average fare and a lower load factor: it gives up volume for yield, mostly on Leisure and VFR passengers, while Business revenue rises.

| Segment | Revenue change % | Avg fare buckets (EUR) | Avg fare continuous (EUR) |
| --- | --- | --- | --- |
| Business | +35.7 | 707 | 1,265 |
| Leisure | -17.1 | 244 | 353 |
| VFR | -9.1 | 239 | 396 |

| Route | Buckets (m EUR) | Continuous (m EUR) | Change % |
| --- | --- | --- | --- |
| Frankfurt | 20.74 | 23.08 | +11.3 |
| London | 22.77 | 25.64 | +12.6 |
| Paris | 11.38 | 12.36 | +8.5 |
| Milan | 8.90 | 9.86 | +10.7 |
| Madrid | 6.48 | 6.85 | +5.7 |
| Berlin | 6.50 | 6.92 | +6.5 |

### Risks

| Scenario | Buckets (m EUR) | Continuous (m EUR) | Change % |
| --- | --- | --- | --- |
| Base | 76.79 | 84.70 | +10.3 |
| Forecast underestimates demand by 15% | 76.90 | 84.54 | +9.9 |
| Competitor cuts price 10% (forecast unaware) | 74.48 | 82.32 | +10.5 |
| World more price sensitive (low end of estimated range) | 81.54 | 75.43 | -7.5 |
| World less price sensitive (high end of estimated range) | 70.69 | 96.29 | +36.2 |

- **Prices drifting down when the forecast is too low.** When the forecast underestimates demand by 15%, the average continuous price in the first booking period is 2.8% lower than in the base scenario (1,604 vs 1,651 EUR). The rescaling from actual sales pulls it back by period 3, and the final revenue advantage barely moves (9.9%). The drift is real but small and temporary here.
- **Competitor moves.** A 10% competitor price cut costs both policies about 3% of revenue (buckets -3.0%, continuous -2.8%). The relative advantage holds because both policies learn from sales.
- **Berlin.** The advantage is smaller on Berlin (+6.5% vs +10.7% on other routes), where the forecast is weakest.
- **The result depends on the price sensitivity estimate.** If customers are more price sensitive than the point estimate (still inside the estimated range), continuous pricing loses 7.5%, because it sets prices from the wrong demand curve. The estimates have wide ranges, so the benefit should be read as conditional on them.

### Limits of the replay

- Observed bookings stand in for demand. They are capped by seats, so demand on full flights is understated and revenue gains from higher prices there are conservative.
- Returning passengers are already booked and fixed. Only originating passengers on their outbound leg are priced, so repricing return journeys as a whole is not captured.
- Revenue is in one-way-fare terms and ignores connecting prorates and network effects such as displacement of high-value connections.
- Customers' willingness to pay follows a constant-elasticity curve, which is a simplification. Both policies use the same estimated curve, so neither has an information advantage.
- The 6th-price-point fence for Business customers is an assumption. Results move with it.
