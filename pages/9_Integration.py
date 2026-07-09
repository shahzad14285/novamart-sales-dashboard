"""Integration page.

Sprint 6.8 -- Integration Platform & API Gateway, Task 10.

Hosts the Integration Dashboard: Registered Endpoints, Request
History, Rate Limit Statistics, API Version Usage, Gateway
Performance, Validation Failures, and Integration Provider Status, all
read from ``endpoint_registry``, ``rate_limiter``,
``integration_provider_registry``, and the platform's existing
``monitoring_service`` -- the same centralized observability channel
every instrumented business service already publishes into. Like every
other page in ``pages/``, this file is intentionally thin: it only
wires page configuration and the shared header/sidebar/footer around
``ui.integration_dashboard.render_integration_dashboard()``, which owns
everything else.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from authorization.permissions import VIEW_INTEGRATIONS
from components.auth import require_authentication
from components.authorization import get_active_user_context, require_permission_ui
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.integration_dashboard import render_integration_dashboard

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Integrations"})
inject_header_styles()

# Sprint 6.6 -- Identity & Authentication Framework, Task 8: authentication
# must complete before authorization begins.
require_authentication()

tenant_context = render_sidebar(active_label="Integrations")
render_header(title="Integrations", subtitle="API Gateway endpoints, request history, and provider status")

# Sprint 6.8 -- Integration Platform & API Gateway, Task 10: the
# Integration Dashboard requires VIEW_INTEGRATIONS. Checked once, up
# front, so an unauthorized user sees a single "Access Denied" panel
# instead of a page that starts rendering operational data before
# stopping partway.
user_context = get_active_user_context(tenant_context)
if require_permission_ui(
    VIEW_INTEGRATIONS, service_name="IntegrationDashboard", operation="view",
    tenant_context=tenant_context, user_context=user_context,
):
    render_integration_dashboard(tenant_context=tenant_context)

render_footer()
