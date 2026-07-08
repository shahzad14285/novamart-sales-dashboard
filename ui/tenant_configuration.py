"""Tenant Configuration screen for the NovaMart Sales Intelligence Dashboard.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 8.

A minimal Administration screen giving a System or Tenant Administrator
visibility into the platform's tenant directory
(``tenancy.registry.tenant_registry``, populated from
``config/tenants.py``) and its user directory (the active
:class:`~authorization.provider.AuthorizationProvider`, populated from
``config/users.py``). This module reads both registries; it never
writes to them -- onboarding, renaming, or deactivating a tenant or
user remains a one-file configuration change (``config/tenants.py`` /
``config/users.py``), exactly as ``docs/MULTI_TENANT_ARCHITECTURE.md``
and ``docs/AUTHORIZATION_ARCHITECTURE.md`` already document. Building a
full create/edit/deactivate UI is a natural next iteration, not
required by this sprint's ticket, which asks only that access to
"Tenant Configuration" be protected behind ``MANAGE_TENANTS``.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from authorization.registry import authorization_provider_registry
from components.empty_state import render_empty_state
from tenancy.registry import tenant_registry


def render_tenant_configuration() -> None:
    """Render the read-only Tenant Configuration screen.

    Authorization (``MANAGE_TENANTS``) is enforced by the caller
    (``pages/7_Tenant_Configuration.py``), exactly like every other
    protected page in this app -- this function assumes it has already
    been authorized to run, per the Target Architecture's "Business
    services should assume authorization has already been completed."
    """
    st.markdown('<p class="nm-section-title">🏢 Tenant Directory</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Every organization registered with the platform, '
        "from config/tenants.py.</p>",
        unsafe_allow_html=True,
    )
    _render_tenant_table()

    st.divider()

    st.markdown('<p class="nm-section-title">🧑‍🤝‍🧑 User Directory</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Every user known to the active authorization provider, '
        "from config/users.py.</p>",
        unsafe_allow_html=True,
    )
    _render_user_table()


def _render_tenant_table() -> None:
    """Render every registered tenant as a read-only table."""
    tenants = tenant_registry.all_tenants()
    if not tenants:
        render_empty_state("No tenants are registered.", icon="🏢")
        return

    table = pd.DataFrame(
        {
            "Tenant ID": [tenant.tenant_id for tenant in tenants],
            "Organization": [tenant.display_name for tenant in tenants],
            "Status": ["Active" if tenant.is_active else "Inactive" for tenant in tenants],
            "Plan": [tenant.metadata.get("plan", "—") for tenant in tenants],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)


def _render_user_table() -> None:
    """Render every registered user as a read-only table."""
    provider = authorization_provider_registry.get_active()
    users = provider.list_users()
    if not users:
        render_empty_state("No users are registered.", icon="🧑‍🤝‍🧑")
        return

    table = pd.DataFrame(
        {
            "User ID": [user.user_id for user in users],
            "Name": [user.display_name for user in users],
            "Tenant": [user.tenant_id for user in users],
            "Roles": [", ".join(user.roles) or "—" for user in users],
            "Status": ["Active" if user.is_active else "Inactive" for user in users],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
