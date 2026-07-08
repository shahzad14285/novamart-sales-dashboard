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

from authorization.permissions import VIEW_REPORTS
from components.auth import require_authentication
from components.authorization import get_active_user_context, require_permission_ui
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.executive_report_center import render_executive_report_center

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Reports"})
inject_header_styles()

# Sprint 6.6 -- Identity & Authentication Framework, Task 8: authentication
# must complete before authorization begins.
require_authentication()

tenant_context = render_sidebar(active_label="Reports")
render_header(title="Reports", subtitle="Generate, review, and export business reports")

# Sprint 6.5 -- Permission-Based Authorization Framework, Task 8: the
# Reports page itself requires VIEW_REPORTS just to be entered (defense
# in depth alongside the sidebar already hiding its nav link). The
# finer-grained GENERATE_REPORTS / USE_AI_RECOMMENDATIONS / GENERATE_PDF
# / EXPORT_DATA checks for each individual capability live inside
# ui.executive_report_center, gating each tab independently.
user_context = get_active_user_context(tenant_context)
if require_permission_ui(
    VIEW_REPORTS, service_name="ReportsPage", operation="view",
    tenant_context=tenant_context, user_context=user_context,
):
    render_executive_report_center(tenant_context=tenant_context, user_context=user_context)

render_footer()
