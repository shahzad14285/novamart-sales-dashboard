"""Monitoring page.

Sprint 6.4 -- Observability & Monitoring Service, Task 9.

Hosts the Administration / Monitoring dashboard: Platform Overview,
Service Statistics, Tenant Activity, and a Recent Events log, all read
from ``monitoring_service`` -- the same centralized service every
business service (Upload Center, Data Loader, KPI Engine, Business
Insights, Reporting, AI Recommendation, PDF Generator, Export Service,
Executive Report Center) already records operational events into. Like
every other page in ``pages/``, this file is intentionally thin: it
only wires page configuration and the shared header/sidebar/footer
around ``ui.monitoring_dashboard.render_monitoring_dashboard()``, which
owns everything else.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from authorization.permissions import VIEW_MONITORING
from components.auth import require_authentication
from components.authorization import get_active_user_context, require_permission_ui
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.monitoring_dashboard import render_monitoring_dashboard

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Monitoring"})
inject_header_styles()

# Sprint 6.6 -- Identity & Authentication Framework, Task 8: authentication
# must complete before authorization begins.
require_authentication()

tenant_context = render_sidebar(active_label="Monitoring")
render_header(title="Monitoring", subtitle="Operational health, performance, and tenant activity across the platform")

# Sprint 6.5 -- Permission-Based Authorization Framework, Task 8: the
# Monitoring Dashboard requires VIEW_MONITORING. Checked once, up front,
# so an unauthorized user sees a single "Access Denied" panel instead of
# a page that starts rendering operational data before stopping partway.
user_context = get_active_user_context(tenant_context)
if require_permission_ui(
    VIEW_MONITORING, service_name="MonitoringDashboard", operation="view",
    tenant_context=tenant_context, user_context=user_context,
):
    render_monitoring_dashboard(tenant_context=tenant_context)

render_footer()
