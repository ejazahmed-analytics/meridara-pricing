"""Data Story: the case from question to recommendation. Every number comes from the databases."""
import pandas as pd
import streamlit as st

import common as c
from views import network, summary


def _metric(mm, model, scope, lead):
    row = mm[(mm.model == model) & (mm.scope == scope) & (mm.asof_days == lead)]
    return float(row.wape.iloc[0])


def render(cur):
    s = c.sim_summary(cur)
    obs, bk, ct, lf = (c.policy_row(s, "base", p) for p in ("observed", "buckets", "continuous", "continuous_lf"))
    gain, gain_bk = 100 * (ct.revenue / obs.revenue - 1), 100 * (ct.revenue / bk.revenue - 1)
    gain_lf = 100 * (lf.revenue / obs.revenue - 1)
    kept = 100 * (lf.revenue - obs.revenue) / (ct.revenue - obs.revenue)

    fl = c.flights_table()
    first, last = fl.departure_date.min(), fl.departure_date.max()
    test_first = fl[fl.is_test == 1].departure_date.min()
    n_test = int((fl.is_test == 1).sum())

    mm = c.query("results", "SELECT * FROM model_metrics")
    acc = mm[(mm.analysis == "accuracy") & (mm.scope == "all test flights except Berlin")]
    cold = mm[mm.analysis == "berlin_cold_start"]
    sens = c.query("results", "SELECT * FROM sensitivity_estimates WHERE parameter = 'price'")
    low = sens[sens["sample"] == "low-season flights"].set_index("segment_id")

    pos = c.query("results", "SELECT * FROM agg_pos_month")
    pos_all = c.convert(pos, ["rev_eur"], "EUR").groupby("pos_station_id").rev_eur.sum()
    tot = pos_all.sum()
    hub_share = 100 * pos_all.get(11, 0) / tot
    beyond_share = 100 * pos_all[[7, 8, 9, 10]].sum() / tot
    europe_share = 100 * pos_all[[1, 2, 3, 4, 5, 6]].sum() / tot
    rm_ = c.query("results", "SELECT segment_id, trip_type, SUM(pax) AS pax FROM agg_route_month WHERE leg_seq = 1 "
                             "GROUP BY segment_id, trip_type")
    rt = rm_.pivot(index="segment_id", columns="trip_type", values="pax")
    rt_share = 100 * rt["RT"] / rt.sum(axis=1)
    fb = c.query("data", "SELECT ladder, price_point_eur FROM fare_buckets WHERE route_id = 1 AND cabin_id = 1 AND class_rank = 10")
    lift = fb.set_index("ladder").price_point_eur
    ladder_scale = lift["standard"] / lift["low"]

    feed = network.feed_table(cur)
    ll = feed[feed.Segment.isin(["Leisure", "VFR"])]
    lost_conn = ll["Lost connecting pax"].sum()
    lost_conn_lf = ll["Lost connecting pax (floor)"].sum()
    st_tbl = summary.station_table(cur, s)
    below = st_tbl[st_tbl["Revenue vs target %"] < 100]

    st.title("Data Story")
    st.caption("A short narrative of the case. All numbers are read from the project's databases and change with "
               "the currency filter where they are money.")

    st.header("Why this project mirrors my work")
    st.markdown(
        "In my day-to-day role, I sit between three teams that look at the same flights through very different "
        "lenses: pricing and merchandising at head office, network revenue management and inventory at head "
        "office, and the station GM and sales team in the local market. Pricing asks what fare to file, inventory "
        "asks which seats to protect, and the station asks how to hit its sales targets. My job is to bring their "
        "data together, explain the trade-offs, and help them agree on the right decision. This dashboard "
        "recreates that role with a fictional airline.")

    st.header("1. The business question")
    st.markdown(
        f"Should a hub carrier keep selling from about ten filed fare buckets, or move to prices that can sit "
        f"anywhere between a floor and a ceiling? The case uses {len(fl):,} simulated flights between "
        f"{first} and {last}. The first 30 months train the models; the last six months, from {test_first} "
        f"({n_test:,} flights), are held out and replayed under each policy.")

    st.header("2. How I approached it: three lenses")
    st.markdown(
        "- **Pricing and Revenue Management (HO):** is the forecast right, and what price should we offer today?\n"
        "- **Network Revenue and Inventory (HO):** is this seat worth more to a local or a connecting passenger?\n"
        "- **Station (GM and Sales - local Market):** are we on target, and where are we losing ground?\n\n"
        "I built one dataset that all three can read, then looked for the places where their answers disagree.")

    st.header("3. Key design decisions and why")
    st.markdown(
        f"- **Point of sale versus point of origin.** Revenue is credited to where the ticket is sold, because "
        f"that is what a station is judged on. Only {europe_share:.0f}% of revenue is sold at the six European "
        f"stations; {hub_share:.0f}% is sold at the hub and {beyond_share:.0f}% beyond it, mostly by journeys that start "
        f"there. The Station view therefore splits origin-sold from foreign-origin-sold revenue.\n"
        f"- **One way versus return, and the 60% rule.** Most passengers fly return ({rt_share[1]:.0f}% of Business, "
        f"{rt_share[2]:.0f}% of Leisure, {rt_share[3]:.0f}% of VFR journeys), so the data is built from journeys, not "
        f"independent legs. A one-way fare is set at 60% of the return fare in every segment and cabin. That is a "
        f"stated simplification, not a market fact.\n"
        f"- **Seasonal fare ladders.** The standard price ladder is the low-season ladder scaled by "
        f"{ladder_scale:.2f}, used in shoulder and peak months. Low season (January, February, November) keeps the "
        f"lower ladder, so yields there are lower by design. The scale is applied once, to the target fare, so it is "
        f"not counted twice.\n"
        f"- **Berlin as a cold-start case.** Berlin launches on 26 October 2025 with no history, inside the test "
        f"window, to show how a forecast behaves on a new route.\n"
        f"- **A data window that ends in February 2026.** The test months are winter only: no summer peak, no "
        f"Easter, no Eid. Accuracy reflects those conditions, and events from March 2026 are not modelled.")

    st.header("4. What the data shows")
    st.subheader("Forecast accuracy")
    rows = []
    for lead in (90, 60, 30, 14, 7):
        b_, g_ = _metric(acc, "baseline", "all test flights except Berlin", lead), _metric(acc, "gbm", "all test flights except Berlin", lead)
        rows.append({"Days before departure": lead, "Pickup baseline error %": b_, "Gradient boosting error %": g_,
                     "Improvement %": 100 * (1 - g_ / b_)})
    st.dataframe(pd.DataFrame(rows).round(1), hide_index=True, width="stretch")
    b90, g90 = rows[0]["Pickup baseline error %"], rows[0]["Gradient boosting error %"]
    c.takeaway(f"At 90 days out the model's error is {g90:.0f}% against {b90:.0f}% for the historical pickup baseline; "
               f"the advantage fades to a few percent in the last week.")

    st.subheader("Berlin learning curve")
    periods = ["weeks 1-4", "weeks 5-8", "weeks 9-12", "weeks 13-18"]
    bl = pd.DataFrame({"Period": periods,
                       "Berlin error %": [_metric(cold, "gbm", f"Berlin {p}", 90) for p in periods],
                       "Frankfurt, same weeks %": [_metric(cold, "gbm", f"Frankfurt {p}", 90) for p in periods]})
    st.dataframe(bl.round(1), hide_index=True, width="stretch")
    c.takeaway(f"At 90 days out Berlin's forecast error starts at {bl.iloc[0, 1]:.0f}% against {bl.iloc[0, 2]:.0f}% for "
               f"Frankfurt and closes to {bl.iloc[3, 1]:.0f}% against {bl.iloc[3, 2]:.0f}% by weeks 13 to 18.")

    st.subheader("Price sensitivity")
    ps = pd.DataFrame({"Segment": [c.SEGMENT_NAMES[i] for i in low.index], "Estimate": low.estimate.values,
                       "Low": low.ci_low.values, "High": low.ci_high.values})
    st.dataframe(ps.round(2), hide_index=True, width="stretch")
    c.takeaway(f"Business is the least price sensitive ({low.estimate[1]:.2f}) and Leisure the most ({low.estimate[2]:.2f}), "
               f"but the ranges are wide, so conclusions should be read as conditional on them.")

    st.subheader("Revenue and the load factor trade-off")
    t = pd.DataFrame([{"Policy": c.POLICY_LABELS[p], f"Revenue ({cur} m)": c.policy_row(s, "base", p).revenue / 1e6,
                       "vs as flown %": 100 * (c.policy_row(s, "base", p).revenue / obs.revenue - 1),
                       "Load factor %": c.policy_row(s, "base", p).load_factor}
                      for p in ("observed", "buckets", "continuous", "continuous_lf")])
    st.dataframe(t.round(1), hide_index=True, width="stretch")
    c.takeaway(f"Continuous pricing earns {c.pct(gain, True)} against as flown ({c.pct(gain_bk, True)} against the "
               f"simplified bucket policy) but at a load factor of {ct.load_factor:.0f}% instead of {obs.load_factor:.0f}%; "
               f"a floor keeps {kept:.0f}% of the gain.")

    st.header("5. How I read it as an analyst")
    st.markdown(
        '<div class="draft"><span class="draft-tag">DRAFT - for the author to rewrite in their own words</span></div>',
        unsafe_allow_html=True)
    st.markdown(
        f"The revenue gain is real inside the simulation, but it comes from selling fewer seats at higher prices. "
        f"Business customers are barely price sensitive, so higher prices cost little volume there, while Leisure "
        f"and VFR customers are price sensitive and walk away. That is exactly where the connecting passengers "
        f"sit: about {lost_conn:,.0f} connecting passengers are priced out. The forecast is good enough to price "
        f"from on established routes and not yet on Berlin. The result also leans on a price sensitivity "
        f"estimate with a wide range, which is why I would not roll it out everywhere at once.")

    st.header("6. Recommendation")
    st.markdown(
        '<div class="draft"><span class="draft-tag">DRAFT - for the author to rewrite in their own words</span></div>',
        unsafe_allow_html=True)
    st.markdown(
        f"Adopt continuous pricing with a load factor floor at the as-flown level. It earns {c.pct(gain_lf, True)} "
        f"against as flown, keeps {kept:.0f}% of the full gain and holds the load factor at {lf.load_factor:.0f}%. "
        f"Without the floor about {lost_conn:,.0f} connecting passengers are lost; {network.floor_phrase(lost_conn_lf)}. Start on the "
        f"established routes, keep bucket control on Berlin for its first weeks, and re-estimate price "
        f"sensitivity from live promotions every quarter.")

    st.header("7. Action items")
    names = ", ".join(below.Station) if len(below) else "none"
    st.markdown(
        f"**Pricing and Revenue Management (HO)**\n"
        f"- Pilot continuous pricing with the load factor floor on the established routes first.\n"
        f"- Review the flights the booking-pace flags mark as unusual before accepting the system price.\n"
        f"- Keep bucket control with borrowed pickup ratios on new routes for the first eight weeks.\n\n"
        f"**Network Revenue and Inventory (HO)**\n"
        f"- Protect seats for connecting demand where the connecting contribution beats the local leg revenue.\n"
        f"- Track the connecting passengers lost to higher Leisure and VFR prices (about {lost_conn:,.0f} without a "
        f"floor in the replay).\n\n"
        f"**Station (GM and Sales - local Market)**\n"
        f"- Stations below target in the held-out months: {names}. Hold volume there with the load factor floor.\n"
        f"- Push promotions and corporate or agency deals in the segment that has lost the most ground year on year.")

    st.header("8. Limitations and next steps")
    st.markdown(
        "- All data is simulated and the carrier is fictional; public figures used for calibration are cited in the README.\n"
        "- The test window is winter only (no summer peak, Easter or Eid), so accuracy may not hold in other seasons.\n"
        "- Observed bookings are capped by seats, so demand on full flights is understated and the replay is conservative there.\n"
        "- The replay prices originating passengers on their outbound leg only, ignores network effects beyond a simple "
        "displacement cost, and assumes a fence below which Business customers cannot buy.\n"
        "- The headline depends on a price sensitivity estimate with a wide range.\n\n"
        "**Next steps (Version 2):** a stronger directional imbalance in the data, unconstraining demand on full flights, "
        "repricing return journeys as a whole, network (origin and destination) optimisation, and using the stored "
        "sales channel in a separate NDC project.")
