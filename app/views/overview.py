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
        ("Continuous vs buckets", f"{h['gain_bk']:+.1f}%", f"{c.money(ct.revenue, cur)} vs {c.money(bk.revenue, cur)}, "
         f"same customers", c.ROYAL),
        ("Route floor vs buckets", f"{h['gain_lf_bk']:+.1f}%", f"load factor {lf.load_factor:.1f}% vs {bk.load_factor:.1f}%",
         c.TEAL),
        ("Continuous vs as flown", f"{h['gain']:+.1f}%", f"as flown {c.money(obs.revenue, cur)}", c.CORAL,
         None, None),
        ("Load factor, continuous", f"{ct.load_factor:.1f}%", f"as flown {obs.load_factor:.1f}%", c.AMBER),
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
            c.chart(fig, f"On the same customers continuous pricing earns {c.vs_text(h['gain_bk'])} than the bucket rule; "
                         f"as flown is a higher reference ({c.vs_text(h['gain'])} than continuous).", 300, legend=False)
    with right:
        with c.panel("Load factor by policy (%)"):
            fig = go.Figure(go.Bar(x=labels, y=[r.load_factor for r in rows], marker_color=colors,
                                   text=[f"{r.load_factor:.1f}" for r in rows], textposition="outside"))
            fig.update_yaxes(range=[0, 108])
            c.chart(fig, f"Buckets fill {bk.load_factor:.0f}% of seats at low fares; continuous pricing holds "
                         f"{ct.load_factor:.0f}% and the route floor {lf.load_factor:.0f}%, level with as flown "
                         f"({obs.load_factor:.0f}%).", 300, legend=False)

    left, right = st.columns(2)
    with left:
        with c.panel("Continuous pricing by route (%)"):
            by = c.sim_by(cur, "station_id").pivot(index="station_id", columns="policy", values="revenue_eur")
            names = [c.STATION_NAMES[i] for i in by.index]
            vs_b = 100 * (by["continuous"] / by["buckets"] - 1)
            vs_o = 100 * (by["continuous"] / by["observed"] - 1)
            fig = go.Figure()
            fig.add_bar(x=names, y=vs_b, name="vs buckets", marker_color=c.ROYAL)
            fig.add_bar(x=names, y=vs_o, name="vs as flown", marker_color=c.CORAL)
            fig.update_layout(barmode="group")
            best, worst = vs_b.idxmax(), vs_b.idxmin()
            c.chart(fig, f"Against buckets the gain is largest on {c.STATION_NAMES[best]} ({vs_b[best]:+.1f}%) and "
                         f"smallest on {c.STATION_NAMES[worst]} ({vs_b[worst]:+.1f}%).", 300)
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
            c.chart(fig, ("Continuous pricing falls behind buckets if customers are more price sensitive than estimated."
                          if neg else "Continuous pricing stays ahead of buckets in every stress test."),
                    300, legend=False)

    c.notes(
        f"**The problem.** Most airlines are moving from filed fare buckets toward continuous pricing. Meridara, a "
        f"fictional carrier connecting Europe with Asia, Africa and Australia through one hub, replays six months of "
        f"simulated flights to see what continuous pricing would earn. Pricing, network and stations each see it "
        f"differently, so the analyst shows the trade-offs and recommends one decision.\n\n"
        f"**The fair comparison.** The bucket rule (EMSR-b, with advance-purchase rules that close the cheapest classes 14 and "
        f"7 days out) and continuous pricing face the same simulated customers and the same rules: one base price per booking "
        f"period, with Business customers fenced at the 6th price point. Continuous pricing earns {c.vs_text(h['gain_bk'])} "
        f"than buckets, and the route floor {c.vs_text(h['gain_lf_bk'])}.\n\n"
        f"**Why 'as flown' is higher.** In the simulated data each customer's fare is drawn individually, so a Business "
        f"traveller and a Leisure traveller pay very different fares in the same week. Neither replayed policy can do that, so "
        f"as flown works as an upper reference, not a policy to beat. Continuous pricing earns {c.vs_text(h['gain'])} than "
        f"as flown and the route floor {c.vs_text(h['gain_lf'])}.\n\n"
        f"**Route floor.** Each route must keep at least its as-flown average load factor over the six held-out months; "
        f"individual flights can vary. {c.floor_vs_continuous(h)}\n\n"
        f"**Demand model.** Willingness to pay is bounded and rises towards departure, so prices fall inside the price range "
        f"and rise across booking periods. Its spread (0.45) is an assumption: {c.spread_text()}.\n\n"
        f"**Scope.** Revenue is for originating passengers on their outbound leg, in one-way-fare terms, for September 2025 "
        f"to February 2026 (winter only). See the Data Story page for limits.")
