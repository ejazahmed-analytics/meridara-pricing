"""Phase 4b: replay flights under a calibrated fare bucket policy and under continuous pricing.

Illustrative case study using fictitious and simulated data.

Policies, all facing the same simulated customers on every flight:
  * buckets    about 10 fixed one-way price points opened and closed by EMSR-b, with
               advance-purchase rules, calibrated on the training period so that the replay
               reproduces as-flown revenue and load factor
  * continuous a price anywhere between the lowest and highest bucket price,
               re-chosen each booking period to maximise expected revenue
  * continuous_lf (base scenario only) the same, but each route must keep at least its
               as-flown average load factor over the test window; single flights can vary

Calibration. The bucket policy has three settings that a carrier's revenue management practice
determines: how strongly it protects seats for higher fares (protect), which classes count as
flexible fares that Business customers buy from (fence, one per cabin) and how early the cheap
classes close (ap). They are fitted on the training period so that replaying the bucket policy
reproduces as-flown revenue and load factor. Continuous pricing uses the same fences. The
validated bucket policy is then compared with continuous pricing in the test period.

Demand model. Each customer has a willingness to pay (WTP). WTP is lognormal with a spread of
SIGMA, so the revenue-maximising price falls inside the price range. Its location is set so that
the slope of demand at the as-flown price equals the price sensitivity estimated in Phase 4a. WTP
rises with the booking period, following the average price paid by booking window in the training
data. The market fare trend applies to the whole fare ladder (price points, floor, ceiling and
fence) and to willingness to pay, exactly as in the data generator, so every policy is compared on
the same price level.

Policies see the Phase 3 forecast (90 days out) in the test period, not the truth, and rescale their
remaining-demand forecast from actual sales after every booking period. In the training period
(calibration) there is no out-of-sample forecast, so the forecast is perfect there.

Simplifications: returning passengers are already booked and fixed, so only originating passengers on
their outbound leg are priced; revenue is in one-way-fare terms in EUR; observed bookings stand in
for demand, which understates demand on full flights.

Run from the project root:   python src/pricing_sim.py   (optional: --sigma 0.35 --dry)
"""
import argparse
import sqlite3

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.special import ndtr
from scipy.stats import norm

from forecast import md
from generate_data import TREND_MID, YIELD_TREND
from results_db import DATA_DB, RESULTS_DB, open_results

SEED = 7
PERIODS = 7                                   # 330-181, 180-91, 90-61, 60-31, 30-15, 14-8, 7-0 days out
EDGES = [-1, 7, 14, 30, 60, 90, 180, 10_000]  # days_before bins, nearest departure first
SIGMA = 0.45                                  # spread of willingness to pay (log scale), an assumption
AP_VARIANTS = [[1, 1, 1, 1, 1, 3, 5],         # lowest class open in each period; the two cheapest classes
               [1, 1, 1, 1, 3, 5, 7],         # close 14 days out in variant 0, earlier in the others
               [1, 1, 2, 3, 4, 6, 8],
               [1, 1, 1, 2, 3, 5, 6],
               [1, 1, 1, 1, 2, 4, 6]]
FORECAST_CV = 0.2                             # forecast uncertainty used by EMSR-b (about the 90-day WAPE)
PRIOR_PAX = 3.0                               # weight of the forecast when rescaling after sales
GRID = 60
SCENARIOS = ["base", "underforecast", "competitor_cut", "elastic_world", "inelastic_world"]
BERLIN_INTRO_END = pd.Timestamp("2026-01-25")
CAL_FLIGHTS = 1600                            # training flights used while searching for the calibration
DEFAULT_PARAMS = dict(protect=1.0, fence={1: 6, 2: 6}, ap=0)


# ---------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------


def load_base():
    """Read everything the replay needs from the databases."""
    con = sqlite3.connect(DATA_DB)
    fl = pd.read_sql("""SELECT f.flight_id, f.route_id, f.departure_date, f.season, f.promo_discount_pct AS promo,
                               f.capacity_business, f.capacity_economy, f.is_test, r.station_id
                        FROM flights f JOIN routes r ON r.route_id = f.route_id""", con)
    fl["departure_date"] = pd.to_datetime(fl.departure_date)
    fb = pd.read_sql("SELECT route_id, cabin_id, ladder, class_rank, price_point_eur FROM fare_buckets", con)
    b = pd.read_sql("SELECT flight_id, days_before, segment_id, cabin_id, leg_seq, class_rank, pax FROM bookings", con)
    con.close()
    rc = sqlite3.connect(RESULTS_DB)
    fc = pd.read_sql("SELECT * FROM forecast_results WHERE asof_days = 90", rc)
    sens = pd.read_sql("SELECT * FROM sensitivity_estimates", rc)
    rc.close()
    fl["ladder"] = np.where(fl.season == "low", "low", "standard")
    fl["intro"] = np.where((fl.station_id == 2) & (fl.departure_date < BERLIN_INTRO_END), 0.9, 1.0)
    fl["trend"] = (1 + YIELD_TREND) ** ((fl.departure_date - TREND_MID).dt.days.to_numpy() / 365.25)
    return dict(fl=fl, fb=fb, b=b, fc=fc, sens=sens)


