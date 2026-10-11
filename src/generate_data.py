"""Generate the synthetic Meridara dataset and load it into SQLite.

Illustrative case study using fictitious and simulated data.

Run from the project root:   python src/generate_data.py
The same seed always produces the same database.

Bookings are generated as journeys. A one-way journey has one flight leg; a
return journey has an outbound leg and an inbound leg on the opposite-direction
route, linked by journey_id.

Assumptions are documented in docs/assumptions.md. Numbers in the constant
tables below are the agreed generator inputs, not results.
"""
import argparse
import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SCHEMA_FILE = ROOT / "sql" / "schema.sql"
DEFAULT_SEED = 2026

START = pd.Timestamp("2023-03-01")
END = pd.Timestamp("2026-02-28")
TEST_START = pd.Timestamp("2025-09-01")
BERLIN_LAUNCH = pd.Timestamp("2025-10-26")
BERLIN_SALES_OPEN = BERLIN_LAUNCH - pd.Timedelta(days=180)
BURN_IN_DAYS = 75                 # unstored departures before START, so early returns exist
COMP_WEEK0 = pd.Timestamp("2022-12-12")   # a Monday, covers the burn-in period
MAX_DAYS_OUT = 330
HUB_ID = 11

SEGMENTS = ["Business", "Leisure", "VFR"]          # segment_id = index + 1
CABINS = ["Economy", "Business"]                   # cabin_id = index + 1
TRIP_TYPES = ["OW", "RT"]                          # trip_type_id = index + 1
CHANNELS = ["Airline direct", "NDC", "GDS", "OTA"]  # channel_id = index + 1
SEASONS = ["low", "shoulder", "summer", "christmas"]

# ---------------------------------------------------------------------
# Reference inputs (agreed assumptions)
# ---------------------------------------------------------------------

# (station_id, name, region, role, sales currency)
STATIONS = [
    (1, "Frankfurt", "Europe", "featured", "EUR"),
    (2, "Berlin", "Europe", "featured", "EUR"),
    (3, "London", "Europe", "core", "GBP"),
    (4, "Paris", "Europe", "core", "EUR"),
    (5, "Milan", "Europe", "core", "EUR"),
    (6, "Madrid", "Europe", "core", "EUR"),
    (7, "Bangkok", "Asia", "beyond hub", "USD"),
    (8, "Sydney", "Australia", "beyond hub", "AUD"),
    (9, "Nairobi", "Africa", "beyond hub", "USD"),
    (10, "Mumbai", "South Asia", "beyond hub", "USD"),
    (11, "HUB", "Hub", "hub", "AED"),
]
STATION_COUNTRY = {1: "DE", 2: "DE", 3: "UK", 4: "FR", 5: "IT", 6: "ES"}

# One spec per European station (each makes two directional routes).
# lf = generator load factor input in % for (low, shoulder, summer, christmas). Summer and
# Christmas values sit about 2 points above the agreed range midpoints to offset spill
# (whole journeys are dropped when a leg is full), so achieved load factors land in the ranges.
# mix = passenger mix % (business, leisure, VFR); conn = connecting share.
SPECS = [
    dict(station_id=1, band="Band 2", aircraft="Type A", seats=(30, 230), freq=7,
         days=[0, 1, 2, 3, 4, 5, 6], idx=1.00, conn=0.45, mix=(38, 42, 20),
         lf=(73, 81, 92.5, 95), pro_adj=1.00),
    dict(station_id=2, band="Band 2", aircraft="Type B", seats=(24, 196), freq=5,
         days=[0, 1, 3, 4, 6], idx=0.96, conn=0.60, mix=(22, 50, 28),
         lf=(0, 0, 0, 0), pro_adj=0.99),   # Berlin load factor comes from a ramp
    dict(station_id=3, band="Band 3", aircraft="Type A", seats=(30, 230), freq=7,
         days=[0, 1, 2, 3, 4, 5, 6], idx=1.08, conn=0.40, mix=(40, 36, 24),
         lf=(75, 83, 93.5, 96), pro_adj=1.02),
    dict(station_id=4, band="Band 3", aircraft="Type B", seats=(24, 196), freq=5,
         days=[0, 1, 3, 4, 6], idx=0.98, conn=0.50, mix=(28, 50, 22),
         lf=(71, 80, 91.5, 94), pro_adj=1.01),
    dict(station_id=5, band="Band 2", aircraft="Type B", seats=(24, 196), freq=4,
         days=[0, 2, 4, 6], idx=0.95, conn=0.55, mix=(30, 50, 20),
         lf=(69, 78, 90.5, 93), pro_adj=0.99),
    dict(station_id=6, band="Band 3", aircraft="Type C", seats=(16, 164), freq=4,
         days=[0, 2, 4, 6], idx=0.97, conn=0.55, mix=(20, 60, 20),
         lf=(67, 76, 89.5, 92), pro_adj=1.01),
]
SPEC = {s["station_id"]: s for s in SPECS}

# Connecting flows: Bangkok, Sydney, Nairobi, Mumbai (flow 1 to 4; flow 0 = local).
CITY_SHARE = np.array([0.30, 0.25, 0.20, 0.25])
CITY_MIX = np.array([[15, 70, 15], [25, 50, 25], [30, 20, 50], [20, 20, 60]]) / 100
CITY_LEG_SHARE = [0.50, 0.28, 0.53, 0.63]    # share of through fare on the European leg
REL_LEG = {1: [0.82, 0.62, 0.72, 0.65],      # leg fare vs local average, Economy
           2: [1.00, 1.08, 0.93, 0.92]}      # Business

MONTH_IDX = {1: .88, 2: .85, 3: .95, 4: 1.02, 5: .98, 6: 1.08,
             7: 1.22, 8: 1.25, 9: 1.02, 10: .96, 11: .88, 12: 1.12}
