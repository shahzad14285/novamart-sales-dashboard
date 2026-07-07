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

from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.monitoring_dashboard import render_monitoring_dashboard

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Monitoring"})
inject_header_styles()

tenant_context = render_sidebar(active_label="Monitoring")
render_header(title="Monitoring", subtitle="Operational health, performance, and tenant activity across the platform")

render_monitoring_dashboard(tenant_context=tenant_context)

render_footer()
