"""Shared helpers for the Meridara app: data access, currency, layout, styling.

Illustrative case study using fictitious and simulated data.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
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

# Palette: navy text and header, royal blue and teal as main accents, coral for highlights, amber for small touches.
NAVY, ROYAL, TEAL, CORAL, AMBER = "#0B1F3A", "#1F4FD8", "#0E8F8F", "#F0644D", "#E5A800"
SLATE, BG, LINE = "#4A5D7A", "#EEF3FA", "#D5DEEC"

POLICY_LABELS = {"observed": "As flown", "buckets": "Simplified buckets (EMSR-b)",
                 "continuous": "Continuous pricing", "continuous_lf": "Continuous with route load factor floor"}
POLICY_SHORT = {"observed": "As flown", "buckets": "Buckets", "continuous": "Continuous",
                "continuous_lf": "Continuous + floor"}
POLICY_COLORS = {"observed": SLATE, "buckets": CORAL, "continuous": ROYAL, "continuous_lf": TEAL}
SEGMENT_NAMES = {1: "Business", 2: "Leisure", 3: "VFR"}
SEGMENT_COLORS = {"Business": ROYAL, "Leisure": TEAL, "VFR": CORAL}
STATION_NAMES = {1: "Frankfurt", 2: "Berlin", 3: "London", 4: "Paris", 5: "Milan", 6: "Madrid"}
CITY_NAMES = {0: "Local", 1: "Bangkok", 2: "Sydney", 3: "Nairobi", 4: "Mumbai"}
WINDOWS = ["330-181", "180-91", "90-61", "60-31", "30-15", "14-8", "7-0"]


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


def headline(cur):
    """The numbers the Overview, Analyst summary and Data Story all quote."""
    s = sim_summary(cur)
    obs, bk, ct, lf = (policy_row(s, "base", p) for p in ("observed", "buckets", "continuous", "continuous_lf"))
    return dict(s=s, obs=obs, bk=bk, ct=ct, lf=lf,
                gain=100 * (ct.revenue / obs.revenue - 1), gain_bk=100 * (ct.revenue / bk.revenue - 1),
                gain_lf=100 * (lf.revenue / obs.revenue - 1), bk_vs_obs=100 * (bk.revenue / obs.revenue - 1),
                gain_lf_bk=100 * (lf.revenue / bk.revenue - 1),
                pax_ct=100 * (ct.pax / obs.pax - 1), pax_lf=100 * (lf.pax / obs.pax - 1))


@st.cache_data(show_spinner=False)
def spread_text():
    """Plain wording for how the gain against buckets moves with the assumed spread of willingness to pay."""
    t = query("results", "SELECT * FROM simulation_spread_check ORDER BY spread")
    lo, hi = t.spread.min(), t.spread.max()
    a, b = t.continuous_vs_buckets_pct.min(), t.continuous_vs_buckets_pct.max()
    return (f"between {lo:.2f} and {hi:.2f} the gain against buckets stays between about {a:+.0f}% and {b:+.0f}%")


def vs_text(x):
    """'4.7% more' or '4.7% less' for a percentage difference."""
    return f"{abs(x):.1f}% {'more' if x >= 0 else 'less'}"


def floor_vs_continuous(h):
    """Plain wording for how the route-level floor compares with unconstrained continuous pricing."""
    d = h["gain_lf"] - h["gain"]
    if d >= 0:
        return (f"The floor earns {abs(d):.1f} points more than unconstrained continuous pricing, because "
                f"the unconstrained price rule leaves seats empty.")
    return f"The floor gives up {abs(d):.1f} points of the continuous pricing gain."


# ---------------------------------------------------------------------
# Layout helpers
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


def hero(title, question, cur=None):
    """Navy header band: title and question on the left, small pills on the right, then the disclaimer."""
    pills = ["Fictional carrier", "Simulated data", "Held out: Sep 2025 to Feb 2026"]
    if cur:
        pills.append(f"Currency: {cur}")
    pill_html = "".join(f'<span class="pill">{p}</span>' for p in pills)
    st.markdown(f'<div class="hero"><div class="hero-left"><div class="hero-brand">MERIDARA <span>PRICING CASE STUDY</span></div>'
                f'<div class="hero-title">{title}</div>'
                f'<div class="hero-q">{question}</div></div><div class="hero-pills">{pill_html}</div></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="disclaimer">{DISCLAIMER}</div>', unsafe_allow_html=True)


def kpi_row(items):
    """A row of KPI cards: (label, value, note, accent colour, optional delta text, delta is good)."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value, note, color = item[:4]
        delta = item[4] if len(item) > 4 else None
        good = item[5] if len(item) > 5 else True
        badge = ""
        if delta:
            arrow = "&#9650;" if not str(delta).startswith("-") else "&#9660;"
            klass = "good" if good else "bad"
            badge = f'<span class="delta {klass}">{arrow} {delta}</span> '
        with col:
            st.markdown(f'<div class="kpi" style="border-top-color:{color}"><div class="kpi-label">{label}</div>'
                        f'<div class="kpi-value">{value}</div><div class="kpi-note">{badge}{note}</div></div>',
                        unsafe_allow_html=True)
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)


