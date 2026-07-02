"""Dashboard page.

Hosts the Upload Center, which lets a user bring their own CSV/Excel
data into the app, and the Key Performance Indicators section, which
is calculated entirely from that uploaded dataset via
``utils/kpi_engine.py`` (itself built on the shared ``DataLoader`` and
``utils/calculations.py``). There are no hard-coded placeholder KPI
values on this page: before a file is uploaded the section shows a
guidance message, and once a file is uploaded and validated it shows
real, computed numbers -- which recalculate automatically every time a
new file is uploaded, since Streamlit re-runs the page top-to-bottom on
every widget interaction.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable when Streamlit runs this page
# as a standalone script inside pages/.
sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.kpi_cards import render_kpi_cards
from components.sidebar import render_sidebar
from components.upload_center import render_upload_center
from config.settings import PAGE_CONFIG
from utils.kpi_engine import sales_kpi_engine

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Dashboard"})
inject_header_styles()

render_sidebar(active_label="Dashboard")
render_header(title="Dashboard", subtitle="Cross-functional overview of business performance")

st.caption(
    "Upload a CSV or Excel file below to calculate live KPIs from your "
    "own sales data."
)

# render_upload_center() returns the cleaned DataFrame for the file
# currently uploaded (or None if nothing is uploaded / validation
# failed). Streamlit re-runs this whole script top-to-bottom on every
# widget interaction -- including a new file being dropped into the
# uploader -- so simply recomputing the KPIs from that return value on
# every run is what makes the section "automatically refresh": there is
# no stale state to invalidate and nothing extra to wire up.
uploaded_df = render_upload_center()

st.divider()
st.markdown("### 📊 Key Performance Indicators")

if uploaded_df is None:
    # No hard-coded numbers here -- just guidance. Real KPI values only
    # ever come from an uploaded, validated dataset.
    st.info(
        "Upload a dataset above to see your KPIs calculated live. This "
        "section updates automatically as soon as a file is uploaded.",
        icon="📄",
    )
else:
    st.caption("Recalculated automatically from the file uploaded above.")
    try:
        kpi_results = sales_kpi_engine.calculate_all(uploaded_df)
        render_kpi_cards(kpi_results)
    except Exception as exc:  # noqa: BLE001 - defensive: a KPI bug must never crash the dashboard
        st.error(f"Unable to calculate KPIs for the uploaded file: {exc}", icon="⚠️")

render_footer()
