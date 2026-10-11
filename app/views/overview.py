"""Overview page: the headline result at a glance."""
import plotly.graph_objects as go
import streamlit as st

import common as c

SCENARIO_LABELS = {"base": "Base", "underforecast": "Forecast 15% too low", "competitor_cut": "Competitor cuts 10%",
                   "elastic_world": "Customers more price sensitive", "inelastic_world": "Customers less price sensitive"}


def render(cur):
    h = c.headline(cur)
    s, obs, bk, ct, lf = h["s"], h["obs"], h["bk"], h["ct"], h["lf"]
    c.hero("From Fare Buckets to Continuous Pricing", "Pricing the Europe to Asia corridor at a hub carrier", cur)

    c.kpi_row([
        ("Continuous pricing revenue", c.money(ct.revenue, cur), f"vs as flown {c.money(obs.revenue, cur)}",
         c.ROYAL, f"{h['gain']:+.1f}%", h["gain"] >= 0),
        ("Load factor, continuous", f"{ct.load_factor:.1f}%", f"as flown {obs.load_factor:.1f}%", c.CORAL,
         f"{ct.load_factor - obs.load_factor:+.1f} pts", ct.load_factor >= obs.load_factor),
        ("With route load factor floor", c.money(lf.revenue, cur), f"load factor {lf.load_factor:.1f}%", c.TEAL,
         f"{h['gain_lf']:+.1f}%", h["gain_lf"] >= 0),
        ("Continuous vs simplified buckets", f"{h['gain_bk']:+.1f}%", "EMSR-b replay", c.AMBER),
    ])

    order = ["observed", "buckets", "continuous", "continuous_lf"]
    rows = [c.policy_row(s, "base", p) for p in order]
    labels = [c.POLICY_SHORT[p] for p in order]
    colors = [c.POLICY_COLORS[p] for p in order]

    left, right = st.columns(2)
    with left:
        with c.panel(f"Revenue by policy ({cur} millions)"):
            fig = go.Figure(go.Bar(x=labels, y=[r.revenue / 1e6 for r in rows], marker_color=colors,
                                   text=[f"{r.revenue / 1e6:,.1f}" for r in rows], textposition="outside"))
            fig.update_yaxes(range=[0, max(r.revenue for r in rows) / 1e6 * 1.18])
            c.chart(fig, f"Continuous pricing earns {h['gain']:+.1f}% against as flown; the route floor "
                         f"{h['gain_lf']:+.1f}%.", 300, legend=False)
    with right:
        with c.panel("Load factor by policy (%)"):
            fig = go.Figure(go.Bar(x=labels, y=[r.load_factor for r in rows], marker_color=colors,
                                   text=[f"{r.load_factor:.1f}" for r in rows], textposition="outside"))
            fig.update_yaxes(range=[0, 108])
            c.chart(fig, f"Continuous pricing trades volume for yield: {ct.load_factor:.0f}% load factor against "
                         f"{obs.load_factor:.0f}% as flown. The floor holds {lf.load_factor:.0f}%.", 300, legend=False)

    left, right = st.columns(2)
    with left:
        with c.panel("Revenue change by route vs as flown (%)"):
            by = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="revenue_eur")
            names = [c.STATION_NAMES[i] for i in by.index]
            fig = go.Figure()
            fig.add_bar(x=names, y=100 * (by["continuous"] / by["observed"] - 1), name="Continuous",
                        marker_color=c.ROYAL)
            fig.add_bar(x=names, y=100 * (by["continuous_lf"] / by["observed"] - 1), name="With floor",
                        marker_color=c.TEAL)
            fig.update_layout(barmode="group")
            chg = by["continuous"] / by["observed"] - 1
            best, worst = chg.idxmax(), chg.idxmin()
            c.chart(fig, f"Continuous pricing gains most on {c.STATION_NAMES[best]} ({100 * chg[best]:+.1f}%) and "
                         f"least on {c.STATION_NAMES[worst]} ({100 * chg[worst]:+.1f}%).", 300)
    with right:
        with c.panel("Stress tests: continuous vs buckets (%)"):
            sc = []
            for key, label in SCENARIO_LABELS.items():
                b_, c_ = c.policy_row(s, key, "buckets"), c.policy_row(s, key, "continuous")
                sc.append((label, 100 * (c_.revenue / b_.revenue - 1)))
            fig = go.Figure(go.Bar(y=[a for a, _ in sc][::-1], x=[b for _, b in sc][::-1], orientation="h",
                                   marker_color=[c.CORAL if v < 0 else c.ROYAL for _, v in sc][::-1],
                                   text=[f"{v:+.1f}%" for _, v in sc][::-1], textposition="outside"))
            lo, hi = min(v for _, v in sc), max(v for _, v in sc)
            fig.update_xaxes(range=[min(0, lo) - 8, hi + 12], zeroline=True, zerolinecolor=c.NAVY)
            neg = [a for a, v in sc if v < 0]
            c.chart(fig, ("Continuous pricing loses against buckets if customers are more price sensitive than "
                          "estimated." if neg else "Continuous pricing stays ahead of buckets in every stress test."),
                    300, legend=False)

    c.notes(
        f"**The problem.** Most airlines are moving from filed fare buckets toward continuous pricing. Meridara, a "
        f"fictional carrier connecting Europe with Asia, Africa and Australia through one hub, replays six months of "
        f"simulated flights to see what continuous pricing would earn. Pricing, network and stations each see it "
        f"differently, so the analyst shows the trade-offs and recommends one decision.\n\n"
        f"**Headline.** Continuous pricing earns {h['gain']:+.1f}% against as flown. The simplified bucket replay (EMSR-b) "
        f"earns {h['bk_vs_obs']:+.1f}% against as flown because it offers one price per booking period to every customer, "
        f"so cheap classes dilute yield, while real fares also discriminate by segment and booking time. "
        f"{c.floor_vs_continuous(h)}\n\n"
        f"**Route floor.** Each route must keep at least its as-flown average load factor over the six held-out months; "
        f"individual flights can vary.\n\n"
        f"**Scope.** Revenue is for originating passengers on their outbound leg, in one-way-fare terms, for September 2025 "
        f"to February 2026 (winter only). See the Data Story page for limits.")
