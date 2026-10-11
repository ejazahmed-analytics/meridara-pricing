"""Overview page: the problem, the headline result and a map of the views."""
import plotly.graph_objects as go
import streamlit as st

import common as c


def render(cur):
    s = c.sim_summary(cur)
    obs = c.policy_row(s, "base", "observed")
    bk = c.policy_row(s, "base", "buckets")
    ct = c.policy_row(s, "base", "continuous")
    lf = c.policy_row(s, "base", "continuous_lf")
    gain = 100 * (ct.revenue / obs.revenue - 1)
    gain_vs_buckets = 100 * (ct.revenue / bk.revenue - 1)
    gain_lf = 100 * (lf.revenue / obs.revenue - 1)
    kept = 100 * (lf.revenue - obs.revenue) / (ct.revenue - obs.revenue)

    st.title("From Fare Buckets to Continuous Pricing")
    st.markdown("**Pricing the Europe to Asia corridor at a hub carrier.** Meridara is a fictional airline.")
    st.markdown(
        "Most airlines are moving from filed fare buckets toward continuous pricing, and a hub carrier has to "
        "decide how far to go. Meridara connects Europe with Asia, Africa and Australia through a single hub; "
        "this case study replays six months of simulated flights to see what continuous pricing would earn. "
        "The answer looks different to pricing, to network and to the stations, so the analyst's job is to "
        "show the trade-offs and recommend one decision.")

    st.subheader("Headline result")
    a, b, d = st.columns(3)
    with a:
        c.metric_card("Continuous pricing vs as flown", c.pct(gain, True),
                      f"{c.money(ct.revenue, cur)} vs {c.money(obs.revenue, cur)}")
    with b:
        c.metric_card("Load factor", f"{ct.load_factor:.1f}%", f"as flown {obs.load_factor:.1f}%")
    with d:
        c.metric_card("With a load factor floor", c.pct(gain_lf, True),
                      f"load factor {lf.load_factor:.1f}%; keeps {kept:.0f}% of the gain")

    order = ["observed", "buckets", "continuous", "continuous_lf"]
    rows = [c.policy_row(s, "base", p) for p in order]
    fig = go.Figure(go.Bar(
        x=[c.POLICY_LABELS[p] for p in order], y=[r.revenue / 1e6 for r in rows],
        marker_color=[c.POLICY_COLORS[p] for p in order],
        text=[f"{r.revenue / 1e6:,.1f}m<br>LF {r.load_factor:.0f}%" for r in rows], textposition="outside"))
    fig.update_yaxes(title=f"Revenue, {cur} millions", range=[0, max(r.revenue for r in rows) / 1e6 * 1.2])
    c.show(fig, f"Continuous pricing earns {c.pct(gain, True)} on the same held-out flights, and holding the load "
                f"factor at the as-flown level still keeps {kept:.0f}% of that gain.", 360, legend=False)

    st.markdown(
        f"**Secondary comparison.** Against a simplified fare bucket policy (EMSR-b) continuous pricing earns "
        f"{c.pct(gain_vs_buckets, True)}. That bucket replay earns {c.pct(100 * (bk.revenue / obs.revenue - 1), True)} "
        f"against as flown because it offers one price per booking period to every customer, so cheap classes "
        f"dilute yield, while real fares also discriminate by segment and booking time.")
    st.caption("Revenue is for originating passengers on their outbound leg, in one-way-fare terms, for the six "
               "held-out months (September 2025 to February 2026, winter only). Details and limits are on the "
               "Data Story page.")

    st.subheader("What each view shows")
    st.markdown(
        "- **Pricing and Revenue Management (HO):** is the forecast right, and what price should we offer today?\n"
        "- **Network Revenue and Inventory (HO):** is this seat worth more to a local or a connecting passenger?\n"
        "- **Station (GM and Sales - local Market):** are we on target, and where are we losing ground?\n"
        "- **Analyst summary:** where do the three teams disagree, and what should happen?\n"
        "- **Data Story:** the case from question to recommendation, in a few minutes.")
