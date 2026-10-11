"""Phase 3: demand forecast. Historical-pickup baseline vs gradient boosting.

Illustrative case study using fictitious and simulated data.

For every flight and segment we forecast final passengers at several points
before departure, using only bookings made by that point. Models are trained
on departures up to 31 August 2025 and tested on September 2025 to February
2026. Berlin has no training history, so it tests the cold-start case.

Run from the project root:   python src/forecast.py
"""
import sqlite3

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from results_db import DATA_DB, open_results

ASOF = [90, 60, 30, 14, 7]            # days before departure
LAUNCH = pd.Timestamp("2025-10-26")   # Berlin first departure
BORROW_FROM = (1, 4, 5)               # Frankfurt, Paris, Milan: markets Berlin borrows from
FEATURES = ["segment_id", "lead", "onhand", "pace", "inbound_share", "conn_share", "flight_onhand",
            "fill", "cap_total", "cap_business", "weekly_frequency", "price_index", "to_hub",
            "weekday", "month", "season_code", "xmas", "easter", "eid", "diwali", "school", "autumn",
            "promo", "comp_idx"]


def md(df, digits=1):
    """Print a dataframe as a markdown table."""
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else f"{v:,.{digits}f}"
        return str(v)
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    print("\n".join(lines) + "\n")


