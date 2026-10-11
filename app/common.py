"""Shared helpers for the Meridara app: data access, currency, banner, styling.

Illustrative case study using fictitious and simulated data.
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DB = ROOT / "data" / "meridara.db"
RESULTS_DB = ROOT / "data" / "results.db"

CURRENCIES = ["EUR", "GBP", "AUD", "AED", "USD"]

DISCLAIMER = (
    "<b>Illustrative case study using fictitious and simulated data.</b> Meridara is a fictional airline. "
    "All bookings, fares, seat volumes, revenue figures, forecasts and results in this project are "
    "synthetically generated and do not represent the commercial performance, data, systems or practices "
    "of any real airline, airport, agency or data provider. Public figures used for calibration are cited "
    "in the README. Methods follow published revenue management literature. This project is a personal "
    "portfolio piece created to demonstrate analytical and data science capability, and is not affiliated "
    "with or endorsed by any employer, past or present."
)
SHORT_DISCLAIMER = "Fictional airline, simulated data. For illustration only."

# Neutral palette that resembles no real airline.
TEAL, OCHRE, SLATE, GREEN, RED, SAND, GREY = "#0F5C63", "#C98A2B", "#34495E", "#2E7D5B", "#B5483A", "#F4F1EA", "#8A939B"
POLICY_LABELS = {"observed": "As flown", "buckets": "Simplified buckets (EMSR-b)",
                 "continuous": "Continuous pricing", "continuous_lf": "Continuous with load factor floor"}
POLICY_COLORS = {"observed": SLATE, "buckets": OCHRE, "continuous": TEAL, "continuous_lf": GREEN}
SEGMENT_NAMES = {1: "Business", 2: "Leisure", 3: "VFR"}
SEGMENT_COLORS = {"Business": SLATE, "Leisure": OCHRE, "VFR": TEAL}
STATION_NAMES = {1: "Frankfurt", 2: "Berlin", 3: "London", 4: "Paris", 5: "Milan", 6: "Madrid"}
CITY_NAMES = {0: "Local", 1: "Bangkok", 2: "Sydney", 3: "Nairobi", 4: "Mumbai"}


# ---------------------------------------------------------------------
# Data access (read-only, cached)
# ---------------------------------------------------------------------


@st.cache_resource
def _connection(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)


@st.cache_data(show_spinner=False)
def query(db, sql):
    """Run a read-only SQL query on 'data' (meridara.db) or 'results' (results.db)."""
    path = DATA_DB if db == "data" else RESULTS_DB
    return pd.read_sql(sql, _connection(str(path)))


@st.cache_data(show_spinner=False)
def fx_pivot():
    df = query("data", "SELECT month, currency, rate_to_eur FROM fx_rates")
    return df.pivot(index="month", columns="currency", values="rate_to_eur")


def convert(df, cols, cur, month_col="month"):
    """Convert EUR columns to the display currency at each row's month rate."""
    if cur == "EUR":
        return df
    rate = df[month_col].map(fx_pivot()[cur])
    out = df.copy()
    for c in cols:
        out[c] = out[c] / rate
    return out


@st.cache_data(show_spinner=False)
def flights_table():
    """One row per flight with route, station, month and capacity."""
    return query("data", """SELECT f.flight_id, f.route_id, f.departure_date, substr(f.departure_date, 1, 7) AS month,
                                   f.season, f.promo_discount_pct, f.is_test, f.capacity_business, f.capacity_economy,
                                   r.station_id, r.direction, e.event_name
                            FROM flights f JOIN routes r ON r.route_id = f.route_id
                            LEFT JOIN events e ON e.event_id = f.event_id""")


@st.cache_data(show_spinner=False)
def sim_summary(cur):
    """Revenue, passengers, average fare and load factor by scenario and policy, in the display currency."""
    res = query("results", "SELECT * FROM simulation_results")
    ft = query("results", "SELECT * FROM simulation_flights")
    fl = flights_table()[["flight_id", "month", "station_id"]]
    res = convert(res.merge(fl, on="flight_id"), ["revenue_eur"], cur)
    seats = ft.groupby("flight_id")[["capacity", "inbound_pax"]].sum()
    rows = []
    for (scen, pol), g in res.groupby(["scenario", "policy"]):
        flights = g.flight_id.unique()
        lf = (g.pax.sum() + seats.loc[flights].inbound_pax.sum()) / seats.loc[flights].capacity.sum()
        rows.append(dict(scenario=scen, policy=pol, revenue=g.revenue_eur.sum(), pax=g.pax.sum(),
                         avg_fare=g.revenue_eur.sum() / g.pax.sum(), load_factor=100 * lf))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def sim_by(cur, by):
    """Base-scenario revenue and passengers by policy and 'by' ('station_id' or 'segment_id')."""
    res = query("results", "SELECT * FROM simulation_results WHERE scenario = 'base'")
    fl = flights_table()[["flight_id", "month", "station_id"]]
    res = convert(res.merge(fl, on="flight_id"), ["revenue_eur"], cur)
    return res.groupby([by, "policy"])[["pax", "revenue_eur"]].sum().reset_index()


