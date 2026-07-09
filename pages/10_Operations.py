"""Operations page.

Sprint 6.9 -- Production Readiness Platform, Task 10.

Hosts the Operations Dashboard: current environment, active
configuration provider, feature flags, health status, readiness
status, configuration summary, and deployment information -- all read
from ``configuration_service``, ``feature_flag_service``,
``health_check_service``, and ``readiness_service``. Like every other
page in ``pages/``, this file is intentionally thin: it only wires page
configuration and the shared header/sidebar/footer around
``ui.operations_dashboard.render_operations_dashboard()``, which owns
everything else.

Administrator access only (Task 10): gated behind the existing
``manage_platform`` permission -- reused rather than duplicated, since
it already means exactly "full platform administration" and is granted
only to the System Administrator role (see
``authorization/roles.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from authorization.permissions import MANAGE_PLATFORM
from components.auth import require_authentication
from components.authorization import get_active_user_context, require_permission_ui
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.operations_dashboard import render_operations_dashboard

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Operations"})
inject_header_styles()

# Sprint 6.6 -- Identity & Authentication Framework, Task 8: authentication
# must complete before authorization begins.
require_authentication()

tenant_context = render_sidebar(active_label="Operations")
render_header(title="Operations", subtitle="Configuration, feature flags, health, and readiness")

# Sprint 6.9 -- Production Readiness Platform, Task 10: the Operations
# Dashboard requires MANAGE_PLATFORM (administrator access only).
# Checked once, up front, so an unauthorized user sees a single "Access
# Denied" panel instead of a page that starts rendering operational
# data before stopping partway.
user_context = get_active_user_context(tenant_context)
if require_permission_ui(
    MANAGE_PLATFORM, service_name="OperationsDashboard", operation="view",
    tenant_context=tenant_context, user_context=user_context,
):
    render_operations_dashboard()

render_footer()
