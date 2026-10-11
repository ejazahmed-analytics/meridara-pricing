"""Phase 4b: replay the held-out period under two pricing policies.

Illustrative case study using fictitious and simulated data.

Policies, both facing the same simulated customers on every flight:
  * buckets    about 10 fixed one-way price points opened and closed by EMSR-b
  * continuous a price anywhere between the lowest and highest bucket price,
               re-chosen each booking period to maximise expected revenue

Demand for each flight, cabin and segment is sized from observed originating
passengers, with a constant-elasticity demand curve using the segment price
sensitivity estimated in Phase 4a. Policies see the Phase 3 forecast (90 days
out), not the truth, and rescale their remaining-demand forecast from actual
sales after every booking period.

Simplifications: returning passengers are already booked and fixed, so only
originating passengers on their outbound leg are priced; revenue is in
one-way-fare terms in EUR; observed bookings stand in for demand, which
understates demand on full flights.

Run from the project root:   python src/pricing_sim.py
"""
import sqlite3

import numpy as np
import pandas as pd
from scipy.stats import norm

from forecast import md
from results_db import DATA_DB, RESULTS_DB, open_results

SEED = 7
PERIODS = 7                                   # 330-181, 180-91, 90-61, 60-31, 30-15, 14-8, 7-0 days out
EDGES = [-1, 7, 14, 30, 60, 90, 180, 10_000]  # days_before bins, nearest departure first
XM = 0.3                                      # lowest willingness to pay as a share of the reference price
FORECAST_CV = 0.2                             # forecast uncertainty used by EMSR-b (about the 90-day WAPE)
PRIOR_PAX = 3.0                               # weight of the forecast when rescaling after sales
GRID = 60
FENCE_RANK = 6                                # Business-segment customers buy only the 6th price point or above
SCENARIOS = ["base", "underforecast", "competitor_cut", "elastic_world", "inelastic_world"]
BERLIN_INTRO_END = pd.Timestamp("2026-01-25")


def load_inputs():
    """Demand cells, capacities, ladders, forecasts and sensitivity estimates for the test flights."""
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
    return fl, test, fb, cells, inbound, share, sens


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


def make_customers(N, p_ref, eps_world, scale, share, rng):
    """Customers for one flight and cabin: booking period, segment and willingness to pay."""
    periods, segs, wtp = [], [], []
    for s in range(3):
        if N[s] <= 0:
            continue
        xm = XM * p_ref[s]
        population = N[s] * scale[s] * (xm / p_ref[s]) ** eps_world[s]    # buyers at p_ref equal N
        k = rng.poisson(population)
        periods.append(rng.choice(PERIODS, size=k, p=share[s]))
        segs.append(np.full(k, s))
        wtp.append(xm * rng.random(k) ** (1 / eps_world[s]))
    if not periods:
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0)
    period, seg, w = np.concatenate(periods), np.concatenate(segs), np.concatenate(wtp)
    order = rng.permutation(len(period))                                  # random arrival order
    return period[order], seg[order], w[order]


def emsr_b_price(prices, mu, c_rem):
    """Lowest open fare class under EMSR-b protection levels. prices ascending; mu = class demand."""
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
    return prices[open_idx]


def run_policy(policy, ladder, cust, N_hat, p_ref, belief, share, cap, floor, ceiling):
    """Play one flight and cabin under one policy. Returns pax and revenue by segment and prices by period.

    Both policies offer one base price per period. Business-segment customers pay at least the fence
    price (the 6th price point), so they cannot buy down to the cheapest classes.
    """
    c_rem = cap
    period, seg, wtp = cust
    fence = ladder[FENCE_RANK - 1]
    grid = np.linspace(floor, ceiling, GRID)

    def effective(prices):
        """Price each segment pays when the base price is `prices` (shape n x 3)."""
        eff = np.repeat(prices[:, None], 3, axis=1)
        eff[:, 0] = np.maximum(eff[:, 0], fence)
        return eff

    eff_grid, eff_class = effective(grid), effective(ladder)
    dem_grid = (eff_grid / p_ref[None, :]) ** belief[None, :]            # share of N willing to pay
    dem_class = (eff_class / p_ref[None, :]) ** belief[None, :]
    rem = np.cumsum(share[:, ::-1], axis=1)[:, ::-1]                      # demand still to come from period t
    pax, rev, prices = np.zeros(3), np.zeros(3), np.full(PERIODS, np.nan)
    obs, expc = 0.0, 0.0
    for t in range(PERIODS):
        if c_rem <= 0:
            break
        kappa = np.clip((obs + PRIOR_PAX) / (expc + PRIOR_PAX), 0.3, 3.0)
        w = N_hat * rem[:, t] * kappa
        if policy == "continuous":
            seg_d = dem_grid * w[None, :]                                  # expected buyers by segment
            total = seg_d.sum(1)
            scale = np.minimum(1.0, c_rem / np.maximum(total, 1e-9))
            price = grid[np.argmax(scale * (seg_d * eff_grid).sum(1))]
        else:
            d = dem_class @ w
            mu = np.maximum(d - np.append(d[1:], 0.0), 1e-9)               # demand in each fare band
            price = emsr_b_price(ladder, mu, c_rem)
        prices[t] = price
        pay = np.array([max(price, fence), price, price])
        buy = np.flatnonzero((period == t) & (wtp >= pay[seg]))[:int(c_rem)]
        sold = np.bincount(seg[buy], minlength=3)
        pax += sold
        rev += sold * pay
        c_rem -= len(buy)
        obs += len(buy)
        expc += float(((pay / p_ref) ** belief * N_hat * share[:, t]).sum())
    return pax, rev, prices


