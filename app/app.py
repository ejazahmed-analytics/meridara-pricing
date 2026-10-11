"""Meridara pricing case study: Streamlit app.

Illustrative case study using fictitious and simulated data.
Run from the project root:   streamlit run app/app.py
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402
from views import network, overview, rm, station, story, summary  # noqa: E402

st.set_page_config(page_title="Meridara pricing case study", layout="wide", initial_sidebar_state="collapsed")
st.markdown(c.CSS, unsafe_allow_html=True)
c.banner()

PAGES = {
    "Overview": overview,
    "Pricing and Revenue Management (HO)": rm,
    "Network Revenue and Inventory (HO)": network,
    "Station (GM and Sales - local Market)": station,
    "Analyst summary": summary,
    "Data Story": story,
}

left, right = st.columns([3, 1])
with left:
    page = st.selectbox("View as", list(PAGES))
with right:
    cur = st.selectbox("Currency", c.CURRENCIES, help="All money figures are converted at the monthly average "
                       "rate of the month each flight departs. AED is derived from the USD peg.")

PAGES[page].render(cur)
c.footer()
