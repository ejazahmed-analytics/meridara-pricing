"""Phase 4b: replay the held-out period under two pricing policies.

Illustrative case study using fictitious and simulated data.

Policies, all facing the same simulated customers on every flight:
  * buckets    about 10 fixed one-way price points opened and closed by EMSR-b, with
               advance-purchase rules (the two cheapest classes close 14 days out and
               classes 3 and 4 close 7 days out)
  * continuous a price anywhere between the lowest and highest bucket price,
               re-chosen each booking period to maximise expected revenue
  * continuous_lf (base scenario only) the same, but each route must keep at least its
               as-flown average load factor over the test window; single flights can vary

Demand model. Each customer has a willingness to pay (WTP). WTP is lognormal with a
spread of SIGMA, so it is bounded in practice and the revenue-maximising price falls
inside the price range. The location is set so that the slope of demand at the
as-flown price equals the price sensitivity estimated in Phase 4a. WTP also scales with
the booking period: later customers are willing to pay more, following the pattern of
average prices paid by booking window in the training data.

Policies see the Phase 3 forecast (90 days out), not the truth, and rescale their
remaining-demand forecast from actual sales after every booking period.

Simplifications: returning passengers are already booked and fixed, so only
originating passengers on their outbound leg are priced; revenue is in
one-way-fare terms in EUR; observed bookings stand in for demand, which
understates demand on full flights.

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
from results_db import DATA_DB, RESULTS_DB, open_results

SEED = 7
PERIODS = 7                                   # 330-181, 180-91, 90-61, 60-31, 30-15, 14-8, 7-0 days out
EDGES = [-1, 7, 14, 30, 60, 90, 180, 10_000]  # days_before bins, nearest departure first
SIGMA = 0.45                                  # spread of willingness to pay (log scale), an assumption
MIN_RANK = [1, 1, 1, 1, 1, 3, 5]              # lowest bucket class open in each period (advance purchase)
FORECAST_CV = 0.2                             # forecast uncertainty used by EMSR-b (about the 90-day WAPE)
PRIOR_PAX = 3.0                               # weight of the forecast when rescaling after sales
GRID = 60
FENCE_RANK = 6                                # Business-segment customers buy only the 6th price point or above
SCENARIOS = ["base", "underforecast", "competitor_cut", "elastic_world", "inelastic_world"]
BERLIN_INTRO_END = pd.Timestamp("2026-01-25")


def load_inputs():
    """Demand cells, capacities, ladders, forecasts, time profile and sensitivity estimates."""
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
    train_ids = set(fl[fl.is_test == 0].flight_id)
    out_train = b[(b.leg_seq == 1) & b.flight_id.isin(train_ids)].copy()
    out_train["period"] = PERIODS - 1 - pd.cut(out_train.days_before, EDGES, labels=False)
    share = (out_train.groupby(["segment_id", "period"]).pax.sum().unstack().fillna(0))
    share = share.div(share.sum(axis=1), axis=0).reindex(columns=range(PERIODS), fill_value=0).to_numpy()

    # Time profile of willingness to pay: average price paid by booking period in the training data,
    # relative to the arrival-weighted average for the same cabin and segment.
    tr = out_train.merge(fl[["flight_id", "route_id", "ladder", "promo", "intro"]], on="flight_id")
    tr = tr.merge(fb, on=["route_id", "cabin_id", "ladder", "class_rank"])
    tr["paid"] = tr.price_point_eur * (1 - tr.promo / 100) * tr.intro
    tr["spend"] = tr.paid * tr.pax
    m = tr.groupby(["cabin_id", "segment_id", "period"])[["spend", "pax"]].sum()
    price = (m.spend / m.pax).unstack().reindex(columns=range(PERIODS))
    g = np.zeros((2, 3, PERIODS))
    for ci in range(2):
        for si in range(3):
            raw = price.loc[(ci + 1, si + 1)].to_numpy()
            g[ci, si] = raw / (share[si] * raw).sum()                 # arrival-weighted mean of 1

    test = fl[fl.is_test == 1]
    bt = b[b.flight_id.isin(test.flight_id)]
    o = bt[bt.leg_seq == 1].merge(test[["flight_id", "route_id", "ladder", "promo", "intro"]], on="flight_id")
    o = o.merge(fb, on=["route_id", "cabin_id", "ladder", "class_rank"])
    o["paid"] = o.price_point_eur * (1 - o.promo / 100) * o.intro
    o["spend"] = o.paid * o.pax
    cells = o.groupby(["flight_id", "cabin_id", "segment_id"]).agg(N=("pax", "sum"), spend=("spend", "sum")).reset_index()
    cells["p_ref"] = cells.spend / cells.N
    inbound = (bt[bt.leg_seq == 2].groupby(["flight_id", "cabin_id"]).pax.sum().rename("inbound").reset_index())

    fc["ratio"] = np.where(fc.actual_final > 0, (fc.gbm_forecast / fc.actual_final.clip(lower=1e-9)), 1.0)
    fc["ratio"] = fc.ratio.clip(0.5, 2.0)
    cells = cells.merge(fc[["flight_id", "segment_id", "ratio"]], on=["flight_id", "segment_id"], how="left")
    cells["ratio"] = cells.ratio.fillna(1.0)
    return fl, test, fb, cells, inbound, share, g, sens


def ladder_prices(fb):
    """Dictionary (route, cabin, ladder) -> array of the 10 one-way price points, cheapest first."""
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


def solve_z(elasticity):
    """Position of the as-flown price on the willingness-to-pay curve for each segment.

    For lognormal willingness to pay with spread SIGMA, the price elasticity at a price is
    hazard(z) / SIGMA, where z is the standard-normal position of that price. Solve for z so that
    the elasticity equals the estimate. More negative z means demand is further from the point
    where it turns elastic.
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


