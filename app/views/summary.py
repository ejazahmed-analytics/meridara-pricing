"""Analyst summary: where do the three teams disagree, and what should happen?"""
import pandas as pd
import streamlit as st

import common as c
from views import network


def station_table(cur, s_all):
    """Per station: revenue against target in the held-out months, and the change in originating passengers."""
    pos = c.query("results", "SELECT * FROM agg_pos_month WHERE month >= '2025-09' AND pos_station_id <= 6")
    pos = c.convert(pos, ["rev_eur"], cur).groupby(["pos_station_id", "month"]).rev_eur.sum().reset_index()
    tg = c.query("data", "SELECT station_id, month, target_revenue_eur FROM revenue_targets WHERE month >= '2025-09'")
    tg = c.convert(tg, ["target_revenue_eur"], cur)
    m = pos.merge(tg, left_on=["pos_station_id", "month"], right_on=["station_id", "month"]).groupby("station_id")[["rev_eur", "target_revenue_eur"]].sum()
    by = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="pax")
    rev = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="revenue_eur")
    rows = []
    for sid, name in c.STATION_NAMES.items():
        rows.append({"Station": name, "Revenue vs target %": 100 * m.loc[sid, "rev_eur"] / m.loc[sid, "target_revenue_eur"],
                     "Passengers, continuous vs as flown %": 100 * (by.loc[sid, "continuous"] / by.loc[sid, "observed"] - 1),
                     "Passengers, with load factor floor %": 100 * (by.loc[sid, "continuous_lf"] / by.loc[sid, "observed"] - 1),
                     "Revenue, continuous vs as flown %": 100 * (rev.loc[sid, "continuous"] / rev.loc[sid, "observed"] - 1)})
    return pd.DataFrame(rows)


