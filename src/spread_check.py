"""Check how much the pricing replay depends on the assumed spread of willingness to pay.

Illustrative case study using fictitious and simulated data.

Runs src/pricing_sim.py without saving, for three spreads, and stores the headline comparisons in
data/results.db (table simulation_spread_check). The app quotes this table.

Run from the project root after pricing_sim.py:   python src/spread_check.py
"""
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

from results_db import RESULTS_DB, open_results

ROOT = Path(__file__).resolve().parents[1]
SPREADS = [0.35, 0.45, 0.60]


def headline(sigma):
    """Revenue by policy in the base scenario for one spread."""
    out = subprocess.run([sys.executable, str(ROOT / "src" / "pricing_sim.py"), "--dry", "--sigma", str(sigma)],
                         capture_output=True, text=True, cwd=ROOT).stdout
    rev = {}
    for line in out.splitlines():
        m = re.match(r"\| (observed|buckets|continuous|continuous_lf) \| ([\d.]+) \|", line)
        if m and m.group(1) not in rev:          # the headline table comes first; later tables repeat the names
            rev[m.group(1)] = float(m.group(2))
    return rev


def main():
    rows = []
    for s in SPREADS:
        r = headline(s)
        rows.append(dict(spread=s,
                         continuous_vs_buckets_pct=100 * (r["continuous"] / r["buckets"] - 1),
                         floor_vs_buckets_pct=100 * (r["continuous_lf"] / r["buckets"] - 1),
                         continuous_vs_as_flown_pct=100 * (r["continuous"] / r["observed"] - 1),
                         floor_vs_as_flown_pct=100 * (r["continuous_lf"] / r["observed"] - 1)))
        print(rows[-1])
    rc = open_results(["simulation_spread_check"])
    rc.execute("""CREATE TABLE IF NOT EXISTS simulation_spread_check (
        spread REAL, continuous_vs_buckets_pct REAL, floor_vs_buckets_pct REAL,
        continuous_vs_as_flown_pct REAL, floor_vs_as_flown_pct REAL)""")
    pd.DataFrame(rows).round(2).to_sql("simulation_spread_check", rc, if_exists="append", index=False)
    rc.commit()
    rc.close()


if __name__ == "__main__":
    main()
