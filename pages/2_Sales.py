"""Sales page (placeholder).

Intended to host detailed sales analysis: revenue by channel, region,
and time period, plus drill-down tables. Currently a placeholder
pending data integration.
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

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Sales"})
inject_header_styles()

render_sidebar(active_label="Sales")
render_header(title="Sales", subtitle="Revenue performance by channel, region, and time")

st.info(PLACEHOLDER_NOTICE, icon="🚧")

tab1, tab2, tab3 = st.tabs(["By Channel", "By Region", "By Time Period"])
for tab, label in zip((tab1, tab2, tab3), ("channel", "region", "time period")):
    with tab:
        st.caption(f"Sales breakdown by {label} will appear here.")

render_footer()