@contextmanager
def panel(title):
    """A white panel with a small title; charts and takeaways go inside."""
    box = st.container(border=True)
    with box:
        st.markdown(f'<div class="panel-title">{title}</div>', unsafe_allow_html=True)
        yield


def takeaway(text):
    st.markdown(f'<div class="takeaway">{text}</div>', unsafe_allow_html=True)


def style(fig, height=300, legend=True):
    """Apply the common chart style. The legend sits above the plot so it never meets the axis title."""
    is_pie = bool(fig.data) and fig.data[0].type == "pie"
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=40 if legend else 14, b=10), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(size=12, color=NAVY),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11, color=NAVY)) if legend else dict(),
        showlegend=legend, hoverlabel=dict(font_size=12, font_color="white", bgcolor=NAVY),
        colorway=[ROYAL, TEAL, CORAL, AMBER, SLATE])
    if is_pie:
        # Leave room inside the figure: the donut sits in the upper part, short labels outside it, legend underneath.
        fig.update_traces(domain=dict(x=[0.12, 0.88], y=[0.24, 0.90]))
        fig.update_layout(height=height + 70, margin=dict(l=20, r=20, t=20, b=10), showlegend=True,
                          legend=dict(orientation="h", yanchor="bottom", y=0, x=0.5, xanchor="center",
                                      font=dict(size=12, color=NAVY)))
    fig.update_xaxes(showgrid=False, linecolor=LINE, tickfont=dict(color=NAVY), title_font=dict(color=NAVY),
                     automargin=True)
    fig.update_yaxes(gridcolor="#E3EAF5", zeroline=False, tickfont=dict(color=NAVY), title_font=dict(color=NAVY),
                     automargin=True)
    return fig


def chart(fig, takeaway_text, height=300, legend=True):
    """Draw a chart followed by its one or two line takeaway (call inside a panel)."""
    st.plotly_chart(style(fig, height, legend), width="stretch", config={"displayModeBar": False})
    takeaway(takeaway_text)


def notes(markdown_text):
    """Longer explanations, methods and caveats, collapsed at the bottom of a page."""
    st.markdown('<div class="gap"></div>', unsafe_allow_html=True)
    with st.expander("How to read this"):
        st.markdown(markdown_text)
    st.markdown(f'<div class="footer">{SHORT_DISCLAIMER}</div>', unsafe_allow_html=True)


