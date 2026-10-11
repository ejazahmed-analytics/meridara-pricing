# Meridara assumptions

Status: agreed with the owner before Phase 2 coding. Every number here is a generator input, not a result. Calibration targets sit inside ranges seen in public sources (airport traffic statistics, airline annual reports, industry traffic releases). The specific citations are added in Phase 2 and listed in the README.

Short version for screenshots: Fictional airline, simulated data. For illustration only.

## 1. Structure

| Item | Assumption |
| --- | --- |
| Flights modelled | The 12 directional legs between HUB and the six European stations. Bangkok, Sydney, Nairobi and Mumbai appear as connecting origins and destinations, not as flights. This is a stated simplification. |
| Data window | March 2023 to February 2026 (36 months). Train: March 2023 to August 2025 (30 months). Test: September 2025 to February 2026 (6 months). |
| Window note | The window ends in February 2026 and does not model events from March 2026 onward, such as Easter 2026 and Eid al-Fitr 2026. |
| Split rule | Train and test are split by departure date. Bookings for early flights are made before the window starts (up to 330 days out), so booking dates begin before March 2023. |
| Fare unit | One-way, per passenger, stored in the sales currency. |
| Cabins | Economy and Business, 10 booking classes each. No premium economy. |
| Booking row | One row per booking (party), with a passenger count. |
| Display currencies | EUR, GBP, AUD, AED, USD. AED is pegged to USD. USD pricing for Bangkok, Nairobi and Mumbai points of sale is a simplification. |

## 2. Load factors (% of seats)

| Route (both directions) | Weekly freq. per direction | Seats (J+Y) | Low (Jan, Feb, Nov) | Shoulder (Mar to Jun, Sep, Oct) | Summer (Jul, Aug) | Christmas and New Year | Annual |
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

## 3. Fares (EUR equivalent, one-way, local passenger on a European leg)

Mean paid, with P10 to P90 in brackets.

| Cabin | Business segment | Leisure | VFR | Booking class ladder |
| --- | --- | --- | --- | --- |
| Economy | 520 (380-720) | 300 (190-430) | 310 (200-470) | about 140 to about 720 |
| Business | 1,900 (1,300-2,600) | 1,350 (950-1,800) | 1,200 (900-1,600) | about 800 to about 2,800 |

- Route price index: Frankfurt 1.00, London 1.08, Paris 0.98, Milan 0.95, Madrid 0.97, Berlin 0.96. Berlin has a further 10% introductory discount for its first 3 months.
- Share of each segment in the Business cabin: Business 35%, Leisure 6%, VFR 3%.

### Connecting passengers: two fare fields

Each connecting booking stores both:

- **through_fare**: the full fare for the whole journey, in the sales currency.
- **leg_fare**: the prorated share attributed to this flight.

Local bookings have through_fare equal to leg_fare.

Prorated leg share relative to the local average on the same leg:

| Cabin | Connecting leg share of local average |
| --- | --- |
| Economy | 60-85% |
| Business | 90-110% |

### Network contribution (used by the Network Revenue view)

network contribution = through_fare - estimated displacement cost on the beyond-hub leg

- This is a deliberately simple version. It is not bid-price logic, which is left for a later project.
- The displacement cost is a fixed assumption per beyond-hub city and season (the average value of the seat that the connecting passenger takes on the beyond-hub leg). The values are set in Phase 2 and shown in a small table for the owner to review before they are used.
- Local passengers are compared on leg revenue only, since they use no beyond-hub seat.

## 4. Segment mix (% of passengers, local and connecting combined)

| Route | Business | Leisure | VFR | Connecting share |
| --- | --- | --- | --- | --- |
| Frankfurt | 38 | 42 | 20 | 45% |
| London | 40 | 36 | 24 | 40% |
| Paris | 28 | 50 | 22 | 50% |
| Milan | 30 | 50 | 20 | 55% |
| Madrid | 20 | 60 | 20 | 55% |
| Berlin | 22 rising to 30 | 50 | 20 to 28 | 60% |

Connecting flows beyond the hub:

| Beyond-hub city | Share of connecting traffic | Business | Leisure | VFR |
| --- | --- | --- | --- | --- |
| Bangkok | 30% | 15 | 70 | 15 |
| Sydney | 25% | 25 | 50 | 25 |
| Nairobi | 20% | 30 | 20 | 50 |
| Mumbai | 25% | 20 | 20 | 60 |