def time_profile(base):
    """Arrival shares and the time profile of willingness to pay, from the training data."""
    fl, fb, b = base["fl"], base["fb"], base["b"]
    train_ids = set(fl[fl.is_test == 0].flight_id)
    out = b[(b.leg_seq == 1) & b.flight_id.isin(train_ids)].copy()
    out["period"] = PERIODS - 1 - pd.cut(out.days_before, EDGES, labels=False)
    share = out.groupby(["segment_id", "period"]).pax.sum().unstack().fillna(0)
    share = share.div(share.sum(axis=1), axis=0).reindex(columns=range(PERIODS), fill_value=0).to_numpy()
    tr = out.merge(fl[["flight_id", "route_id", "ladder", "promo", "intro", "trend"]], on="flight_id")
    tr = tr.merge(fb, on=["route_id", "cabin_id", "ladder", "class_rank"])
    tr["spend"] = tr.price_point_eur * tr.trend * (1 - tr.promo / 100) * tr.intro * tr.pax
    m = tr.groupby(["cabin_id", "segment_id", "period"])[["spend", "pax"]].sum()
    price = (m.spend / m.pax).unstack().reindex(columns=range(PERIODS))
    g = np.zeros((2, 3, PERIODS))
    for ci in range(2):
        for si in range(3):
            raw = price.loc[(ci + 1, si + 1)].to_numpy()
            g[ci, si] = raw / (share[si] * raw).sum()                 # arrival-weighted mean of 1
    return share, g


def build_cells(base, flight_ids, use_forecast):
    """Demand cells (originating passengers and average price paid) and returning passengers by flight and cabin."""
    fl, fb, b = base["fl"], base["fb"], base["b"]
    sub = fl[fl.flight_id.isin(flight_ids)]
    bt = b[b.flight_id.isin(sub.flight_id)]
    o = bt[bt.leg_seq == 1].merge(sub[["flight_id", "route_id", "ladder", "promo", "intro", "trend"]], on="flight_id")
    o = o.merge(fb, on=["route_id", "cabin_id", "ladder", "class_rank"])
    o["spend"] = o.price_point_eur * o.trend * (1 - o.promo / 100) * o.intro * o.pax
    cells = o.groupby(["flight_id", "cabin_id", "segment_id"]).agg(N=("pax", "sum"), spend=("spend", "sum")).reset_index()
    cells["p_ref"] = cells.spend / cells.N
    inbound = bt[bt.leg_seq == 2].groupby(["flight_id", "cabin_id"]).pax.sum().rename("inbound").reset_index()
    if use_forecast:
        fc = base["fc"].copy()
        fc["ratio"] = np.where(fc.actual_final > 0, fc.gbm_forecast / fc.actual_final.clip(lower=1e-9), 1.0)
        fc["ratio"] = fc.ratio.clip(0.5, 2.0)
        cells = cells.merge(fc[["flight_id", "segment_id", "ratio"]], on=["flight_id", "segment_id"], how="left")
        cells["ratio"] = cells.ratio.fillna(1.0)
    else:
        cells["ratio"] = 1.0
    return cells, inbound


def ladder_prices(fb):
    """Dictionary (route, cabin, ladder) -> array of the 10 one-way price points, cheapest first (base price level)."""
    return {k: g.sort_values("class_rank").price_point_eur.to_numpy()
            for k, g in fb.groupby(["route_id", "cabin_id", "ladder"])}


