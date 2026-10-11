"""Network Revenue and Inventory (HO): is this seat worth more to a local or a connecting passenger?"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c

SEASONS = ["low", "shoulder", "summer", "christmas"]


def _contribution(cur, station_id):
    ac = c.query("results", "SELECT * FROM agg_contribution")
    ac = c.convert(ac, ["leg_eur", "through_eur", "displacement_eur"], cur)
    return ac if station_id is None else ac[ac.station_id == station_id]


def floor_phrase(lost_conn_floor):
    """A self-contained clause for what the load factor floor does to the connecting feed."""
    if lost_conn_floor <= 0:
        return (f"with a load factor floor the feed is kept whole (about {abs(lost_conn_floor):,.0f} more connecting "
                f"passengers than as flown)")
    return f"with a load factor floor the loss falls to about {lost_conn_floor:,.0f}"


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
                     "Continuous with load factor floor": seg.loc[s, "continuous_lf"],
                     "Connecting share %": 100 * share_c, "Lost connecting pax": lost * share_c,
                     f"Lost network contribution ({cur} k)": lost * share_c * contrib / 1e3,
                     "Lost connecting pax (floor)": lost_lf * share_c})
    return pd.DataFrame(rows)


def render(cur):
    st.title("Network Revenue and Inventory (HO)")
    st.markdown("**Question:** is this seat worth more to a local or a connecting passenger? "
                "**Decision:** sell the local seat now or protect it for connecting demand.")
    names = {v: k for k, v in c.STATION_NAMES.items()}
    scope = st.selectbox("Route", ["All routes"] + list(names))
    sid = None if scope == "All routes" else names[scope]

    # ---- Local vs connecting mix ----
    st.subheader("Local vs connecting mix")
    rmth = c.query("results", "SELECT * FROM agg_route_month")
    if sid is not None:
        rmth = rmth[rmth.station_id == sid]
    mix = rmth.groupby(["month", "traffic_type"]).pax.sum().unstack().fillna(0)
    share = 100 * mix["connecting"] / mix.sum(axis=1)
    fig = go.Figure()
    fig.add_bar(x=mix.index, y=mix["local"], name="Local", marker_color=c.OCHRE)
    fig.add_bar(x=mix.index, y=mix["connecting"], name="Connecting", marker_color=c.TEAL)
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="Passengers per month")
    c.show(fig, f"{share.mean():.0f}% of passengers on {scope.lower() if scope != 'All routes' else 'the network'} "
                f"connect beyond the hub; the share runs from {share.min():.0f}% to {share.max():.0f}% by month.", 320)

    # ---- Revenue per seat by flow ----
    st.subheader("Revenue per seat by flow")
    cabin = st.radio("Cabin", ["Economy", "Business"], horizontal=True)
    cid = 1 if cabin == "Economy" else 2
    ac = _contribution(cur, sid)
    ac = ac[ac.cabin_id == cid]
    loc = ac[ac.beyond_city_id == 0].groupby("season")[["pax", "leg_eur"]].sum()
    con = ac[ac.beyond_city_id > 0].groupby("season")[["pax", "leg_eur", "through_eur", "displacement_eur"]].sum()
    seasons = [s for s in SEASONS if s in loc.index and s in con.index]
    local_rev = [loc.leg_eur[s] / loc.pax[s] for s in seasons]
    conn_rev = [con.leg_eur[s] / con.pax[s] for s in seasons]
    conn_contrib = [(con.through_eur[s] - con.displacement_eur[s]) / con.pax[s] for s in seasons]
    fig = go.Figure()
    fig.add_bar(x=seasons, y=local_rev, name="Local passenger: leg revenue", marker_color=c.OCHRE)
    fig.add_bar(x=seasons, y=conn_rev, name="Connecting passenger: leg revenue (prorated)", marker_color=c.GREY)
    fig.add_bar(x=seasons, y=conn_contrib, name="Connecting passenger: network contribution", marker_color=c.TEAL)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title=f"Average per passenger per leg, {cur}")
    gaps = [cc - lr for cc, lr in zip(conn_contrib, local_rev)]
    k = int(np.argmax(gaps))
    higher = sum(g > 0 for g in gaps)
    c.show(fig, f"In {higher} of {len(seasons)} seasons a connecting passenger's network contribution beats the "
                f"local leg revenue in {cabin}; the gap is widest in {seasons[k]} ({gaps[k]:+,.0f} {cur}).", 360)
    st.caption("Network contribution = through fare minus an estimated displacement cost on the beyond-hub leg. "
               "It is a deliberately simple version, not bid-price logic.")

    # By beyond-hub city
    rows = []
    loc_avg = loc.leg_eur.sum() / loc.pax.sum()
    for city in (1, 2, 3, 4):
        d = ac[ac.beyond_city_id == city][["pax", "leg_eur", "through_eur", "displacement_eur"]].sum()
        contrib = (d.through_eur - d.displacement_eur) / d.pax
        rows.append({"Connecting via": c.CITY_NAMES[city], f"Leg revenue ({cur})": d.leg_eur / d.pax,
                     f"Network contribution ({cur})": contrib, f"Local leg revenue ({cur})": loc_avg,
                     "Seat decision": "Protect for connecting" if contrib > loc_avg else "Sell local seat now"})
    st.dataframe(pd.DataFrame(rows).round(0), hide_index=True, width="stretch")

    # ---- Displacement of connecting feed under continuous pricing ----
    st.subheader("Connecting feed lost under continuous pricing")
    t = feed_table(cur)
    fig = go.Figure()
    fig.add_bar(x=t.Segment, y=t["As flown"] - t["Continuous"], name="Continuous pricing", marker_color=c.TEAL)
    fig.add_bar(x=t.Segment, y=t["As flown"] - t["Continuous with load factor floor"],
                name="Continuous with load factor floor", marker_color=c.GREEN)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="Fewer originating passengers than as flown")
    ll = t[t.Segment.isin(["Leisure", "VFR"])]
    c.show(fig, f"Continuous pricing carries {ll['As flown'].sum() - ll['Continuous'].sum():,.0f} fewer Leisure and VFR "
                f"originating passengers than as flown, about {ll['Lost connecting pax'].sum():,.0f} of them connecting "
                f"(roughly {ll[f'Lost network contribution ({cur} k)'].sum():,.0f}k {cur} of network contribution); "
                f"{floor_phrase(ll['Lost connecting pax (floor)'].sum())}.", 330)
    st.dataframe(t.drop(columns=["Lost connecting pax (floor)"]).round(0), hide_index=True, width="stretch")
    st.caption("Held-out flights, all routes. Lost connecting passengers assume the segment's as-flown connecting "
               "share applies to the passengers priced out.")

    # ---- Directional balance ----
    st.subheader("Directional balance")
    fm = c.query("results", "SELECT * FROM agg_flights_month")
    if sid is not None:
        fm = fm[fm.station_id == sid]
    d = fm.groupby(["month", "direction"]).pax.sum().unstack()
    ratio = d["to_hub"] / d["from_hub"]
    fig = go.Figure(go.Scatter(x=ratio.index, y=ratio, mode="lines+markers", line=dict(color=c.TEAL)))
    fig.add_hline(y=1.0, line_dash="dash", line_color=c.GREY)
    fig.update_yaxes(title="Passengers to the HUB / passengers from it")
    peak, low = ratio.idxmax(), ratio.idxmin()
    c.show(fig, f"Traffic is balanced to within {100 * max(ratio.max() - 1, 1 - ratio.min()):.0f}% in every month; "
                f"it leans toward the HUB most in {peak} ({ratio.max():.2f}) and away from it in {low} ({ratio.min():.2f}).",
           300, legend=False)
    ow = rmth.groupby(["direction", "trip_type"]).pax.sum().unstack()
    ow_share = 100 * ow["OW"] / ow.sum(axis=1)
    st.markdown(f"One-way passengers are {ow_share.get('to_hub', np.nan):.1f}% of passengers toward the HUB and "
                f"{ow_share.get('from_hub', np.nan):.1f}% of those from it.")
