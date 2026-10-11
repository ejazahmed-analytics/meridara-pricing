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

The held-out flights replayed under two pricing policies facing identical simulated customers. Revenue is for originating passengers on their outbound leg, in millions of EUR in one-way-fare terms. Both policies see the Phase 3 forecast at 90 days (not the truth) and rescale from actual sales.

- **Buckets:** 10 fixed one-way price points opened and closed by EMSR-b, with advance-purchase rules: the two cheapest classes close 14 days out and classes 3 and 4 close 7 days out.
- **Continuous:** a price anywhere between the lowest and highest bucket price, re-chosen each booking period to maximise expected revenue.
- **Fence:** Business-segment customers can only buy the 6th price point or above, in both policies.
- **Demand model:** each customer has a willingness to pay (WTP) drawn from a lognormal curve with a spread of 0.45 (an assumption), set so that the slope of demand at the as-flown price equals the estimated price sensitivity. WTP also rises towards departure, following the average price paid by booking window in the training data (about 0.82 in the earliest window to 1.25 in the last week). Because WTP is bounded, the revenue-maximising price falls inside the price range.

### Base scenario

| Policy | Revenue (m EUR) | vs buckets | vs as flown | Passengers | Average fare (EUR) | Load factor % |
| --- | --- | --- | --- | --- | --- | --- |
| Observed (as flown) | 79.19 | | | 153,040 | 517 | 76.9 |
| Simplified buckets (EMSR-b) | 67.79 | | -14.4% | 187,008 | 362 | 86.1 |
| Continuous pricing | 75.46 | +11.3% | -4.7% | 130,481 | 578 | 70.7 |
| Continuous with a route-level load factor floor | 76.66 | +13.1% | -3.2% | 153,067 | 501 | 76.9 |

**Headline: on the same customers and the same rules, continuous pricing earns 11.3% more than the bucket rule, and continuous pricing with a route load factor floor 13.1% more.** The bucket rule fills 86% of seats at low fares; continuous pricing holds 71%; the route floor holds 77%, level with as flown (77%).

**Why both policies earn less than as flown.** Fares in the simulated data are drawn customer by customer, so a Business traveller and a Leisure traveller pay very different fares in the same week. Both replayed policies offer one base price per booking period (with the Business fence), so neither can match that. As flown is an upper reference, not a policy to beat; the like-for-like comparison is continuous pricing against buckets. Against as flown, continuous pricing is -4.7% and the route floor -3.2%.

**Route-level load factor floor.** Each of the 12 routes must keep at least its as-flown average load factor over the six held-out months; single flights can vary. For each route the solver adds a per-passenger value to the pricing objective (a crude seat value) until the route reaches its floor (32 to 166 EUR per passenger across routes). The floor earns +1.6% more than unconstrained continuous pricing because the unconstrained price rule re-solves one price at a time and leaves seats empty. It keeps the connecting feed whole but uses the same price sensitivity estimates, so it is a better-tuned policy, not a free gain.

### Does the price pattern look like real pricing?

Mean price offered by booking period (EUR, base scenario; period 1 is 330-181 days out, period 7 is the last week).

Business cabin:

| Policy | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Buckets | 923 | 959 | 990 | 1,000 | 1,017 | 1,250 | 1,556 |
| Continuous | 2,037 | 2,108 | 2,244 | 2,334 | 2,478 | 2,552 | 2,692 |
| Continuous with route floor | 1,967 | 2,031 | 2,178 | 2,278 | 2,429 | 2,510 | 2,656 |

Economy cabin:

| Policy | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Buckets | 184 | 199 | 206 | 208 | 213 | 265 | 350 |
| Continuous | 288 | 308 | 354 | 408 | 497 | 558 | 624 |
| Continuous with route floor | 253 | 271 | 293 | 315 | 401 | 473 | 563 |

- Continuous prices rise towards departure and mostly sit inside the range: 9% of Business and 0.4% of Economy prices are at the ceiling.
- Bucket prices stay at or near the cheapest class while departure is far away (the cabins are lightly loaded, so EMSR-b protects little), then step up when the advance-purchase rules close the cheap classes.
- An earlier version of the replay used a constant-elasticity demand curve with no limit on willingness to pay and a flat willingness to pay over time. With a Business sensitivity of about -0.5, revenue then rose with every price increase, so Business prices sat at the ceiling 97% of the time and bucket prices at the floor 83% of the time. The bounded, time-varying model replaced it.

| Segment | vs as flown % | vs buckets % | Avg fare buckets (EUR) | Avg fare continuous (EUR) | Passengers, as flown -> continuous |
| --- | --- | --- | --- | --- | --- |
| Business | +2.2 | +19.5 | 703 | 948 | 49,249 -> 46,108 |
| Leisure | -13.6 | -1.1 | 232 | 376 | 67,869 -> 54,874 |
| VFR | -11.2 | +7.4 | 230 | 377 | 35,922 -> 29,499 |

| Route | Buckets (m EUR) | Continuous (m EUR) | vs buckets % | vs as flown % |
| --- | --- | --- | --- | --- |
| Frankfurt | 18.92 | 20.86 | +10.3 | -3.9 |
| Berlin | 5.41 | 5.98 | +10.6 | -3.4 |
| London | 20.24 | 22.51 | +11.2 | -5.6 |
| Paris | 9.93 | 11.10 | +11.8 | -5.2 |
| Milan | 7.76 | 8.68 | +11.9 | -5.0 |
| Madrid | 5.53 | 6.33 | +14.5 | -4.0 |

### Risks

| Scenario | Buckets (m EUR) | Continuous (m EUR) | vs buckets | vs as flown |
| --- | --- | --- | --- | --- |
| Base | 67.79 | 75.46 | +11.3% | -4.7% |
| Forecast underestimates demand by 15% | 67.58 | 76.33 | +12.9% | -3.6% |
| Competitor cuts price 10% (forecast unaware) | 64.50 | 72.37 | +12.2% | -8.6% |
| Customers more price sensitive (low end of estimated range) | 72.06 | 71.53 | -0.7% | -9.7% |
| Customers less price sensitive (high end of estimated range) | 63.57 | 80.56 | +26.7% | +1.7% |

- **Prices drifting down when the forecast is too low.** When the forecast underestimates demand by 15%, continuous pricing still earns about as much against buckets as in the base case, because sales feed back into the forecast after each booking period.
- **Competitor moves.** A 10% competitor price cut costs both policies revenue; the relative advantage holds.
- **The result depends on the price sensitivity estimate.** If customers are more price sensitive than the point estimate (still inside the estimated range), continuous pricing is level with buckets; if less sensitive, it is far ahead.
- **The result depends on the assumed spread of willingness to pay.** At 0.35 the gain against buckets is +13.9% (-6.4% against as flown); at 0.60 it is +8.9% (-3.0% against as flown). The sign of both comparisons is the same across the range.

### Limits of the replay

- Observed bookings stand in for demand. They are capped by seats, so demand on full flights is understated and revenue gains from higher prices there are conservative.
- Returning passengers are already booked and fixed. Only originating passengers on their outbound leg are priced, so repricing return journeys as a whole is not captured.
- Revenue is in one-way-fare terms and ignores connecting prorates and network effects such as displacement of high-value connections.
- Customers' willingness to pay is lognormal with an assumed spread of 0.45 and rises with the booking period as in the training data. Both policies use the same estimated curve, so neither has an information advantage.
- The 6th-price-point fence for Business customers is an assumption. Results move with it.
