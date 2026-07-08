"""Customers page (placeholder).

Intended to host customer analytics: segmentation, retention, and
lifetime value. Currently a placeholder pending data integration.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from components.auth import require_authentication
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.constants import PLACEHOLDER_NOTICE
from config.settings import PAGE_CONFIG

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Customers"})
inject_header_styles()

# Sprint 6.6 -- Identity & Authentication Framework, Task 8: authentication
# must complete before authorization begins.
require_authentication()

render_sidebar(active_label="Customers")
render_header(title="Customers", subtitle="Segmentation, retention, and lifetime value")

st.info(PLACEHOLDER_NOTICE, icon="🚧")

col1, col2, col3 = st.columns(3)
for col, label in zip((col1, col2, col3), ("Segmentation", "Retention", "Lifetime Value")):
    with col:
        with st.container(border=True):
            st.subheader(label)
            st.caption("Coming soon")

render_footer()