SEASON_MONTHS = {"low": [1, 2, 11], "shoulder": [3, 4, 5, 6, 9, 10, 12], "summer": [7, 8]}
SEASON_AVG_IDX = {s: np.mean([MONTH_IDX[m] for m in ms]) for s, ms in SEASON_MONTHS.items()}
SEASON_AVG_IDX["christmas"] = 1.12
SEASON_PRICE = {"low": 0.90, "shoulder": 1.00, "summer": 1.12, "christmas": 1.18}

# One-way fare ladders. The 'standard' ladder (shoulder and peak departures) is
# the 'low' ladder scaled up. The same factor lifts the target fare in those
# seasons, so the ladder only widens the set of price points: the 1.18 is
# applied once to the fare level, not twice.
ECON_LADDER = np.geomspace(140, 720, 10)
BIZ_LADDER = np.geomspace(800, 2800, 10)
CLASS_CODES = {1: list("LKTQVWMHBY"), 2: list("ONUPZRDICJ")}
STANDARD_SCALE = 1.18
ONE_WAY_RATIO = 0.6               # one-way fare = 60% of the return fare (simplification)

# Mean one-way-equivalent fare in EUR for a local passenger, [cabin][segment].
FARE_MEAN = np.array([[520, 300, 310], [1900, 1350, 1200]], float)
FARE_SIGMA = 0.22

# Share of final bookings by days before departure, per segment.
# Column order: 330-181, 180-91, 90-61, 60-31, 30-15, 14-8, 7-0.
WINDOW_SHARE = np.array([[2, 6, 8, 18, 24, 22, 20],
                         [14, 28, 20, 18, 11, 6, 3],
                         [20, 25, 15, 17, 12, 6, 5]]) / 100
KNOTS = np.array([0, 8, 15, 31, 61, 91, 181, 331])     # window edges in days
WINDOW_TIMING = np.array([.85, .85, 1.0, 1.0, 1.15, 1.15, 1.30])  # fare uplift near departure

PARTY = [([1, 2], [.88, .12]),
         ([1, 2, 3, 4], [.25, .45, .12, .18]),
         ([1, 2, 3, 4, 5], [.25, .35, .18, .17, .05])]
MEAN_PARTY = np.array([np.dot(s, p) for s, p in PARTY])

# Return travel: share of journeys that are returns, by segment.
RT_SHARE = np.array([0.85, 0.92, 0.70])


def build_stay_distributions():
    """Stay length in days (days, probabilities) per segment, with the agreed shapes."""
    biz_days = np.arange(3, 15)         # mostly 3-10, peak at 4-5, small tail to 14
    biz_w = np.array([.095, .209, .209, .1425, .095, .076, .0665, .057,
                      .0125, .0125, .0125, .0125])
    lei_days = np.arange(7, 22)         # peaks at 7 and 14 days, within 7-21
    lei_w = np.array([.20, .05, .04, .05, .05, .06, .07, .22,
                      .06, .04, .03, .03, .02, .02, .06])
    vfr_days = np.arange(14, 61)        # broad peak at 21-30 days, within 14-60
    vfr_w = np.interp(vfr_days, [14, 21, 30, 45, 60], [.45, 1.0, 1.0, .25, .05])
    return [(d, w / w.sum()) for d, w in ((biz_days, biz_w), (lei_days, lei_w), (vfr_days, vfr_w))]


STAY = build_stay_distributions()

# Point of sale for each journey: share sold at the journey origin, the
# destination, or a third station. Rows: Business, Leisure, VFR.
POS_MIX = np.array([[.85, .12, .03], [.95, .03, .02], [.80, .18, .02]])
THIRD_POOL = np.array([1, 3, 4, 5, 6, 7, 8, 9, 10])   # Berlin excluded, HUB excluded

E_PRICE = np.array([-0.5, -1.6, -1.3])   # true price sensitivity by segment
E_COMP = np.array([0.2, 0.5, 0.5])       # reaction to the competitor index
CABIN_PROP = np.array([0.35, 0.06, 0.03])  # relative wish for the Business cabin by segment

CHANNEL_MIX = np.array([[.30, .08, .50, .12],   # placeholder, not calibrated
                        [.30, .07, .08, .55],
                        [.28, .04, .06, .62]])

TARGET_BIAS = {1: 0.96, 2: 1.12, 3: 1.03, 4: 0.99, 5: 1.06, 6: 0.94}  # target / actual

# ---------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------


def build_routes():
    """12 directional routes: 6 European stations, each to and from the HUB."""
    rows = []
    for i, sp in enumerate(SPECS):
        for k, direction in enumerate(("to_hub", "from_hub")):
            rows.append(dict(route_id=2 * i + 1 + k, station_id=sp["station_id"],
                             direction=direction, distance_band=sp["band"],
                             aircraft_type=sp["aircraft"], seats_business=sp["seats"][0],
                             seats_economy=sp["seats"][1], weekly_frequency=sp["freq"],
                             price_index=sp["idx"]))
    return pd.DataFrame(rows)


def build_fare_buckets(routes):
    """10 one-way price points per route, cabin and ladder (low and standard)."""
    rows = []
    for r in routes.itertuples():
        for cabin, base in ((1, ECON_LADDER), (2, BIZ_LADDER)):
            for ladder, scale in (("low", 1.0), ("standard", STANDARD_SCALE)):
                for rank, price in enumerate(base, start=1):
                    rows.append(dict(route_id=r.route_id, cabin_id=cabin, ladder=ladder,
                                     class_rank=rank, class_code=CLASS_CODES[cabin][rank - 1],
                                     price_point_eur=round(price * r.price_index * scale, 2)))
    return pd.DataFrame(rows)


