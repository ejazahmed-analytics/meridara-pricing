# Meridara assumptions

Status: agreed with the owner before and during Phase 2. Every number here is a generator input, not a result. Calibration targets sit inside ranges seen in public sources (airport traffic statistics, airline annual reports, industry traffic releases). The specific citations are added in Phase 2 and listed in the README.

Short version for screenshots: Fictional airline, simulated data. For illustration only.

## 1. Structure

| Item | Assumption |
| --- | --- |
| Flights modelled | The 12 directional legs between HUB and the six European stations. Bangkok, Sydney, Nairobi and Mumbai appear as connecting origins and destinations, not as flights. This is a stated simplification. |
| Data window | March 2023 to February 2026 (36 months). Train: March 2023 to August 2025 (30 months). Test: September 2025 to February 2026 (6 months). |
| Window note | The window ends in February 2026 and does not model events from March 2026 onward, such as Easter 2026 and Eid al-Fitr 2026. |
| Split rule | Train and test are split by departure date. Bookings for early flights are made before the window starts (up to 330 days out, and up to about 390 for inbound legs), so booking dates begin before March 2023. |
| Burn-in | The generator also simulates the 75 days before the window (unstored). Without them, inbound legs in March 2023 would have no outbound journeys behind them. Burn-in departures are not in the database. |
| Fare unit | Per passenger, per flight leg, stored in the sales currency (whole units). |
| Cabins | Economy and Business, 10 booking classes each. No premium economy. |
| Booking row | One row per flight leg of a booking (a party of 1 or more passengers). Journeys have one or two legs (section 8). |
| Display currencies | EUR, GBP, AUD, AED, USD. AED is pegged to USD. USD pricing for Bangkok, Nairobi and Mumbai points of sale is a simplification. |
| HUB sales currency | The HUB sells in AED, so journeys that start at the HUB have a point of sale. This is a simplification. |

## 2. Load factors (% of seats)

| Route (both directions) | Weekly freq. per direction | Seats (J+Y) | Low (Jan, Feb, Nov) | Shoulder (Mar to Jun, Sep, Oct, 1 to 17 Dec) | Summer (Jul, Aug) | Christmas and New Year | Annual |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Frankfurt | 7 | 260 (30+230) | 70-76 | 78-84 | 88-93 | 90-95 | about 82 |
| London | 7 | 260 (30+230) | 72-78 | 80-86 | 89-94 | 91-96 | about 84 |
| Paris | 5 | 220 (24+196) | 68-74 | 77-83 | 87-92 | 89-94 | about 81 |
| Milan | 4 | 220 (24+196) | 66-72 | 75-81 | 86-91 | 88-93 | about 79 |
| Madrid | 4 | 180 (16+164) | 64-70 | 73-79 | 85-90 | 87-92 | about 77 |
| Berlin (new) | 5 | 220 (24+196) | 45-55 in month 1, rising to 68-74 by month 4 | n/a | n/a | n/a | about 62 over its departures |

- Network target: about 80%.
- Direction effect: Europe-origin flights peak in late June to July and at Christmas. Return flights peak in late August and early January (3 to 5 points).
- Weekday effect: Tuesday to Thursday and Sunday run about 3 points higher on business-heavy routes.
- The 1 to 17 December period is treated as shoulder. The owner's list of shoulder months did not mention it, so this is an assumption to confirm.
- Seasons for pricing: low = January, February, November; shoulder = March to June, September, October and 1 to 17 December; peak = July, August and 18 December to 5 January.

## 3. Fares

### One-way ladders and the seasonal scale

The booking class ladders are fixed ONE-WAY price points. A return fare is the one-way price divided by 0.6.

| Ladder | Used for departures in | Economy (EUR, Frankfurt level) | Business (EUR, Frankfurt level) |
| --- | --- | --- | --- |
| low | January, February, November | about 140 to 720 | about 800 to 2,800 |
| standard | all other months (shoulder and peak) | the low ladder x 1.18: about 165 to 850 | the low ladder x 1.18: about 940 to 3,300 |

