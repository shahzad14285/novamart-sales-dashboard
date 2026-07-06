"""Reports page.

Hosts the Executive Report Center (Sprint 6.2, Module 5): upload/filter
a dataset, assemble an executive report, review AI-generated
recommendations, and generate PDF/CSV/Excel/JSON exports -- all backed
by the Reporting, AI Recommendation, PDF Generator, and Export
services. This page is intentionally thin: it only wires page
configuration and the shared header/sidebar/footer around
``ui.executive_report_center.render_executive_report_center()``, which
owns everything else.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.executive_report_center import render_executive_report_center

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Reports"})
inject_header_styles()

render_sidebar(active_label="Reports")
render_header(title="Reports", subtitle="Generate, review, and export business reports")

render_executive_report_center()

render_footer()