def build_proration(routes):
    """Leg share of the through fare, per route, beyond-hub city and cabin."""
    rows = []
    for r in routes.itertuples():
        for city in range(4):
            for cabin in (1, 2):
                factor = round(CITY_LEG_SHARE[city] * SPEC[r.station_id]["pro_adj"], 3)
                rows.append(dict(route_id=r.route_id, beyond_city_id=city + 1,
                                 cabin_id=cabin, factor=factor))
    return pd.DataFrame(rows)


def build_events():
    """Dated events. 'family' and 'country' are helper columns, not stored."""
    items = []

    def add(name, family, start, end, country=None):
        items.append(dict(event_name=name, family=family, country=country,
                          start_date=pd.Timestamp(start), end_date=pd.Timestamp(end)))

    for y in (2022, 2023, 2024, 2025):     # 2022 only feeds the burn-in period
        add("Christmas and New Year", "xmas", f"{y}-12-18", f"{y + 1}-01-05")
    for s, e in (("2023-03-31", "2023-04-14"), ("2024-03-22", "2024-04-05"),
                 ("2025-04-11", "2025-04-25")):
        add("Easter holidays", "easter", s, e)
    for s, e in (("2023-04-11", "2023-04-21"), ("2024-03-31", "2024-04-10"),
                 ("2025-03-21", "2025-03-31")):
        add("Eid al-Fitr", "eid", s, e)
    for s, e in (("2023-06-18", "2023-06-28"), ("2024-06-06", "2024-06-16"),
                 ("2025-05-27", "2025-06-06")):
        add("Eid al-Adha", "eid", s, e)
    for s, e in (("2023-11-02", "2023-11-12"), ("2024-10-21", "2024-10-31"),
                 ("2025-10-10", "2025-10-20")):
        add("Diwali", "diwali", s, e)
    summer = {"UK": ("07-22", "09-03"), "DE": ("07-05", "09-05"), "FR": ("07-08", "09-01"),
              "IT": ("06-10", "09-10"), "ES": ("06-22", "09-08")}
    for y in (2023, 2024, 2025):
        for c, (s, e) in summer.items():
            add(f"School summer holidays ({c})", "school_summer", f"{y}-{s}", f"{y}-{e}", c)
    autumn = {2023: ("10-23", "10-27"), 2024: ("10-28", "11-01"), 2025: ("10-27", "10-31")}
    for y, (s, e) in autumn.items():
        for c in ("UK", "DE", "FR"):
            add(f"Autumn half-term ({c})", "autumn", f"{y}-{s}", f"{y}-{e}", c)
    ev = pd.DataFrame(items)
    ev.insert(0, "event_id", np.arange(1, len(ev) + 1))
    return ev


def build_fx():
    """Monthly rates to EUR from the ECB file; AED derived from the USD peg."""
    raw = pd.read_csv(DATA_DIR / "ecb_fx_monthly.csv")
    months = pd.period_range("2023-03", "2026-02", freq="M").astype(str)
    src = ("ECB euro foreign exchange reference rates, monthly average, series "
           "EXR.M.{c}.EUR.SP00.A, ECB Data Portal (data-api.ecb.europa.eu)")
    rows = []
    for m in months:
        rows.append((m, "EUR", 1.0, "Base currency"))
        for c in ("GBP", "USD", "AUD"):
            per_eur = raw[(raw.CURRENCY == c) & (raw.TIME_PERIOD == m)].OBS_VALUE.iloc[0]
            rows.append((m, c, round(1 / per_eur, 6), src.format(c=c)))
            if c == "USD":
                usd_per_eur = per_eur
        rows.append((m, "AED", round(1 / (usd_per_eur * 3.6725), 6),
                     "Derived from the USD rate using the fixed peg of 3.6725 AED per USD"))
    return pd.DataFrame(rows, columns=["month", "currency", "rate_to_eur", "source"])


def build_competitor_index(routes, rng):
    """Weekly competing-hub price index per route: a mean-reverting random walk."""
    weeks = pd.date_range(COMP_WEEK0, "2026-02-23", freq="7D")
    matrix = np.zeros((len(routes), len(weeks)))
    for i in range(len(routes)):
        eps = rng.normal(0, 2.5, len(weeks))
        x = np.zeros(len(weeks))
        x[0] = 100
        for t in range(1, len(weeks)):
            x[t] = np.clip(100 + 0.85 * (x[t - 1] - 100) + eps[t], 85, 120)
        matrix[i] = x
    rows = [(r.route_id, w.strftime("%Y-%m-%d"), round(matrix[i, j], 1))
            for i, r in enumerate(routes.itertuples())
            for j, w in enumerate(weeks) if w >= pd.Timestamp("2023-02-27")]
    df = pd.DataFrame(rows, columns=["route_id", "week_start", "index_value"])
    return df, matrix


# ---------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------


def window_flag(f, events, family):
    """True where a flight departs inside any event window of one family."""
    flag = np.zeros(len(f), bool)
    dates = f["departure_date"].to_numpy()
    stn = f["station_id"].to_numpy()
    for e in events[events.family == family].itertuples():
        hit = (dates >= e.start_date.to_datetime64()) & (dates <= e.end_date.to_datetime64())
        if e.country is not None:
            hit &= np.isin(stn, [s for s, c in STATION_COUNTRY.items() if c == e.country])
        flag |= hit
    return flag


