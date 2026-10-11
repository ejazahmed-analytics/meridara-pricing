"""Station (GM and Sales - local Market): are we on target, and where are we losing ground?"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c


def render(cur):
    st.title("Station (GM and Sales - local Market)")
    st.markdown("**Question:** are we on target, and where are we losing ground? "
                "**Decision:** where to push promotions, agency or corporate deals.")
    names = {v: k for k, v in c.STATION_NAMES.items()}
    stn = st.selectbox("Station", list(names), index=0, help="Frankfurt is the mature market, Berlin the new route.")
    sid = names[stn]

    pos = c.query("results", "SELECT * FROM agg_pos_month")
    pos = pos[pos.pos_station_id == sid]
    pos = c.convert(pos, ["rev_eur"], cur)
    tg = c.query("data", f"SELECT month, target_revenue_eur FROM revenue_targets WHERE station_id = {sid}")
    tg = c.convert(tg, ["target_revenue_eur"], cur)

    # ---- Revenue vs target ----
    st.subheader("Revenue sold at this station vs target")
    rev = pos.groupby("month").rev_eur.sum().rename("actual").reset_index().merge(tg, on="month")
    fig = go.Figure()
    fig.add_bar(x=rev.month, y=rev.actual / 1e6, name="Revenue sold", marker_color=c.TEAL)
    fig.add_trace(go.Scatter(x=rev.month, y=rev.target_revenue_eur / 1e6, mode="lines", name="Target",
                             line=dict(color=c.OCHRE, width=3)))
    fig.update_yaxes(title=f"{cur} millions per month")
    att = 100 * rev.actual.sum() / rev.target_revenue_eur.sum()
    beat = int((rev.actual >= rev.target_revenue_eur).sum())
    verb = "above" if att >= 100 else "below"
    c.show(fig, f"{stn} sold {c.money(rev.actual.sum(), cur)} against a target of {c.money(rev.target_revenue_eur.sum(), cur)} "
                f"({att:.0f}%, {verb} target), beating the monthly target in {beat} of {len(rev)} months.", 340)
    st.caption("Revenue is sold at this station's point of sale, on all routes, counted in the month each leg "
               "departs. Targets are synthetic.")

    # ---- Origin-sold vs foreign-origin-sold ----
    st.subheader("Origin-sold and foreign-origin-sold revenue")
    sp = pos.groupby(["month", "sold_at_origin"]).rev_eur.sum().unstack().fillna(0)
    fig = go.Figure()
    fig.add_bar(x=sp.index, y=sp[1] / 1e6, name="Origin-sold (journey started here)", marker_color=c.TEAL)
    if 0 in sp:
        fig.add_bar(x=sp.index, y=sp[0] / 1e6, name="Foreign-origin-sold (journey started elsewhere)", marker_color=c.OCHRE)
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title=f"{cur} millions per month")
    share_f = 100 * sp[0].sum() / sp.values.sum() if 0 in sp else 0
    c.show(fig, f"{share_f:.0f}% of the revenue sold here is for journeys that start elsewhere (destination or third "
                f"market sales); the rest is sold at the point where the passenger starts.", 320)

    # ---- Return vs one-way mix ----
    st.subheader("Return vs one-way mix by segment")
    tm = pos.groupby(["segment_id", "trip_type"]).pax.sum().unstack().fillna(0)
    tm_share = 100 * tm.div(tm.sum(axis=1), axis=0)
    fig = go.Figure()
    fig.add_bar(x=[c.SEGMENT_NAMES[i] for i in tm_share.index], y=tm_share["RT"], name="Return", marker_color=c.TEAL)
    fig.add_bar(x=[c.SEGMENT_NAMES[i] for i in tm_share.index], y=tm_share["OW"], name="One way", marker_color=c.OCHRE)
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="% of passengers sold here", range=[0, 100])
    ow_all = 100 * tm["OW"].sum() / tm.values.sum()
    hi = tm_share["OW"].idxmax()
    c.show(fig, f"{ow_all:.0f}% of passengers sold here travel one way, highest for {c.SEGMENT_NAMES[hi]} "
                f"({tm_share['OW'].max():.0f}%).", 300)

    # ---- Price position vs competing hub ----
    st.subheader("Price position vs the competing hub")
    ci = c.query("data", f"""SELECT ci.week_start, AVG(ci.index_value) AS idx FROM competitor_index ci
                             JOIN routes r ON r.route_id = ci.route_id WHERE r.station_id = {sid}
                             GROUP BY ci.week_start ORDER BY ci.week_start""")
    ci = ci[ci.week_start >= (pos.month.min() + "-01")]
    fig = go.Figure(go.Scatter(x=ci.week_start, y=ci.idx, mode="lines", line=dict(color=c.TEAL)))
    fig.add_hline(y=100, line_dash="dash", line_color=c.GREY, annotation_text="Same price", annotation_position="top left")
    fig.update_yaxes(title="Competing hub price index (100 = Meridara)")
    cheaper = 100 * (ci.idx < 100).mean()
    c.show(fig, f"The competing hub was cheaper than Meridara in {cheaper:.0f}% of weeks; its price averaged "
                f"{ci.idx.mean() - 100:+.1f}% against ours.", 300, legend=False)

    # ---- Segment trends ----
    st.subheader("Segment trends")
    sg = pos.groupby(["month", "segment_id"]).pax.sum().unstack().fillna(0)
    fig = go.Figure()
    for s, name in c.SEGMENT_NAMES.items():
        fig.add_trace(go.Scatter(x=sg.index, y=sg[s], mode="lines", name=name, line=dict(color=c.SEGMENT_COLORS[name])))
    fig.update_yaxes(title="Passengers sold per month")
    months = sorted(sg.index)
    last, prev = months[-12:], months[-24:-12]
    chg = {}
    if len(prev) == 12:
        for s, name in c.SEGMENT_NAMES.items():
            chg[name] = 100 * (sg.loc[last, s].sum() / max(sg.loc[prev, s].sum(), 1) - 1)
    if chg:
        worst = min(chg, key=chg.get)
        best = max(chg, key=chg.get)
        c.show(fig, f"Over the latest 12 months {best} sold {chg[best]:+.1f}% against the year before and {worst} "
                    f"{chg[worst]:+.1f}%; push promotions or corporate and agency deals where the gap is widest.", 320)
    else:
        c.show(fig, "Passengers sold by segment since the route launched.", 320)

    # ---- Mature vs launch ----
    st.subheader("Mature market vs launch: Frankfurt and Berlin since the Berlin launch")
    lw = c.query("results", "SELECT * FROM agg_launch_week")
    lw = c.convert(lw, ["rev_eur"], cur)
    lw["lf"] = 100 * lw.pax / lw.seats
    lw["yield"] = lw.rev_eur / lw.pax
    fig = go.Figure()
    for s, color in ((1, c.TEAL), (2, c.OCHRE)):
        d = lw[lw.station_id == s]
        fig.add_trace(go.Scatter(x=d.week + 1, y=d.lf, mode="lines+markers", name=c.STATION_NAMES[s], line=dict(color=color)))
    fig.update_xaxes(title="Week since Berlin launch")
    fig.update_yaxes(title="Load factor %")
    b, f = lw[lw.station_id == 2], lw[lw.station_id == 1]
    first4 = b[b.week < 4]
    last4 = b[b.week >= b.week.max() - 3]
    c.show(fig, f"Berlin's load factor climbed from {100 * first4.pax.sum() / first4.seats.sum():.0f}% in its first four weeks to "
                f"{100 * last4.pax.sum() / last4.seats.sum():.0f}% in the latest four, against "
                f"{100 * f.pax.sum() / f.seats.sum():.0f}% for Frankfurt over the same weeks.", 320)
    fig = go.Figure()
    for s, color in ((1, c.TEAL), (2, c.OCHRE)):
        d = lw[lw.station_id == s]
        fig.add_trace(go.Scatter(x=d.week + 1, y=d["yield"], mode="lines+markers", name=c.STATION_NAMES[s], line=dict(color=color)))
    fig.update_xaxes(title="Week since Berlin launch")
    fig.update_yaxes(title=f"Average revenue per passenger leg, {cur}")
    gap = 100 * (b.rev_eur.sum() / b.pax.sum()) / (f.rev_eur.sum() / f.pax.sum()) - 100
    c.show(fig, f"Berlin earns {gap:+.0f}% per passenger against Frankfurt over the same weeks, reflecting its lower route "
                f"price index, low-season ladder and 90-day introductory discount.", 320)