def main():
    fl, test, fb, cells, inbound, share, sens = load_inputs()
    lad = ladder_prices(fb)
    caps = test.set_index("flight_id")[["capacity_business", "capacity_economy"]]
    ib = inbound.set_index(["flight_id", "cabin_id"]).inbound
    meta = test.set_index("flight_id")[["route_id", "ladder"]]
    print(f"{test.flight_id.nunique():,} held-out flights, {len(cells):,} demand cells, "
          f"{int(cells.N.sum()):,} originating passengers\n")

    results, flights_tab, paths = [], [], []
    by_flight = {k: g for k, g in cells.groupby(["flight_id", "cabin_id"])}
    for si, scen in enumerate(SCENARIOS):
        belief, world, scale, bias = scenario_world(sens, scen)
        price_sum = {p: np.zeros(PERIODS) for p in ("buckets", "continuous")}
        price_n = {p: np.zeros(PERIODS) for p in ("buckets", "continuous")}
        for (fid, cabin), g in by_flight.items():
            cap_total = caps.loc[fid, "capacity_business" if cabin == 2 else "capacity_economy"]
            inb = int(ib.get((fid, cabin), 0))
            cap = int(cap_total - inb)
            if si == 0:
                flights_tab.append((fid, cabin, int(cap_total), inb))
            if cap <= 0:
                continue
            N, p_ref, ratio = np.zeros(3), np.ones(3), np.ones(3)
            for r in g.itertuples():
                N[r.segment_id - 1], p_ref[r.segment_id - 1], ratio[r.segment_id - 1] = r.N, r.p_ref, r.ratio
            N_hat = N * ratio * bias
            rng = np.random.default_rng([SEED, int(fid), cabin, si])
            cust = make_customers(N, p_ref, world, scale, share, rng)
            ladder = lad[(meta.loc[fid, "route_id"], cabin, meta.loc[fid, "ladder"])]
            for policy in ("buckets", "continuous"):
                pax, rev, prices = run_policy(policy, ladder, cust, N_hat, p_ref, belief, share, cap,
                                              ladder[0], ladder[-1])
                for s in range(3):
                    results.append((scen, policy, fid, cabin, s + 1, int(pax[s]), float(rev[s])))
                ok = ~np.isnan(prices)
                price_sum[policy][ok] += prices[ok]
                price_n[policy][ok] += 1
            if si == 0:
                for s in range(3):
                    results.append(("base", "observed", fid, cabin, s + 1, int(N[s]), float(N[s] * p_ref[s])))
        for policy in price_sum:
            for t in range(PERIODS):
                paths.append((scen, policy, t + 1, price_sum[policy][t] / max(price_n[policy][t], 1)))
        print(f"scenario {scen} done")

    res = pd.DataFrame(results, columns=["scenario", "policy", "flight_id", "cabin_id", "segment_id",
                                         "pax", "revenue_eur"])
    rc = open_results(["simulation_results", "simulation_flights", "simulation_price_paths"])
    res.round(2).to_sql("simulation_results", rc, if_exists="append", index=False)
    pd.DataFrame(flights_tab, columns=["flight_id", "cabin_id", "capacity", "inbound_pax"]).to_sql(
        "simulation_flights", rc, if_exists="append", index=False)
    pd.DataFrame(paths, columns=["scenario", "policy", "period", "avg_price_eur"]).round(2).to_sql(
        "simulation_price_paths", rc, if_exists="append", index=False)
    rc.commit()
    rc.close()
    report(res, test, pd.DataFrame(flights_tab, columns=["flight_id", "cabin_id", "capacity", "inbound_pax"]),
           pd.DataFrame(paths, columns=["scenario", "policy", "period", "avg_price"]))