def build_flights(routes, events, rng):
    """One row per departure, burn-in days included (their flight_id is 0 or less)."""
    dates = pd.date_range(START - pd.Timedelta(days=BURN_IN_DAYS), END)
    parts = []
    for r in routes.itertuples():
        d = dates[dates.dayofweek.isin(SPEC[r.station_id]["days"])]
        if r.station_id == 2:
            d = d[d >= BERLIN_LAUNCH]                       # Berlin starts at launch
        parts.append(pd.DataFrame({"route_id": r.route_id, "departure_date": d}))
    f = pd.concat(parts).sort_values(["departure_date", "route_id"]).reset_index(drop=True)
    n_burn = int((f.departure_date < START).sum())
    f.insert(0, "flight_id", np.arange(len(f)) - n_burn + 1)

    rt = routes.set_index("route_id")
    f["station_id"] = f.route_id.map(rt.station_id)
    f["direction"] = f.route_id.map(rt.direction)
    f["capacity_business"] = f.route_id.map(rt.seats_business)
    f["capacity_economy"] = f.route_id.map(rt.seats_economy)
    f["weekday"] = f.departure_date.dt.dayofweek
    f["month"] = f.departure_date.dt.month
    day = f.departure_date.dt.day
    xmas = ((f.month == 12) & (day >= 18)) | ((f.month == 1) & (day <= 5))
    f["season"] = np.select(
        [xmas, f.month.isin([7, 8]), f.month.isin([1, 2, 11])],
        ["christmas", "summer", "low"], default="shoulder")

    for fam in ("xmas", "easter", "eid", "diwali", "school_summer", "autumn"):
        f[fam] = window_flag(f, events, fam)

    # Main event per flight: the first match in priority order.
    f["event_id"] = np.nan
    for fam in ("xmas", "diwali", "eid", "easter", "school_summer", "autumn"):
        for e in events[events.family == fam].itertuples():
            hit = (f.departure_date >= e.start_date) & (f.departure_date <= e.end_date)
            if e.country is not None:
                hit &= f.station_id.isin([s for s, c in STATION_COUNTRY.items() if c == e.country])
            f.loc[hit & f.event_id.isna(), "event_id"] = e.event_id

    f["berlin_launch_flag"] = (f.station_id == 2).astype(int)
    u = rng.random(len(f))
    disc = rng.uniform(5, 20, len(f)).round(1)
    f["promo_discount_pct"] = np.where(u < 0.15, disc, 0.0)    # random, unrelated to demand
    f["is_test"] = (f.departure_date >= TEST_START).astype(int)
    return f


# ---------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------


def flow_weights(route_mix, conn_share):
    """Share of passengers by segment and flow, as a (3, 5) array summing to 1.

    Flow 0 is local; flows 1 to 4 are connecting via Bangkok, Sydney, Nairobi, Mumbai.
    The route mix is for all passengers, so the local mix is backed out of it.
    """
    route_mix = np.array(route_mix, float) / 100
    conn_mix = (CITY_SHARE[:, None] * CITY_MIX).sum(0)
    local = (route_mix - conn_share * conn_mix) / (1 - conn_share)
    local = np.clip(local, 0.02, None)
    local /= local.sum()
    w = np.zeros((3, 5))
    w[:, 0] = (1 - conn_share) * local
    for c in range(4):
        w[:, c + 1] = conn_share * CITY_SHARE[c] * CITY_MIX[c]
    return w


def base_flow_weights(f):
    """Flow weights per flight (Berlin's mix shifts during its ramp-up)."""
    cache = {sid: flow_weights(sp["mix"], sp["conn"]) for sid, sp in SPEC.items() if sid != 2}
    out = np.zeros((len(f), 3, 5))
    weeks = ((f.departure_date - BERLIN_LAUNCH).dt.days / 7).to_numpy()
    for i, (sid, wk) in enumerate(zip(f.station_id.to_numpy(), weeks)):
        if sid == 2:
            t = min(max(wk / 16, 0), 1)
            out[i] = flow_weights((22 + 8 * t, 50, 28 - 8 * t), SPEC[2]["conn"])
        else:
            out[i] = cache[sid]
    return out


def base_load_factor(f):
    """Expected load factor per flight before noise (a share between 0 and 1)."""
    season = f.season.to_numpy()
    stn = f.station_id.to_numpy()
    m = f.month.to_numpy()
    d = f.departure_date.dt.day.to_numpy()
    mid = np.array([SPEC[s]["lf"][SEASONS.index(se)] for s, se in zip(stn, season)], float)

    # Berlin: load factor ramps from 50 to 71 over its first 16 weeks.
    weeks = ((f.departure_date - BERLIN_LAUNCH).dt.days / 7).to_numpy()
    ramp = 50 + 21 * np.clip(weeks / 16, 0, 1) + np.where(season == "christmas", 5, 0)
    mid = np.where(stn == 2, ramp, mid)

    # Month-to-month shape within a season.
    idx = np.array([MONTH_IDX[x] for x in m])
    avg = np.array([SEASON_AVG_IDX[s] for s in season])
    month_adj = np.where(season == "christmas", 0, (idx - avg) * 30)

    # Direction: outbound peaks in late Jun/Jul and before Christmas, returns in late Aug and early Jan.
    to_hub = (f.direction == "to_hub").to_numpy()
    out_peak = ((m == 6) & (d >= 15)) | ((m == 7) & (d <= 20)) | ((m == 12) & (d >= 18) & (d <= 23))
    back_peak = ((m == 8) & (d >= 15)) | ((m == 9) & (d <= 5)) | ((m == 1) & (d >= 2) & (d <= 6))
    dir_adj = (np.where(out_peak, np.where(to_hub, 3, -2), 0)
               + np.where(back_peak, np.where(to_hub, -2, 3), 0))

    # Weekday: Tue-Thu and Sun run higher on business-heavy routes (3 points at 38% business).
    biz = np.array([SPEC[s]["mix"][0] for s in stn], float)
    on = np.isin(f.weekday.to_numpy(), [1, 2, 3, 6])
    wk_adj = 3 * biz / 38 * np.where(on, 3 / 7, -4 / 7)

    return np.clip((mid + month_adj + dir_adj + wk_adj) / 100, 0.30, 0.99)


