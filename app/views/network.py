"""Network Revenue and Inventory (HO): is this seat worth more to a local or a connecting passenger?"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c

SEASONS = ["low", "shoulder", "summer", "christmas"]


def floor_phrase(lost_conn_floor):
    """A self-contained clause for what the route load factor floor does to the connecting feed."""
    if lost_conn_floor <= 0:
        return (f"with the route load factor floor the feed is kept whole (about {abs(lost_conn_floor):,.0f} more "
                f"connecting passengers than as flown)")
    return f"with the route load factor floor the loss falls to about {lost_conn_floor:,.0f}"


def feed_table(cur):
    """Originating passengers by segment under each policy, with the connecting feed lost vs as flown."""
    seg = c.sim_by(cur, "segment_id").pivot(index="segment_id", columns="policy", values="pax")
    ot = c.query("results", "SELECT * FROM agg_origin_test")
    ot = c.convert(ot, ["through_eur", "displacement_eur"], cur)
    rows = []
    for s, name in c.SEGMENT_NAMES.items():
        o = ot[ot.segment_id == s]
        conn = o[o.traffic_type == "connecting"]
        share_c = conn.pax.sum() / o.pax.sum()
        contrib = (conn.through_eur.sum() - conn.displacement_eur.sum()) / conn.pax.sum()
        lost = seg.loc[s, "observed"] - seg.loc[s, "continuous"]
        lost_lf = seg.loc[s, "observed"] - seg.loc[s, "continuous_lf"]
        rows.append({"Segment": name, "As flown": seg.loc[s, "observed"], "Continuous": seg.loc[s, "continuous"],
                     "Continuous with floor": seg.loc[s, "continuous_lf"],
                     "Connecting share %": 100 * share_c, "Lost connecting pax": lost * share_c,
                     f"Lost network contribution ({cur} k)": lost * share_c * contrib / 1e3,
                     "Lost connecting pax (floor)": lost_lf * share_c})
    return pd.DataFrame(rows)


def _contribution(cur, station_id):
    ac = c.convert(c.query("results", "SELECT * FROM agg_contribution"), ["leg_eur", "through_eur", "displacement_eur"], cur)
    return ac if station_id is None else ac[ac.station_id == station_id]


def render(cur):
    c.hero("Network Revenue and Inventory (HO)",
           "Is this seat worth more to a local or a connecting passenger?", cur)
    names = {v: k for k, v in c.STATION_NAMES.items()}
    with c.panel("Filters"):
        a, b = st.columns(2)
        scope = a.selectbox("Route", ["All routes"] + list(names))
        cabin = b.radio("Cabin", ["Economy", "Business"], horizontal=True)
    sid = None if scope == "All routes" else names[scope]
    cid = 1 if cabin == "Economy" else 2

    rmth = c.query("results", "SELECT * FROM agg_route_month")
    if sid is not None:
        rmth = rmth[rmth.station_id == sid]
    ac = _contribution(cur, sid)
    ac_c = ac[ac.cabin_id == cid]
    feed = feed_table(cur)
    ll = feed
    lost_conn, lost_floor = ll["Lost connecting pax"].sum(), ll["Lost connecting pax (floor)"].sum()

    mix = rmth.groupby("traffic_type").pax.sum()
    conn_share = 100 * mix["connecting"] / mix.sum()
    loc = ac_c[ac_c.beyond_city_id == 0][["pax", "leg_eur"]].sum()
    con = ac_c[ac_c.beyond_city_id > 0][["pax", "leg_eur", "through_eur", "displacement_eur"]].sum()
    local_avg = loc.leg_eur / loc.pax
    contrib_avg = (con.through_eur - con.displacement_eur) / con.pax

    c.kpi_row([
        ("Connecting share of passengers", f"{conn_share:.0f}%", scope if sid else "whole network", c.ROYAL),
        (f"Connecting contribution, {cabin}", f"{contrib_avg:,.0f}", f"{cur} per passenger vs local leg {local_avg:,.0f}",
         c.TEAL, f"{100 * (contrib_avg / local_avg - 1):+.0f}%", contrib_avg >= local_avg),
        ("Connecting pax lost, continuous", f"{lost_conn:,.0f}", "all segments, held-out flights", c.CORAL,
         f"-{lost_conn:,.0f}", False),
        ("Connecting feed with floor", f"{-lost_floor:+,.0f}", "connecting passengers vs as flown", c.AMBER),
    ])

    left, right = st.columns(2)
    with left:
        with c.panel("Local vs connecting passengers by month"):
            mx = rmth.groupby(["month", "traffic_type"]).pax.sum().unstack().fillna(0)
            fig = go.Figure()
            fig.add_bar(x=mx.index, y=mx["local"], name="Local", marker_color=c.ROYAL)
            fig.add_bar(x=mx.index, y=mx["connecting"], name="Connecting", marker_color=c.TEAL)
            fig.update_layout(barmode="stack")
            share = 100 * mx["connecting"] / mx.sum(axis=1)
            c.chart(fig, f"Connecting passengers are {share.min():.0f}% to {share.max():.0f}% of traffic by month.", 300)
    with right:
        with c.panel("Passengers by flow"):
            flows = ac.groupby("beyond_city_id").pax.sum()
            fig = go.Figure(go.Pie(labels=[c.CITY_NAMES[i] for i in flows.index], values=flows.values, hole=0.55,
                                   marker=dict(colors=[c.NAVY, c.ROYAL, c.TEAL, c.CORAL, c.AMBER]),
                                   textinfo="percent", sort=False, textposition="outside",
                                   textfont=dict(color=c.NAVY, size=12)))
            top = flows[flows.index > 0].idxmax()
            c.chart(fig, f"Local travel is {100 * flows[0] / flows.sum():.0f}% of passengers; {c.CITY_NAMES[top]} is the "
                         f"biggest connecting flow.", 300, legend=True)

    left, right = st.columns(2)
    with left:
        with c.panel(f"Value of a seat by season ({cur} per passenger, {cabin})"):
            loc_s = ac_c[ac_c.beyond_city_id == 0].groupby("season")[["pax", "leg_eur"]].sum()
            con_s = ac_c[ac_c.beyond_city_id > 0].groupby("season")[["pax", "leg_eur", "through_eur", "displacement_eur"]].sum()
            seasons = [s for s in SEASONS if s in loc_s.index and s in con_s.index]
            lr = [loc_s.leg_eur[s] / loc_s.pax[s] for s in seasons]
            cc = [(con_s.through_eur[s] - con_s.displacement_eur[s]) / con_s.pax[s] for s in seasons]
            fig = go.Figure()
            fig.add_bar(x=seasons, y=lr, name="Local leg revenue", marker_color=c.ROYAL)
            fig.add_bar(x=seasons, y=cc, name="Connecting network contribution", marker_color=c.TEAL)
            fig.update_layout(barmode="group")
            higher = sum(x > y for x, y in zip(cc, lr))
            c.chart(fig, f"A connecting seat contributes more than a local seat in {higher} of {len(seasons)} seasons "
                         f"in {cabin}.", 300)
    with right:
        with c.panel(f"Seat decision by connecting city ({cur}, {cabin})"):
            rows = []
            for city in (1, 2, 3, 4):
                d = ac_c[ac_c.beyond_city_id == city][["pax", "leg_eur", "through_eur", "displacement_eur"]].sum()
                rows.append((c.CITY_NAMES[city], (d.through_eur - d.displacement_eur) / d.pax))
            fig = go.Figure(go.Bar(x=[r[0] for r in rows], y=[r[1] for r in rows],
                                   marker_color=[c.TEAL if r[1] > local_avg else c.CORAL for r in rows],
                                   text=[f"{r[1]:,.0f}" for r in rows], textposition="outside"))
            fig.add_hline(y=local_avg, line_dash="dash", line_color=c.NAVY, annotation_text="Local leg revenue",
                          annotation_position="top left", annotation_font_color=c.NAVY)
            fig.update_yaxes(range=[0, max(max(r[1] for r in rows), local_avg) * 1.2])
            protect = [r[0] for r in rows if r[1] > local_avg]
            c.chart(fig, ("Protect seats for connecting demand via " + ", ".join(protect) + "; sell the rest locally."
                          if protect else "Local seats are worth more than connecting seats on every flow."),
                    300, legend=False)

    left, right = st.columns(2)
    with left:
        with c.panel("Fewer originating passengers than as flown"):
            fig = go.Figure()
            fig.add_bar(x=feed.Segment, y=feed["As flown"] - feed["Continuous"], name="Continuous", marker_color=c.ROYAL)
            fig.add_bar(x=feed.Segment, y=feed["As flown"] - feed["Continuous with floor"], name="With route floor",
                        marker_color=c.TEAL)
            fig.update_layout(barmode="group")
            c.chart(fig, f"Continuous pricing prices out about {lost_conn:,.0f} connecting passengers; "
                         f"{floor_phrase(lost_floor)}.", 300)
    with right:
        with c.panel("Directional balance (passengers to HUB / from HUB)"):
            fm = c.query("results", "SELECT * FROM agg_flights_month")
            if sid is not None:
                fm = fm[fm.station_id == sid]
            d = fm.groupby(["month", "direction"]).pax.sum().unstack()
            ratio = d["to_hub"] / d["from_hub"]
            fig = go.Figure(go.Scatter(x=ratio.index, y=ratio, mode="lines+markers", line=dict(color=c.ROYAL)))
            fig.add_hline(y=1.0, line_dash="dash", line_color=c.NAVY)
            c.chart(fig, f"Traffic is balanced to within {100 * max(ratio.max() - 1, 1 - ratio.min()):.0f}% in every month; "
                         f"it leans toward the HUB most in {ratio.idxmax()}.", 300, legend=False)

    ow = rmth.groupby(["direction", "trip_type"]).pax.sum().unstack()
    ow_share = 100 * ow["OW"] / ow.sum(axis=1)
    c.notes(
        "**Network contribution** is the through fare minus an estimated displacement cost on the beyond-hub leg. It is a "
        "deliberately simple version, not bid-price logic. Local passengers are compared on leg revenue only.\n\n"
        "**Seat decision.** Where the connecting contribution beats the local leg revenue, protect the seat for connecting "
        "demand; otherwise sell it to the local passenger now.\n\n"
        "**Feed lost.** Compares originating passengers in the pricing replay with as flown. Lost connecting passengers "
        "assume each segment's as-flown connecting share applies to the passengers priced out. Held-out flights, all routes.\n\n"
        f"**Directional balance.** One-way passengers are {ow_share.get('to_hub', np.nan):.1f}% of passengers toward the HUB "
        f"and {ow_share.get('from_hub', np.nan):.1f}% of those from it.")
