"""Tenant Configuration page.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 8.

Hosts the read-only Tenant Configuration screen (tenant + user
directories). Like every other page in ``pages/``, this file is
intentionally thin: it only wires page configuration, the shared
header/sidebar/footer, and the ``MANAGE_TENANTS`` authorization gate
around ``ui.tenant_configuration.render_tenant_configuration()``, which
owns everything else.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from authorization.permissions import MANAGE_TENANTS
from components.authorization import get_active_user_context, require_permission_ui
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.settings import PAGE_CONFIG
from ui.tenant_configuration import render_tenant_configuration

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Tenant Configuration"})
inject_header_styles()

tenant_context = render_sidebar(active_label="Tenant Configuration")
render_header(title="Tenant Configuration", subtitle="Platform-wide tenant and user directory")

# Sprint 6.5 -- Permission-Based Authorization Framework, Task 8: Tenant
# Configuration requires MANAGE_TENANTS. Checked once, up front, so an
# unauthorized user sees a single "Access Denied" panel.
user_context = get_active_user_context(tenant_context)
if require_permission_ui(
    MANAGE_TENANTS, service_name="TenantConfiguration", operation="view",
    tenant_context=tenant_context, user_context=user_context,
):
    render_tenant_configuration()

render_footer()