def fit_segment_cabin(seg_totals, cabin_totals, seed):
    """Split passengers into a segment x cabin table that matches both sets of totals.

    Iterative proportional fitting: start from the seed table, then repeatedly
    rescale rows to match segment totals and columns to match cabin totals.
    """
    m = np.broadcast_to(seed, (len(seg_totals), 3, 2)).copy()
    seg_totals = seg_totals * (cabin_totals.sum(1) / seg_totals.sum(1))[:, None]
    for _ in range(40):
        m *= (seg_totals / m.sum(2))[:, :, None]
        m *= (cabin_totals / np.maximum(m.sum(1), 1e-9))[:, None, :]
    return m


def target_loads(f, rng):
    """Target passengers per flight x cabin x segment x flow (all legs, before price effects).

    Returns the loads and the share of VFR bookings in the pre-festival wave.
    Price effects (promotion, competitor) are applied later to originating
    demand only, so that the true price sensitivity is the one in E_PRICE.
    """
    F = len(f)
    cap_j = f.capacity_business.to_numpy().astype(float)
    cap_y = f.capacity_economy.to_numpy().astype(float)
    cap = cap_j + cap_y
    lf = base_load_factor(f)
    B = base_flow_weights(f)

    # Multipliers that change the total (events).
    Madd = np.ones((F, 3, 5))
    Madd[:, 1, :] *= np.where(f.easter, 1.18, 1.0)[:, None]
    Madd[:, 1, :] *= np.where(f.autumn, 1.12, 1.0)[:, None]
    eid = np.where(f.eid, 1.35, 1.0)
    for c in (1, 3, 4):                                   # Bangkok, Nairobi, Mumbai flows
        Madd[:, 2, c] *= eid
    Madd[:, 2, 4] *= np.where(f.diwali, 1.5, 1.0)         # Mumbai flow

    # Multipliers that only shift the mix (these effects are already inside the load factors).
    T = np.ones((F, 3, 5))
    T[:, 1:, :] *= np.where(f.xmas, 1.30, 1.0)[:, None, None]
    T[:, 1, :] *= np.where(f.school_summer, 1.12, 1.0)[:, None]
    T[:, 1, 0] *= np.where(f.month.isin([11, 12, 1, 2]), 1.15, 1.0)   # winter sun, local leisure
    mid = f.weekday.isin([1, 2, 3]).to_numpy()
    T[:, 0, :] *= np.where(mid, 1.10, 1.0)[:, None]
    T[:, 1, :] *= np.where(mid, 0.95, 1.0)[:, None]
    T *= rng.lognormal(0, 0.08, size=(F, 3, 1))                       # segment noise

    base = B * Madd
    add_factor = base.sum((1, 2))
    W = base * T
    W *= (add_factor / W.sum((1, 2)))[:, None, None]
    share = W / add_factor[:, None, None]                              # sums to 1

    total = cap * lf * rng.lognormal(0, 0.06, F) * add_factor          # passengers wanted
    j_dem = np.minimum(cap_j, cap_j * 0.88 * total / cap)              # Business cabin runs lighter
    y_dem = np.minimum(cap_y, total - j_dem)                           # demand above seats spills
    cabin_totals = np.stack([y_dem, j_dem], axis=1)
    seg_totals = share.sum(2) * total[:, None]
    seed = np.stack([1 - CABIN_PROP, CABIN_PROP], axis=1)              # (3, 2)
    m = fit_segment_cabin(seg_totals, cabin_totals, seed)              # (F, segment, cabin)

    flow_share = share / share.sum(2, keepdims=True)
    n = m.transpose(0, 2, 1)[:, :, :, None] * flow_share[:, None, :, :]   # (F, cabin, seg, flow)

    spike = np.zeros((F, 3, 5))
    for c in (1, 3, 4):
        spike[:, 2, c] = np.where(f.eid, 1 - 1 / 1.35, 0)
    spike[:, 2, 4] = np.maximum(spike[:, 2, 4], np.where(f.diwali, 1 - 1 / 1.5, 0))
    return n, spike


def price_effects(f, comp_idx):
    """Demand multiplier per flight and segment from the promotion and the competitor index."""
    promo = 1 - f.promo_discount_pct.to_numpy() / 100
    return promo[:, None] ** E_PRICE[None, :] * (comp_idx / 100)[:, None] ** E_COMP[None, :]


# ---------------------------------------------------------------------
# Return travel
# ---------------------------------------------------------------------


def find_return_flights(route, day, by_route, orig_idx, stays):
    """Index of the first opposite-direction flight on or after departure + stay (-1 if none)."""
    out = np.full(len(orig_idx), -1)
    origin_routes = route[orig_idx]
    for ro in np.unique(origin_routes):
        m = origin_routes == ro
        rr = ro + 1 if ro % 2 == 1 else ro - 1               # the opposite direction route
        ret_idx = by_route[rr]
        pos = np.searchsorted(day[ret_idx], day[orig_idx[m]] + stays[m], side="left")
        found = np.full(m.sum(), -1)
        ok = pos < len(ret_idx)
        found[ok] = ret_idx[pos[ok]]
        out[m] = found
    return out