- Why 1.18: with the 60% rule a return leg earns 0.83 of the one-way fare, so average leg revenue would fall about 15% below the agreed fare means. Scaling the ladders by about 1.18 in shoulder and peak restores the agreed average leg yields.
- Low season is not scaled. Low-season yields are therefore about 15% lower than the agreed means (a stated, accepted effect). Berlin launches in the low season with a 10% introductory discount, so its early yields are lower still.
- No double-counting: the fare level is set once, by a target price (segment mean x route index x seasonal price factor x booking-timing factor x noise). In shoulder and peak the target is lifted by the same 1.18. The ladder is only the set of price points the target snaps to, and the scaled ladder stops the top price point from capping it. The 1.18 is never applied again after snapping.
- Seasonal price factor (mean 1 across the year, applied inside the target): low 0.90, shoulder 1.00, summer 1.12, Christmas 1.18.
- Booking-timing factor (higher fares closer to departure): 0.85 at 91+ days out, 1.00 at 31-90 days, 1.15 at 8-30 days, 1.30 at 0-7 days, divided by each segment's expected value so that it averages to 1.
- Fare noise: lognormal, sigma 0.22.

### Agreed fare means (EUR, one-way equivalent, local passenger on a European leg)

Mean paid, with P10 to P90 in brackets, before the 60% rule and the low-season effect.

| Cabin | Business segment | Leisure | VFR |
| --- | --- | --- | --- |
| Economy | 520 (380-720) | 300 (190-430) | 310 (200-470) |
| Business | 1,900 (1,300-2,600) | 1,350 (950-1,800) | 1,200 (900-1,600) |

- Route price index: Frankfurt 1.00, London 1.08, Paris 0.98, Milan 0.95, Madrid 0.97, Berlin 0.96. Berlin has a further 10% introductory discount for its first 90 days (departures to 24 January 2026).
- Business-cabin demand by segment: the agreed shares (35% of Business, 6% of Leisure, 3% of VFR) would fill the Business cabin beyond capacity at the agreed seat counts. They are therefore used as relative propensities only. The Business cabin load is set at 0.88 times the aircraft load factor and the segments are fitted around it. The achieved shares are reported in the sanity checks.

### Connecting passengers

Each booking stores one fare, `through_fare`, per passenger per leg. A small `proration_factors` table (route, beyond-hub city, cabin) holds the leg share. The view `v_bookings_with_leg_fare` derives `leg_fare = through_fare x factor`. Local bookings use a factor of 1.

Simplification: the factor is fixed per route, city and cabin, so leg_fare varies only with through_fare. Real prorates also vary by fare type and date.

Leg fare relative to the local average on the same leg:

| Cabin | Connecting leg share of local average |
| --- | --- |
| Economy | 60-85% (Bangkok 0.82, Sydney 0.62, Nairobi 0.72, Mumbai 0.65) |
| Business | 90-110% (Bangkok 1.00, Sydney 1.08, Nairobi 0.93, Mumbai 0.92) |

### Network contribution (used by the Network Revenue view)

network contribution = through_fare - estimated displacement cost on the beyond-hub leg

- This is a deliberately simple version. It is not bid-price logic, which is left for a later project.
- The displacement cost is a fixed assumption per beyond-hub city, season and cabin. The values are shown to the owner for review in Phase 2 and loaded only after approval (the `displacement_costs` table is created empty).
- Local passengers are compared on leg revenue only, since they use no beyond-hub seat.

## 4. Segment mix (% of passengers, local and connecting combined)

| Route | Business | Leisure | VFR | Connecting share |
| --- | --- | --- | --- | --- |
| Frankfurt | 38 | 42 | 20 | 45% |
| London | 40 | 36 | 24 | 40% |
| Paris | 28 | 50 | 22 | 50% |
| Milan | 30 | 50 | 20 | 55% |
| Madrid | 20 | 60 | 20 | 55% |
| Berlin | 22 rising to 30 | 50 | 28 falling to 20 | 60% |

Connecting flows beyond the hub:

| Beyond-hub city | Share of connecting traffic | Business | Leisure | VFR |
| --- | --- | --- | --- | --- |
| Bangkok | 30% | 15 | 70 | 15 |
| Sydney | 25% | 25 | 50 | 25 |
| Nairobi | 20% | 30 | 20 | 50 |
| Mumbai | 25% | 20 | 20 | 60 |

The local mix is backed out of the route mix after removing the connecting flows. Where that leaves a segment below zero (Berlin VFR at the end of its ramp), it is floored at 2%, so the achieved route mix deviates slightly from the target.

## 5. Booking curves (share of a segment's final bookings by days before departure)

| Segment | 330-181 | 180-91 | 90-61 | 60-31 | 30-15 | 14-8 | 7-0 | Average days out |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Business | 2% | 6% | 8% | 18% | 24% | 22% | 20% | about 26 |
| Leisure | 14% | 28% | 20% | 18% | 11% | 6% | 3% | about 95 |
| VFR | 20% | 25% | 15% | 17% | 12% | 6% | 5% | about 105 |