def load_factor(r, ft):
    """Load factor of the flights in r: originating passengers plus returning passengers already booked."""
    pax = r.pax.sum() + ft[ft.flight_id.isin(r.flight_id.unique())].inbound_pax.sum()
    return 100 * pax / ft[ft.flight_id.isin(r.flight_id.unique())].capacity.sum()


def report(res, test, ft, paths):
    """Print the headline tables."""
    st = test.set_index("flight_id").station_id
    res = res.assign(station_id=res.flight_id.map(st))
    names = {1: "Frankfurt", 2: "Berlin", 3: "London", 4: "Paris", 5: "Milan", 6: "Madrid"}
    print("\n## Headline (base scenario, all held-out flights; revenue in millions EUR, one-way-fare terms)\n")
    rows = []
    for pol in ("observed", "buckets", "continuous"):
        r = res[(res.scenario == "base") & (res.policy == pol)]
        rows.append({"Policy": pol, "Revenue": r.revenue_eur.sum() / 1e6, "Passengers": r.pax.sum(),
                     "Average fare EUR": r.revenue_eur.sum() / r.pax.sum(), "Load factor %": load_factor(r, ft)})
    md(pd.DataFrame(rows), 2)

    def uplift(r):
        b = r[r.policy == "buckets"].revenue_eur.sum()
        c = r[r.policy == "continuous"].revenue_eur.sum()
        return 100 * (c / b - 1)

    print("## Continuous vs buckets by scenario\n")
    rows = []
    for sc in SCENARIOS:
        r = res[res.scenario == sc]
        rb, rcn = r[r.policy == "buckets"], r[r.policy == "continuous"]
        rows.append({"Scenario": sc, "Buckets revenue (m)": rb.revenue_eur.sum() / 1e6,
                     "Continuous revenue (m)": rcn.revenue_eur.sum() / 1e6, "Revenue change %": uplift(r),
                     "Avg fare buckets": rb.revenue_eur.sum() / rb.pax.sum(),
                     "Avg fare continuous": rcn.revenue_eur.sum() / rcn.pax.sum(),
                     "LF buckets %": load_factor(rb, ft), "LF continuous %": load_factor(rcn, ft)})
    md(pd.DataFrame(rows), 2)

    print("## Base scenario by route (revenue change of continuous vs buckets)\n")
    base = res[res.scenario == "base"]
    rows = []
    for sid, g in base.groupby("station_id"):
        rb, rcn = g[g.policy == "buckets"], g[g.policy == "continuous"]
        rows.append({"Route": names[sid], "Buckets revenue (m)": rb.revenue_eur.sum() / 1e6,
                     "Continuous revenue (m)": rcn.revenue_eur.sum() / 1e6, "Revenue change %": uplift(g),
                     "Avg fare buckets": rb.revenue_eur.sum() / rb.pax.sum(),
                     "Avg fare continuous": rcn.revenue_eur.sum() / rcn.pax.sum(),
                     "LF buckets %": load_factor(rb, ft), "LF continuous %": load_factor(rcn, ft)})
    md(pd.DataFrame(rows), 2)

    print("## Base scenario by segment\n")
    rows = []
    for seg, name in ((1, "Business"), (2, "Leisure"), (3, "VFR")):
        g = base[base.segment_id == seg]
        rb, rcn = g[g.policy == "buckets"], g[g.policy == "continuous"]
        rows.append({"Segment": name, "Revenue change %": uplift(g),
                     "Avg fare buckets": rb.revenue_eur.sum() / rb.pax.sum(),
                     "Avg fare continuous": rcn.revenue_eur.sum() / rcn.pax.sum(),
                     "Passengers buckets": rb.pax.sum(), "Passengers continuous": rcn.pax.sum()})
    md(pd.DataFrame(rows), 2)

    print("## Average price offered by booking period (1 = earliest, 7 = last week), continuous policy\n")
    p = paths[paths.policy == "continuous"].pivot(index="scenario", columns="period", values="avg_price").reset_index()
    md(p, 0)

    print("## Underforecast scenario: Berlin vs other routes (revenue change, continuous vs buckets)\n")
    rows = []
    for sc in ("base", "underforecast"):
        g = res[res.scenario == sc]
        rows.append({"Scenario": sc, "Berlin %": uplift(g[g.station_id == 2]),
                     "All other routes %": uplift(g[g.station_id != 2])})
    md(pd.DataFrame(rows), 2)


if __name__ == "__main__":
    main()
