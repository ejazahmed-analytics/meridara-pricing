"""How this was built: design approach, tools, data sourcing and reproducibility."""
import pandas as pd
import streamlit as st

import common as c


@st.cache_data(show_spinner=False)
def _facts():
    n_book = int(c.query("data", "SELECT COUNT(*) AS n FROM bookings").n.iloc[0])
    n_tables = int(c.query("data", "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table'").n.iloc[0])
    n_flights = int(c.query("data", "SELECT COUNT(*) AS n FROM flights").n.iloc[0])
    win = c.query("data", "SELECT MIN(departure_date) AS a, MAX(departure_date) AS b FROM flights").iloc[0]
    return n_book, n_tables, n_flights, win.a, win.b


def _step(n, title, text, color):
    return (f'<div class="flow-step" style="border-top-color:{color}"><div class="flow-n">{n}</div>'
            f'<div class="flow-t">{title}</div><div class="flow-x">{text}</div></div>')


def render(cur):
    c.hero("How this was built", "Design approach, tools, data sources and how to reproduce it", cur)
    n_book, n_tables, n_flights, d0, d1 = _facts()
    db_mb = c.DATA_DB.stat().st_size / 1e6
    res_mb = c.RESULTS_DB.stat().st_size / 1e6

    c.kpi_row([
        ("Simulated flights", f"{n_flights:,}", f"{d0} to {d1}", c.ROYAL),
        ("Booking rows", f"{n_book:,}", "one row per flight leg of a booking", c.TEAL),
        ("Data tables", f"{n_tables}", f"database {db_mb:.0f} MB, model outputs {res_mb:.0f} MB", c.CORAL),
        ("Real data used", "0", "all bookings and fares are simulated", c.AMBER),
    ])

    with c.panel("The pipeline, in six steps"):
        steps = [
            ("1", "Generate", "A seeded generator builds flights, journeys, fares and bookings.", c.ROYAL),
            ("2", "Store", "Everything is loaded into SQLite with SQL tables and views.", c.TEAL),
            ("3", "Forecast", "Pickup baseline and gradient boosting, tested on held-out months.", c.CORAL),
            ("4", "Estimate", "Price sensitivity by segment from random promotions.", c.AMBER),
            ("5", "Replay", "Calibrate the bucket policy on the training period, then compare it with continuous pricing.", c.ROYAL),
            ("6", "Present", "Summary tables feed this Streamlit app, with a currency filter.", c.TEAL),
        ]
        st.markdown('<div class="flow">' + "".join(_step(*s) for s in steps) + "</div>", unsafe_allow_html=True)
        c.takeaway("Each step is a short script that reads the previous step's output, so the whole result can be rebuilt from one seed.")

    left, right = st.columns(2)
    with left:
        with c.panel("How the dashboard was designed"):
            st.markdown(
                "- **Three lenses, one dataset.** Pricing and Revenue Management, Network Revenue and Inventory, and Station "
                "each get a page that starts with KPI cards, then a grid of charts with a one or two line takeaway.\n"
                "- **An analyst page on top.** The Analyst summary and Data Story bring the three views together and show where "
                "they disagree.\n"
                "- **Numbers come from the data.** Every takeaway sentence is generated from the databases, so the text stays "
                "accurate when the data changes.\n"
                "- **Readable design.** Dark text on light backgrounds, built to read well on desktop and mobile.\n"
                "- **Honest labels.** The disclaimer is on every page, and charts note simplifications.")
    with right:
        with c.panel("Guardrails"):
            st.markdown(
                "- **Fictional carrier only.** Meridara, with the hub labelled HUB. No real airline names, logos or colours.\n"
                "- **Synthetic data only.** No employer data or methods; only textbook and published revenue management methods.\n"
                "- **Tested on unseen data.** Every model is evaluated on months it never saw during training.\n"
                "- **Stated simplifications.** For example, a one-way fare is set at 60% of the return fare.")

    with c.panel("Tools used"):
        tools = pd.DataFrame([
            ("Data generation", "Python 3.11, pandas, NumPy, SciPy", "Seeded synthetic flights, journeys, fares and bookings"),
            ("Database", "SQLite and SQL", "Schema, views and joins; the data file is about 33 MB"),
            ("Forecasting", "scikit-learn", "Gradient boosting on remaining pickup, against a historical pickup baseline"),
            ("Price sensitivity", "statsmodels", "Poisson regression with week-clustered errors and 95% ranges"),
            ("Pricing replay", "NumPy, SciPy", "EMSR-b protection levels and revenue-maximising continuous prices"),
            ("App and charts", "Streamlit, Plotly", "Sidebar pages, KPI cards, charts and a currency filter"),
            ("Version control", "Git and GitHub", "Code, docs and generated data in one repository"),
            ("Build assistant", "Claude Code", "AI coding assistant that explained each step as it built; the author reviews every part"),
        ], columns=["Layer", "Tool", "Used for"])
        st.dataframe(tools, hide_index=True, width="stretch")

    with c.panel("How the data is sourced"):
        st.markdown(
            "**All bookings, fares, seat volumes and revenue are generated.** The generator uses a fixed random seed, so "
            "the same code always produces the same data. It simulates 36 months of departures between "
            f"{d0} and {d1}, with journeys that are one-way or return, three passenger segments, fare ladders, "
            "seasons, events such as Easter, Eid and Diwali, a competing-hub price index and a new route launch. Fares drift up "
            "3% a year (ladders and willingness to pay in the replay follow the same drift), so the market grows, and station revenue targets are budgets set in advance (last year's same "
            "month times a growth factor, a planned curve in the first year, a launch plan for the new route).\n\n"
            "**One external source.** Exchange rates are the European Central Bank euro foreign exchange reference rates "
            "(monthly averages for GBP, USD and AUD; ECB Data Portal series EXR.M.GBP.EUR.SP00.A, EXR.M.USD.EUR.SP00.A and "
            "EXR.M.AUD.EUR.SP00.A). AED is derived from the USD peg of 3.6725 AED per USD.\n\n"
            "**Calibration.** Load factors, fare levels and seasonality are set inside ranges seen in published airport "
            "traffic statistics and airline annual reports; the specific sources are cited in the README. The numbers are "
            "generator inputs, documented in `docs/assumptions.md`, not results.")

    c.notes(
        "**Train and test.** The first 30 months (March 2023 to August 2025) train the models; the last six months "
        "(September 2025 to February 2026) are held out. The window ends in February 2026, so events from March 2026 are not "
        "modelled and the test months are winter only.\n\n"
        "**Reproduce it.** Run `generate_data.py`, `forecast.py`, `sensitivity.py`, `pricing_sim.py` and `build_app_data.py` "
        "in `src/`, then `streamlit run app/app.py`. The project was built on Python 3.11.\n\n"
        "**Where things live.** `sql/` has the schema, `src/` the pipeline, `app/` this app, `data/` the databases, and `docs/` "
        "the data dictionary, assumptions and model results.\n\n"
        "**Checks.** Sanity checks compare the generated data with the agreed inputs (load factors, fares, segment mix, booking "
        "curves, point-of-sale shares); every page is tested under all five currencies.")
