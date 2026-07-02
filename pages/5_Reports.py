"""Reports page (placeholder).

Intended to host exportable, scheduled, and ad-hoc reports. Currently
a placeholder pending report-generation integration.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.constants import PLACEHOLDER_NOTICE
from config.settings import PAGE_CONFIG

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Reports"})
inject_header_styles()

render_sidebar(active_label="Reports")
render_header(title="Reports", subtitle="Generate, schedule, and export business reports")

st.info(PLACEHOLDER_NOTICE, icon="🚧")

with st.container(border=True):
    st.subheader("Report Builder")
    st.caption("Coming soon: choose a report type, date range, and export format.")
    st.selectbox("Report type", ["Sales Summary", "Product Performance", "Customer Insights"], disabled=True)
    st.button("Generate Report", disabled=True)

render_footer()
