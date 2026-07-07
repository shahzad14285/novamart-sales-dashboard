"""Tenant selector for the NovaMart Multi-Tenant platform.

Sprint 6.3 -- Multi-Tenant Business Intelligence Platform, Tasks 2, 6.

Renders the "which organization am I working as" picker and resolves
it into a :class:`~tenancy.context.TenantContext` every tenant-aware
service call needs. This is the one place in the UI layer that reads
and writes the active tenant selection, so every page gets it the same
way through :func:`~components.sidebar.render_sidebar`.

Why ``st.session_state``, not a module-level global
------------------------------------------------------
A Streamlit server process serves multiple browser sessions
concurrently from the same Python process. A plain module-level
variable holding "the current tenant" would be shared by every session
on that process -- exactly the cross-tenant leak this platform exists
to prevent. ``st.session_state`` is keyed per browser session by
Streamlit itself, so storing the selection there is what actually
gives each concurrent user their own isolated active tenant.
"""

from __future__ import annotations

import streamlit as st

# Imported for its side effect: populates the shared tenant_registry
# from config.tenants.TENANT_DEFINITIONS as soon as this module loads.
import config.tenants  # noqa: F401
from tenancy.context import TenantContext
from tenancy.registry import tenant_registry

_SESSION_KEY = "novamart_active_tenant_id"


def render_tenant_selector() -> TenantContext:
    """Render the tenant picker and return the resolved :class:`TenantContext`.

    Intended to be called once per page, from
    :func:`~components.sidebar.render_sidebar` (already invoked by
    every page), so no page needs to render this a second time.

    Returns:
        A :class:`TenantContext` bound to whichever tenant is currently
        selected in this browser session, or an empty context if no
        active tenant is configured at all.
    """
    active_tenants = tenant_registry.active_tenants()

    st.markdown('<p class="nm-eyebrow">Active Tenant</p>', unsafe_allow_html=True)

    if not active_tenants:
        st.error("No active tenants are configured. Unable to process request.", icon="🔒")
        return TenantContext.empty()

    options = [tenant.tenant_id for tenant in active_tenants]
    labels = {tenant.tenant_id: tenant.display_name for tenant in active_tenants}

    previous_selection = st.session_state.get(_SESSION_KEY)
    default_index = options.index(previous_selection) if previous_selection in options else 0

    selected_id = st.selectbox(
        "Organization",
        options=options,
        index=default_index,
        format_func=lambda tenant_id: labels[tenant_id],
        key="novamart_tenant_selectbox",
        label_visibility="collapsed",
        help="Every KPI, report, recommendation, and export you see is scoped to this organization.",
    )
    st.session_state[_SESSION_KEY] = selected_id

    tenant = tenant_registry.get(selected_id)
    return TenantContext.for_tenant(tenant) if tenant is not None else TenantContext.empty()


def get_active_tenant_context() -> TenantContext:
    """Return the current session's active :class:`TenantContext` without re-rendering the picker.

    Useful for a component or page that needs the resolved tenant but
    isn't the one responsible for drawing the selectbox (which
    :func:`~components.sidebar.render_sidebar` already does once per
    page).

    Returns:
        The active :class:`TenantContext` for this session, or an
        empty context if nothing has been selected yet (e.g. the
        sidebar hasn't rendered on this run for some reason).
    """
    tenant_id = st.session_state.get(_SESSION_KEY)
    if not tenant_id:
        return TenantContext.empty()
    tenant = tenant_registry.get(tenant_id)
    return TenantContext.for_tenant(tenant) if tenant is not None else TenantContext.empty()
