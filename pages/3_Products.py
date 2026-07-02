"""Products page (placeholder).

Intended to host product-level performance: best sellers, inventory
health, and category breakdowns. Currently a placeholder pending data
integration.
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

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Products"})
inject_header_styles()

render_sidebar(active_label="Products")
render_header(title="Products", subtitle="Catalog performance, inventory, and category insights")

st.info(PLACEHOLDER_NOTICE, icon="🚧")

col1, col2 = st.columns(2)
with col1:
    with st.container(border=True):
        st.subheader("Top Selling Products")
        st.caption("Coming soon")
with col2:
    with st.container(border=True):
        st.subheader("Inventory Health")
        st.caption("Coming soon")

render_footer()