def scenario_world(sens, name):
    """Price elasticity in the simulated world, demand scale (competitor shock) and forecast bias."""
    low = sens[(sens["sample"] == "low-season flights") & (sens.parameter == "price")].set_index("segment_id")
    comp = sens[(sens["sample"] == "all training flights") & (sens.parameter == "competitor")].set_index("segment_id")
    belief = low.estimate.reindex([1, 2, 3]).to_numpy()
    world, scale, bias = belief.copy(), np.ones(3), 1.0
    if name == "underforecast":
        bias = 0.85
    elif name == "competitor_cut":
        scale = 0.90 ** comp.estimate.reindex([1, 2, 3]).to_numpy()    # competitor index falls 10%
    elif name == "elastic_world":
        world = low.ci_low.reindex([1, 2, 3]).to_numpy()
    elif name == "inelastic_world":
        world = low.ci_high.reindex([1, 2, 3]).to_numpy()
    return belief, world, scale, bias


# ---------------------------------------------------------------------
# Demand model
# ---------------------------------------------------------------------


def solve_z(elasticity):
    """Position of the as-flown price on the willingness-to-pay curve for each segment.

    For lognormal willingness to pay with spread SIGMA, the price elasticity at a price is
    hazard(z) / SIGMA, where z is the standard-normal position of that price. Solve for z so that
    the elasticity equals the estimate.
    """
    out = []
    for e in elasticity:
        target = abs(min(e, -0.05)) * SIGMA
        out.append(brentq(lambda z: norm.pdf(z) / norm.sf(z) - target, -12, 8))
    return np.array(out)


def make_customers(N, p_ref, z_world, scale, share, g, rng):
    """Customers for one flight and cabin: booking period, segment and willingness to pay."""
    periods, segs, wtp = [], [], []
    for s in range(3):
        if N[s] <= 0:
            continue
        population = N[s] * scale[s] / ndtr(-z_world[s])                 # buyers at the as-flown price equal N
        k = rng.poisson(population)
        per = rng.choice(PERIODS, size=k, p=share[s])
        z = rng.standard_normal(k)
        periods.append(per)
        segs.append(np.full(k, s))
        wtp.append(p_ref[s] * g[s][per] * np.exp(SIGMA * (z - z_world[s])))
    if not periods:
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0)
    period, seg, w = np.concatenate(periods), np.concatenate(segs), np.concatenate(wtp)
    order = rng.permutation(len(period))                                  # random arrival order
    return period[order], seg[order], w[order]


def build_tables(ladder, p_ref, z, g, share, floor, ceiling, fence_rank, with_grid=True):
    """Expected demand still to come, by period, candidate price and segment (per unit of forecast)."""
    fence = ladder[fence_rank - 1]

    def effective(prices):
        eff = np.repeat(prices[:, None], 3, axis=1)
        eff[:, 0] = np.maximum(eff[:, 0], fence)                          # Business cannot buy below the fence
        return eff

    def remaining(prices_eff):
        ln = np.log(prices_eff[None, :, :] / (p_ref[None, None, :] * g.T[:, None, :]))
        surv = ndtr(-(z[None, None, :] + ln / SIGMA)) / ndtr(-z)[None, None, :]
        arrivals = surv * share.T[:, None, :]                              # (period, price, segment)
        return np.cumsum(arrivals[::-1], axis=0)[::-1]                     # demand from period t onward

    tb = dict(ladder=ladder, fence=fence, R_class=remaining(effective(ladder)))
    if with_grid:
        grid = np.linspace(floor, ceiling, GRID)
        tb.update(grid=grid, eff_grid=effective(grid), R_grid=remaining(effective(grid)))
    return tb


def emsr_b_index(prices, mu, c_rem):
    """Index of the lowest open fare class under EMSR-b protection levels. prices ascending; mu = class demand."""
    sigma2 = mu + (FORECAST_CV * mu) ** 2
    order = np.arange(len(prices))[::-1]                    # highest fare first
    mu_agg = np.cumsum(mu[order])
    var_agg = np.cumsum(sigma2[order])
    rev_agg = np.cumsum((mu * prices)[order])
    open_idx = order[0]                                     # the top class is always open
    for j in range(len(prices) - 1):
        if mu_agg[j] <= 1e-9:
            y = 0.0
        else:
            avg = rev_agg[j] / mu_agg[j]
            z = norm.ppf(np.clip(1 - prices[order[j + 1]] / avg, 1e-6, 1 - 1e-6))
            y = mu_agg[j] + np.sqrt(var_agg[j]) * z
        if c_rem > y:
            open_idx = order[j + 1]
        else:
            break
    return open_idx


