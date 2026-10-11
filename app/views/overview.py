"""Overview page: the headline result at a glance."""
import plotly.graph_objects as go
import streamlit as st

import common as c

SCENARIO_LABELS = {"base": "Base", "underforecast": "Forecast 15% too low", "competitor_cut": "Competitor cuts 10%",
                   "elastic_world": "Customers more price sensitive", "inelastic_world": "Customers less price sensitive"}


def render(cur):
    h = c.headline(cur)
    s, obs, bk, ct, lf = h["s"], h["obs"], h["bk"], h["ct"], h["lf"]
    cal = c.calibration()
    tr = cal["training"]
    c.hero("From Fare Buckets to Continuous Pricing", "Pricing the Europe to Asia corridor at a hub carrier", cur)

    c.kpi_row([
        ("Continuous vs validated buckets", f"{h['gain_bk']:+.1f}%", f"{c.money(ct.revenue, cur)} vs {c.money(bk.revenue, cur)}",
         c.ROYAL),
        ("Route floor vs validated buckets", f"{h['gain_lf_bk']:+.1f}%", f"load factor {lf.load_factor:.1f}% vs {bk.load_factor:.1f}%",
         c.TEAL),
        ("Bucket baseline check", f"{tr['rev_gap']:+.1f}%", f"revenue vs as flown in the training period; load factor "
         f"{tr['lf_gap']:+.1f} pts", c.AMBER),
        ("Continuous vs as flown", f"{h['gain']:+.1f}%", f"as flown {c.money(obs.revenue, cur)}, for reference", c.CORAL),
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
            c.chart(fig, f"Against the validated bucket baseline, continuous pricing earns {c.vs_text(h['gain_bk'])} and "
                         f"the route floor {c.vs_text(h['gain_lf_bk'])}; as flown is shown for reference.", 300, legend=False)
    with right:
        with c.panel("Load factor by policy (%)"):
            fig = go.Figure(go.Bar(x=labels, y=[r.load_factor for r in rows], marker_color=colors,
                                   text=[f"{r.load_factor:.1f}" for r in rows], textposition="outside"))
            fig.update_yaxes(range=[0, 108])
            c.chart(fig, f"The bucket baseline holds {bk.load_factor:.0f}% of seats (as flown {obs.load_factor:.0f}%); continuous "
                         f"pricing {ct.load_factor:.0f}% and the route floor {lf.load_factor:.0f}%.", 300, legend=False)

    left, right = st.columns(2)
    with left:
        with c.panel("Continuous pricing by route (%)"):
            by = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="revenue_eur")
            names = [c.STATION_NAMES[i] for i in by.index]
            vs_b = 100 * (by["continuous"] / by["buckets"] - 1)
            vs_o = 100 * (by["continuous"] / by["observed"] - 1)
            fig = go.Figure()
            fig.add_bar(x=names, y=vs_b, name="vs validated buckets", marker_color=c.ROYAL)
            fig.add_bar(x=names, y=vs_o, name="vs as flown", marker_color=c.CORAL)
            fig.update_layout(barmode="group")
            best, worst = vs_b.idxmax(), vs_b.idxmin()
            c.chart(fig, f"Against buckets the gain is largest on {c.STATION_NAMES[best]} ({vs_b[best]:+.1f}%) and "
                         f"smallest on {c.STATION_NAMES[worst]} ({vs_b[worst]:+.1f}%).", 300)
    with right:
        with c.panel("Stress tests: continuous vs validated buckets (%)"):
            sc = []
            for key, label in SCENARIO_LABELS.items():
                b_, c_ = c.policy_row(s, key, "buckets"), c.policy_row(s, key, "continuous")
                sc.append((label, 100 * (c_.revenue / b_.revenue - 1)))
            fig = go.Figure(go.Bar(y=[a for a, _ in sc][::-1], x=[b for _, b in sc][::-1], orientation="h",
                                   marker_color=[c.CORAL if v < 0 else c.ROYAL for _, v in sc][::-1],
                                   text=[f"{v:+.1f}%" for _, v in sc][::-1], textposition="outside"))
            lo, hi = min(v for _, v in sc), max(v for _, v in sc)
            fig.update_xaxes(range=[min(0, lo) - 3, hi + 4], zeroline=True, zerolinecolor=c.NAVY)
            lo_s = min(sc, key=lambda x: x[1])
            c.chart(fig, f"The gain holds in every stress test, from {lo_s[1]:+.1f}% ({lo_s[0].lower()}) to {hi:+.1f}%."
                         if lo > 0 else "Continuous pricing falls behind buckets if customers are more price sensitive than estimated.",
                    300, legend=False)

    c.notes(
        f"**The problem.** Most airlines are moving from filed fare buckets toward continuous pricing. Meridara, a "
        f"fictional carrier connecting Europe with Asia, Africa and Australia through one hub, replays six months of "
        f"simulated flights to see what continuous pricing would earn. Pricing, network and stations each see it "
        f"differently, so the analyst shows the trade-offs and recommends one decision.\n\n"
        f"**A validated baseline.** The bucket policy (EMSR-b with advance-purchase rules) is calibrated on the training "
        f"period so that replaying it reproduces as-flown results: revenue {tr['rev_gap']:+.1f}% and load factor "
        f"{tr['lf_gap']:+.1f} points against as flown. In the held-out period it is {cal['test']['rev_gap']:+.1f}% and "
        f"{cal['test']['lf_gap']:+.1f} points. Continuous pricing and the route floor are compared with this baseline on "
        f"the same simulated customers and the same rules: one base price per booking period, Business customers fenced "
        f"at the calibrated flexible class.\n\n"
        f"**How the gain arises.** Continuous pricing sets the price period by period from the demand still to come, so it "
        f"sells fewer cheap seats and earns more per passenger. {c.floor_vs_continuous(h)}\n\n"
        f"**Route floor.** Each route must keep at least its as-flown average load factor over the six held-out months; "
        f"individual flights can vary.\n\n"
        f"**What a sceptic should ask.** The replay knows the demand curve the simulated customers follow (estimated from "
        f"random promotions), assumes a spread of willingness to pay ({c.spread_text()}), ignores network effects and "
        f"competitor reactions beyond the stress tests, and covers six winter months. Read the gain as an upper bound for "
        f"what a pilot could show, not a forecast.\n\n"
        f"**Scope.** Revenue is for originating passengers on their outbound leg, in one-way-fare terms, for September 2025 "
        f"to February 2026. See the Data Story page for limits.")
