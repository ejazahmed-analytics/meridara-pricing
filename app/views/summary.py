"""Analyst summary: where do the three teams disagree, and what should happen?"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c
from views import network


def station_table(cur, s_all=None):
    """Per station: revenue against target in the held-out months, and the change in originating passengers."""
    pos = c.query("results", "SELECT * FROM agg_pos_month WHERE month >= '2025-09' AND pos_station_id <= 6")
    pos = c.convert(pos, ["rev_eur"], cur).groupby(["pos_station_id", "month"]).rev_eur.sum().reset_index()
    tg = c.query("data", "SELECT station_id, month, target_revenue_eur FROM revenue_targets WHERE month >= '2025-09'")
    tg = c.convert(tg, ["target_revenue_eur"], cur)
    m = pos.merge(tg, left_on=["pos_station_id", "month"], right_on=["station_id", "month"]).groupby("station_id")[["rev_eur", "target_revenue_eur"]].sum()
    sb = c.sim_by(cur, "station_id")
    by = sb.pivot(index="station_id", columns="policy", values="pax")
    rev = sb.pivot(index="station_id", columns="policy", values="revenue_eur")
    rows = []
    for sid, name in c.STATION_NAMES.items():
        rows.append({"Station": name, "Revenue vs target %": 100 * m.loc[sid, "rev_eur"] / m.loc[sid, "target_revenue_eur"],
                     "Passengers, continuous vs as flown %": 100 * (by.loc[sid, "continuous"] / by.loc[sid, "observed"] - 1),
                     "Passengers, with floor %": 100 * (by.loc[sid, "continuous_lf"] / by.loc[sid, "observed"] - 1),
                     "Revenue, continuous vs as flown %": 100 * (rev.loc[sid, "continuous"] / rev.loc[sid, "observed"] - 1)})
    return pd.DataFrame(rows)


def _team(color, name, number, text):
    st.markdown(f'<div class="team" style="border-top-color:{color}"><div class="team-name">{name}</div>'
                f'<div class="team-number">{number}</div><div class="team-text">{text}</div></div>',
                unsafe_allow_html=True)


def render(cur):
    c.hero("Analyst summary", "Where do the three teams disagree, and what should happen?", cur)
    h = c.headline(cur)
    s, obs, bk, ct, lf = h["s"], h["obs"], h["bk"], h["ct"], h["lf"]
    feed = network.feed_table(cur)
    ll = feed[feed.Segment.isin(["Leisure", "VFR"])]
    lost_pax = ll["As flown"].sum() - ll["Continuous"].sum()
    lost_conn, lost_conn_lf = ll["Lost connecting pax"].sum(), ll["Lost connecting pax (floor)"].sum()
    lost_contrib = ll[f"Lost network contribution ({cur} k)"].sum() * 1e3
    seg_pax = c.sim_by(cur, "segment_id").pivot(index="segment_id", columns="policy", values="revenue_eur")
    seg_gain = (seg_pax["continuous"] / seg_pax["buckets"] - 1).sort_values(ascending=False)
    top_names = " and ".join(c.SEGMENT_NAMES[i] for i in seg_gain.index[:2])
    st_tbl = station_table(cur)
    below = st_tbl[st_tbl["Revenue vs target %"] < 100]
    below_txt = ", ".join(f"{r.Station} ({r['Revenue vs target %']:.0f}%)" for _, r in below.iterrows()) or "none"

    st.markdown("#### The main conflict")
    a, b, d = st.columns(3)
    with a:
        _team(c.ROYAL, "Pricing and Revenue Management (HO)", f"{h['gain_bk']:+.1f}% vs buckets",
              f"Wants continuous pricing: {c.money(ct.revenue, cur)} against {c.money(bk.revenue, cur)} for the validated "
              f"bucket baseline on the same customers, mostly from higher {top_names} fares. Against as flown it is "
              f"{h['gain']:+.1f}%.")
    with b:
        _team(c.TEAL, "Network Revenue and Inventory (HO)", f"{lost_conn:,.0f} connecting pax lost",
              f"Worried about feed: {lost_pax:,.0f} fewer Leisure and VFR passengers, about {lost_conn:,.0f} connecting, "
              f"worth roughly {c.money(lost_contrib, cur, 'k')} of network contribution.")
    with d:
        _team(c.CORAL, "Station (GM and Sales - local Market)", f"{h['pax_ct']:+.1f}% volume",
              f"Load factor {ct.load_factor:.0f}% vs {obs.load_factor:.0f}% as flown. Stations below target in the "
              f"held-out months: {below_txt}.")
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)

    order = ["observed", "buckets", "continuous", "continuous_lf"]
    rows = [c.policy_row(s, "base", p) for p in order]
    labels = [c.POLICY_SHORT[p] for p in order]
    colors = [c.POLICY_COLORS[p] for p in order]
    left, right = st.columns(2)
    with left:
        with c.panel(f"Revenue, four policies ({cur} millions)"):
            fig = go.Figure(go.Bar(x=labels, y=[r.revenue / 1e6 for r in rows], marker_color=colors,
                                   text=[f"{r.revenue / 1e6:,.1f}<br>{100 * (r.revenue / obs.revenue - 1):+.1f}%" if p != "observed"
                                         else f"{r.revenue / 1e6:,.1f}" for r, p in zip(rows, order)],
                                   textposition="outside"))
            fig.update_yaxes(range=[0, max(r.revenue for r in rows) / 1e6 * 1.25])
            c.chart(fig, f"Against the validated bucket baseline the route floor earns {h['gain_lf_bk']:+.1f}% and continuous "
                         f"pricing {h['gain_bk']:+.1f}%; as flown is shown for reference.", 310, legend=False)
    with right:
        with c.panel("Load factor, four policies (%)"):
            fig = go.Figure(go.Bar(x=labels, y=[r.load_factor for r in rows], marker_color=colors,
                                   text=[f"{r.load_factor:.1f}<br>{r.pax:,.0f} pax" for r in rows], textposition="outside"))
            fig.update_yaxes(range=[0, 118])
            c.chart(fig, f"The bucket baseline holds {bk.load_factor:.0f}% (as flown {obs.load_factor:.0f}%); continuous pricing "
                         f"{ct.load_factor:.0f}% and the route floor {lf.load_factor:.0f}%.", 310, legend=False)

    st.markdown(
        f'<div class="callout"><div class="callout-title">Recommendation</div>'
        f'<div class="callout-main">Continuous pricing with a route-level load factor floor</div>'
        f'Revenue {h["gain_lf_bk"]:+.1f}% against the bucket rule ({c.money(lf.revenue, cur)} vs {c.money(bk.revenue, cur)}) '
        f'at a load factor of {lf.load_factor:.1f}%, level with as flown ({obs.load_factor:.1f}%). Without the floor about '
        f'{lost_conn:,.0f} connecting passengers are lost; {network.floor_phrase(lost_conn_lf)}. Against as flown revenue is '
        f'{h["gain_lf"]:+.1f}%.</div>',
        unsafe_allow_html=True)
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)

    with st.expander("How to read this"):
        st.markdown(
            "**The conflict.** Pricing wants the highest revenue, Network wants to keep connecting feed, and the stations "
            "want volume against target. A route-level load factor floor makes each route keep at least its as-flown "
            "average load factor over the six held-out months; individual flights can vary.\n\n"
            f"**The baseline.** The bucket policy is calibrated on the training period so that replaying it reproduces as-flown "
            f"results (revenue {c.calibration()['training']['rev_gap']:+.1f}%, load factor {c.calibration()['training']['lf_gap']:+.1f} "
            f"points). The comparison is against that validated baseline, on the same customers and rules.\n\n"
            "**Why the floor can earn more.** The unconstrained price rule re-solves one price at a time and leaves seats "
            "empty; adding a value per passenger acts like a seat value and fills seats at a better price. It uses the "
            "same price sensitivity estimates, so it is still conditional on them.")
        mm = c.query("results", "SELECT * FROM model_metrics WHERE analysis = 'berlin_cold_start' AND asof_days = 90 AND model = 'gbm'").set_index("scope").wape
        sim_b = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="revenue_eur")
        ber_gain = 100 * (sim_b.loc[2, "continuous"] / sim_b.loc[2, "buckets"] - 1)
        oth = sim_b.drop(index=2).sum()
        oth_gain = 100 * (oth["continuous"] / oth["buckets"] - 1)
        ela = s[s.scenario == "elastic_world"].set_index("policy").revenue
        st.markdown("**Other conflicts in the data**")
        st.dataframe(pd.DataFrame([
            {"Conflict": "Berlin: system price vs weak forecast", "Teams": "RM vs Station",
             "Evidence": f"First-month forecast error {mm['Berlin weeks 1-4']:.0f}% vs {mm['Frankfurt weeks 1-4']:.0f}% for Frankfurt; "
                         f"gain from continuous pricing {ber_gain:+.1f}% vs {oth_gain:+.1f}% elsewhere.",
             "Resolution": "Keep bucket control with borrowed pickup ratios for the first eight weeks."},
            {"Conflict": "Price sensitivity may be higher than estimated", "Teams": "RM vs leadership",
             "Evidence": f"At the high-sensitivity end of the range, continuous pricing earns {100 * (ela['continuous'] / ela['buckets'] - 1):+.1f}% vs buckets.",
             "Resolution": "Roll out route by route; re-estimate sensitivity each quarter."},
            {"Conflict": "Stations below target vs higher prices", "Teams": "Station vs RM", "Evidence": below_txt,
             "Resolution": "Apply the floor first on stations below target."}]), hide_index=True, width="stretch")
        st.markdown("**Station view of the options**")
        st.dataframe(st_tbl.round(1), hide_index=True, width="stretch")
        st.caption("Revenue against target is for revenue sold at each station's point of sale in the six held-out months. "
                   "Passenger and revenue changes are for the station's routes in the pricing replay.")
    st.markdown(f'<div class="footer">{c.SHORT_DISCLAIMER}</div>', unsafe_allow_html=True)