def run_policy(policy, tb, cust, N_hat, p_ref, z, share, g, cap, bonus=0.0, protect=1.0, min_rank=None):
    """Play one flight and cabin under one policy. Returns pax and revenue by segment and prices by period.

    Both policies offer one base price per period. Business-segment customers pay at least the fence
    price. Bucket prices cannot go below the lowest class still open under the advance-purchase rules,
    and `protect` scales the demand the bucket rule protects seats for. For the load factor floor policy,
    `bonus` is a value per passenger added to the objective: it pushes prices down until the route reaches
    its target load factor. It never enters the revenue that is counted.
    """
    c_rem = cap
    period, seg, wtp = cust
    ladder, fence = tb["ladder"], tb["fence"]
    min_rank = AP_VARIANTS[0] if min_rank is None else min_rank
    pax, rev, prices = np.zeros(3), np.zeros(3), np.full(PERIODS, np.nan)
    obs, expc = 0.0, 0.0
    for t in range(PERIODS):
        if c_rem <= 0:
            break
        kappa = np.clip((obs + PRIOR_PAX) / (expc + PRIOR_PAX), 0.3, 3.0)
        w = N_hat * kappa
        if policy in ("continuous", "continuous_lf"):
            seg_d = tb["R_grid"][t] * w[None, :]                           # expected buyers by segment
            total = seg_d.sum(1)
            scale = np.minimum(1.0, c_rem / np.maximum(total, 1e-9))
            price = tb["grid"][np.argmax(scale * (seg_d * (tb["eff_grid"] + bonus)).sum(1))]
        else:
            d = tb["R_class"][t] @ (w * protect)
            mu = np.maximum(d - np.append(d[1:], 0.0), 1e-9)               # demand in each fare band
            idx = max(emsr_b_index(ladder, mu, c_rem), min_rank[t] - 1)    # advance-purchase rules close cheap classes
            price = ladder[idx]
        prices[t] = price
        pay = np.array([max(price, fence), price, price])
        buy = np.flatnonzero((period == t) & (wtp >= pay[seg]))[:int(c_rem)]
        sold = np.bincount(seg[buy], minlength=3)
        pax += sold
        rev += sold * pay
        c_rem -= len(buy)
        obs += len(buy)
        surv = ndtr(-(z + np.log(pay / (p_ref * g[:, t])) / SIGMA)) / ndtr(-z)
        expc += float((surv * N_hat * share[:, t]).sum())
    return pax, rev, prices


# ---------------------------------------------------------------------
# Tasks: one per flight and cabin
# ---------------------------------------------------------------------


def iter_tasks(base, cells, inbound, lad, share, g, z_belief, z_world, scale, bias, tag):
    """Generate simulation tasks (customers and demand inputs) for each flight and cabin."""
    fl = base["fl"].set_index("flight_id")
    ib = inbound.set_index(["flight_id", "cabin_id"]).inbound
    for (fid, cabin), gr in cells.groupby(["flight_id", "cabin_id"]):
        row = fl.loc[fid]
        cap_total = int(row.capacity_business if cabin == 2 else row.capacity_economy)
        inb = int(ib.get((fid, cabin), 0))
        task = dict(fid=int(fid), cabin=cabin, route=int(row.route_id), cap_total=cap_total, inbound=inb,
                    cap=cap_total - inb)
        if task["cap"] <= 0:
            yield dict(task, skip=True)
            continue
        N, p_ref, ratio = np.zeros(3), np.ones(3), np.ones(3)
        for r in gr.itertuples():
            N[r.segment_id - 1], p_ref[r.segment_id - 1], ratio[r.segment_id - 1] = r.N, r.p_ref, r.ratio
        rng = np.random.default_rng([SEED, int(fid), cabin, tag])
        gc = g[cabin - 1]
        ladder = lad[(row.route_id, cabin, row.ladder)] * row.trend          # the ladder moves with the market
        yield dict(task, skip=False, N=N, N_hat=N * ratio * bias, p_ref=p_ref, ladder=ladder, z=z_belief, g=gc,
                   cust=make_customers(N, p_ref, z_world, scale, share, gc, rng))


def tables_for(task, share, params, with_grid):
    ladder = task["ladder"]
    return build_tables(ladder, task["p_ref"], task["z"], task["g"], share, ladder[0], ladder[-1],
                        params["fence"][task["cabin"]], with_grid)


# ---------------------------------------------------------------------
# Calibration of the bucket policy
# ---------------------------------------------------------------------