def build_tables(ladder, p_ref, z, g, share, floor, ceiling):
    """Expected demand still to come, by period, candidate price and segment (per unit of forecast)."""
    fence = ladder[FENCE_RANK - 1]
    grid = np.linspace(floor, ceiling, GRID)

    def effective(prices):
        eff = np.repeat(prices[:, None], 3, axis=1)
        eff[:, 0] = np.maximum(eff[:, 0], fence)                          # Business cannot buy below the fence
        return eff

    def remaining(prices_eff):
        ln = np.log(prices_eff[None, :, :] / (p_ref[None, None, :] * g.T[:, None, :]))
        surv = ndtr(-(z[None, None, :] + ln / SIGMA)) / ndtr(-z)[None, None, :]
        arrivals = surv * share.T[:, None, :]                              # (period, price, segment)
        return np.cumsum(arrivals[::-1], axis=0)[::-1]                     # demand from period t onward

    eff_grid, eff_class = effective(grid), effective(ladder)
    return dict(ladder=ladder, grid=grid, eff_grid=eff_grid, fence=fence,
                R_grid=remaining(eff_grid), R_class=remaining(eff_class))


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


def run_policy(policy, tb, cust, N_hat, p_ref, z, share, g, cap, bonus=0.0):
    """Play one flight and cabin under one policy. Returns pax and revenue by segment and prices by period.

    Both policies offer one base price per period. Business-segment customers pay at least the fence
    price (the 6th price point). Bucket prices cannot go below the lowest class still open under the
    advance-purchase rules. For the load factor floor policy, `bonus` is a value per passenger added to
    the objective: it pushes prices down until the route reaches its target load factor. It never enters
    the revenue that is counted.
    """
    c_rem = cap
    period, seg, wtp = cust
    ladder, fence = tb["ladder"], tb["fence"]
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
            d = tb["R_class"][t] @ w
            mu = np.maximum(d - np.append(d[1:], 0.0), 1e-9)               # demand in each fare band
            idx = max(emsr_b_index(ladder, mu, c_rem), MIN_RANK[t] - 1)    # advance-purchase rules close cheap classes
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


