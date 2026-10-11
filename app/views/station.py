"""Station (GM and Sales - local Market): are we on target, and where are we losing ground?"""
import plotly.graph_objects as go
import streamlit as st

import common as c


def render(cur):
    c.hero("Station (GM and Sales - local Market)", "Are we on target, and where are we losing ground?", cur)
    names = {v: k for k, v in c.STATION_NAMES.items()}
    with c.panel("Filters"):
        stn = st.selectbox("Station", list(names), help="Frankfurt is the mature market, Berlin the new route.")
    sid = names[stn]
    plan = "launch plan" if sid == 2 else "target"

    pos = c.convert(c.query("results", "SELECT * FROM agg_pos_month"), ["rev_eur"], cur)
    pos = pos[pos.pos_station_id == sid]
    tg = c.convert(c.query("data", f"SELECT month, target_revenue_eur FROM revenue_targets WHERE station_id = {sid}"),
                   ["target_revenue_eur"], cur)
    rev = pos.groupby("month").rev_eur.sum().rename("actual").reset_index().merge(tg, on="month")
    att = 100 * rev.actual.sum() / rev.target_revenue_eur.sum()
    beat = int((rev.actual >= rev.target_revenue_eur).sum())
    sp = pos.groupby(["month", "sold_at_origin"]).rev_eur.sum().unstack().fillna(0)
    origin_share = 100 * sp[1].sum() / sp.values.sum()
    tm = pos.groupby(["segment_id", "trip_type"]).pax.sum().unstack().fillna(0)
    ow_all = 100 * tm["OW"].sum() / tm.values.sum()

    c.kpi_row([
        (f"Revenue vs {plan}", f"{att:.0f}%", f"{c.money(rev.actual.sum(), cur)} vs {c.money(rev.target_revenue_eur.sum(), cur)}",
         c.ROYAL, f"{att - 100:+.0f}%", att >= 100),
        (f"Months beating {plan}", f"{beat} of {len(rev)}", "monthly revenue sold here", c.TEAL),
        ("Origin-sold revenue", f"{origin_share:.0f}%", "journey started at this station", c.CORAL),
        ("One-way passengers", f"{ow_all:.0f}%", "of passengers sold here", c.AMBER),
    ])

    left, right = st.columns(2)
    with left:
        with c.panel(f"Revenue sold vs {plan} ({cur} millions per month)"):
            fig = go.Figure()
            fig.add_bar(x=rev.month, y=rev.actual / 1e6, name="Revenue sold", marker_color=c.ROYAL)
            fig.add_trace(go.Scatter(x=rev.month, y=rev.target_revenue_eur / 1e6, mode="lines", name=plan.capitalize(),
                                     line=dict(color=c.AMBER, width=3)))
            worst = (rev.actual / rev.target_revenue_eur).idxmin()
            c.chart(fig, f"{stn} is at {att:.0f}% of {plan} and beat it in {beat} of {len(rev)} months; the biggest miss "
                         f"was {rev.month[worst]} ({100 * (rev.actual[worst] / rev.target_revenue_eur[worst] - 1):+.0f}%).", 320)
    with right:
        with c.panel("Origin-sold vs foreign-origin-sold revenue"):
            tot = {"Origin-sold": sp[1].sum(), "Foreign-origin-sold": sp[0].sum() if 0 in sp else 0}
            fig = go.Figure(go.Pie(labels=list(tot), values=list(tot.values()), hole=0.6,
                                   marker=dict(colors=[c.ROYAL, c.CORAL]), textinfo="percent",
                                   textposition="outside", textfont=dict(color=c.NAVY, size=12)))
            c.chart(fig, f"{100 - origin_share:.0f}% of revenue sold here is for journeys that start elsewhere.", 320, legend=True)

    left, right = st.columns(2)
    with left:
        with c.panel("Return vs one-way passengers by segment (%)"):
            share = 100 * tm.div(tm.sum(axis=1), axis=0)
            seg = [c.SEGMENT_NAMES[i] for i in share.index]
            fig = go.Figure()
            fig.add_bar(x=seg, y=share["RT"], name="Return", marker_color=c.ROYAL)
            fig.add_bar(x=seg, y=share["OW"], name="One way", marker_color=c.CORAL)
            fig.update_layout(barmode="stack")
            hi = share["OW"].idxmax()
            c.chart(fig, f"One-way travel is highest for {c.SEGMENT_NAMES[hi]} ({share['OW'].max():.0f}%).", 300)
    with right:
        with c.panel("Price position vs the competing hub"):
            ci = c.query("data", f"""SELECT ci.week_start, AVG(ci.index_value) AS idx FROM competitor_index ci
                                     JOIN routes r ON r.route_id = ci.route_id WHERE r.station_id = {sid}
                                     GROUP BY ci.week_start ORDER BY ci.week_start""")
            ci = ci[ci.week_start >= pos.month.min() + "-01"]
            fig = go.Figure(go.Scatter(x=ci.week_start, y=ci.idx, mode="lines", line=dict(color=c.ROYAL)))
            fig.add_hline(y=100, line_dash="dash", line_color=c.NAVY, annotation_text="Same price",
                          annotation_position="top left", annotation_font_color=c.NAVY)
            fig.update_yaxes(title="Competitor price index")
            c.chart(fig, f"The competing hub was cheaper than Meridara in {100 * (ci.idx < 100).mean():.0f}% of weeks "
                         f"(index {ci.idx.mean():.0f} on average).", 300, legend=False)

    left, right = st.columns(2)
    with left:
        with c.panel("Passengers sold by segment (per month)"):
            sg = pos.groupby(["month", "segment_id"]).pax.sum().unstack().fillna(0)
            fig = go.Figure()
            for s_, name in c.SEGMENT_NAMES.items():
                fig.add_trace(go.Scatter(x=sg.index, y=sg[s_], mode="lines", name=name, line=dict(color=c.SEGMENT_COLORS[name])))
            months = sorted(sg.index)
            last, prev = months[-12:], months[-24:-12]
            if len(prev) == 12:
                chg = {n: 100 * (sg.loc[last, s_].sum() / max(sg.loc[prev, s_].sum(), 1) - 1) for s_, n in c.SEGMENT_NAMES.items()}
                worst, best = min(chg, key=chg.get), max(chg, key=chg.get)
                msg = (f"Latest 12 months: {best} {chg[best]:+.1f}%, {worst} {chg[worst]:+.1f}% vs the year before; "
                       f"push promotions and deals toward {worst}.")
            else:
                msg = "Passengers sold by segment since the route launched."
            c.chart(fig, msg, 300)
    lw = c.convert(c.query("results", "SELECT * FROM agg_launch_week"), ["rev_eur"], cur)
    lw["lf"] = 100 * lw.pax / lw.seats
    lw["yield"] = lw.rev_eur / lw.pax
    b, f = lw[lw.station_id == 2], lw[lw.station_id == 1]
    with right:
        with c.panel("Launch vs mature: load factor by week since the Berlin launch (%)"):
            fig = go.Figure()
            for s_, color in ((1, c.ROYAL), (2, c.CORAL)):
                d = lw[lw.station_id == s_]
                fig.add_trace(go.Scatter(x=d.week + 1, y=d.lf, mode="lines+markers", name=c.STATION_NAMES[s_], line=dict(color=color)))
            fig.update_xaxes(title="Week since Berlin launch")
            first4, last4 = b[b.week < 4], b[b.week >= b.week.max() - 3]
            c.chart(fig, f"Berlin climbed from {100 * first4.pax.sum() / first4.seats.sum():.0f}% to "
                         f"{100 * last4.pax.sum() / last4.seats.sum():.0f}% load factor; Frankfurt held "
                         f"{100 * f.pax.sum() / f.seats.sum():.0f}%.", 300)
    with c.panel(f"Launch vs mature: average revenue per passenger leg ({cur})"):
        fig = go.Figure()
        for s_, color in ((1, c.ROYAL), (2, c.CORAL)):
            d = lw[lw.station_id == s_]
            fig.add_trace(go.Scatter(x=d.week + 1, y=d["yield"], mode="lines+markers", name=c.STATION_NAMES[s_], line=dict(color=color)))
        fig.update_xaxes(title="Week since Berlin launch")
        gap = 100 * (b.rev_eur.sum() / b.pax.sum()) / (f.rev_eur.sum() / f.pax.sum()) - 100
        c.chart(fig, f"Berlin earns {gap:+.0f}% per passenger against Frankfurt over the same weeks, from its lower price "
                     f"index, low-season ladder and 90-day introductory discount.", 300)

    c.notes(
        "**Revenue sold** is revenue sold at this station's point of sale, on all routes, counted in the month each leg departs. "
        "**Targets** are synthetic budgets set in advance for each financial year (April to March): the same month last year "
        "times a station growth factor (+5% to +8%). The first year uses a planned seasonal curve scaled to an annual budget built "
        "from capacity, planned load factor and planned fares. Berlin is judged against a launch plan (scheduled flights, a load "
        "factor ramp and introductory fares). No target uses the actual revenue of its own month, so misses appear around moving "
        "holidays, promotions and competitor moves.\n\n"
        "**Origin-sold vs foreign-origin-sold.** Origin-sold means the journey started at this station; foreign-origin-sold means "
        "it started elsewhere and was sold here (destination or third market).\n\n"
        "**Price position.** The competing hub's weekly price index on this station's routes: 100 means the same price as "
        "Meridara, above 100 means the competitor is dearer.\n\n"
        "**Launch vs mature.** Frankfurt and Berlin compared week by week from the Berlin launch on 26 October 2025.")