def evaluate_buckets(tasks, share, params):
    """Replay the bucket policy on tasks. Returns revenue, passengers, load factor and the as-flown references."""
    rev = pax = obs_rev = obs_pax = inbound = seats = 0.0
    flights = {}
    for tk in tasks:
        flights[(tk["fid"], tk["cabin"])] = (tk["inbound"], tk["cap_total"])
        if tk["skip"]:
            continue
        tb = tables_for(tk, share, params, with_grid=False)
        p, r, _ = run_policy("buckets", tb, tk["cust"], tk["N_hat"], tk["p_ref"], tk["z"], share, tk["g"], tk["cap"],
                             protect=params["protect"], min_rank=AP_VARIANTS[params["ap"]])
        rev += r.sum()
        pax += p.sum()
        obs_rev += float((tk["N"] * tk["p_ref"]).sum())
        obs_pax += tk["N"].sum()
    inbound = sum(v[0] for v in flights.values())
    seats = sum(v[1] for v in flights.values())
    return dict(rev=rev, pax=pax, lf=100 * (pax + inbound) / seats, obs_rev=obs_rev,
                obs_lf=100 * (obs_pax + inbound) / seats)


def objective(res):
    return abs(res["rev"] / res["obs_rev"] - 1) + abs(res["lf"] / res["obs_lf"] - 1)


def calibrate(base, lad, share, g, sens):
    """Fit protect, fence ranks and advance-purchase variant so the bucket replay reproduces as-flown results."""
    belief, _, scale, bias = scenario_world(sens, "base")
    z = solve_z(belief)
    train = base["fl"][base["fl"].is_test == 0]
    ids = train.flight_id.sample(CAL_FLIGHTS, random_state=1).tolist()
    cells, inbound = build_cells(base, ids, use_forecast=False)
    tasks = list(iter_tasks(base, cells, inbound, lad, share, g, z, z, scale, bias, tag=99))
    cache = {}

    def score(params):
        key = (params["protect"], params["fence"][1], params["fence"][2], params["ap"])
        if key not in cache:
            cache[key] = evaluate_buckets(tasks, share, params)
        return objective(cache[key])

    params = dict(protect=2.0, fence={1: 6, 2: 6}, ap=0)
    for _ in range(3):
        for name, values in (("protect", [1.0, 1.2, 1.35, 1.5, 1.65, 1.8, 2.0, 2.5, 3.0, 4.0]),
                             ("fence1", [6, 7, 8, 9, 10]), ("fence2", [5, 6, 7, 8, 9, 10]), ("ap", [0, 1, 2, 3, 4])):
            best = None
            for v in values:
                trial = dict(params, fence=dict(params["fence"]))
                if name == "protect":
                    trial["protect"] = v
                elif name == "fence1":
                    trial["fence"][1] = v
                elif name == "fence2":
                    trial["fence"][2] = v
                else:
                    trial["ap"] = v
                s = score(trial)
                if best is None or s < best[0]:
                    best = (s, trial)
            params = best[1]
        print(f"  calibration pass: protect {params['protect']}, fence {params['fence']}, ap {params['ap']}, "
              f"gap {score(params):.3f}")
    return params


def validate_calibration(base, lad, share, g, sens, params, period_name, test_flag):
    """Replay the calibrated bucket policy on a whole period and compare with as flown."""
    belief, _, scale, bias = scenario_world(sens, "base")
    z = solve_z(belief)
    ids = base["fl"][base["fl"].is_test == test_flag].flight_id.tolist()
    cells, inbound = build_cells(base, ids, use_forecast=bool(test_flag))
    tasks = iter_tasks(base, cells, inbound, lad, share, g, z, z, scale, bias, tag=99 if not test_flag else 0)
    res = evaluate_buckets(tasks, share, params)
    return dict(period=period_name, rev=res["rev"], obs_rev=res["obs_rev"], lf=res["lf"], obs_lf=res["obs_lf"],
                pax=res["pax"])


# ---------------------------------------------------------------------
# Route-level load factor floor
# ---------------------------------------------------------------------


