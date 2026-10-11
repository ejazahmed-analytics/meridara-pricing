"""Data Story: the case from question to recommendation. Every number comes from the databases."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import common as c
from views import network, summary


def _metric(mm, model, scope, lead):
    row = mm[(mm.model == model) & (mm.scope == scope) & (mm.asof_days == lead)]
    return float(row.wape.iloc[0])


def _insight(kicker, title, text, color):
    st.markdown(f'<div class="insight" style="border-top-color:{color}"><div class="insight-kicker">{kicker}</div>'
                f'<div class="insight-title">{title}</div><div class="insight-text">{text}</div></div>',
                unsafe_allow_html=True)


def _callout(kind, title, text):
    st.markdown(f'<div class="co co-{kind}"><b>{title}</b><br>{text}</div>', unsafe_allow_html=True)


def render(cur):
    h = c.headline(cur)
    s, obs, bk, ct, lf = h["s"], h["obs"], h["bk"], h["ct"], h["lf"]
    fl = c.flights_table()
    first, last = fl.departure_date.min(), fl.departure_date.max()
    test_first, n_test = fl[fl.is_test == 1].departure_date.min(), int((fl.is_test == 1).sum())

    mm = c.query("results", "SELECT * FROM model_metrics")
    acc = mm[(mm.analysis == "accuracy") & (mm.scope == "all test flights except Berlin")]
    cold = mm[mm.analysis == "berlin_cold_start"]
    sens = c.query("results", "SELECT * FROM sensitivity_estimates WHERE parameter = 'price'")
    low = sens[sens["sample"] == "low-season flights"].set_index("segment_id")
    g90, b90 = _metric(acc, "gbm", "all test flights except Berlin", 90), _metric(acc, "baseline", "all test flights except Berlin", 90)
    ber1, fra1 = _metric(cold, "gbm", "Berlin weeks 1-4", 90), _metric(cold, "gbm", "Frankfurt weeks 1-4", 90)

    pos = c.convert(c.query("results", "SELECT * FROM agg_pos_month"), ["rev_eur"], "EUR").groupby("pos_station_id").rev_eur.sum()
    tot = pos.sum()
    hub_share, beyond_share = 100 * pos.get(11, 0) / tot, 100 * pos[[7, 8, 9, 10]].sum() / tot
    europe_share = 100 * pos[[1, 2, 3, 4, 5, 6]].sum() / tot
    rt = c.query("results", "SELECT segment_id, trip_type, SUM(pax) AS pax FROM agg_route_month WHERE leg_seq = 1 "
                            "GROUP BY segment_id, trip_type").pivot(index="segment_id", columns="trip_type", values="pax")
    rt_share = 100 * rt["RT"] / rt.sum(axis=1)
    fb = c.query("data", "SELECT ladder, price_point_eur FROM fare_buckets WHERE route_id = 1 AND cabin_id = 1 AND class_rank = 10").set_index("ladder").price_point_eur
    ladder_scale = fb["standard"] / fb["low"]
    feed = network.feed_table(cur)
    ll = feed[feed.Segment.isin(["Leisure", "VFR"])]
    lost_conn, lost_conn_lf = ll["Lost connecting pax"].sum(), ll["Lost connecting pax (floor)"].sum()
    st_tbl = summary.station_table(cur)
    below = st_tbl[st_tbl["Revenue vs target %"] < 100]
    ela = s[s.scenario == "elastic_world"].set_index("policy").revenue
    ela_chg = 100 * (ela["continuous"] / ela["buckets"] - 1)

    c.hero("Data Story", "The case from question to recommendation", cur)

    # Story hero with four big numbers
    st.markdown(
        f'<div class="story-hero"><div class="story-kicker">MERIDARA &middot; DATA STORY &middot; HELD-OUT FLIGHTS, SEP 2025 TO FEB 2026</div>'
        f'<div class="story-title">Continuous pricing beats the bucket rule, and a route load factor floor keeps the network whole</div>'
        f'<div class="story-intro">A replay of {n_test:,} simulated flights under fare buckets and continuous pricing, '
        f'seen through three lenses: pricing, network and station.</div>'
        f'<div class="story-stats">'
        f'<div><div class="story-num">{h["gain_bk"]:+.1f}%</div><div class="story-cap">Continuous vs buckets, same customers</div></div>'
        f'<div><div class="story-num">{h["gain_lf_bk"]:+.1f}%</div><div class="story-cap">Route floor vs buckets, at the as-flown load factor</div></div>'
        f'<div><div class="story-num">{h["gain"]:+.1f}%</div><div class="story-cap">Continuous vs as flown (an upper reference)</div></div>'
        f'<div><div class="story-num">{g90:.0f}%</div><div class="story-cap">Forecast error at 90 days (baseline {b90:.0f}%)</div></div>'
        f'</div></div>', unsafe_allow_html=True)

    with c.panel("Why this project mirrors my work"):
        st.markdown(
            "In my day-to-day role, I sit between three teams that look at the same flights through very different "
            "lenses: pricing and merchandising at head office, network revenue management and inventory at head "
            "office, and the station GM and sales team in the local market. Pricing asks what fare to file, inventory "
            "asks which seats to protect, and the station asks how to hit its sales targets. My job is to bring their "
            "data together, explain the trade-offs, and help them agree on the right decision. This dashboard "
            "recreates that role with a fictional airline.")

    # 1. Question + headline visual
    st.markdown("#### 1. The business question")
    left, right = st.columns([1, 1])
    with left:
        st.markdown(
            f"Should a hub carrier keep selling from about ten filed fare buckets, or let prices sit anywhere between a "
            f"floor and a ceiling? The case uses {len(fl):,} simulated flights from {first} to {last}. The first 30 months "
            f"train the models; the last six months, from {test_first} ({n_test:,} flights), are held out and replayed "
            f"under each policy.")
    with right:
        with c.panel(f"Revenue by policy ({cur} millions)"):
            order = ["observed", "buckets", "continuous", "continuous_lf"]
            rows = [c.policy_row(s, "base", p) for p in order]
            fig = go.Figure(go.Bar(x=[c.POLICY_SHORT[p] for p in order], y=[r.revenue / 1e6 for r in rows],
                                   marker_color=[c.POLICY_COLORS[p] for p in order],
                                   text=[f"{r.revenue / 1e6:,.1f}" for r in rows], textposition="outside"))
            fig.update_yaxes(range=[0, max(r.revenue for r in rows) / 1e6 * 1.18])
            c.chart(fig, f"Continuous pricing earns {c.vs_text(h['gain_bk'])} than buckets; as flown is the higher reference.",
                    280, legend=False)

    # 2. Three lenses
    st.markdown("#### 2. How I approached it: three lenses")
    a, b, d = st.columns(3)
    with a:
        _insight("LENS 01", "Pricing and Revenue Management (HO)", "Is the forecast right, and what price should we offer today?", c.ROYAL)
    with b:
        _insight("LENS 02", "Network Revenue and Inventory (HO)", "Is this seat worth more to a local or a connecting passenger?", c.TEAL)
    with d:
        _insight("LENS 03", "Station (GM and Sales - local Market)", "Are we on target, and where are we losing ground?", c.CORAL)
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)

    # 3. Design decisions
    st.markdown("#### 3. Key design decisions and why")
    a, b = st.columns(2)
    with a:
        _insight("DECISION 01 - POINT OF SALE", "Revenue is credited where the ticket is sold",
                 f"That is what a station is judged on. Only {europe_share:.0f}% of revenue is sold at the six European "
                 f"stations; {hub_share:.0f}% is sold at the hub and {beyond_share:.0f}% beyond it.", c.ROYAL)
        _insight("DECISION 03 - SEASONAL FARE LADDERS", f"Shoulder and peak ladders are {ladder_scale:.2f} times the low ladder",
                 "Low season keeps the lower ladder, so yields there are lower by design. The scale is applied once, to the "
                 "target fare, so it is not counted twice.", c.CORAL)
        _insight("DECISION 05 - DATA WINDOW", "The window ends in February 2026",
                 "The test months are winter only: no summer peak, Easter or Eid. Events from March 2026 are not modelled.", c.AMBER)
    with b:
        _insight("DECISION 02 - ONE WAY VS RETURN", "Journeys, not independent legs",
                 f"{rt_share[1]:.0f}% of Business, {rt_share[2]:.0f}% of Leisure and {rt_share[3]:.0f}% of VFR journeys are "
                 f"return. A one-way fare is 60% of the return fare, a stated simplification.", c.TEAL)
        _insight("DECISION 04 - BERLIN COLD START", "A new route with no history",
                 "Berlin launches on 26 October 2025, inside the test window, to show how a forecast behaves on a new route.", c.ROYAL)
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)

    # 4. What the data shows
    st.markdown("#### 4. What the data shows")
    left, right = st.columns(2)
    with left:
        with c.panel("Berlin learning curve: forecast error at 90 days (%)"):
            periods = ["weeks 1-4", "weeks 5-8", "weeks 9-12", "weeks 13-18"]
            be = [_metric(cold, "gbm", f"Berlin {p}", 90) for p in periods]
            fr = [_metric(cold, "gbm", f"Frankfurt {p}", 90) for p in periods]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=periods, y=be, mode="lines+markers", name="Berlin", line=dict(color=c.CORAL, width=3)))
            fig.add_trace(go.Scatter(x=periods, y=fr, mode="lines+markers", name="Frankfurt, same weeks", line=dict(color=c.ROYAL, width=3)))
            fig.update_xaxes(type="category")
            fig.update_yaxes(rangemode="tozero")
            c.chart(fig, f"Berlin starts at {be[0]:.0f}% error against {fr[0]:.0f}% for Frankfurt and closes to {be[3]:.0f}% "
                         f"against {fr[3]:.0f}% by weeks 13 to 18.", 300)
    with right:
        with c.panel("Load factor trade-off: revenue vs load factor by policy"):
            fig = go.Figure()
            for p in order:
                r = c.policy_row(s, "base", p)
                fig.add_trace(go.Scatter(x=[r.load_factor], y=[r.revenue / 1e6], mode="markers+text", name=c.POLICY_SHORT[p],
                                         text=[c.POLICY_SHORT[p]], textposition="top center",
                                         marker=dict(size=16, color=c.POLICY_COLORS[p]), textfont=dict(color=c.NAVY)))
            fig.update_xaxes(title="Load factor (%)", range=[65, 99])
            fig.update_yaxes(title=f"Revenue ({cur} millions)")
            c.chart(fig, f"Buckets reach {bk.load_factor:.0f}% by selling cheap seats; the route floor earns the most of the "
                         f"three policies at the as-flown load factor ({lf.load_factor:.0f}%).", 300, legend=False)

    left, right = st.columns(2)
    with left:
        with c.panel("Forecast error by look-ahead (%)"):
            leads = [90, 60, 30, 14, 7]
            labels = [str(x) for x in leads]
            base_err = [_metric(acc, "baseline", "all test flights except Berlin", x) for x in leads]
            model_err = [_metric(acc, "gbm", "all test flights except Berlin", x) for x in leads]
            fig = go.Figure()
            fig.add_bar(x=labels, y=base_err, name="Pickup baseline", marker_color=c.CORAL,
                        text=[f"{v:.1f}" for v in base_err], textposition="outside")
            fig.add_bar(x=labels, y=model_err, name="Gradient boosting", marker_color=c.ROYAL,
                        text=[f"{v:.1f}" for v in model_err], textposition="outside")
            fig.update_layout(barmode="group")
            fig.update_xaxes(type="category", categoryorder="array", categoryarray=labels,
                             title="Days before departure")
            fig.update_yaxes(title="Forecast error, %", range=[0, max(base_err) * 1.2])
            c.chart(fig, f"The model's error is {g90:.0f}% at 90 days against {b90:.0f}% for the baseline; the gap closes in the last week.", 280)
    with right:
        with c.panel("Price sensitivity by segment (elasticity, 95% range)"):
            seg_names = [c.SEGMENT_NAMES[i] for i in low.index]
            fig = go.Figure(go.Scatter(
                x=low.estimate, y=seg_names, mode="markers+text", text=[f"{v:.2f}" for v in low.estimate],
                textposition="top center", textfont=dict(color=c.NAVY, size=13),
                marker=dict(size=12, color=c.NAVY),
                error_x=dict(type="data", symmetric=False, array=(low.ci_high - low.estimate).values,
                             arrayminus=(low.estimate - low.ci_low).values, color=c.ROYAL, thickness=3)))
            fig.add_vline(x=-1, line_dash="dot", line_color="#9FB1CE", line_width=2,
                          annotation_text="-1", annotation_position="top", annotation_font_color=c.NAVY)
            fig.update_xaxes(title="Elasticity (more negative = more price sensitive)")
            c.chart(fig, f"Business is least price sensitive ({low.estimate[1]:.2f}) and Leisure most ({low.estimate[2]:.2f}), "
                         f"but the ranges are wide.", 280, legend=False)

    a, b, d = st.columns(3)
    with a:
        _callout("opp", "Opportunity: route load factor floor",
                 f"Revenue {h['gain_lf_bk']:+.1f}% against buckets at {lf.load_factor:.0f}% load factor (as flown {obs.load_factor:.0f}%); "
                 f"{network.floor_phrase(lost_conn_lf)}.")
    with b:
        _callout("watch", "Watch: Berlin cold start",
                 f"First-month forecast error {ber1:.0f}% against {fra1:.0f}% for Frankfurt; use bucket control for the first weeks.")
    with d:
        _callout("risk", "Risk: price sensitivity",
                 f"If customers are at the high end of the estimated range, continuous pricing earns {ela_chg:+.1f}% against buckets.")
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)

    # 5 and 6: drafts
    st.markdown("#### 5. How I read it as an analyst")
    st.markdown('<div class="draft">DRAFT - for the author to rewrite in their own words</div>', unsafe_allow_html=True)
    st.markdown(
        f"On the same customers continuous pricing beats the bucket rule, but unconstrained it does so by selling fewer "
        f"seats at higher prices, and it still earns {c.vs_text(h['gain'])} than as flown, which sets fares customer by "
        f"customer. Business customers are barely price sensitive, so higher prices cost little volume there, while Leisure "
        f"and VFR customers are price sensitive and walk away, and that is where the connecting passengers sit: about "
        f"{lost_conn:,.0f} are priced out. The forecast is good enough to price from on established routes and not yet on "
        f"Berlin. The result also leans on a price sensitivity estimate with a wide range, so I would not roll it out "
        f"everywhere at once.")
    st.markdown("#### 6. Recommendation")
    st.markdown('<div class="draft">DRAFT - for the author to rewrite in their own words</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="callout"><div class="callout-main">Adopt continuous pricing with a route-level load factor floor</div>'
        f'Revenue {h["gain_lf_bk"]:+.1f}% against the bucket rule at a load factor of {lf.load_factor:.0f}% (as flown '
        f'{obs.load_factor:.0f}%). Without the floor about '
        f'{lost_conn:,.0f} connecting passengers are lost; {network.floor_phrase(lost_conn_lf)}. Start on the established '
        f'routes, keep bucket control on Berlin for its first weeks, and re-estimate price sensitivity from live promotions '
        f'every quarter.</div>', unsafe_allow_html=True)
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)

    # 7. Actions
    st.markdown("#### 7. Action items")
    names = ", ".join(below.Station) if len(below) else "none"
    recs = [
        ("Pricing and Revenue Management (HO)", "Pilot continuous pricing with the route load factor floor on the established routes first; review flagged flights before accepting the system price; keep bucket control with borrowed pickup ratios on new routes for eight weeks."),
        ("Network Revenue and Inventory (HO)", f"Protect seats for connecting demand where the connecting contribution beats the local leg revenue, and track the connecting passengers priced out (about {lost_conn:,.0f} without a floor in the replay)."),
        ("Station (GM and Sales - local Market)", f"Stations below target in the held-out months: {names}. Hold volume there with the floor, and push promotions and corporate or agency deals in the segment that lost most ground year on year."),
    ]
    st.markdown("".join(f'<div class="rec"><div class="rec-n">{i}</div><div><div class="rec-h">{t}</div>'
                        f'<div class="rec-t">{x}</div></div></div>' for i, (t, x) in enumerate(recs, 1)),
                unsafe_allow_html=True)
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)

    # 8. Limitations
    st.markdown("#### 8. Limitations and next steps")
    with st.expander("How to read this"):
        st.markdown(
            "- All data is simulated and the carrier is fictional; public figures used for calibration are cited in the README.\n"
            "- The test window is winter only (no summer peak, Easter or Eid), so accuracy may not hold in other seasons.\n"
            "- Observed bookings are capped by seats, so demand on full flights is understated and the replay is conservative there.\n"
            "- The replay prices originating passengers on their outbound leg only, ignores network effects beyond a simple "
            "displacement cost, and assumes a fence below which Business customers cannot buy.\n"
            "- The headline depends on a price sensitivity estimate with a wide range, and on an assumed spread of willingness "
            f"to pay (0.45; {c.spread_text()}).\n"
            "- As flown is an upper reference: fares in the simulated data are set customer by customer, which neither replayed "
            "policy can match. The like-for-like comparison is continuous pricing against the bucket rule.\n"
            "- The route floor earns more than unconstrained continuous pricing because the unconstrained price rule leaves "
            "seats empty; it should be read as a better-tuned policy, not a free gain.\n\n"
            "**Next steps (Version 2):** a stronger directional imbalance in the data, unconstraining demand on full flights, "
            "repricing return journeys as a whole, network (origin and destination) optimisation, and using the stored "
            "sales channel in a separate NDC project.")
    st.markdown(f'<div class="footer">{c.SHORT_DISCLAIMER}</div>', unsafe_allow_html=True)
