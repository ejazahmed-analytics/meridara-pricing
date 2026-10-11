"""Helper for writing model outputs to data/results.db.

Illustrative case study using fictitious and simulated data.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DB = ROOT / "data" / "meridara.db"
RESULTS_DB = ROOT / "data" / "results.db"
RESULTS_SCHEMA = ROOT / "sql" / "results_schema.sql"


def open_results(reset_tables):
    """Open results.db, empty the named tables and make sure all tables exist."""
    con = sqlite3.connect(RESULTS_DB)
    for table in reset_tables:
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.executescript(RESULTS_SCHEMA.read_text(encoding="utf-8"))
    return con