- These curves describe the booking time of the OUTBOUND leg of a journey (or a one-way journey).
- An inbound leg is booked at the same time as its outbound leg, so its days before departure equal the outbound value plus the stay. Flight-level booking curves are therefore a blend of both.
- Berlin: sales open 180 days before the first flight, so early curves are truncated.
- VFR has an extra spike 60 to 90 days before Eid and Diwali.
- Daily booking counts are drawn from a Poisson distribution around these shapes.

## 6. Seasonality and events (demand multiplier, 1.00 = annual average)

Monthly index: Jan 0.88, Feb 0.85, Mar 0.95, Apr 1.02, May 0.98, Jun 1.08, Jul 1.22, Aug 1.25, Sep 1.02, Oct 0.96, Nov 0.88, Dec 1.12.

| Event | Dates in the window | Effect on top of monthly index | Segments and flows |
| --- | --- | --- | --- |
| Christmas and New Year | 18 Dec to 5 Jan | Mix shift only (already inside the load factors): leisure and VFR x1.30 | Leisure, VFR |
| Easter | Good Friday plus or minus 7 days: 7 Apr 2023, 29 Mar 2024, 18 Apr 2025 | +18% | Leisure |
| School summer holidays (UK, DE, FR, IT, ES) | Simplified windows per country | Mix shift only: leisure x1.12 from that country's station | Leisure |
| School autumn half-term (UK, DE, FR) | One week at the end of October | +12% | Leisure |
| Eid al-Fitr | 21 Apr 2023, 10 Apr 2024, 31 Mar 2025 | VFR +35% in the 10 days before | Mumbai, Nairobi, Bangkok-linked flows |
| Eid al-Adha | 28 Jun 2023, 16 Jun 2024, 6 Jun 2025 | VFR +35% in the 10 days before | Mumbai, Nairobi, Bangkok-linked flows |
| Diwali | 12 Nov 2023, 31 Oct 2024, 20 Oct 2025 | VFR +50% in the 10 days before | Mumbai flows |
| Winter sun to the Gulf | Nov to Feb | Mix shift only: local leisure x1.15 | Leisure |
| Weekday | Tue to Thu | Mix shift only: Business x1.10, Leisure x0.95 | Business, Leisure |

The held-out window (September 2025 to February 2026) contains Diwali 2025, Christmas and New Year, the low season and the Berlin launch. It contains no summer peak, no Easter and no Eid. Christmas 2022 is in the events table only to feed the burn-in period.

## 7. Berlin launch

| Item | Assumption |
| --- | --- |
| Sales open | about 29 April 2025 (180 days before launch) |
| First departure | 26 October 2025, the start of the winter schedule |
| Departures in the dataset | 26 October 2025 to 28 February 2026, about 18 weeks |
| Berlin training history | None. Only the pre-launch booking pace for early flights is visible. |
| Ramp | Load factor 45-55% in month 1, reaching 68-74% by month 4. Business share 22% rising to 30%. |
| Frequency | 5 per week per direction |
| Pricing | Route index 0.96 and a 10% introductory discount for 90 days. Berlin starts in the low season, so it sells on the low ladder in November. |
| Cold-start method | Borrow patterns from Frankfurt, Paris and Milan, then compare Berlin's early forecast error with Frankfurt's. |

## 8. Journeys: one-way and return travel

Bookings are generated as journeys. Each journey has a `journey_id`, a `trip_type` (OW or RT) and one or two legs on opposite-direction flights of the same station.

| Segment | Return (RT) share of journeys | Stay length |
| --- | --- | --- |
| Business | 85% | 3 to 10 days, peaking at 4 to 5 (a small tail to 14 days) |
| Leisure | 92% | 7 to 21 days, clear peaks at 7 and 14 days |
| VFR | 70% | 14 to 60 days, peaking around 21 to 30 days |

- Stay shapes are fixed probability tables in the generator (see `build_stay_distributions`).
- Routes do not fly daily, so the inbound leg uses the first operating departure on or after the drawn stay. The realised stay can be a day or two longer than drawn.
- Both legs share segment, cabin, booking class, party size, point of sale, channel and beyond-hub city.
- Pricing rule (stated simplification): a one-way fare is always 60% of the return fare for the same journey, in every segment and cabin. Real fare structures vary by market and fare class.
- A return journey is priced once, at the outbound flight: `through_fare` per leg is half of the return fare, so both legs carry the same amount. Promotions and the Berlin introductory discount apply to the outbound flight only.
- Window edges. Returns after 28 February 2026 keep their journey and `trip_type` RT but have no inbound row. Mirror case: inbound legs in March 2023 whose outbound left before the window have `leg_seq = 2` and no outbound row.
- Flight loads: each flight's target load is split into originating passengers and expected returning passengers, solved by repeated substitution, so that flight load factors stay on target. Price effects act on originating demand only.
- Capacity: if either leg of a journey would exceed seats, the whole journey is dropped (random spill). This lowers load factors a little.
- Directional balance (Network view): the data holds each route's two directions, round-trip and one-way legs by direction, so imbalance by route and week can be shown.