## 5. Booking curves (share of final bookings by days before departure)

| Segment | 330-181 | 180-91 | 90-61 | 60-31 | 30-15 | 14-8 | 7-0 | Average days out |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Business | 2% | 6% | 8% | 18% | 24% | 22% | 20% | about 26 |
| Leisure | 14% | 28% | 20% | 18% | 11% | 6% | 3% | about 95 |
| VFR | 20% | 25% | 15% | 17% | 12% | 6% | 5% | about 105 |

- Berlin: sales open 180 days before the first flight, so early curves are truncated.
- VFR has an extra spike 60 to 90 days before Eid and Diwali.
- Daily booking counts are drawn from a Poisson distribution around these shapes.

## 6. Seasonality and events (demand multiplier, 1.00 = annual average)

Monthly index: Jan 0.88, Feb 0.85, Mar 0.95, Apr 1.02, May 0.98, Jun 1.08, Jul 1.22, Aug 1.25, Sep 1.02, Oct 0.96, Nov 0.88, Dec 1.12.

| Event | Dates in the window | Effect on top of monthly index | Segments and flows |
| --- | --- | --- | --- |
| Christmas and New Year | 18 Dec to 5 Jan | +30%. Outbound 18 to 23 Dec, return 2 to 6 Jan. | Leisure, VFR |
| Easter | Good Friday plus or minus 7 days: 7 Apr 2023, 29 Mar 2024, 18 Apr 2025 | +18% | Leisure |
| School holidays (UK, DE, FR, IT, ES) | Simplified windows per country | +10 to 15% from that country's station | Leisure |
| Eid al-Fitr | 21 Apr 2023, 10 Apr 2024, 31 Mar 2025 | VFR +35% in the 10 days before | Mumbai, Nairobi, Bangkok-linked flows |
| Eid al-Adha | 28 Jun 2023, 16 Jun 2024, 6 Jun 2025 | VFR +35% in the 10 days before | Mumbai, Nairobi, Bangkok-linked flows |
| Diwali | 12 Nov 2023, 31 Oct 2024, 20 Oct 2025 | VFR +50% in the 10 days before | Mumbai flows |
| Winter sun to the Gulf | Nov to Feb, peaking Dec to Feb and Feb half-term | +15% on local (HUB) traffic | Leisure |
| Weekday | Tue to Thu | Business +10%, Leisure -5% | Business, Leisure |

The held-out window (September 2025 to February 2026) contains Diwali 2025, Christmas and New Year, the low season and the Berlin launch. It contains no summer peak, no Easter and no Eid.

## 7. Berlin launch

| Item | Assumption |
| --- | --- |
| Sales open | about 29 April 2025 (180 days before launch) |
| First departure | 26 October 2025, the start of the winter schedule |
| Departures in the dataset | 26 October 2025 to 28 February 2026, about 18 weeks |
| Berlin training history | None. Only the pre-launch booking pace for early flights is visible. |
| Ramp | Load factor 45-55% in month 1, reaching 68-74% by month 4. Business share 22% rising to 30%. |
| Frequency | 5 per week per direction |
| Cold-start method | Borrow patterns from Frankfurt, Paris and Milan, then compare Berlin's early forecast error with Frankfurt's. |

## 8. Price sensitivity and promotions

- True price sensitivity used by the generator: Business -0.5, Leisure -1.6, VFR -1.3, each with random noise.
- About 15% of flights get a randomised promotional discount of 5 to 20%, unrelated to demand. Phase 4 uses this variation to estimate sensitivity without bias from demand-driven pricing.

## 9. Size budget

| Item | Estimate |
| --- | --- |
| Flights | about 8,600 |
| Bookings | about 0.9 to 1.0 million rows |
| Database size target | under 40 MB, hard ceiling 50 MB. The two fare fields add roughly 2 to 3 MB, so the estimate is about 32 to 41 MB. It will be measured after generation. |
| Safety lever | If the measured size is over 40 MB, reduce the Madrid and Milan frequencies or raise the party size, then rerun. |
| Git | The database and small CSVs are committed. The large bookings CSV is not committed, because the fixed seed regenerates it. |
| booking_date | Not stored. Derived in a SQL view as departure date minus days before departure. |