def policy_row(summary, scenario, policy):
    return summary[(summary.scenario == scenario) & (summary.policy == policy)].iloc[0]


# ---------------------------------------------------------------------
# Formatting and layout
# ---------------------------------------------------------------------


def money(x, cur, unit="m"):
    """Format a money amount, for example 'EUR 84.7m'."""
    if unit == "m":
        return f"{cur} {x / 1e6:,.1f}m"
    if unit == "k":
        return f"{cur} {x / 1e3:,.0f}k"
    return f"{cur} {x:,.0f}"


def pct(x, signed=False, digits=1):
    return f"{x:+.{digits}f}%" if signed else f"{x:.{digits}f}%"


def banner():
    """The disclaimer, shown at the top of every page."""
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)


def footer():
    st.markdown(f'<div class="footer">{SHORT_DISCLAIMER}</div>', unsafe_allow_html=True)


def takeaway(text):
    """One-line takeaway under a chart, in business language."""
    st.markdown(f'<div class="takeaway">{text}</div>', unsafe_allow_html=True)


def style(fig, height=340, legend=True):
    """Apply the common chart style (works on narrow screens too)."""
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=30, b=8), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(size=12, color=SLATE),
        legend=dict(orientation="h", yanchor="top", y=-0.18, x=0) if legend else dict(),
        showlegend=legend, hoverlabel=dict(font_size=12))
    fig.update_xaxes(showgrid=False, linecolor="#D9D5CB")
    fig.update_yaxes(gridcolor="#E8E5DC", zeroline=False)
    return fig


def show(fig, takeaway_text, height=340, legend=True):
    """Draw a chart followed by its takeaway."""
    st.plotly_chart(style(fig, height, legend), width="stretch", config={"displayModeBar": False})
    takeaway(takeaway_text)


def metric_card(label, value, note=""):
    st.markdown(f'<div class="card"><div class="card-label">{label}</div><div class="card-value">{value}</div>'
                f'<div class="card-note">{note}</div></div>', unsafe_allow_html=True)


CSS = f"""
<style>
.block-container {{ padding-top: 3.2rem; padding-bottom: 2rem; max-width: 1100px; }}
.disclaimer {{ background: #FBF3DC; border: 1px solid #E3CF93; border-left: 5px solid {OCHRE}; color: #4A3F1F;
               padding: 0.55rem 0.8rem; font-size: 0.74rem; line-height: 1.35; border-radius: 4px; margin-bottom: 0.8rem; }}
.footer {{ color: {GREY}; font-size: 0.75rem; text-align: center; margin-top: 2rem; padding-top: 0.6rem;
           border-top: 1px solid #E3DFD3; }}
.takeaway {{ color: {TEAL}; font-size: 0.88rem; font-weight: 600; margin: -0.2rem 0 1.1rem 0; }}
.card {{ background: {SAND}; border-radius: 6px; padding: 0.7rem 0.9rem; border-top: 3px solid {TEAL}; height: 100%; }}
.card-label {{ font-size: 0.78rem; color: {SLATE}; }}
.card-value {{ font-size: 1.6rem; font-weight: 700; color: {TEAL}; line-height: 1.2; }}
.card-note {{ font-size: 0.78rem; color: {GREY}; }}
.draft {{ background: #FFF4F2; border: 1px dashed {RED}; border-radius: 6px; padding: 0.7rem 0.9rem; margin: 0.6rem 0; }}
.draft-tag {{ color: {RED}; font-weight: 700; font-size: 0.8rem; }}
h1 {{ font-size: 1.7rem !important; color: {TEAL}; }}
h2 {{ font-size: 1.25rem !important; color: {SLATE}; }}
/* Long labels in the sidebar menu wrap instead of being cut off, also on phones. */
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p, [data-testid="stRadio"] label p {{
    white-space: normal !important; overflow-wrap: anywhere; }}
div[data-baseweb="select"] > div {{ white-space: normal !important; height: auto; min-height: 2.4rem; }}
div[data-baseweb="select"] span {{ white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}
@media (max-width: 640px) {{ .card-value {{ font-size: 1.3rem; }} .block-container {{ padding-left: 1rem; padding-right: 1rem; }} }}
</style>
"""