def route_level_floor(tasks, tbs, share, seats_by_flight, route_of_flight, params):
    """Continuous pricing with a route-level load factor floor.

    For every route, find the smallest per-passenger bonus that brings the route's average load factor
    over the test window up to its as-flown level (bisection), then keep that run.
    """
    by_route = {}
    for tk, tb in zip(tasks, tbs):
        by_route.setdefault(tk["route"], []).append((tk, tb))
    results, prices, table = [], [], []
    for route, items in sorted(by_route.items()):
        flights = [f for f, r in route_of_flight.items() if r == route and f in seats_by_flight.index]
        seats = seats_by_flight.loc[flights].capacity.sum()
        inbound = seats_by_flight.loc[flights].inbound_pax.sum()
        target = (sum(tk["N"].sum() for tk, _ in items) + inbound) / seats

        def play(bonus):
            out = [run_policy("continuous_lf", tb, tk["cust"], tk["N_hat"], tk["p_ref"], tk["z"], share, tk["g"],
                              tk["cap"], bonus=bonus) for tk, tb in items]
            return (sum(o[0].sum() for o in out) + inbound) / seats, out

        lf, out = play(0.0)
        bonus = 0.0
        if lf < target:
            lo, hi = 0.0, 2 * max(tk["ladder"][-1] for tk, _ in items)
            lf_hi, out_hi = play(hi)
            if lf_hi >= target:
                for _ in range(14):
                    mid = (lo + hi) / 2
                    lf_m, out_m = play(mid)
                    if lf_m >= target:
                        hi, lf_hi, out_hi = mid, lf_m, out_m
                    else:
                        lo = mid
            bonus, lf, out = hi, lf_hi, out_hi
        table.append((int(route), float(target), float(lf), float(bonus)))
        for (tk, _), (pax, rev, pr) in zip(items, out):
            for s in range(3):
                results.append(("base", "continuous_lf", tk["fid"], tk["cabin"], s + 1, int(pax[s]), float(rev[s])))
            prices += [("continuous_lf", tk["fid"], tk["cabin"], k + 1, float(pr[k])) for k in np.flatnonzero(~np.isnan(pr))]
        print(f"route {route}: floor {100 * target:.1f}% load factor, reached {100 * lf:.1f}% (bonus {bonus:.0f})")
    return results, prices, table


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main():
    global SIGMA
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sigma", type=float, default=SIGMA, help="spread of willingness to pay")
    parser.add_argument("--dry", action="store_true", help="do not write results to the database")
    args = parser.parse_args()
    SIGMA = args.sigma

    base = load_base()
    lad = ladder_prices(base["fb"])
    share, g = time_profile(base)
    sens = base["sens"]
    print(f"willingness-to-pay spread {SIGMA}; fare trend {YIELD_TREND:.0%} a year applied to ladders and willingness to pay\n")

    print("Calibrating the bucket policy on the training period ...")
    params = calibrate(base, lad, share, g, sens)
    checks = [validate_calibration(base, lad, share, g, sens, params, "training", 0),
              validate_calibration(base, lad, share, g, sens, params, "test", 1)]
    print("\n## Calibration of the bucket policy\n")
    md(pd.DataFrame([{"Period": c["period"], "As flown revenue (m)": c["obs_rev"] / 1e6, "Bucket replay revenue (m)": c["rev"] / 1e6,
                      "Revenue gap %": 100 * (c["rev"] / c["obs_rev"] - 1), "As flown load factor %": c["obs_lf"],
                      "Bucket replay load factor %": c["lf"], "Load factor gap pts": c["lf"] - c["obs_lf"]} for c in checks]), 2)
    print(f"Settings: protect {params['protect']}, fence class Economy {params['fence'][1]}, Business {params['fence'][2]}, "
          f"advance-purchase variant {params['ap']}\n")

    test = base["fl"][base["fl"].is_test == 1]
    cells, inbound = build_cells(base, test.flight_id.tolist(), use_forecast=True)
    results, flights_tab, paths, price_rows, base_tasks, base_tbs = [], [], [], [], [], []
    print(f"{test.flight_id.nunique():,} held-out flights, {len(cells):,} demand cells, "
          f"{int(cells.N.sum()):,} originating passengers\n")
    for si, scen in enumerate(SCENARIOS):
        belief, world, scale, bias = scenario_world(sens, scen)
        z_belief, z_world = solve_z(belief), solve_z(world)
        price_sum = {p: np.zeros(PERIODS) for p in ("buckets", "continuous")}
        price_n = {p: np.zeros(PERIODS) for p in ("buckets", "continuous")}
        for tk in iter_tasks(base, cells, inbound, lad, share, g, z_belief, z_world, scale, bias, tag=si):
            if si == 0:
                flights_tab.append((tk["fid"], tk["cabin"], tk["cap_total"], tk["inbound"]))
            if tk["skip"]:
                continue
            tb = tables_for(tk, share, params, with_grid=True)
            if si == 0:
                base_tasks.append(tk)
                base_tbs.append(tb)
            for policy in ("buckets", "continuous"):
                pax, rev, prices = run_policy(policy, tb, tk["cust"], tk["N_hat"], tk["p_ref"], tk["z"], share, tk["g"],
                                              tk["cap"], protect=params["protect"], min_rank=AP_VARIANTS[params["ap"]])
                for s in range(3):
                    results.append((scen, policy, tk["fid"], tk["cabin"], s + 1, int(pax[s]), float(rev[s])))
                ok = ~np.isnan(prices)
                price_sum[policy][ok] += prices[ok]
                price_n[policy][ok] += 1
                if si == 0:
                    price_rows += [(policy, tk["fid"], tk["cabin"], k + 1, float(prices[k])) for k in np.flatnonzero(ok)]
            if si == 0:
                for s in range(3):
                    results.append(("base", "observed", tk["fid"], tk["cabin"], s + 1, int(tk["N"][s]),
                                    float(tk["N"][s] * tk["p_ref"][s])))
        for policy in price_sum:
            for t in range(PERIODS):
                paths.append((scen, policy, t + 1, price_sum[policy][t] / max(price_n[policy][t], 1)))
        print(f"scenario {scen} done")

    ft = pd.DataFrame(flights_tab, columns=["flight_id", "cabin_id", "capacity", "inbound_pax"])
    seats_by_flight = ft.groupby("flight_id")[["capacity", "inbound_pax"]].sum()
    route_of_flight = test.set_index("flight_id").route_id.to_dict()
    floor_res, floor_prices, floor_table = route_level_floor(base_tasks, base_tbs, share, seats_by_flight,
                                                             route_of_flight, params)
    results += floor_res
    price_rows += floor_prices
    fp = {}
    for pol, fid, cab, per, price in floor_prices:
        fp.setdefault(per, []).append(price)
    paths += [("base", "continuous_lf", per, float(np.mean(v))) for per, v in sorted(fp.items())]

    res = pd.DataFrame(results, columns=["scenario", "policy", "flight_id", "cabin_id", "segment_id", "pax", "revenue_eur"])
    pr_df = pd.DataFrame(price_rows, columns=["policy", "flight_id", "cabin_id", "period", "price_eur"])
    if not args.dry:
        rc = open_results(["simulation_results", "simulation_flights", "simulation_price_paths", "simulation_prices",
                           "simulation_floor", "simulation_calibration", "simulation_calibration_check"])
        res.round(2).to_sql("simulation_results", rc, if_exists="append", index=False)
        ft.to_sql("simulation_flights", rc, if_exists="append", index=False)
        pd.DataFrame(paths, columns=["scenario", "policy", "period", "avg_price_eur"]).round(2).to_sql(
            "simulation_price_paths", rc, if_exists="append", index=False)
        pr_df.round(2).to_sql("simulation_prices", rc, if_exists="append", index=False)
        pd.DataFrame(floor_table, columns=["route_id", "target_load_factor", "achieved_load_factor", "bonus_eur"]).round(4).to_sql(
            "simulation_floor", rc, if_exists="append", index=False)
        pd.DataFrame([("protect", params["protect"], "demand the bucket rule protects seats for, as a multiple of the forecast"),
                      ("fence_economy", params["fence"][1], "first class Business-segment customers can buy in Economy"),
                      ("fence_business", params["fence"][2], "first class Business-segment customers can buy in Business"),
                      ("advance_purchase_variant", params["ap"], "0 closes the two cheapest classes 14 days out"),
                      ("willingness_to_pay_spread", SIGMA, "assumed spread of willingness to pay"),
                      ("fare_trend", YIELD_TREND, "market fare trend a year, applied to ladders and willingness to pay")],
                     columns=["item", "value", "note"]).to_sql("simulation_calibration", rc, if_exists="append", index=False)
        pd.DataFrame([(c["period"], "as flown", c["obs_rev"], None, c["obs_lf"]) for c in checks]
                     + [(c["period"], "bucket replay", c["rev"], int(c["pax"]), c["lf"]) for c in checks],
                     columns=["period", "policy", "revenue_eur", "passengers", "load_factor"]).round(2).to_sql(
            "simulation_calibration_check", rc, if_exists="append", index=False)
        rc.commit()
        rc.close()
    report(res, test, ft, pr_df, base["fl"], lad)