def route_level_floor(tasks, share, seats_by_flight, route_of_flight):
    """Continuous pricing with a route-level load factor floor.

    For every route, find the smallest per-passenger bonus that brings the route's average load factor
    over the test window up to its as-flown level (bisection), then keep that run.
    """
    by_route = {}
    for tk in tasks:
        by_route.setdefault(tk["route"], []).append(tk)
    results, prices, table = [], [], []
    for route, tks in sorted(by_route.items()):
        flights = [f for f, r in route_of_flight.items() if r == route and f in seats_by_flight.index]
        seats = seats_by_flight.loc[flights].capacity.sum()
        inbound = seats_by_flight.loc[flights].inbound_pax.sum()
        target = (sum(tk["N"].sum() for tk in tks) + inbound) / seats

        def play(bonus):
            out = [run_policy("continuous_lf", tk["tb"], tk["cust"], tk["N_hat"], tk["p_ref"], tk["z"], share,
                              tk["g"], tk["cap"], bonus=bonus) for tk in tks]
            return (sum(o[0].sum() for o in out) + inbound) / seats, out

        lf, out = play(0.0)
        bonus = 0.0
        if lf < target:
            lo, hi = 0.0, 2 * max(tk["ladder"][-1] for tk in tks)
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
        for tk, (pax, rev, pr) in zip(tks, out):
            for s in range(3):
                results.append(("base", "continuous_lf", int(tk["fid"]), tk["cabin"], s + 1, int(pax[s]), float(rev[s])))
            prices += [("continuous_lf", int(tk["fid"]), tk["cabin"], k + 1, float(pr[k]))
                       for k in np.flatnonzero(~np.isnan(pr))]
        print(f"route {route}: floor {100 * target:.1f}% load factor, reached {100 * lf:.1f}% (bonus {bonus:.0f})")
    return results, prices, table


