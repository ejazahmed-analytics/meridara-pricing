"""Sanity checks: compare the generated database with the agreed inputs.

Illustrative case study using fictitious and simulated data.

Run from the project root:   python src/sanity_checks.py
Prints simple markdown tables. Nothing here changes the database.
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import generate_data as g  # noqa: E402  (agreed inputs live here)

DB = ROOT / "data" / "meridara.db"
NAMES = {1: "Frankfurt", 2: "Berlin", 3: "London", 4: "Paris", 5: "Milan", 6: "Madrid",
         7: "Bangkok", 8: "Sydney", 9: "Nairobi", 10: "Mumbai", 11: "HUB"}
SEG = ["Business", "Leisure", "VFR"]
LF_RANGES = {1: [(70, 76), (78, 84), (88, 93), (90, 95)], 3: [(72, 78), (80, 86), (89, 94), (91, 96)],
             4: [(68, 74), (77, 83), (87, 92), (89, 94)], 5: [(66, 72), (75, 81), (86, 91), (88, 93)],
             6: [(64, 70), (73, 79), (85, 90), (87, 92)]}
PRICE_GROUP = {"low": "low", "shoulder": "shoulder", "summer": "peak", "christmas": "peak"}


def md(df, digits=1):
    """Print a dataframe as a markdown table."""
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else f"{v:,.{digits}f}"
        return str(v)
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    print("\n".join(lines) + "\n")


def load(con):
    """All booking legs from the view, with EUR values at the departure-month rate."""
    cols = ("booking_id, flight_id, route_id, route_station_id, direction, departure_date, days_before, "
            "journey_id, trip_type, leg_seq, segment_id, cabin_id, pos_station_id, sales_currency, pax, "
            "through_fare, class_rank, traffic_type, beyond_city_id, leg_fare, journey_origin_station_id, sold_at_origin")
    b = pd.read_sql(f"SELECT {cols} FROM v_bookings_with_leg_fare", con)
    fx = pd.read_sql("SELECT month, currency AS sales_currency, rate_to_eur FROM fx_rates", con)
    fl = pd.read_sql("SELECT f.flight_id, f.departure_date, f.season, f.promo_discount_pct, "
                     "f.capacity_business, f.capacity_economy, f.is_test, r.station_id AS station "
                     "FROM flights f JOIN routes r ON r.route_id = f.route_id", con)
    b["month"] = b.departure_date.str[:7]
    b = b.merge(fx, on=["month", "sales_currency"]).merge(
        fl.drop(columns=["departure_date", "station"]), on="flight_id")
    b["leg_eur"] = b.leg_fare * b.rate_to_eur
    b["rev_eur"] = b.leg_eur * b.pax
    b["price_group"] = b.season.map(PRICE_GROUP)
    return b, fl


def wavg(df, col, w="pax"):
    return (df[col] * df[w]).sum() / df[w].sum()


def check_load_factors(b, fl):
    print("## 1. Load factor by route and season (% of seats, both directions)\n")
    pax = b.groupby("flight_id").pax.sum().rename("pax")
    f = fl.join(pax, on="flight_id").fillna({"pax": 0})
    f["cap"] = f.capacity_business + f.capacity_economy
    rows = []
    for sid in (1, 3, 4, 5, 6):
        row = {"Route": NAMES[sid]}
        for k, season in enumerate(g.SEASONS):
            s = f[(f.station == sid) & (f.season == season)]
            lf = 100 * s.pax.sum() / s.cap.sum()
            lo, hi = LF_RANGES[sid][k]
            row[season] = f"{lf:.1f} (target {lo}-{hi}){'' if lo <= lf <= hi else ' *'}"
        rows.append(row)
    md(pd.DataFrame(rows))
    print("`*` = outside the agreed range.\n")
    ber = f[f.station == 2].assign(month=lambda s: s.departure_date.str[:7])
    t = ber.groupby("month").apply(lambda s: 100 * s.pax.sum() / s.cap.sum(), include_groups=False)
    print("Berlin load factor by month (agreed: 45-55 in month 1, 68-74 by month 4):\n")
    md(pd.DataFrame({"Month": t.index, "Load factor %": t.values}))
    j = f.assign(cj=f.capacity_business).join(
        b[b.cabin_id == 2].groupby("flight_id").pax.sum().rename("jpax"), on="flight_id").fillna({"jpax": 0})
    print(f"Network load factor {100 * f.pax.sum() / f.cap.sum():.1f}% (target about 80). "
          f"Business cabin load factor {100 * j.jpax.sum() / j.cj.sum():.1f}%.\n")


def expected_ratio(d, norm):
    """Yield ratio the generator rules should give: seasonal factor x ladder lift x return-leg factor."""
    sp = d.season.map(g.SEASON_PRICE) / norm
    lift = np.where(d.season == "low", 1.0, g.STANDARD_SCALE)
    leg = np.where(d.trip_type == "RT", 1 / (2 * g.ONE_WAY_RATIO), 1.0)
    intro = np.where((d.route_station_id == 2) & (d.departure_date < "2026-01-25"), 0.9, 1.0)
    promo = 1 - d.promo_discount_pct / 100
    return (d.agreed * sp * lift * leg * intro * promo * d.pax).sum() / (d.agreed * d.pax).sum()


def check_yields(b):
    local = b[b.traffic_type == "local"].copy()
    local["agreed"] = [g.FARE_MEAN[c - 1, s - 1] for c, s in zip(local.cabin_id, local.segment_id)]
    local["agreed"] *= local.route_station_id.map({k: v["idx"] for k, v in g.SPEC.items()})
    norm = (b.groupby("flight_id").pax.sum() * b.drop_duplicates("flight_id").set_index("flight_id").season
            .map(g.SEASON_PRICE)).sum() / b.pax.sum()   # pax-weighted mean seasonal price factor
    print("## 2. Average leg yield by cabin and segment (EUR per passenger per leg, local passengers)\n")
    rows = []
    for c, cn in ((1, "Economy"), (2, "Business")):
        for s, sn in enumerate(SEG, start=1):
            d = local[(local.cabin_id == c) & (local.segment_id == s)]
            lo, hi = d.leg_eur.quantile([.1, .9])
            rows.append({"Cabin": cn, "Segment": sn, "Actual": wavg(d, "leg_eur"),
                         "Agreed mean": wavg(d, "agreed"),
                         "Ratio": wavg(d, "leg_eur") / wavg(d, "agreed"), "P10": lo, "P90": hi})
    md(pd.DataFrame(rows), 2)
    print("Agreed mean is the one-way-equivalent mean times the route index. Ratios a little below 1.00 "
          "are expected: low-season departures are not grossed up, so they pull the all-season average down "
          "(see section 3).\n")

    print("## 3. Average leg yield by season group and cabin (local passengers, excluding Berlin)\n")
    rows = []
    for grp in ("low", "shoulder", "peak"):
        for c, cn in ((1, "Economy"), (2, "Business")):
            d = local[(local.price_group == grp) & (local.cabin_id == c) & (local.route_station_id != 2)]
            rows.append({"Season": grp, "Cabin": cn, "Avg yield EUR": wavg(d, "leg_eur"),
                         "Agreed baseline EUR": wavg(d, "agreed"),
                         "Ratio": wavg(d, "leg_eur") / wavg(d, "agreed"),
                         "Expected from rules": expected_ratio(d, norm), "Legs": len(d)})
    md(pd.DataFrame(rows), 2)
    print("Expected from rules = seasonal price factor x ladder lift (1.18 in shoulder and peak, none in low) "
          "x return-leg factor (0.833), averaged over the legs. If the 1.18 were counted twice, "
          "actual would sit well above expected.\n")

    print("Berlin separately (launches 26 Oct 2025 with a 10% introductory discount to 24 Jan 2026):\n")
    ber = local[local.route_station_id == 2]
    rows = []
    for m, d in ber.groupby("month"):
        for c, cn in ((1, "Economy"), (2, "Business")):
            x = d[d.cabin_id == c]
            if len(x):
                rows.append({"Month": m, "Cabin": cn, "Season": x.season.mode().iloc[0],
                             "Avg yield EUR": wavg(x, "leg_eur"), "Agreed baseline EUR": wavg(x, "agreed"),
                             "Ratio": wavg(x, "leg_eur") / wavg(x, "agreed"),
                             "Expected from rules": expected_ratio(x, norm), "Legs": len(x)})
    md(pd.DataFrame(rows), 2)

    print("## 4. One-way vs return pricing (the 60% rule)\n")
    # Outbound legs only: a journey is priced at its outbound flight, so promotions on that flight apply.
    clean = local[(local.leg_seq == 1) & (local.promo_discount_pct == 0)
                  & (local.route_station_id != 2) & (local.season != "low")]
    grp = clean.groupby(["route_id", "cabin_id", "class_rank", "trip_type"]).leg_eur.mean().unstack()
    ratio = (grp["RT"] / grp["OW"]).dropna()
    print(f"Return leg price / one-way price, same route, cabin and class, outbound legs, no promotion: "
          f"median {ratio.median():.3f} (rule implies 0.833, which is 0.5 / 0.6), "
          f"middle 80% of groups {ratio.quantile(.1):.3f} to {ratio.quantile(.9):.3f}.\n")


def check_mix(b):
    print("## 5. Segment mix by route (% of passengers, all legs)\n")
    rows = []
    for sid, sp in g.SPEC.items():
        d = b[b.route_station_id == sid]
        sh = d.groupby("segment_id").pax.sum() / d.pax.sum() * 100
        tgt = sp["mix"] if sid != 2 else (26, 50, 24)
        rows.append({"Route": NAMES[sid], "Business": sh[1], "Leisure": sh[2], "VFR": sh[3],
                     "Target (B/L/V)": "/".join(str(x) for x in tgt) + (" (Berlin averaged)" if sid == 2 else "")})
    md(pd.DataFrame(rows))
    d = b.copy()
    conn = d.groupby("route_station_id").apply(lambda s: s[s.traffic_type == "connecting"].pax.sum() / s.pax.sum() * 100,
                                               include_groups=False)
    print("Connecting share (%), actual vs agreed: " +
          ", ".join(f"{NAMES[k]} {conn[k]:.0f} vs {round(v['conn'] * 100)}" for k, v in g.SPEC.items()) + "\n")
    cab = b.groupby(["segment_id"]).apply(lambda s: s[s.cabin_id == 2].pax.sum() / s.pax.sum() * 100,
                                          include_groups=False)
    print("Business cabin share by segment (agreed 35 / 6 / 3 as relative propensities only; "
          f"achieved {cab[1]:.1f} / {cab[2]:.1f} / {cab[3]:.1f}).\n")


def check_curves(b):
    print("## 6. Booking curves (outbound legs, excluding Berlin; % of a segment's bookings)\n")
    out = b[(b.leg_seq == 1) & (b.route_station_id != 2)]
    bins = [-1, 7, 14, 30, 60, 90, 180, 400]
    labels = ["7-0", "14-8", "30-15", "60-31", "90-61", "180-91", "330-181"]
    rows = []
    for s, sn in enumerate(SEG, start=1):
        d = out[out.segment_id == s]
        cut = pd.cut(d.days_before, bins=bins, labels=labels)
        act = cut.value_counts(normalize=True).reindex(labels) * 100
        tgt = pd.Series(g.WINDOW_SHARE[s - 1][::-1] * 100, index=labels)
        for lab in ("Actual", "Agreed"):
            v = act if lab == "Actual" else tgt
            rows.append({"Segment": sn, "": lab, **{k: v[k] for k in labels},
                         "Avg days out": d.days_before.mean() if lab == "Actual" else float(np.dot(
                             g.WINDOW_SHARE[s - 1], [255, 135, 75, 45, 22, 11, 3]))})
    md(pd.DataFrame(rows))
    inb = b[b.leg_seq == 2]
    print("Inbound legs are booked with their outbound leg, so they book earlier: average days out "
          + ", ".join(f"{sn} {inb[inb.segment_id == s].days_before.mean():.0f}" for s, sn in enumerate(SEG, 1))
          + ".\n")


def check_journeys(b):
    print("## 7. Journeys: return share and stay length\n")
    j = b.sort_values("leg_seq").drop_duplicates("journey_id")
    cnt = b.groupby("journey_id").size()
    two = b[b.journey_id.isin(cnt[cnt == 2].index)]
    d = (pd.to_datetime(two.departure_date) - pd.Timestamp("1970-01-01")).dt.days
    stay = two.assign(day=d).groupby("journey_id").agg(lo=("day", "min"), hi=("day", "max"),
                                                       seg=("segment_id", "first"))
    stay["stay"] = stay.hi - stay.lo
    rows = []
    for s, sn in enumerate(SEG, start=1):
        js = j[j.segment_id == s]
        st = stay[stay.seg == s].stay
        vc = st.value_counts(normalize=True)
        top = ", ".join(f"{int(k)}d {100 * v:.0f}%" for k, v in vc.head(3).items())
        rows.append({"Segment": sn, "Return share %": 100 * (js.trip_type == "RT").mean(),
                     "Agreed %": g.RT_SHARE[s - 1] * 100, "Mean stay": st.mean(),
                     "Min-max": f"{int(st.min())}-{int(st.max())}", "Most common stays": top})
    md(pd.DataFrame(rows))
    one_row_rt = ((j.trip_type == "RT") & (j.journey_id.map(cnt) == 1)).sum()
    print(f"Journeys in the data: {len(j):,}. Return journeys with only one row (return outside the window "
          f"or outbound before it): {one_row_rt:,} ({100 * one_row_rt / (j.trip_type == 'RT').sum():.1f}% of return journeys).\n")


def check_pos(b):
    print("## 8. Point of sale per journey (% of journeys sold at origin, destination or elsewhere)\n")
    j = b.sort_values("leg_seq").drop_duplicates("journey_id").copy()
    europe_origin = j.journey_origin_station_id == j.route_station_id
    beyond = j.beyond_city_id.fillna(0).astype(int) + 6
    dest = np.where(europe_origin, np.where(j.beyond_city_id.isna(), 11, beyond), j.route_station_id)
    j["kind"] = np.select([j.pos_station_id == j.journey_origin_station_id, j.pos_station_id == dest],
                          ["Origin", "Destination"], "Third station")
    rows = []
    for s, sn in enumerate(SEG, start=1):
        sh = j[j.segment_id == s].kind.value_counts(normalize=True) * 100
        tgt = g.POS_MIX[s - 1] * 100
        rows.append({"Segment": sn, "Origin": sh.get("Origin", 0), "Destination": sh.get("Destination", 0),
                     "Third": sh.get("Third station", 0),
                     "Agreed": f"{tgt[0]:.0f} / {tgt[1]:.0f} / {tgt[2]:.0f}"})
    md(pd.DataFrame(rows))


def check_revenue(b, con):
    print("## 9. Revenue sold at each station vs target (EUR millions, whole window)\n")
    tg = pd.read_sql("SELECT * FROM revenue_targets", con)
    sold = b[b.pos_station_id <= 6].groupby(["pos_station_id", "month"]).rev_eur.sum().rename("actual").reset_index()
    m = sold.merge(tg, left_on=["pos_station_id", "month"], right_on=["station_id", "month"])
    rows = []
    for sid, d in m.groupby("pos_station_id"):
        s = b[b.pos_station_id == sid]
        rows.append({"Station": NAMES[sid], "Actual": d.actual.sum() / 1e6, "Target": d.target_revenue_eur.sum() / 1e6,
                     "Actual / target %": 100 * d.actual.sum() / d.target_revenue_eur.sum(),
                     "Months beating target": f"{(d.actual >= d.target_revenue_eur).sum()} of {len(d)}",
                     "Origin-sold %": 100 * s[s.sold_at_origin == 1].rev_eur.sum() / s.rev_eur.sum()})
    md(pd.DataFrame(rows), 1)
    tot = b.rev_eur.sum()
    print(f"Total leg revenue {tot / 1e6:,.0f} million EUR; sold at the HUB {100 * b[b.pos_station_id == 11].rev_eur.sum() / tot:.1f}%, "
          f"at beyond-hub cities {100 * b[b.pos_station_id.between(7, 10)].rev_eur.sum() / tot:.1f}%.\n")


def check_balance(b):
    print("## 10. Directional balance (passengers, both legs, whole window)\n")
    rows = []
    for sid in g.SPEC:
        d = b[b.route_station_id == sid]
        to, fr = d[d.direction == "to_hub"], d[d.direction == "from_hub"]
        rows.append({"Route": NAMES[sid], "To HUB": to.pax.sum(), "From HUB": fr.pax.sum(),
                     "To / from": to.pax.sum() / fr.pax.sum(),
                     "One-way share to HUB %": 100 * to[to.trip_type == "OW"].pax.sum() / to.pax.sum(),
                     "One-way share from HUB %": 100 * fr[fr.trip_type == "OW"].pax.sum() / fr.pax.sum()})
    md(pd.DataFrame(rows), 2)
    print("Directional balance by calendar month (all routes; passengers to the HUB divided by passengers "
          "from it). Above 1 means more traffic is leaving Europe than coming back.\n")
    months = []
    for m in range(1, 13):
        d = b[b.departure_date.str[5:7] == f"{m:02d}"]
        to, fr = d[d.direction == "to_hub"].pax.sum(), d[d.direction == "from_hub"].pax.sum()
        months.append({"Month": m, "To HUB": to, "From HUB": fr, "To / from": to / fr})
    md(pd.DataFrame(months), 2)


def check_integrity(con):
    print("## 11. Integrity\n")
    q = lambda s: con.execute(s).fetchone()[0]  # noqa: E731
    print(f"- Foreign key problems: {len(con.execute('PRAGMA foreign_key_check').fetchall())}")
    print(f"- Bookings over seat capacity (flight and cabin): "
          f"{q('SELECT COUNT(*) FROM (SELECT b.flight_id, b.cabin_id, SUM(b.pax) p FROM bookings b GROUP BY 1,2) x JOIN flights f ON f.flight_id = x.flight_id WHERE x.p > CASE x.cabin_id WHEN 1 THEN f.capacity_economy ELSE f.capacity_business END')}")
    print(f"- Return journeys with two rows whose legs are not in opposite directions: "
          f"{q('SELECT COUNT(*) FROM (SELECT b.journey_id FROM bookings b JOIN flights f ON f.flight_id=b.flight_id JOIN routes r ON r.route_id=f.route_id GROUP BY b.journey_id HAVING COUNT(*)=2 AND COUNT(DISTINCT r.direction)<>2)')}")
    print(f"- Database size: {DB.stat().st_size / 1e6:.1f} MB\n")


def displacement_proposal():
    print("## 12. Proposed displacement cost (EUR per passenger, for your review; not yet in the database)\n")
    print("Method: cost = chance the beyond-hub seat would have sold to someone else x average local fare on that "
          "beyond-hub leg. Both inputs are assumptions.\n")
    prob = {"low": .25, "shoulder": .40, "summer": .60, "christmas": .65}
    fare = {1: {"Bangkok": 260, "Sydney": 480, "Nairobi": 300, "Mumbai": 190},
            2: {"Bangkok": 1100, "Sydney": 1900, "Nairobi": 1200, "Mumbai": 800}}
    print("Chance the beyond-hub seat is displaced: " + ", ".join(f"{k} {int(v * 100)}%" for k, v in prob.items()) + ".\n")
    for c, cn in ((1, "Economy"), (2, "Business")):
        rows = [{"City": city, "Avg local fare": f, **{s: f * p for s, p in prob.items()}}
                for city, f in fare[c].items()]
        print(f"{cn}:\n")
        md(pd.DataFrame(rows), 0)


def main():
    con = sqlite3.connect(DB)
    b, fl = load(con)
    print(f"# Sanity checks on {DB.name}: {len(b):,} booking rows, {b.pax.sum():,} passengers\n")
    check_load_factors(b, fl)
    check_yields(b)
    check_mix(b)
    check_curves(b)
    check_journeys(b)
    check_pos(b)
    check_revenue(b, con)
    check_balance(b)
    check_integrity(con)
    displacement_proposal()


if __name__ == "__main__":
    main()
