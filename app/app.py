"""Meridara pricing case study: Streamlit app.

Illustrative case study using fictitious and simulated data.
Run from the project root:   streamlit run app/app.py
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common as c  # noqa: E402
from views import about, network, overview, rm, station, story, summary  # noqa: E402

st.set_page_config(page_title="Meridara pricing case study", layout="wide", initial_sidebar_state="auto")
st.markdown(c.CSS, unsafe_allow_html=True)


def _page(module):
    """A page function that renders one view with the currency chosen in the sidebar."""
    def run():
        module.render(st.session_state["currency"])
    return run


pages = [
    st.Page(_page(overview), title="Overview", url_path="overview", default=True),
    st.Page(_page(rm), title="Pricing and Revenue Management (HO)", url_path="pricing-revenue-management"),
    st.Page(_page(network), title="Network Revenue and Inventory (HO)", url_path="network-revenue-inventory"),
    st.Page(_page(station), title="Station (GM and Sales - local Market)", url_path="station"),
    st.Page(_page(summary), title="Analyst summary", url_path="analyst-summary"),
    st.Page(_page(story), title="Data Story", url_path="data-story"),
    st.Page(_page(about), title="How this was built", url_path="how-this-was-built"),
]
navigation = st.navigation(pages, position="sidebar")

with st.sidebar:
    st.markdown('<div class="brand">Meridara</div><div class="brand-sub">Pricing case study, fictional airline</div>',
                unsafe_allow_html=True)
    st.selectbox("Currency", c.CURRENCIES, key="currency",
                 help="All money figures are converted at the monthly average rate of the month each flight "
                      "departs. AED is derived from the USD peg.")
    st.markdown(f'<div class="brand-sub">{c.SHORT_DISCLAIMER}</div>', unsafe_allow_html=True)

navigation.run()