def load(con):
    """Bookings and flight attributes needed for the forecast."""
    b = pd.read_sql("SELECT flight_id, days_before, segment_id, leg_seq, pax, beyond_city_id "
                    "FROM bookings", con)
    fl = pd.read_sql("""SELECT f.flight_id, f.route_id, f.departure_date, f.weekday, f.season,
                               f.capacity_business, f.capacity_economy, f.promo_discount_pct AS promo,
                               f.is_test, r.station_id, r.direction, r.weekly_frequency, r.price_index,
                               e.event_name
                        FROM flights f JOIN routes r ON r.route_id = f.route_id
                        LEFT JOIN events e ON e.event_id = f.event_id""", con)
    comp = pd.read_sql("SELECT route_id, week_start, index_value AS comp_idx FROM competitor_index", con)
    fl["departure_date"] = pd.to_datetime(fl.departure_date)
    fl["week_start"] = (fl.departure_date - pd.to_timedelta(fl.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    fl = fl.merge(comp, on=["route_id", "week_start"], how="left")
    fl["month"] = fl.departure_date.dt.month
    fl["to_hub"] = (fl.direction == "to_hub").astype(int)
    fl["cap_total"] = fl.capacity_business + fl.capacity_economy
    fl["cap_business"] = fl.capacity_business
    fl["season_code"] = fl.season.map({"low": 0, "shoulder": 1, "summer": 2, "christmas": 3})
    name = fl.event_name.fillna("")
    for col, key in (("xmas", "Christmas"), ("easter", "Easter"), ("eid", "Eid"), ("diwali", "Diwali"),
                     ("school", "School"), ("autumn", "Autumn")):
        fl[col] = name.str.contains(key).astype(int)
    return b, fl


def build_frame(b, fl, asof):
    """One row per flight and segment with features known `asof` days before departure."""
    idx = pd.MultiIndex.from_product([fl.flight_id.to_numpy(), [1, 2, 3]],
                                     names=["flight_id", "segment_id"])
    key = ["flight_id", "segment_id"]

    def agg(mask, name):
        return b[mask].groupby(key).pax.sum().rename(name)

    known = b.days_before >= asof
    df = pd.DataFrame(index=idx).join([
        agg(known, "onhand"),
        agg(b.days_before >= asof + 14, "onhand_prev"),
        agg(known & (b.leg_seq == 2), "inbound"),
        agg(known & b.beyond_city_id.notna(), "conn"),
        agg(b.days_before >= 0, "final"),
    ]).fillna(0).reset_index()
    df["lead"] = asof
    df["pace"] = df.onhand - df.onhand_prev                  # booked in the last 14 days
    df["inbound_share"] = np.where(df.onhand > 0, df.inbound / df.onhand.clip(lower=1), 0)
    df["conn_share"] = np.where(df.onhand > 0, df.conn / df.onhand.clip(lower=1), 0)
    df["flight_onhand"] = df.groupby("flight_id").onhand.transform("sum")
    keep = ["flight_id", "route_id", "station_id", "direction", "departure_date", "is_test", "cap_total",
            "cap_business", "weekly_frequency", "price_index", "to_hub", "weekday", "month",
            "season_code", "xmas", "easter", "eid", "diwali", "school", "autumn", "promo", "comp_idx"]
    df = df.merge(fl[keep], on="flight_id")
    df["fill"] = df.flight_onhand / df.cap_total
    return df


def fit_pickup_ratios(train):
    """Historical pickup: final / on hand, summed over training flights of each route, segment, as-of."""
    g = train.groupby(["route_id", "segment_id", "lead"])
    ratio = (g.final.sum() / g.onhand.sum().replace(0, np.nan)).fillna(1.0)
    return ratio


def baseline_forecast(df, ratio, routes):
    """Pickup forecast. Routes with no history borrow the average ratio of similar markets."""
    r = df.set_index(["route_id", "segment_id", "lead"]).index.map(ratio.to_dict())
    r = pd.Series(r, index=df.index)
    borrowed = []
    for _, row in df[r.isna()].drop_duplicates(["route_id", "segment_id", "lead"]).iterrows():
        peers = routes[(routes.station_id.isin(BORROW_FROM)) & (routes.direction == row.direction)].route_id
        vals = [ratio.get((p, row.segment_id, row.lead), np.nan) for p in peers]
        borrowed.append((row.route_id, row.segment_id, row.lead, np.nanmean(vals)))
    bd = {(a, b_, c): v for a, b_, c, v in borrowed}
    miss = r.isna()
    r[miss] = [bd[(a, b_, c)] for a, b_, c in zip(df.route_id[miss], df.segment_id[miss], df.lead[miss])]
    return df.onhand * r


def own_history_forecast(ber):
    """Berlin forecast that learns from Berlin's own departed flights (borrowed ratio until 30 rows exist)."""
    out = ber.baseline_forecast.copy()
    for (route, seg, asof), g in ber.groupby(["route_id", "segment_id", "lead"]):
        g = g.sort_values("departure_date")
        for i, row in g.iterrows():
            done = g[g.departure_date <= row.departure_date - pd.Timedelta(days=int(asof))]
            if len(done) >= 30 and done.onhand.sum() > 0:
                out[i] = row.onhand * done.final.sum() / done.onhand.sum()
    return out


def metrics(df, col):
    """WAPE, MAPE (actual >= 10) and bias of one forecast column."""
    a, f = df.final, df[col]
    big = a >= 10
    return dict(wape=100 * (f - a).abs().sum() / a.sum(),
                mape=100 * ((f - a).abs() / a)[big].mean() if big.any() else np.nan,
                bias=100 * (f.sum() - a.sum()) / a.sum(), n_rows=len(df))


def main():
    con = sqlite3.connect(DATA_DB)
    b, fl = load(con)
    routes = pd.read_sql("SELECT route_id, station_id, direction FROM routes", con)
    con.close()

    frames = pd.concat([build_frame(b, fl, a) for a in ASOF], ignore_index=True)
    train, test = frames[frames.is_test == 0].copy(), frames[frames.is_test == 1].copy()
    print(f"Training rows {len(train):,} (departures to Aug 2025), test rows {len(test):,} "
          f"(Sep 2025 to Feb 2026, {test.flight_id.nunique():,} flights)\n")

    ratio = fit_pickup_ratios(train)
    test["baseline_forecast"] = baseline_forecast(test, ratio, routes)

    gbm = HistGradientBoostingRegressor(max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
                                        min_samples_leaf=50, l2_regularization=1.0,
                                        early_stopping=True, validation_fraction=0.1,
                                        n_iter_no_change=25, random_state=0)
    gbm.fit(train[FEATURES], train.final - train.onhand)               # learn the remaining pickup
    test["gbm_forecast"] = test.onhand + np.clip(gbm.predict(test[FEATURES]), 0, None)
    print(f"Gradient boosting trained for {gbm.n_iter_} rounds.\n")

    rows = []

    def add(analysis, scope, d, models, asof=None):
        for name, col in models:
            rows.append(dict(analysis=analysis, model=name, scope=scope, asof_days=asof,
                             **metrics(d, col)))

    models = (("baseline", "baseline_forecast"), ("gbm", "gbm_forecast"))
    other = test[test.station_id != 2]
    for a in ASOF:
        add("accuracy", "all test flights except Berlin", other[other.lead == a], models, a)
    add("accuracy", "all test flights except Berlin", other, models, None)
    for seg, name in ((1, "Business"), (2, "Leisure"), (3, "VFR")):
        for a in (90, 30):
            add("accuracy", f"segment {name}", other[(other.segment_id == seg) & (other.lead == a)], models, a)
    for sid, name in ((1, "Frankfurt"), (3, "London"), (4, "Paris"), (5, "Milan"), (6, "Madrid")):
        add("accuracy", f"route {name}", other[(other.station_id == sid) & (other.lead == 30)], models, 30)

    # Berlin cold start, by weeks since launch, against Frankfurt in the same calendar weeks.
    test["weeks"] = (test.departure_date - LAUNCH).dt.days // 7
    test["period"] = pd.cut(test.weeks, [-100, 3, 7, 11, 100],
                            labels=["weeks 1-4", "weeks 5-8", "weeks 9-12", "weeks 13-18"])
    ber = test[test.station_id == 2].copy()
    ber["own_history_forecast"] = own_history_forecast(ber)
    fra = test[(test.station_id == 1) & (test.weeks >= 0)]
    # For Berlin the pickup baseline borrows ratios from Frankfurt, Paris and Milan.
    cold = (("pickup baseline", "baseline_forecast"), ("own-history pickup", "own_history_forecast"),
            ("gbm", "gbm_forecast"))
    models_cold = (("pickup baseline", "baseline_forecast"), ("gbm", "gbm_forecast"))
    for a in (90, 30):
        for p in ["weeks 1-4", "weeks 5-8", "weeks 9-12", "weeks 13-18"]:
            add("berlin_cold_start", f"Berlin {p}", ber[(ber.period == p) & (ber.lead == a)], cold, a)
            add("berlin_cold_start", f"Frankfurt {p}", fra[(fra.period == p) & (fra.lead == a)], models_cold, a)
        add("berlin_cold_start", "Berlin all weeks", ber[ber.lead == a], cold, a)
        add("berlin_cold_start", "Frankfurt same weeks", fra[fra.lead == a], models_cold, a)
    m = pd.DataFrame(rows)

    print("## Forecast accuracy on held-out flights (excluding Berlin)\n")
    t = m[(m.analysis == "accuracy") & (m.scope == "all test flights except Berlin")]
    wide = t.pivot(index="asof_days", columns="model", values=["wape", "mape", "bias"])
    out = pd.DataFrame({"Days before departure": [int(i) if i == i else "all" for i in wide.index],
                        "Baseline WAPE %": wide[("wape", "baseline")].values,
                        "GBM WAPE %": wide[("wape", "gbm")].values,
                        "Baseline MAPE %": wide[("mape", "baseline")].values,
                        "GBM MAPE %": wide[("mape", "gbm")].values,
                        "Baseline bias %": wide[("bias", "baseline")].values,
                        "GBM bias %": wide[("bias", "gbm")].values})
    out["WAPE improvement %"] = 100 * (1 - out["GBM WAPE %"] / out["Baseline WAPE %"])
    md(out.sort_values("Days before departure", key=lambda s: s.map(lambda v: -1 if v == "all" else -v)), 1)

    print("By segment and route (WAPE %):\n")
    sub = m[(m.analysis == "accuracy") & (m.scope.str.startswith(("segment", "route")))]
    w = sub.pivot_table(index=["scope", "asof_days"], columns="model", values="wape").reset_index()
    w["improvement %"] = 100 * (1 - w.gbm / w.baseline)
    md(w.rename(columns={"asof_days": "days out", "baseline": "Baseline", "gbm": "GBM"}), 1)

    print("## Berlin cold start (WAPE %, all segments)\n")
    c = m[m.analysis == "berlin_cold_start"].pivot_table(
        index=["asof_days", "scope"], columns="model", values="wape", sort=False).reset_index()
    md(c.rename(columns={"asof_days": "days out"}), 1)

    imp = permutation_importance(gbm, test.sample(5000, random_state=0)[FEATURES],
                                 (test.final - test.onhand).loc[test.sample(5000, random_state=0).index],
                                 scoring="neg_mean_absolute_error", n_repeats=3, random_state=0)
    top = pd.Series(imp.importances_mean, index=FEATURES).sort_values(ascending=False).head(8)
    print("Most important features (increase in error when scrambled):\n")
    md(pd.DataFrame({"Feature": top.index, "Importance": top.values}), 2)

    rc = open_results(["forecast_results", "model_metrics"])
    res = test[["flight_id", "segment_id", "lead", "onhand", "final", "baseline_forecast", "gbm_forecast"]]
    res.columns = ["flight_id", "segment_id", "asof_days", "onhand_pax", "actual_final",
                   "baseline_forecast", "gbm_forecast"]
    res.round(2).to_sql("forecast_results", rc, if_exists="append", index=False)
    m.round(3).to_sql("model_metrics", rc, if_exists="append", index=False)
    rc.commit()
    rc.close()


if __name__ == "__main__":
    main()