CSS = f"""
<style>
/* Page frame: navy header, light page background, navy text */
.stApp {{ background: {BG}; color: {NAVY}; }}
header[data-testid="stHeader"] {{ background: {NAVY}; height: 2.6rem; min-height: 2.6rem; }}
header[data-testid="stHeader"] * {{ color: #FFFFFF !important; fill: #FFFFFF !important; }}
[data-testid="stMainBlockContainer"] {{ padding: 0 2rem 2rem 2rem !important; max-width: 1280px; }}
.stApp p, .stApp li, .stApp label, .stApp span, .stApp div[data-testid="stMarkdownContainer"],
[data-testid="stCaptionContainer"], [data-testid="stWidgetLabel"] p {{ color: {NAVY}; opacity: 1; }}
h1, h2, h3, h4 {{ color: {NAVY} !important; }}
html, body, [data-testid="stMain"], section.main {{ scroll-padding-top: 4rem; }}
.panel-title, [data-testid="stVerticalBlockBorderWrapper"], .kpi, h1, h2, h3, h4 {{ scroll-margin-top: 4rem; }}

/* Navy hero band, full width, with pills on the right */
.hero {{ background: {NAVY}; margin: 0 -2rem 0.9rem -2rem; padding: 3.5rem 2rem 1.2rem 2rem;
         box-shadow: 0 0 0 100vmax {NAVY}; clip-path: inset(0 -100vmax);
         display: flex; flex-wrap: wrap; gap: 0.8rem; align-items: flex-end; justify-content: space-between; }}
.hero-brand {{ color: #FFFFFF !important; font-weight: 800; letter-spacing: 0.14em; font-size: 0.85rem;
              border-left: 4px solid {AMBER}; padding-left: 0.55rem; margin-bottom: 0.45rem; }}
.hero-brand span {{ font-weight: 600; letter-spacing: 0.06em; font-size: 0.75rem; margin-left: 0.4rem; }}
.hero-title {{ color: #FFFFFF !important; font-size: 1.9rem; font-weight: 800; line-height: 1.2; }}
.hero-q {{ color: #FFFFFF !important; font-size: 1rem; margin-top: 0.3rem; }}
.hero-pills {{ display: flex; flex-wrap: wrap; gap: 0.4rem; }}
.pill {{ color: #FFFFFF !important; border: 1px solid #FFFFFF; border-radius: 999px; padding: 0.15rem 0.7rem;
         font-size: 0.78rem; font-weight: 600; white-space: nowrap; }}
.hero *, .hero span {{ color: #FFFFFF !important; }}
.disclaimer {{ background: #FFF6DD; border: 1px solid #F0DFA6; border-left: 6px solid {AMBER}; color: {NAVY};
               padding: 0.5rem 0.8rem; font-size: 0.78rem; line-height: 1.4; border-radius: 4px; margin: 0 0 1rem 0; }}
.disclaimer b {{ color: {NAVY}; }}

/* KPI cards: white, coloured top border, bold number, delta badge */
.kpi {{ background: #FFFFFF; border-radius: 8px; border-top: 5px solid {ROYAL}; padding: 0.75rem 1rem 0.8rem 1rem;
        box-shadow: 0 1px 4px rgba(11,31,58,0.14); height: 100%; }}
.kpi-label {{ font-size: 0.82rem; font-weight: 700; color: {NAVY}; text-transform: uppercase; letter-spacing: 0.02em; }}
.kpi-value {{ font-size: 2.1rem; font-weight: 800; color: {NAVY}; line-height: 1.15; margin: 0.15rem 0; }}
.kpi-note {{ font-size: 0.8rem; color: {NAVY}; }}
.delta {{ display: inline-block; font-weight: 700; font-size: 0.78rem; border-radius: 4px; padding: 0 0.35rem; color: {NAVY}; }}
.delta.good {{ background: #D5F0EC; }} .delta.bad {{ background: #FFE0DA; }}
.gap {{ height: 0.8rem; }}

/* Panels */
[data-testid="stVerticalBlockBorderWrapper"] {{ background: #FFFFFF; border: 1px solid {LINE} !important;
        border-radius: 8px; box-shadow: 0 1px 4px rgba(11,31,58,0.10); }}
.panel-title {{ font-size: 1rem; font-weight: 800; color: {NAVY}; margin-bottom: 0.2rem; }}
.takeaway {{ color: {NAVY}; font-size: 0.9rem; font-weight: 600; border-left: 4px solid {CORAL};
             padding-left: 0.6rem; margin: 0.2rem 0 0.4rem 0; line-height: 1.35; }}
.callout {{ background: #E6EEFF; border: 2px solid {ROYAL}; border-left: 10px solid {ROYAL}; border-radius: 8px;
            padding: 0.9rem 1.1rem; color: {NAVY}; }}
.callout-title {{ font-size: 0.85rem; font-weight: 800; letter-spacing: 0.03em; text-transform: uppercase; }}
.callout-main {{ font-size: 1.35rem; font-weight: 800; margin: 0.2rem 0; }}
.team {{ background: #FFFFFF; border-radius: 8px; border-top: 5px solid {ROYAL}; padding: 0.8rem 1rem;
         box-shadow: 0 1px 4px rgba(11,31,58,0.14); height: 100%; }}
.team-name {{ font-size: 0.95rem; font-weight: 800; }}
.team-number {{ font-size: 1.9rem; font-weight: 800; margin: 0.1rem 0; }}
.team-text {{ font-size: 0.88rem; line-height: 1.35; }}
.draft {{ background: #FFF0ED; border: 2px dashed {CORAL}; border-radius: 6px; padding: 0.5rem 0.8rem; margin: 0.4rem 0;
          font-weight: 800; color: {NAVY}; }}
.footer {{ color: {NAVY}; font-size: 0.8rem; text-align: center; margin-top: 1.5rem; padding-top: 0.6rem;
           border-top: 1px solid {LINE}; }}
[data-testid="stExpander"] {{ background: #FFFFFF; border: 1px solid {LINE}; border-radius: 8px; }}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {{ color: {NAVY} !important; font-weight: 700; }}

/* Sidebar: white, navy text, long page names wrap instead of being cut */
[data-testid="stSidebar"] {{ background: #FFFFFF; border-right: 1px solid {LINE}; }}
[data-testid="stSidebar"] * {{ color: {NAVY}; }}
[data-testid="stSidebarNavLink"] {{ height: auto; min-height: 2.4rem; align-items: flex-start; padding: 0.45rem 0.7rem; }}
[data-testid="stSidebarNavLink"] span {{ white-space: normal !important; overflow: visible !important;
        text-overflow: clip !important; line-height: 1.25; font-weight: 600; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background: #E6EEFF; border-left: 5px solid {ROYAL}; }}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{ font-weight: 800; }}
.brand {{ font-size: 1.4rem; font-weight: 800; color: {NAVY}; }}
.brand-sub {{ font-size: 0.8rem; color: {NAVY}; margin-bottom: 0.6rem; }}
div[data-baseweb="select"] > div {{ background: #FFFFFF; border: 1px solid #9FB1CE; }}
div[data-baseweb="select"] span, div[data-baseweb="select"] div {{ color: {NAVY} !important; }}


/* Data Story: hero, insight cards, callouts, numbered recommendations */
.story-hero {{ background-color: {NAVY}; background-image: linear-gradient(135deg, {NAVY} 0%, #123A6B 100%); border-radius: 12px; padding: 1.5rem 1.6rem;
               margin-bottom: 1rem; }}
.story-hero * {{ color: #FFFFFF !important; }}
.story-kicker {{ font-size: 0.78rem; font-weight: 700; letter-spacing: 0.06em; border-left: 4px solid {AMBER}; padding-left: 0.6rem; }}
.story-title {{ font-size: 1.9rem; font-weight: 800; line-height: 1.2; margin: 0.6rem 0 0.4rem 0; max-width: 46rem; }}
.story-intro {{ font-size: 1rem; line-height: 1.45; max-width: 44rem; }}
.story-stats {{ display: flex; flex-wrap: wrap; gap: 1.6rem; margin-top: 1.1rem; }}
.story-num {{ font-size: 2rem; font-weight: 800; line-height: 1.1; }}
.story-cap {{ font-size: 0.8rem; max-width: 11rem; }}
.insight {{ background: #FFFFFF; border-radius: 8px; border-top: 5px solid {ROYAL}; padding: 0.8rem 1rem; margin-bottom: 0.8rem;
            box-shadow: 0 1px 4px rgba(11,31,58,0.14); }}
.insight-kicker {{ font-size: 0.72rem; font-weight: 800; letter-spacing: 0.05em; color: {NAVY}; }}
.insight-title {{ font-size: 1.1rem; font-weight: 800; color: {NAVY}; margin: 0.15rem 0 0.25rem 0; line-height: 1.25; }}
.insight-text {{ font-size: 0.9rem; line-height: 1.4; color: {NAVY}; }}
.co {{ border-radius: 6px; padding: 0.7rem 0.9rem; font-size: 0.9rem; line-height: 1.4; color: {NAVY}; height: 100%; }}
.co-opp {{ background: #E3ECFF; border-left: 6px solid {ROYAL}; }}
.co-watch {{ background: #FFF3CC; border-left: 6px solid {AMBER}; }}
.co-risk {{ background: #FFE3DE; border-left: 6px solid {CORAL}; }}
.rec {{ display: flex; gap: 0.8rem; background: #FFFFFF; border-radius: 8px; padding: 0.7rem 1rem; margin-bottom: 0.5rem;
        box-shadow: 0 1px 4px rgba(11,31,58,0.10); }}
.rec-n {{ flex: 0 0 2rem; height: 2rem; border-radius: 6px; background: {NAVY}; color: #FFFFFF !important; font-weight: 800;
          display: flex; align-items: center; justify-content: center; }}
.rec-h {{ font-weight: 800; color: {NAVY}; }} .rec-t {{ font-size: 0.9rem; line-height: 1.4; color: {NAVY}; }}


/* Pipeline steps on the About page */
.flow {{ display: flex; flex-wrap: wrap; gap: 0.7rem; }}
.flow-step {{ flex: 1 1 9.5rem; background: #F7F9FD; border: 1px solid {LINE}; border-top: 5px solid {ROYAL}; border-radius: 8px;
              padding: 0.6rem 0.8rem; }}
.flow-n {{ font-weight: 800; font-size: 0.8rem; color: {NAVY}; }}
.flow-t {{ font-weight: 800; font-size: 1.05rem; color: {NAVY}; }}
.flow-x {{ font-size: 0.85rem; line-height: 1.35; color: {NAVY}; }}

@media (max-width: 640px) {{
  [data-testid="stMainBlockContainer"] {{ padding: 0 1rem 2rem 1rem !important; }}
  .hero {{ margin: 0 -1rem 0.9rem -1rem; padding: 3.5rem 1rem 1rem 1rem; }}
  .hero-title {{ font-size: 1.45rem; }} .kpi-value {{ font-size: 1.7rem; }}
}}
</style>
"""