def build_return_operators(route, day, by_route):
    """One sparse matrix per segment: M[j, i] = share of round-trip passengers leaving on
    flight i who return on flight j, given the stay-length shape of that segment."""
    F = len(route)
    everyone = np.arange(F)
    ops = []
    for days, prob in STAY:
        rows, cols, vals = [], [], []
        for d, p in zip(days, prob):
            ret = find_return_flights(route, day, by_route, everyone, np.full(F, d))
            ok = ret >= 0
            rows.append(ret[ok])
            cols.append(everyone[ok])
            vals.append(np.full(ok.sum(), p))
        ops.append(sparse.csr_matrix((np.concatenate(vals),
                                      (np.concatenate(rows), np.concatenate(cols))), shape=(F, F)))
    return ops


def solve_origin_demand(T0, ops, iterations=60):
    """Originating demand = target load - expected returns, found by repeated substitution.

    Returns depend on originating demand on earlier flights, which depends on
    the returns it must leave room for. Repeating the subtraction settles it.
    """
    F = T0.shape[0]
    O = T0.copy()
    for _ in range(iterations):
        R = np.zeros_like(T0)
        for s in range(3):
            X = O[:, :, s, :].reshape(F, -1)
            R[:, :, s, :] = (ops[s] @ X).reshape(F, 2, 5) * RT_SHARE[s]
        O = np.maximum(T0 - R, 0.05 * T0)
    return O, R


# ---------------------------------------------------------------------
# Journeys
# ---------------------------------------------------------------------


def draw_days_before(si, max_days, spike_p, rng):
    """Days before departure for each booking, drawn from its segment's curve."""
    days = np.zeros(len(si))
    for s in range(3):
        mask = si == s
        cdf = np.concatenate([[0], np.cumsum(WINDOW_SHARE[s][::-1])])   # near to far
        umax = np.interp(max_days[mask] + 1, KNOTS, cdf)                # sales may open late
        u = rng.random(mask.sum()) * umax
        days[mask] = np.floor(np.interp(u, cdf, KNOTS))
    spiked = rng.random(len(si)) < spike_p
    days[spiked] = np.floor(rng.uniform(60, 91, spiked.sum()))          # pre-festival booking wave
    return np.minimum(days, max_days).astype(int)


def snap_to_ladder(target, ladder_rows, chunk=250_000):
    """Index (0 to 9) of the fare class whose price point is closest to the target."""
    out = np.empty(len(target), int)
    for a in range(0, len(target), chunk):
        b = a + chunk
        out[a:b] = np.abs(np.log(ladder_rows[a:b]) - np.log(target[a:b])[:, None]).argmin(1)
    return out


def draw_pos(europe_station, to_hub, flow, si, rng):
    """Point of sale per journey: origin, destination or a third station, by segment."""
    conn = flow > 0
    beyond = 6 + flow
    origin = np.where(to_hub, europe_station, np.where(conn, beyond, HUB_ID))
    dest = np.where(to_hub, np.where(conn, beyond, HUB_ID), europe_station)
    kind = (rng.random(len(si))[:, None] > np.cumsum(POS_MIX[si], axis=1)).sum(1)
    third = THIRD_POOL[rng.integers(0, len(THIRD_POOL), len(si))]
    bad = (third == origin) | (third == dest)
    while bad.any():
        third[bad] = THIRD_POOL[rng.integers(0, len(THIRD_POOL), bad.sum())]
        bad = (third == origin) | (third == dest)
    return np.select([kind == 0, kind == 1], [origin, dest], third)


def draw_journeys(f, O, spike, ctx, fx_rate, ladder, pro, rng):
    """Turn originating demand into journeys with trip type, stay, fares, POS and channel."""
    k = rng.poisson(O / MEAN_PARTY[None, None, :, None])             # parties per cell
    cell = np.repeat(np.arange(k.size), k.ravel())
    fi, ci, si, fl = np.unravel_index(cell, k.shape)
    N = len(fi)

    pax = np.zeros(N, int)
    for s in range(3):
        mask = si == s
        pax[mask] = rng.choice(PARTY[s][0], size=mask.sum(), p=PARTY[s][1])

    # Trip type, stay length and the return flight.
    rt = rng.random(N) < RT_SHARE[si]
    stay = np.zeros(N, int)
    for s in range(3):
        mask = si == s
        stay[mask] = rng.choice(STAY[s][0], size=mask.sum(), p=STAY[s][1])
    ret = np.full(N, -1)
    ret[rt] = find_return_flights(ctx["route"], ctx["day"], ctx["by_route"], fi[rt], stay[rt])

    # Booking time for the outbound leg (sales for Berlin open 180 days before launch).
    dep = f.departure_date.to_numpy()[fi]
    berlin = f.station_id.to_numpy()[fi] == 2
    max_days = np.where(berlin, (dep - BERLIN_SALES_OPEN.to_datetime64()).astype("timedelta64[D]").astype(int),
                        MAX_DAYS_OUT)
    max_days = np.minimum(max_days, MAX_DAYS_OUT)
    days = draw_days_before(si, max_days, spike[fi, si, fl], rng)

    # One-way-equivalent fare: segment mean x route x season x timing x noise.
    # In shoulder and peak seasons the target is lifted by STANDARD_SCALE (the same
    # factor as the ladder); in the low season it is not.
    route = f.route_id.to_numpy()[fi] - 1
    price_idx = np.array([SPEC[s]["idx"] for s in f.station_id])
    season = f.season.to_numpy()
    sf = np.array([SEASON_PRICE[s] for s in season])
    weight = O.sum((1, 2, 3))
    sf_norm = sf / ((weight * sf).sum() / weight.sum())               # seasonal premium averages to 1
    lift = np.where(season == "low", 1.0, STANDARD_SCALE)
    kind = (season != "low").astype(int)                              # 0 = low ladder, 1 = standard
    e_timing = WINDOW_SHARE @ WINDOW_TIMING
    timing = np.select([days >= 91, days >= 31, days >= 8], [.85, 1.0, 1.15], 1.30)
    noise = rng.lognormal(-0.5 * FARE_SIGMA ** 2, FARE_SIGMA, N)
    target = (FARE_MEAN[ci, si] * price_idx[fi] * sf_norm[fi] * lift[fi]
              * timing / e_timing[si] * noise)
    lad = ladder[route, ci, kind[fi]]
    rank = snap_to_ladder(target, lad)
    intro = np.where(berlin & (dep < (BERLIN_LAUNCH + pd.Timedelta(days=90)).to_datetime64()), 0.9, 1.0)
    promo = 1 - f.promo_discount_pct.to_numpy()[fi] / 100
    ow_eur = lad[np.arange(N), rank] * promo * intro                  # one-way fare, priced at outbound
    per_leg_eur = np.where(rt, ow_eur / ONE_WAY_RATIO / 2, ow_eur)    # return fare split over two legs

    # Connecting passengers: the leg fare is a share of the local level; through = leg / factor.
    conn = fl > 0
    city = np.maximum(fl - 1, 0)
    rel = np.array([REL_LEG[1], REL_LEG[2]])[ci, city]
    leg_eur = np.where(conn, per_leg_eur * rel, per_leg_eur)
    through_eur = np.where(conn, leg_eur / pro[route, city, ci], leg_eur)

    pos = draw_pos(f.station_id.to_numpy()[fi], (f.direction == "to_hub").to_numpy()[fi], fl, si, rng)
    month_i = np.maximum(((f.departure_date.dt.year - 2023) * 12 + f.month - 3).to_numpy()[fi], 0)
    through_local = np.maximum(np.rint(through_eur / fx_rate[month_i, pos]), 1).astype(int)

    cum = np.cumsum(CHANNEL_MIX[si], axis=1)
    channel = np.minimum((rng.random(N)[:, None] > cum).sum(1) + 1, 4)

    return pd.DataFrame(dict(
        fi=fi, ci=ci, si=si, fl=fl, pax=pax, rt=rt, ret=ret, days_out=days, rank=rank + 1,
        through=through_local, pos=pos, channel=channel))


