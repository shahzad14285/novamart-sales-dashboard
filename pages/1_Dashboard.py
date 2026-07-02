"""Dashboard page.

Hosts the primary at-a-glance sales intelligence view: cross-cutting
placeholders (pending further data integration) plus the Upload
Center, which lets a user bring their own CSV/Excel data into the app
for an instant, validated preview -- and a live KPI section, powered by
``utils/kpi_engine.py``, that recalculates automatically every time a
new file is uploaded.
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
from config.constants import PLACEHOLDER_NOTICE
from config.settings import PAGE_CONFIG
from utils.kpi_engine import sales_kpi_engine

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Dashboard"})
inject_header_styles()

render_sidebar(active_label="Dashboard")
render_header(title="Dashboard", subtitle="Cross-functional overview of business performance")

st.info(PLACEHOLDER_NOTICE, icon="🚧")

col1, col2, col3 = st.columns(3)
for col, label in zip((col1, col2, col3), ("Revenue Overview", "Order Volume", "Top Segments")):
    with col:
        with st.container(border=True):
            st.subheader(label)
            st.caption("Coming soon")

st.divider()

# render_upload_center() returns the cleaned DataFrame for the file
# currently uploaded (or None if nothing is uploaded / validation
# failed). Streamlit re-runs this whole script top-to-bottom on every
# widget interaction -- including a new file being dropped into the
# uploader -- so simply recomputing the KPIs from that return value on
# every run is what makes the cards "automatically refresh": there is
# no stale state to invalidate and nothing extra to wire up.
uploaded_df = render_upload_center()

if uploaded_df is not None:
    st.divider()
    st.markdown("### 📊 Live KPIs")
    st.caption("Recalculated automatically from the file uploaded above.")
    kpi_results = sales_kpi_engine.calculate_all(uploaded_df)
    render_kpi_cards(kpi_results)

render_footer()
