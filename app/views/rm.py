"""Pricing and Revenue Management (HO): is the forecast right, and what price should we offer today?"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c

WINDOWS = ["330-181", "180-91", "90-61", "60-31", "30-15", "14-8", "7-0"]


def _rate(cur, month):
    return 1.0 if cur == "EUR" else float(c.fx_pivot()[cur][month])


def render(cur):
    st.title("Pricing and Revenue Management (HO)")
    st.markdown("**Question:** is the forecast right, and what price should we offer today? "
                "**Decision:** accept the system price or override it.")

    fl = c.flights_table()
    test = fl[fl.is_test == 1]

    st.subheader("Pick a held-out flight")
    c1, c2, c3 = st.columns(3)
    names = {v: k for k, v in c.STATION_NAMES.items()}
    stn = c1.selectbox("Route", list(names), index=0)
    direction = c2.selectbox("Direction", ["Europe to HUB", "HUB to Europe"])
    sel = test[(test.station_id == names[stn]) & (test.direction == ("to_hub" if direction == "Europe to HUB" else "from_hub"))]
    sel = sel.sort_values("departure_date")
    date = c3.selectbox("Departure date", sel.departure_date.tolist(), index=min(len(sel) // 2, len(sel) - 1))
    f = sel[sel.departure_date == date].iloc[0]
    fid = int(f.flight_id)
    cap = int(f.capacity_business + f.capacity_economy)
    ev = f.event_name if isinstance(f.event_name, str) else "none"
    st.caption(f"Flight {fid}: {cap} seats, {f.season} season, event: {ev}, "
               f"promotion: {f.promo_discount_pct:.0f}%.")

    # ---- Booking pace vs forecast ----
    st.subheader("Booking pace vs forecast")
    pace = c.query("results", f"SELECT lead, SUM(pax) AS pax FROM flight_pace WHERE flight_id = {fid} GROUP BY lead")
    pace = pace.sort_values("lead", ascending=False)
    fc = c.query("results", f"""SELECT asof_days, SUM(onhand_pax) AS onhand, SUM(baseline_forecast) AS baseline,
                                       SUM(gbm_forecast) AS gbm, SUM(actual_final) AS actual
                                FROM forecast_results WHERE flight_id = {fid} GROUP BY asof_days ORDER BY asof_days DESC""")
    final = float(fc.actual.iloc[0])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pace.lead, y=pace.pax, mode="lines", name="Booked so far", line=dict(color=c.SLATE, width=3)))
    fig.add_trace(go.Scatter(x=fc.asof_days, y=fc.gbm, mode="markers+lines", name="Gradient boosting forecast",
                             marker=dict(color=c.TEAL, size=9), line=dict(color=c.TEAL, dash="dot")))
    fig.add_trace(go.Scatter(x=fc.asof_days, y=fc.baseline, mode="markers", name="Pickup baseline forecast",
                             marker=dict(color=c.OCHRE, size=9, symbol="diamond")))
    fig.add_hline(y=cap, line_dash="dash", line_color=c.RED, annotation_text="Seats", annotation_position="top left")
    fig.update_xaxes(autorange="reversed", title="Days before departure")
    fig.update_yaxes(title="Passengers", rangemode="tozero")
    r30 = fc[fc.asof_days == 30].iloc[0]
    e_gbm, e_base = 100 * (r30.gbm / final - 1), 100 * (r30.baseline / final - 1)
    c.show(fig, f"At 30 days out the model forecast {r30.gbm:.0f} passengers against {final:.0f} flown "
                f"({e_gbm:+.1f}%); the pickup baseline forecast {r30.baseline:.0f} ({e_base:+.1f}%).", 380)

    seg = c.query("results", f"""SELECT segment_id, onhand_pax, baseline_forecast, gbm_forecast, actual_final
                                 FROM forecast_results WHERE flight_id = {fid} AND asof_days = 30""")
    seg["Segment"] = seg.segment_id.map(c.SEGMENT_NAMES)
    seg["Error %"] = np.where(seg.actual_final > 0, 100 * (seg.gbm_forecast / seg.actual_final.clip(lower=1) - 1), np.nan)
    st.dataframe(seg[["Segment", "onhand_pax", "gbm_forecast", "baseline_forecast", "actual_final", "Error %"]].rename(
        columns={"onhand_pax": "Booked at 30 days", "gbm_forecast": "Model forecast",
                 "baseline_forecast": "Baseline forecast", "actual_final": "Flown"}).round(1),
        hide_index=True, width="stretch")

    # ---- Recommended price ----
    st.subheader("Recommended price")
    cabin = st.radio("Cabin", ["Economy", "Business"], horizontal=True)
    cid = 1 if cabin == "Economy" else 2
    pr = c.query("results", f"SELECT policy, period, price_eur FROM simulation_prices WHERE flight_id = {fid} AND cabin_id = {cid}")
    if pr.empty:
        st.info("No originating demand was recorded in this cabin on this flight, so no price was simulated.")
    else:
        rate = _rate(cur, f.month)
        pr["price"] = pr.price_eur / rate
        fig = go.Figure()
        for pol in ("buckets", "continuous", "continuous_lf"):
            g = pr[pr.policy == pol].sort_values("period")
            fig.add_trace(go.Scatter(x=[WINDOWS[p - 1] for p in g.period], y=g.price, mode="lines+markers",
                                     name=c.POLICY_LABELS[pol], line=dict(color=c.POLICY_COLORS[pol])))
        fig.update_xaxes(title="Days before departure", categoryorder="array", categoryarray=WINDOWS)
        fig.update_yaxes(title=f"One-way price, {cur}")
        now = st.selectbox("Days before departure now", WINDOWS, index=4)
        p_now = pr[pr.period == WINDOWS.index(now) + 1].set_index("policy").price
        if {"continuous", "buckets"} <= set(p_now.index):
            diff = 100 * (p_now["continuous"] / p_now["buckets"] - 1)
            c.show(fig, f"At {now} days out the system would offer {p_now['continuous']:,.0f} {cur} under continuous "
                        f"pricing against {p_now['buckets']:,.0f} {cur} from the bucket rule ({diff:+.0f}%).", 340)
        else:
            c.show(fig, "Prices by booking period for each policy.", 340)
        flag_text = ("Accept the system price unless the flags below show unusual demand for this route; "
                     "override toward the load-factor-floor price when you need to protect volume.")
        st.markdown(f"**Accept or override?** {flag_text}")

    # ---- Buckets vs continuous ----
    st.subheader("Buckets vs continuous, by route")
    by = c.sim_by(cur, "station_id")
    wide = by.pivot(index="station_id", columns="policy", values="revenue_eur")
    tbl = pd.DataFrame({
        "Route": [c.STATION_NAMES[i] for i in wide.index],
        f"As flown ({cur} m)": wide["observed"] / 1e6, f"Buckets ({cur} m)": wide["buckets"] / 1e6,
        f"Continuous ({cur} m)": wide["continuous"] / 1e6,
        "Continuous vs buckets %": 100 * (wide["continuous"] / wide["buckets"] - 1),
        "Continuous vs as flown %": 100 * (wide["continuous"] / wide["observed"] - 1)})
    st.dataframe(tbl.round(1), hide_index=True, width="stretch")
    best, worst = tbl.loc[tbl["Continuous vs as flown %"].idxmax()], tbl.loc[tbl["Continuous vs as flown %"].idxmin()]
    c.takeaway(f"Continuous pricing gains most on {best.Route} ({best['Continuous vs as flown %']:+.1f}% vs as flown) "
               f"and least on {worst.Route} ({worst['Continuous vs as flown %']:+.1f}%).")
    st.caption("Simplified bucket policy (EMSR-b) vs continuous pricing on the same simulated customers. "
               "Revenue is for originating passengers on their outbound leg, in one-way-fare terms.")

    # ---- OW vs RT ----
    st.subheader("One-way vs return pricing")
    scope = st.selectbox("Scope", ["All routes"] + list(names))
    tp = c.query("results", "SELECT * FROM agg_trip_pricing")
    tp = c.convert(tp, ["leg_eur", "journey_eur"], cur)
    if scope != "All routes":
        tp = tp[tp.station_id == names[scope]]
    g = tp.groupby(["segment_id", "trip_type"])[["pax", "leg_eur", "journey_eur"]].sum().reset_index()
    rows = []
    for sid, name in c.SEGMENT_NAMES.items():
        ow = g[(g.segment_id == sid) & (g.trip_type == "OW")].iloc[0]
        rt = g[(g.segment_id == sid) & (g.trip_type == "RT")].iloc[0]
        rows.append(dict(Segment=name, ow=ow.journey_eur / ow.pax, rt_leg=rt.leg_eur / rt.pax, rt=rt.journey_eur / rt.pax))
    d = pd.DataFrame(rows)
    fig = go.Figure()
    fig.add_bar(x=d.Segment, y=d.ow, name="One-way fare", marker_color=c.OCHRE)
    fig.add_bar(x=d.Segment, y=d.rt_leg, name="Return fare, per flight leg", marker_color=c.SLATE)
    fig.add_bar(x=d.Segment, y=d.rt, name="Return fare, whole journey", marker_color=c.TEAL)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title=f"Average fare per passenger, {cur}")
    ratio = (d.ow / d.rt).mean()
    c.show(fig, f"A one-way ticket costs about {100 * ratio:.0f}% of the return fare on average, and a return "
                f"passenger pays {100 * (d.rt_leg / d.ow).mean():.0f}% of the one-way fare on each leg.", 340)
    st.caption("Fares are for outbound legs, by segment. The one-way fare is set at 60% of the return fare in the "
               "simulated data, a stated simplification.")

    # ---- Flags ----
    st.subheader("Flags for unusual demand")
    tf = c.query("results", """SELECT flight_id, SUM(onhand_pax) AS onhand, SUM(gbm_forecast) AS gbm, SUM(actual_final) AS actual
                               FROM forecast_results WHERE asof_days = 30 GROUP BY flight_id""")
    tf = tf.merge(test[["flight_id", "station_id", "direction", "departure_date", "capacity_business",
                        "capacity_economy", "promo_discount_pct", "event_name"]], on="flight_id")
    tf["fill"] = tf.onhand / (tf.capacity_business + tf.capacity_economy)
    grp = tf.groupby(["station_id", "direction"]).fill
    tf["z"] = (tf.fill - grp.transform("mean")) / grp.transform("std").replace(0, np.nan)
    tf["Reason"] = np.select(
        [tf.station_id == 2, tf.promo_discount_pct > 0, tf.event_name.notna()],
        ["New route, no history", "Promotion running", "Event: " + tf.event_name.fillna("")], "No clear driver")
    scope_flags = tf if scope == "All routes" else tf[tf.station_id == names[scope]]
    top = scope_flags.reindex(scope_flags.z.abs().sort_values(ascending=False).index).head(10)
    out = pd.DataFrame({
        "Date": top.departure_date, "Route": top.station_id.map(c.STATION_NAMES),
        "Direction": top.direction.map({"to_hub": "Europe to HUB", "from_hub": "HUB to Europe"}),
        "Booked at 30 days vs normal": np.where(top.z > 0, "Ahead", "Behind"), "Deviation (std)": top.z.round(1),
        "Reason": top.Reason, "Model forecast": top.gbm.round(0), "Flown": top.actual.round(0)})
    st.dataframe(out, hide_index=True, width="stretch")
    n_flag = int((tf.z.abs() > 2).sum())
    c.takeaway(f"{n_flag} of {len(tf):,} held-out flights were booking more than two standard deviations away "
               f"from normal for their route at 30 days out; these are the ones to review before accepting the system price.")