def expand_legs(j, day):
    """One row per flight leg: the outbound leg of every journey, plus inbound legs."""
    out = pd.DataFrame(dict(jid=np.arange(len(j)), leg_seq=1, fi=j.fi.to_numpy(),
                            days_before=j.days_out.to_numpy()))
    has_ret = np.flatnonzero(j.ret.to_numpy() >= 0)
    ret = j.ret.to_numpy()[has_ret]
    inbound = pd.DataFrame(dict(jid=has_ret, leg_seq=2, fi=ret,
                                days_before=j.days_out.to_numpy()[has_ret]
                                + day[ret] - day[j.fi.to_numpy()[has_ret]]))
    legs = pd.concat([out, inbound], ignore_index=True)
    jid = legs.jid.to_numpy()
    for col in ("ci", "si", "fl", "pax", "rt", "rank", "through", "pos", "channel"):
        legs[col] = j[col].to_numpy()[jid]
    return legs


def trim_to_capacity(legs, f, rng):
    """Drop random legs above seat capacity (spill). A journey is dropped as a whole."""
    legs = legs.iloc[rng.permutation(len(legs))].reset_index(drop=True)
    key = legs.fi.to_numpy() * 2 + legs.ci.to_numpy()
    cap = np.stack([f.capacity_economy.to_numpy(), f.capacity_business.to_numpy()], axis=1).ravel()
    running = legs.groupby(key).pax.cumsum().to_numpy()
    spilled_journeys = np.unique(legs.jid.to_numpy()[running > cap[key]])
    return legs[~legs.jid.isin(spilled_journeys)].reset_index(drop=True)


def finish_bookings(legs, f, fx_rate, pro):
    """Keep legs inside the data window, add ids, and value each leg in EUR."""
    legs = legs[f.flight_id.to_numpy()[legs.fi.to_numpy()] >= 1].copy()
    legs["jid"] = np.unique(legs.jid.to_numpy(), return_inverse=True)[1] + 1
    order = np.lexsort((legs.jid, legs.leg_seq, -legs.days_before, legs.fi))
    legs = legs.iloc[order].reset_index(drop=True)
    legs.insert(0, "booking_id", np.arange(1, len(legs) + 1))
    legs["flight_id"] = f.flight_id.to_numpy()[legs.fi.to_numpy()]
    route = f.route_id.to_numpy()[legs.fi.to_numpy()] - 1
    conn = legs.fl.to_numpy() > 0
    factor = np.where(conn, pro[route, np.maximum(legs.fl.to_numpy() - 1, 0), legs.ci.to_numpy()], 1.0)
    month_i = np.maximum(((f.departure_date.dt.year - 2023) * 12 + f.month - 3).to_numpy()[legs.fi.to_numpy()], 0)
    legs["rev_eur"] = legs.pax * legs.through * factor * fx_rate[month_i, legs.pos.to_numpy()]
    return legs