def load_factor(r, ft):
    """Load factor of the flights in r: originating passengers plus returning passengers already booked."""
    pax = r.pax.sum() + ft[ft.flight_id.isin(r.flight_id.unique())].inbound_pax.sum()
    return 100 * pax / ft[ft.flight_id.isin(r.flight_id.unique())].capacity.sum()


def report(res, test, ft, pr, fl, lad):
    """Print the headline tables."""
    st = test.set_index("flight_id").station_id
    res = res.assign(station_id=res.flight_id.map(st))
    names = {1: "Frankfurt", 2: "Berlin", 3: "London", 4: "Paris", 5: "Milan", 6: "Madrid"}
    print("\n## Headline (base scenario, all held-out flights; revenue in millions EUR, one-way-fare terms)\n")
    rows = []
    for pol in ("observed", "buckets", "continuous", "continuous_lf"):
        r = res[(res.scenario == "base") & (res.policy == pol)]
        rows.append({"Policy": pol, "Revenue": r.revenue_eur.sum() / 1e6, "Passengers": r.pax.sum(),
                     "Average fare EUR": r.revenue_eur.sum() / r.pax.sum(), "Load factor %": load_factor(r, ft)})
    md(pd.DataFrame(rows), 2)

    def uplift(r):
        b = r[r.policy == "buckets"].revenue_eur.sum()
        c = r[r.policy == "continuous"].revenue_eur.sum()
        return 100 * (c / b - 1)

    obs_rev = res[(res.scenario == "base") & (res.policy == "observed")].revenue_eur.sum()
    print("## Continuous vs buckets by scenario\n")
    rows = []
    for sc in SCENARIOS:
        r = res[res.scenario == sc]
        rb, rcn = r[r.policy == "buckets"], r[r.policy == "continuous"]
        rows.append({"Scenario": sc, "Buckets revenue (m)": rb.revenue_eur.sum() / 1e6,
                     "Continuous revenue (m)": rcn.revenue_eur.sum() / 1e6, "Revenue change %": uplift(r),
                     "Continuous vs as flown %": 100 * (rcn.revenue_eur.sum() / obs_rev - 1),
                     "LF buckets %": load_factor(rb, ft), "LF continuous %": load_factor(rcn, ft)})
    md(pd.DataFrame(rows), 2)

    print("## Base scenario by route (revenue change vs buckets and vs as flown)\n")
    base = res[res.scenario == "base"]
    rows = []
    for sid, gr in base.groupby("station_id"):
        rb, rcn, ro = gr[gr.policy == "buckets"], gr[gr.policy == "continuous"], gr[gr.policy == "observed"]
        rows.append({"Route": names[sid], "Buckets (m)": rb.revenue_eur.sum() / 1e6,
                     "Continuous (m)": rcn.revenue_eur.sum() / 1e6, "vs buckets %": uplift(gr),
                     "vs as flown %": 100 * (rcn.revenue_eur.sum() / ro.revenue_eur.sum() - 1)})
    md(pd.DataFrame(rows), 2)

    print("## Base scenario by segment\n")
    rows = []
    for seg, name in ((1, "Business"), (2, "Leisure"), (3, "VFR")):
        gr = base[base.segment_id == seg]
        rb, rcn, ro = gr[gr.policy == "buckets"], gr[gr.policy == "continuous"], gr[gr.policy == "observed"]
        rows.append({"Segment": name, "vs as flown %": 100 * (rcn.revenue_eur.sum() / ro.revenue_eur.sum() - 1),
                     "vs buckets %": uplift(gr), "Avg fare buckets": rb.revenue_eur.sum() / rb.pax.sum(),
                     "Avg fare continuous": rcn.revenue_eur.sum() / rcn.pax.sum(),
                     "Pax buckets": rb.pax.sum(), "Pax continuous": rcn.pax.sum(), "Pax as flown": ro.pax.sum()})
    md(pd.DataFrame(rows), 2)

    f = fl.set_index("flight_id")
    pr = pr.assign(route=pr.flight_id.map(f.route_id), ladder=pr.flight_id.map(f.ladder), trend=pr.flight_id.map(f.trend))
    top = pr.apply(lambda r: lad[(r.route, r.cabin_id, r.ladder)][-1] * r.trend, axis=1)
    bottom = pr.apply(lambda r: lad[(r.route, r.cabin_id, r.ladder)][0] * r.trend, axis=1)
    pr["at_ceiling"], pr["at_floor"] = pr.price_eur >= top - 0.5, pr.price_eur <= bottom + 0.5
    print("## Base scenario: share of prices at the ceiling or the floor of the range\n")
    s = pr.groupby(["cabin_id", "policy"])[["at_ceiling", "at_floor"]].mean().reset_index()
    s["cabin"] = s.cabin_id.map({1: "Economy", 2: "Business"})
    md(s[["cabin", "policy", "at_ceiling", "at_floor"]].round(3), 3)
    for cid, cname in ((2, "Business"), (1, "Economy")):
        print(f"## Mean price offered by booking period (EUR), {cname} cabin, base scenario\n")
        p = pr[pr.cabin_id == cid].groupby(["policy", "period"]).price_eur.mean().unstack().reset_index()
        md(p, 0)


if __name__ == "__main__":
    main()