## 9. Point of sale, channel and revenue targets

- Point of sale is assigned per journey, not per leg:

| Segment | Origin | Destination | Third station |
| --- | --- | --- | --- |
| Business | 85% | 12% | 3% |
| Leisure | 95% | 3% | 2% |
| VFR | 80% | 18% | 2% |

- Origin and destination: a local journey runs between a European station and the HUB. A connecting journey runs between a European station and a beyond-hub city, via the HUB. The third station is drawn from Frankfurt, London, Paris, Milan, Madrid and the four beyond-hub cities, excluding the origin and destination. Berlin and the HUB are not third stations (Berlin had no sales office before launch).
- Revenue targets are by point of sale: station revenue is revenue sold at that station's POS (all routes, both legs), counted in the month each leg departs and converted at that month's rate. Targets are synthetic: each month's target is simulated revenue times a fixed station bias (Frankfurt 0.96, Berlin 1.12, London 1.03, Paris 0.99, Milan 1.06, Madrid 0.94) and 3% noise. A bias below 1 means the station beats target. Berlin has targets from October 2025.
- The Station view splits revenue sold at a station into origin-sold (the journey started there) and foreign-origin-sold (the journey started elsewhere and was sold there).
- Sales channels (Airline direct, NDC, GDS, OTA) are assigned with a placeholder mix by segment. They are stored for a later project and are not analysed in Project 1.

## 10. Price sensitivity and promotions

- True price sensitivity used by the generator: Business -0.5, Leisure -1.6, VFR -1.3, each with random noise.
- About 15% of flights get a randomised promotional discount of 5 to 20%, unrelated to demand. The promotion acts on originating demand at that flight, so Phase 4 should estimate sensitivity on outbound legs only (`leg_seq = 1`). Returning passengers do not respond to the promotion on their return flight.
- A competitor price index (a mean-reverting weekly series per route) has a small effect on demand (exponents 0.2 Business, 0.5 Leisure and VFR).

## 11. Views the data supports (Phase 5)

| View | Added content | Data used |
| --- | --- | --- |
| Station | Revenue sold at the station's POS vs target, split into origin-sold and foreign-origin-sold; one-way vs return mix by point of sale | `revenue_targets`, `sold_at_origin`, `trip_type`, `pos_station_id` |
| Revenue Management | One-way vs return pricing (one-way fare vs half the return fare, by route, segment and days out) | `trip_type`, `journey_fare`, `through_fare` |
| Network Revenue | Directional balance by route and week; local vs connecting mix | `direction`, `leg_seq`, `trip_type`, `traffic_type` |

## 12. Size and storage

| Item | Value |
| --- | --- |
| Flights | about 8,600 (plus about 580 unstored burn-in) |
| Booking rows | about 0.96 million |
| Database size | about 34 MB (measured), under the 50 MB limit |
| Layout | `bookings` is stored in flight order (WITHOUT ROWID, key `flight_id, booking_id`), so no separate flight index is needed. No index on `journey_id`. |
| Frequency lever | Only if the database exceeds 50 MB: reduce Madrid and Milan frequencies or raise party sizes, then rerun. |
| Git | The database and small CSVs are committed. The large bookings CSV is not committed or written. |
| booking_date | Not stored. Derived in a SQL view as departure date minus days before departure. |

## 13. Stated simplifications

- Only the European legs are flights. Beyond-hub legs are not modelled.
- A one-way fare is always 60% of the return fare.
- Prorate factors are fixed per route, city and cabin.
- Stay lengths follow fixed shapes and snap to operating days.
- Observed bookings are capped by seats. Spilled demand is not recorded, so booking data understates true demand on full flights.
- Fares are converted to other currencies at the monthly average rate for the month each leg departs. A return fare is set once, in the sales currency, at the outbound month's rate. Burn-in months before March 2023 use the March 2023 rate.
- USD pricing for Bangkok, Nairobi and Mumbai points of sale, and AED sales at the HUB.
- The sales channel mix is a placeholder.
