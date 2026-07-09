"""Automation page.

Sprint 6.7 -- Automation & Notification Platform, Task 10.

Hosts the Automation Dashboard: Recent Events, Scheduled Jobs (with
manual Run Now execution), and Notification History, all read from
``automation_service``, ``scheduler``, and ``notification_service`` --
the same centralized platform every instrumented business service
(Reporting, PDF Generator, Export, AI Recommendation, Data Loader,
Identity) already publishes events into. Like every other page in
``pages/``, this file is intentionally thin: it only wires page
configuration and the shared header/sidebar/footer around
``ui.automation_dashboard.render_automation_dashboard()``, which owns
everything else.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from authorization.permissions import VIEW_AUTOMATION
from components.auth import require_authentication
from components.authorization import get_active_user_context, require_permission_ui
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.automation_dashboard import render_automation_dashboard

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Automation"})
inject_header_styles()

# Sprint 6.6 -- Identity & Authentication Framework, Task 8: authentication
# must complete before authorization begins.
require_authentication()

tenant_context = render_sidebar(active_label="Automation")
render_header(title="Automation", subtitle="Automation events, scheduled jobs, and notification history")

# Sprint 6.7 -- Automation & Notification Platform, Task 10: the
# Automation Dashboard requires VIEW_AUTOMATION. Checked once, up front,
# so an unauthorized user sees a single "Access Denied" panel instead of
# a page that starts rendering operational data before stopping partway.
user_context = get_active_user_context(tenant_context)
if require_permission_ui(
    VIEW_AUTOMATION, service_name="AutomationDashboard", operation="view",
    tenant_context=tenant_context, user_context=user_context,
):
    render_automation_dashboard(tenant_context=tenant_context)

render_footer()