def main():
    global SIGMA
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sigma", type=float, default=SIGMA, help="spread of willingness to pay")
    parser.add_argument("--dry", action="store_true", help="do not write results to the database")
    args = parser.parse_args()
    SIGMA = args.sigma

    fl, test, fb, cells, inbound, share, g, sens = load_inputs()
    lad = ladder_prices(fb)
    caps = test.set_index("flight_id")[["capacity_business", "capacity_economy"]]
    ib = inbound.set_index(["flight_id", "cabin_id"]).inbound
    meta = test.set_index("flight_id")[["route_id", "ladder"]]
    print(f"{test.flight_id.nunique():,} held-out flights, {len(cells):,} demand cells, "
          f"{int(cells.N.sum()):,} originating passengers; willingness-to-pay spread {SIGMA}\n")

    results, flights_tab, paths, price_rows, tasks = [], [], [], [], []
    by_flight = {k: gr for k, gr in cells.groupby(["flight_id", "cabin_id"])}
    for si, scen in enumerate(SCENARIOS):
        belief, world, scale, bias = scenario_world(sens, scen)
        z_belief, z_world = solve_z(belief), solve_z(world)
        price_sum = {p: np.zeros(PERIODS) for p in ("buckets", "continuous")}
        price_n = {p: np.zeros(PERIODS) for p in ("buckets", "continuous")}
        for (fid, cabin), gr in by_flight.items():
            cap_total = caps.loc[fid, "capacity_business" if cabin == 2 else "capacity_economy"]
            inb = int(ib.get((fid, cabin), 0))
            cap = int(cap_total - inb)
            if si == 0:
                flights_tab.append((fid, cabin, int(cap_total), inb))
            if cap <= 0:
                continue
            N, p_ref, ratio = np.zeros(3), np.ones(3), np.ones(3)
            for r in gr.itertuples():
                N[r.segment_id - 1], p_ref[r.segment_id - 1], ratio[r.segment_id - 1] = r.N, r.p_ref, r.ratio
            N_hat = N * ratio * bias
            rng = np.random.default_rng([SEED, int(fid), cabin, si])
            gc = g[cabin - 1]
            cust = make_customers(N, p_ref, z_world, scale, share, gc, rng)
            ladder = lad[(meta.loc[fid, "route_id"], cabin, meta.loc[fid, "ladder"])]
            tb = build_tables(ladder, p_ref, z_belief, gc, share, ladder[0], ladder[-1])
            if si == 0:
                tasks.append(dict(route=int(meta.loc[fid, "route_id"]), fid=fid, cabin=cabin, cust=cust, N=N.copy(),
                                  N_hat=N_hat, p_ref=p_ref, ladder=ladder, cap=cap, z=z_belief, g=gc, tb=tb))
            for policy in ("buckets", "continuous"):
                pax, rev, prices = run_policy(policy, tb, cust, N_hat, p_ref, z_belief, share, gc, cap)
                for s in range(3):
                    results.append((scen, policy, fid, cabin, s + 1, int(pax[s]), float(rev[s])))
                ok = ~np.isnan(prices)
                price_sum[policy][ok] += prices[ok]
                price_n[policy][ok] += 1
                if si == 0:
                    price_rows += [(policy, int(fid), cabin, k + 1, float(prices[k])) for k in np.flatnonzero(ok)]
            if si == 0:
                for s in range(3):
                    results.append(("base", "observed", fid, cabin, s + 1, int(N[s]), float(N[s] * p_ref[s])))
        for policy in price_sum:
            for t in range(PERIODS):
                paths.append((scen, policy, t + 1, price_sum[policy][t] / max(price_n[policy][t], 1)))
        print(f"scenario {scen} done")

    # Route-level load factor floor (base scenario only).
    ft = pd.DataFrame(flights_tab, columns=["flight_id", "cabin_id", "capacity", "inbound_pax"])
    seats_by_flight = ft.groupby("flight_id")[["capacity", "inbound_pax"]].sum()
    route_of_flight = test.set_index("flight_id").route_id.to_dict()
    floor_res, floor_prices, floor_table = route_level_floor(tasks, share, seats_by_flight, route_of_flight)
    results += floor_res
    price_rows += floor_prices
    fp = {}
    for pol, fid, cab, per, price in floor_prices:
        fp.setdefault(per, []).append(price)
    paths += [("base", "continuous_lf", per, float(np.mean(v))) for per, v in sorted(fp.items())]

    res = pd.DataFrame(results, columns=["scenario", "policy", "flight_id", "cabin_id", "segment_id",
                                         "pax", "revenue_eur"])
    pr_df = pd.DataFrame(price_rows, columns=["policy", "flight_id", "cabin_id", "period", "price_eur"])
    if not args.dry:
        rc = open_results(["simulation_results", "simulation_flights", "simulation_price_paths", "simulation_prices",
                           "simulation_floor"])
        res.round(2).to_sql("simulation_results", rc, if_exists="append", index=False)
        ft.to_sql("simulation_flights", rc, if_exists="append", index=False)
        pd.DataFrame(paths, columns=["scenario", "policy", "period", "avg_price_eur"]).round(2).to_sql(
            "simulation_price_paths", rc, if_exists="append", index=False)
        pr_df.round(2).to_sql("simulation_prices", rc, if_exists="append", index=False)
        pd.DataFrame(floor_table, columns=["route_id", "target_load_factor", "achieved_load_factor", "bonus_eur"]).round(4).to_sql(
            "simulation_floor", rc, if_exists="append", index=False)
        rc.commit()
        rc.close()
    report(res, test, ft, pr_df, fl, lad)


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

    # Price paths by cabin: do prices move inside the range and rise towards departure?
    f = fl.set_index("flight_id")
    pr = pr.assign(route=pr.flight_id.map(f.route_id), ladder=pr.flight_id.map(f.ladder))
    top = pr.apply(lambda r: lad[(r.route, r.cabin_id, r.ladder)][-1], axis=1)
    bottom = pr.apply(lambda r: lad[(r.route, r.cabin_id, r.ladder)][0], axis=1)
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