def build_revenue_targets(b, f, rng):
    """Monthly target per European station POS, set relative to simulated revenue sold there."""
    month = f.departure_date.dt.strftime("%Y-%m").to_numpy()[b.fi.to_numpy()]
    sold = b.pos.to_numpy()
    keep = sold <= 6
    actual = b[keep].groupby([sold[keep], month[keep]]).rev_eur.sum().reset_index()
    actual.columns = ["station_id", "month", "actual"]
    noise = rng.normal(0, 0.05, len(actual))
    bias = actual.station_id.map(TARGET_BIAS)
    actual["target_revenue_eur"] = (actual.actual * bias * (1 + noise) / 1000).round() * 1000
    return actual[["station_id", "month", "target_revenue_eur"]]


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def write_database(db_path, tables, bookings):
    """Create the schema, load every table and compact the file."""
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    for name, df in tables.items():
        df.to_sql(name, con, if_exists="append", index=False)
    out = pd.DataFrame(dict(
        booking_id=bookings.booking_id, flight_id=bookings.flight_id, journey_id=bookings.jid,
        trip_type=np.where(bookings.rt, 2, 1), leg_seq=bookings.leg_seq,
        days_before=bookings.days_before, segment_id=bookings.si + 1, cabin_id=bookings.ci + 1,
        pos_station_id=bookings.pos, channel_id=bookings.channel, class_rank=bookings["rank"],
        pax=bookings.pax, through_fare=bookings.through,
        beyond_city_id=pd.array(np.where(bookings.fl > 0, bookings.fl, np.nan), dtype="Int64")))
    out.to_sql("bookings", con, if_exists="append", index=False, chunksize=100_000)
    con.commit()
    con.execute("VACUUM")
    con.close()
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--db", type=Path, default=DATA_DIR / "meridara.db")
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)

    routes = build_routes()
    events = build_events()
    fares = build_fare_buckets(routes)
    pro_df = build_proration(routes)
    fx = build_fx()
    comp_df, comp_matrix = build_competitor_index(routes, rng)
    f = build_flights(routes, events, rng)             # includes burn-in flights

    week_i = ((f.departure_date - COMP_WEEK0).dt.days // 7).to_numpy()
    comp_idx = comp_matrix[f.route_id.to_numpy() - 1, week_i]

    # Lookup arrays used by the journey step.
    fx_rate = np.ones((36, 12))
    months = sorted(fx.month.unique())
    for sid, ccy in ((s[0], s[4]) for s in STATIONS):
        rates = fx[fx.currency == ccy].set_index("month").rate_to_eur
        fx_rate[:, sid] = [rates[m] for m in months]
    ladder = np.zeros((12, 2, 2, 10))
    for r in fares.itertuples():
        ladder[r.route_id - 1, r.cabin_id - 1, int(r.ladder == "standard"), r.class_rank - 1] = r.price_point_eur
    pro = np.ones((12, 4, 2))
    for r in pro_df.itertuples():
        pro[r.route_id - 1, r.beyond_city_id - 1, r.cabin_id - 1] = r.factor

    route = f.route_id.to_numpy()
    day = f.departure_date.to_numpy().astype("datetime64[D]").astype(np.int64)
    by_route = {r: np.flatnonzero(route == r) for r in np.unique(route)}
    ctx = dict(route=route, day=day, by_route=by_route)

    T0, spike = target_loads(f, rng)
    ops = build_return_operators(route, day, by_route)
    O, R = solve_origin_demand(T0, ops)
    O = O * price_effects(f, comp_idx)[:, None, :, None]    # price effects act on originating demand

    j = draw_journeys(f, O, spike, ctx, fx_rate, ladder, pro, rng)
    legs = trim_to_capacity(expand_legs(j, day), f, rng)
    b = finish_bookings(legs, f, fx_rate, pro)
    targets = build_revenue_targets(b, f, rng)

    stored = f[f.flight_id >= 1]
    tables = {
        "segments": pd.DataFrame({"segment_id": [1, 2, 3], "segment_name": SEGMENTS}),
        "cabins": pd.DataFrame({"cabin_id": [1, 2], "cabin_name": CABINS}),
        "trip_types": pd.DataFrame({"trip_type_id": [1, 2], "trip_type_name": TRIP_TYPES}),
        "channels": pd.DataFrame({"channel_id": [1, 2, 3, 4], "channel_name": CHANNELS}),
        "stations": pd.DataFrame(STATIONS, columns=["station_id", "station_name", "region",
                                                    "role", "sales_currency"]),
        "beyond_hub_cities": pd.DataFrame({"beyond_city_id": [1, 2, 3, 4],
                                           "station_id": [7, 8, 9, 10]}),
        "routes": routes,
        "events": events.assign(start_date=events.start_date.dt.strftime("%Y-%m-%d"),
                                end_date=events.end_date.dt.strftime("%Y-%m-%d"))[
            ["event_id", "event_name", "start_date", "end_date"]],
        "flights": stored.assign(departure_date=stored.departure_date.dt.strftime("%Y-%m-%d"),
                                 event_id=stored.event_id.astype("Int64"))[
            ["flight_id", "route_id", "departure_date", "weekday", "season", "event_id",
             "capacity_business", "capacity_economy", "berlin_launch_flag",
             "promo_discount_pct", "is_test"]],
        "fare_buckets": fares,
        "competitor_index": comp_df,
        "fx_rates": fx,
        "proration_factors": pro_df,
        "revenue_targets": targets,
    }
    out = write_database(args.db, tables, b)

    # Small tables are also saved as CSV. The bookings CSV is not written; the seed rebuilds it.
    con = sqlite3.connect(args.db)
    for name in tables:
        pd.read_sql(f"SELECT * FROM {name}", con).to_csv(DATA_DIR / f"{name}.csv", index=False)
    con.close()

    checksum = hashlib.sha256(pd.util.hash_pandas_object(
        out[["flight_id", "journey_id", "days_before", "pax", "through_fare"]], index=False
    ).to_numpy().tobytes()).hexdigest()[:12]
    size_mb = args.db.stat().st_size / 1e6
    print(f"flights: {len(stored):,} (plus {len(f) - len(stored):,} unstored burn-in)   "
          f"journeys generated: {len(j):,}")
    print(f"booking rows: {len(out):,}   passengers: {int(out.pax.sum()):,}")
    print(f"database: {args.db}   size: {size_mb:.1f} MB")
    print(f"bookings checksum (same seed gives same value): {checksum}")


if __name__ == "__main__":
    main()