def render(cur):
    st.title("Analyst summary")
    st.markdown("**Question:** where do the three teams disagree, and what should happen? "
                "**Decision:** one recommendation leadership can act on.")

    s = c.sim_summary(cur)
    obs, bk, ct, lf = (c.policy_row(s, "base", p) for p in ("observed", "buckets", "continuous", "continuous_lf"))
    gain = 100 * (ct.revenue / obs.revenue - 1)
    gain_lf = 100 * (lf.revenue / obs.revenue - 1)
    kept = 100 * (lf.revenue - obs.revenue) / (ct.revenue - obs.revenue)
    pax_chg = 100 * (ct.pax / obs.pax - 1)
    pax_chg_lf = 100 * (lf.pax / obs.pax - 1)
    feed = network.feed_table(cur)
    ll = feed[feed.Segment.isin(["Leisure", "VFR"])]
    lost_pax = ll["As flown"].sum() - ll["Continuous"].sum()
    lost_conn = ll["Lost connecting pax"].sum()
    lost_contrib = ll[f"Lost network contribution ({cur} k)"].sum() * 1e3
    lost_conn_lf = ll["Lost connecting pax (floor)"].sum()
    st_tbl = station_table(cur, s)
    below = st_tbl[st_tbl["Revenue vs target %"] < 100]

    st.subheader("The main conflict")
    a, b, d = st.columns(3)
    with a:
        st.markdown("**Pricing and Revenue Management**")
        c.metric_card("Revenue vs as flown", c.pct(gain, True),
                      f"{c.money(ct.revenue, cur)} vs {c.money(obs.revenue, cur)}")
        st.markdown("Wants continuous pricing: it earns more on the same demand by raising prices for customers "
                    "who are less price sensitive, mainly Business.")
    with b:
        st.markdown("**Network Revenue and Inventory**")
        c.metric_card("Connecting feed lost", f"{lost_conn:,.0f} pax",
                      f"Leisure and VFR; about {c.money(lost_contrib, cur, 'k')} of network contribution")
        st.markdown(f"Worried about feed: {lost_pax:,.0f} fewer Leisure and VFR originating passengers, "
                    f"{lost_conn:,.0f} of them connecting, who are worth more to the network than their leg fare.")
    with d:
        st.markdown("**Station (GM and Sales)**")
        c.metric_card("Volume vs as flown", c.pct(pax_chg, True),
                      f"load factor {ct.load_factor:.1f}% vs {obs.load_factor:.1f}%")
        names = ", ".join(f"{r.Station} ({r['Revenue vs target %']:.0f}%)" for _, r in below.iterrows()) or "none"
        st.markdown(f"Volume falls while stations below target need sales: {names}. A volume loss is hard to "
                    f"defend in the market when the target is already missed.")

    st.markdown(f'<div class="card" style="border-top-color:{c.GREEN};margin-top:0.8rem">'
                f'<div class="card-label">Recommendation</div>'
                f'<div class="card-value" style="font-size:1.2rem">Continuous pricing with a load factor floor at the as-flown level</div>'
                f'<div class="card-note">Revenue {c.pct(gain_lf, True)} vs as flown ({c.money(lf.revenue, cur)}), '
                f'keeping {kept:.0f}% of the full gain; load factor {lf.load_factor:.1f}% (as flown {obs.load_factor:.1f}%); '
                f'passengers {c.pct(pax_chg_lf, True)}; without the floor about {lost_conn:,.0f} connecting passengers are lost, '
                f'{network.floor_phrase(lost_conn_lf)}.</div></div>', unsafe_allow_html=True)
    c.takeaway("The floor gives up about half of the revenue gain to protect feed and station volume, which is the "
               "trade-off leadership has to accept or reject.")

    st.subheader("The four options on the same flights")
    order = ["observed", "buckets", "continuous", "continuous_lf"]
    tbl = pd.DataFrame([{
        "Policy": c.POLICY_LABELS[p], f"Revenue ({cur} m)": c.policy_row(s, "base", p).revenue / 1e6,
        "vs as flown %": 100 * (c.policy_row(s, "base", p).revenue / obs.revenue - 1),
        "Load factor %": c.policy_row(s, "base", p).load_factor, "Passengers": c.policy_row(s, "base", p).pax,
        f"Average fare ({cur})": c.policy_row(s, "base", p).avg_fare} for p in order])
    st.dataframe(tbl.round(1), hide_index=True, width="stretch")

    st.subheader("Other conflicts in the data")
    mm = c.query("results", "SELECT * FROM model_metrics WHERE analysis = 'berlin_cold_start' AND asof_days = 90 AND model = 'gbm'")
    mm = mm.set_index("scope").wape
    sim_b = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="revenue_eur")
    ber_gain = 100 * (sim_b.loc[2, "continuous"] / sim_b.loc[2, "buckets"] - 1)
    oth = sim_b.drop(index=2).sum()
    oth_gain = 100 * (oth["continuous"] / oth["buckets"] - 1)
    ela = s[(s.scenario == "elastic_world")].set_index("policy").revenue
    ela_chg = 100 * (ela["continuous"] / ela["buckets"] - 1)
    rows = [
        {"Conflict": "Berlin: system price vs weak forecast", "Teams": "RM vs Station",
         "Evidence": f"Berlin's first-month forecast error is {mm['Berlin weeks 1-4']:.0f}% against {mm['Frankfurt weeks 1-4']:.0f}% for "
                     f"Frankfurt, and its gain from continuous pricing is {ber_gain:+.1f}% against {oth_gain:+.1f}% elsewhere.",
         "Recommended resolution": "Keep bucket control with borrowed pickup ratios for the first eight weeks, then switch."},
        {"Conflict": "Price sensitivity may be higher than estimated", "Teams": "RM vs leadership",
         "Evidence": f"If customers are at the high end of the estimated range, continuous pricing earns {ela_chg:+.1f}% "
                     f"against buckets.",
         "Recommended resolution": "Roll out route by route and re-estimate sensitivity from live promotions each quarter."},
        {"Conflict": "Stations below target vs higher prices", "Teams": "Station vs RM",
         "Evidence": "; ".join(f"{r.Station}: {r['Revenue vs target %']:.0f}% of target, "
                               f"{r['Passengers, continuous vs as flown %']:+.0f}% passengers" for _, r in below.iterrows()) or "all stations at or above target",
         "Recommended resolution": "Apply the load factor floor first on stations below target; relax it as they recover."},
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.subheader("Station view of the options")
    st.dataframe(st_tbl.round(1), hide_index=True, width="stretch")
    st.caption("Revenue against target is for revenue sold at each station's point of sale in the six held-out months. "
               "Passenger and revenue changes are for the station's routes in the pricing replay.")
