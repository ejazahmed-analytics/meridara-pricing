"""Pricing and Revenue Management (HO): is the forecast right, and what price should we offer today?"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c


def _rate(cur, month):
    return 1.0 if cur == "EUR" else float(c.fx_pivot()[cur][month])


def _flags(test):
    """Held-out flights with their booking pace at 30 days compared with normal for the route."""
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
    return tf


def render(cur):
    c.hero("Pricing and Revenue Management (HO)",
           "Is the forecast right, and what price should we offer today?", cur)
    h = c.headline(cur)
    fl = c.flights_table()
    test = fl[fl.is_test == 1]
    mm = c.query("results", "SELECT * FROM model_metrics WHERE analysis = 'accuracy' "
                            "AND scope = 'all test flights except Berlin'").set_index(["model", "asof_days"]).wape
    tf = _flags(test)
    n_flag = int((tf.z.abs() > 2).sum())

    c.kpi_row([
        ("Forecast error, 30 days out", f"{mm['gbm', 30]:.1f}%", f"pickup baseline {mm['baseline', 30]:.1f}%", c.ROYAL,
         f"-{100 * (1 - mm['gbm', 30] / mm['baseline', 30]):.0f}%", True),
        ("Forecast error, 90 days out", f"{mm['gbm', 90]:.1f}%", f"pickup baseline {mm['baseline', 90]:.1f}%", c.TEAL,
         f"-{100 * (1 - mm['gbm', 90] / mm['baseline', 90]):.0f}%", True),
        ("Continuous vs buckets", f"{h['gain_bk']:+.1f}%", f"vs as flown {h['gain']:+.1f}%", c.CORAL),
        ("Flights flagged at 30 days", f"{n_flag}", f"of {len(tf):,} held-out flights", c.AMBER),
    ])

    # ---- Flight picker ----
    names = {v: k for k, v in c.STATION_NAMES.items()}
    with c.panel("Pick a held-out flight"):
        a, b, d = st.columns(3)
        stn = a.selectbox("Route", list(names))
        direction = b.selectbox("Direction", ["Europe to HUB", "HUB to Europe"])
        sel = test[(test.station_id == names[stn]) & (test.direction == ("to_hub" if direction == "Europe to HUB" else "from_hub"))]
        sel = sel.sort_values("departure_date")
        date = d.selectbox("Departure date", sel.departure_date.tolist(), index=min(len(sel) // 2, len(sel) - 1))
    f = sel[sel.departure_date == date].iloc[0]
    fid = int(f.flight_id)
    cap = int(f.capacity_business + f.capacity_economy)

    left, right = st.columns(2)
    # ---- Booking pace vs forecast ----
    with left:
        with c.panel("Booking pace vs forecast"):
            pace = c.query("results", f"SELECT lead, SUM(pax) AS pax FROM flight_pace WHERE flight_id = {fid} GROUP BY lead")
            pace = pace.sort_values("lead", ascending=False)
            fc = c.query("results", f"""SELECT asof_days, SUM(onhand_pax) AS onhand, SUM(baseline_forecast) AS baseline,
                                               SUM(gbm_forecast) AS gbm, SUM(actual_final) AS actual
                                        FROM forecast_results WHERE flight_id = {fid} GROUP BY asof_days ORDER BY asof_days DESC""")
            final = float(fc.actual.iloc[0])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=pace.lead, y=pace.pax, mode="lines", name="Booked so far",
                                     line=dict(color=c.NAVY, width=3)))
            fig.add_trace(go.Scatter(x=fc.asof_days, y=fc.gbm, mode="markers+lines", name="Model forecast",
                                     marker=dict(color=c.ROYAL, size=9), line=dict(color=c.ROYAL, dash="dot")))
            fig.add_trace(go.Scatter(x=fc.asof_days, y=fc.baseline, mode="markers", name="Pickup baseline",
                                     marker=dict(color=c.CORAL, size=9, symbol="diamond")))
            fig.add_hline(y=cap, line_dash="dash", line_color=c.SLATE, annotation_text="Seats",
                          annotation_position="top left", annotation_font_color=c.NAVY)
            fig.update_xaxes(autorange="reversed", title="Days before departure")
            fig.update_yaxes(title="Passengers", rangemode="tozero")
            r30 = fc[fc.asof_days == 30].iloc[0]
            c.chart(fig, f"At 30 days out the model forecast {r30.gbm:.0f} passengers against {final:.0f} flown "
                         f"({100 * (r30.gbm / final - 1):+.1f}%); the baseline {r30.baseline:.0f} "
                         f"({100 * (r30.baseline / final - 1):+.1f}%).", 340)

    # ---- Recommended price ----
    with right:
        with c.panel("Recommended price by booking period"):
            cabin = st.radio("Cabin", ["Economy", "Business"], horizontal=True, label_visibility="collapsed")
            cid = 1 if cabin == "Economy" else 2
            pr = c.query("results", f"SELECT policy, period, price_eur FROM simulation_prices WHERE flight_id = {fid} AND cabin_id = {cid}")
            if pr.empty:
                st.info("No originating demand in this cabin on this flight, so no price was simulated.")
            else:
                pr["price"] = pr.price_eur / _rate(cur, f.month)
                fig = go.Figure()
                for pol in ("buckets", "continuous", "continuous_lf"):
                    g = pr[pr.policy == pol].sort_values("period")
                    dash = "dash" if pol == "continuous_lf" else "solid"
                    fig.add_trace(go.Scatter(x=[c.WINDOWS[p - 1] for p in g.period], y=g.price, mode="lines+markers",
                                             name=c.POLICY_SHORT[pol] + (" (dashed)" if dash == "dash" else ""),
                                             line=dict(color=c.POLICY_COLORS[pol], dash=dash, width=3 if dash == "dash" else 2),
                                             marker=dict(size=7 if dash == "dash" else 9)))
                fig.update_xaxes(type="category", categoryorder="array", categoryarray=c.WINDOWS,
                                 title="Days before departure")
                fig.update_yaxes(title=f"One-way price, {cur}")
                p5 = pr[pr.period == 5].set_index("policy").price
                msg = "Prices offered by each policy in each booking period."
                if {"continuous", "buckets"} <= set(p5.index):
                    msg = (f"At 30-15 days out the system offers {p5['continuous']:,.0f} {cur} (continuous) against "
                           f"{p5['buckets']:,.0f} {cur} from the validated bucket baseline.")
                c.chart(fig, msg, 340)

    left, right = st.columns(2)
    # ---- Buckets vs continuous by route ----
    with left:
        with c.panel("Continuous vs buckets, by route (%)"):
            by = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="revenue_eur")
            g = 100 * (by["continuous"] / by["buckets"] - 1)
            fig = go.Figure(go.Bar(x=[c.STATION_NAMES[i] for i in g.index], y=g.values, marker_color=c.ROYAL,
                                   text=[f"{v:+.1f}%" for v in g.values], textposition="outside"))
            fig.update_yaxes(range=[0, g.max() * 1.25])
            c.chart(fig, f"Highest on {c.STATION_NAMES[g.idxmax()]} ({g.max():+.1f}%), lowest on "
                         f"{c.STATION_NAMES[g.idxmin()]} ({g.min():+.1f}%).", 300, legend=False)
    # ---- OW vs RT ----
    with right:
        with c.panel(f"One-way vs return fares ({cur}, per passenger)"):
            tp = c.convert(c.query("results", "SELECT * FROM agg_trip_pricing"), ["leg_eur", "journey_eur"], cur)
            g = tp.groupby(["segment_id", "trip_type"])[["pax", "leg_eur", "journey_eur"]].sum().reset_index()
            rows = []
            for sid, name in c.SEGMENT_NAMES.items():
                ow = g[(g.segment_id == sid) & (g.trip_type == "OW")].iloc[0]
                rt = g[(g.segment_id == sid) & (g.trip_type == "RT")].iloc[0]
                rows.append(dict(Segment=name, ow=ow.journey_eur / ow.pax, rt_leg=rt.leg_eur / rt.pax, rt=rt.journey_eur / rt.pax))
            d = pd.DataFrame(rows)
            fig = go.Figure()
            fig.add_bar(x=d.Segment, y=d.ow, name="One-way", marker_color=c.CORAL)
            fig.add_bar(x=d.Segment, y=d.rt_leg, name="Return, per leg", marker_color=c.TEAL)
            fig.add_bar(x=d.Segment, y=d.rt, name="Return, whole journey", marker_color=c.ROYAL)
            fig.update_layout(barmode="group")
            c.chart(fig, f"A one-way ticket costs about {100 * (d.ow / d.rt).mean():.0f}% of the return fare; each "
                         f"return leg earns {100 * (d.rt_leg / d.ow).mean():.0f}% of a one-way fare.", 300)

    # ---- Flags ----
    with c.panel("Flags for unusual demand (booking pace at 30 days vs normal for the route)"):
        top = tf.reindex(tf.z.abs().sort_values(ascending=False).index).head(8)
        out = pd.DataFrame({
            "Date": top.departure_date, "Route": top.station_id.map(c.STATION_NAMES),
            "Direction": top.direction.map({"to_hub": "Europe to HUB", "from_hub": "HUB to Europe"}),
            "Pace": np.where(top.z > 0, "Ahead", "Behind"), "Std from normal": top.z.round(1),
            "Reason": top.Reason, "Model forecast": top.gbm.round(0), "Flown": top.actual.round(0)})
        st.dataframe(out, hide_index=True, width="stretch")
        c.takeaway(f"{n_flag} of {len(tf):,} flights were booking more than two standard deviations from normal; "
                   f"review these before accepting the system price.")

    c.notes(
        "**Booking pace vs forecast.** The black line is passengers booked so far; dots are forecasts made at 90, 60, 30, 14 "
        "and 7 days out using only bookings made by then. The model is gradient boosting; the baseline is historical pickup.\n\n"
        "**Recommended price.** The price each policy would offer in each booking period in the pricing replay, in one-way-fare "
        "terms. Continuous prices rise towards departure because willingness to pay rises; bucket prices step up when the "
        "advance-purchase rules close the cheapest classes 14 and 7 days out. Where two lines overlap the dashed one is the "
        "route-floor price. Accept the system price unless the flags show unusual demand; override toward the route-floor price when "
        "volume must be protected.\n\n"
        "**One-way vs return.** The simulated data sets a one-way fare at 60% of the return fare, a stated simplification.\n\n"
        "**Flags.** Booked passengers at 30 days out as a share of seats, compared with the route and direction average "
        "(standard deviations). The reason is a simple rule: new route, running promotion, then calendar event.")
