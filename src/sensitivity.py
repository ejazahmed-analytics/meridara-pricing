"""Phase 4a: price sensitivity by segment.

Illustrative case study using fictitious and simulated data.

About 15% of flights received a random promotional discount, unrelated to
demand. Because the promotion is random, the effect of price on the number of
originating passengers can be read directly from it. We fit a Poisson
regression of originating passengers (outbound legs) per flight and segment on
the log price ratio (1 - promotion) and the log competitor index, controlling
for route, month, weekday and events. The price coefficient is the elasticity.

Training flights only (departures to 31 August 2025).

Run from the project root:   python src/sensitivity.py
"""
import sqlite3
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from forecast import load, md
from results_db import DATA_DB, open_results

SEGMENTS = {1: "Business", 2: "Leisure", 3: "VFR"}
GENERATOR_PRICE = {1: -0.5, 2: -1.6, 3: -1.3}      # values the synthetic data was built with
GENERATOR_COMP = {1: 0.2, 2: 0.5, 3: 0.5}
FLAGS = ["xmas", "easter", "eid", "diwali", "school", "autumn"]


def build_data(b, fl):
    """Originating passengers per flight and segment, with price and control variables."""
    out = (b[b.leg_seq == 1].groupby(["flight_id", "segment_id"]).pax.sum().rename("y"))
    tr = fl[fl.is_test == 0].copy()
    idx = pd.MultiIndex.from_product([tr.flight_id, [1, 2, 3]], names=["flight_id", "segment_id"])
    d = pd.DataFrame(index=idx).join(out).fillna(0).reset_index().merge(tr, on="flight_id")
    total = b.groupby("flight_id").pax.sum().rename("total_pax")
    d = d.join(total, on="flight_id")
    d["full"] = d.total_pax >= 0.97 * d.cap_total
    d["lp"] = np.log(1 - d.promo / 100)                      # log price ratio (0 when no promotion)
    d["lc"] = np.log(d.comp_idx / 100)
    d["week"] = (d.departure_date - d.departure_date.min()).dt.days // 7
    return d


def fit(d, seg):
    """Poisson regression for one segment with week-clustered standard errors."""
    s = d[d.segment_id == seg]
    flags = " + ".join(f for f in FLAGS if s[f].nunique() > 1)       # skip events absent from this sample
    model = smf.glm(f"y ~ lp + lc + C(route_id) + C(month) + C(weekday) + {flags}", data=s,
                    family=sm.families.Poisson())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return model.fit(cov_type="cluster", cov_kwds={"groups": s.week}), len(s)


def main():
    con = sqlite3.connect(DATA_DB)
    b, fl = load(con)
    con.close()
    d = build_data(b, fl)
    print(f"{d.flight_id.nunique():,} training flights, {int((d.promo > 0).groupby(d.flight_id).first().sum()):,} "
          f"with a promotion, {100 * d.groupby('flight_id').full.first().mean():.1f}% at or above 97% full\n")

    # Capacity hides demand on full flights and pulls estimates toward zero. Low-season flights
    # rarely fill, so they give a cleaner read. The sample is chosen by season, not by outcome.
    samples = {"all training flights": d, "low-season flights": d[d.season == "low"]}
    rows = []
    for sample, data in samples.items():
        for seg in SEGMENTS:
            res, n = fit(data, seg)
            for par, key, truth in (("price", "lp", GENERATOR_PRICE[seg]), ("competitor", "lc", GENERATOR_COMP[seg])):
                lo, hi = res.conf_int().loc[key]
                rows.append(dict(sample=sample, segment_id=seg, parameter=par, estimate=res.params[key],
                                 ci_low=lo, ci_high=hi, std_err=res.bse[key], n_obs=n, generator_input=truth))
    est = pd.DataFrame(rows)

    print("## Price sensitivity (elasticity of originating demand to price)\n")
    p = est[est.parameter == "price"]
    md(pd.DataFrame({"Sample": p["sample"].values, "Segment": [SEGMENTS[s] for s in p.segment_id],
                     "Estimate": p.estimate.values, "95% low": p.ci_low.values, "95% high": p.ci_high.values,
                     "Value used to build the data": p.generator_input.values,
                     "Range contains it?": ["yes" if lo <= t <= hi else "no" for lo, hi, t in
                                            zip(p.ci_low, p.ci_high, p.generator_input)]}), 2)
    print("## Competitor price effect (elasticity of demand to the competing hub's price index)\n")
    c = est[est.parameter == "competitor"]
    md(pd.DataFrame({"Sample": c["sample"].values, "Segment": [SEGMENTS[s] for s in c.segment_id],
                     "Estimate": c.estimate.values, "95% low": c.ci_low.values, "95% high": c.ci_high.values,
                     "Value used to build the data": c.generator_input.values}), 2)

    rc = open_results(["sensitivity_estimates"])
    est.round(4).to_sql("sensitivity_estimates", rc, if_exists="append", index=False)
    rc.commit()
    rc.close()


if __name__ == "__main__":
    main()
