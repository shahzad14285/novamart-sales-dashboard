"""Reusable sidebar navigation component.

Centralizes the app's navigation so links stay consistent across the
Home page and every page in ``pages/``. Since Sprint 6.3 (Multi-Tenant
Business Intelligence Platform), it also renders the tenant selector
(see ``components/tenant_selector.py``) and returns the resolved
:class:`~tenancy.context.TenantContext`, so every page gets tenant
awareness "for free" from the sidebar call it already makes. Since
Sprint 6.6 (Identity & Authentication Framework), it also renders the
authenticated user/session panel (see ``components/auth.py``) in place
of Sprint 6.5's demo user switcher.
"""

from __future__ import annotations

import streamlit as st

from authorization.context import UserContext

# Sprint 6.7 -- Automation & Notification Platform: imported for its
# side effect only (wires NotificationService.handle_event in as an
# AutomationService handler, and registers this sprint's demo scheduled
# jobs -- see that module's docstring). components/sidebar.py is
# imported by every page before any business service can be called,
# mirroring exactly how components/auth.py already imports
# config.credentials for the identical reason.
import config.automation_setup  # noqa: F401
from components.auth import render_user_panel
from components.authorization import is_authorized
from components.tenant_selector import render_tenant_selector
from config.constants import APP_TAGLINE, COMPANY_NAME, NAV_ITEMS
from config.settings import APP_ICON
from tenancy.context import TenantContext


def render_sidebar(active_label: str = "Home") -> TenantContext:
    """Render the shared sidebar: branding, tenant selector, user panel, navigation.

    Note: by the time this is called, ``components.auth.require_authentication()``
    has already run at the top of the calling page (Task 8: "Authentication
    must complete successfully before authorization begins") -- this
    function assumes an authenticated session exists and simply
    displays it via :func:`~components.auth.render_user_panel`.

    Args:
        active_label: The label (from ``NAV_ITEMS``) of the currently
            active page, used to visually highlight it in the nav.

    Returns:
        The :class:`~tenancy.context.TenantContext` resolved from the
        tenant selector for the current session. Existing call sites
        that don't need it can simply ignore the return value, exactly
        as before this function returned ``None``. The resolved
        :class:`~authorization.context.UserContext` (Sprint 6.5) is
        deliberately *not* returned here to keep this function's
        signature backward compatible with every existing call site --
        a page that needs it calls
        ``components.authorization.get_active_user_context(tenant_context)``
        after this function returns, which reads the exact same
        authenticated session this function just displayed.
    """
    with st.sidebar:
        st.markdown(
            f"""
            <div class="nm-sidebar-brand">
                <span class="nm-sidebar-brand-icon">{APP_ICON}</span>
                <h2 class="nm-sidebar-brand-name">{COMPANY_NAME}</h2>
                <p class="nm-sidebar-brand-tagline">{APP_TAGLINE}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()

        tenant_context = render_tenant_selector()
        st.divider()

        # Sprint 6.6 -- Identity & Authentication Framework: displays the
        # already-authenticated user (name, role, tenant, session status,
        # Sign Out) immediately after "which tenant is active", so the nav
        # filtering below already reflects both. Replaces Sprint 6.5's
        # demo user switcher now that real sign-in determines identity.
        user_context = render_user_panel(tenant_context)
        st.divider()

        st.markdown('<p class="nm-eyebrow">Navigation</p>', unsafe_allow_html=True)
        for item in NAV_ITEMS:
            required_permission = item.get("required_permission")
            if required_permission and not _is_authorized(user_context, required_permission):
                # Task 9 (Sprint 6.5): "Hide unauthorized menu items." --
                # an item the current user isn't permitted to use is
                # skipped entirely, not shown disabled, so the sidebar
                # never advertises a capability the user cannot reach.
                continue
            # st.page_link renders a native, clickable nav entry that
            # works across the multipage app without manual routing.
            label = f"{item['icon']}  {item['label']}"
            st.page_link(
                item["path"],
                label=label,
                disabled=(item["label"] == active_label),
            )

    return tenant_context


def _is_authorized(user_context: UserContext, permission: str) -> bool:
    """Check ``permission`` against an already-resolved context (no re-resolution).

    A tiny local wrapper around
    ``authorization.service.authorization_service.has_permission`` so
    the navigation loop above doesn't re-resolve the current user (via
    :func:`components.authorization.is_authorized`) once per nav item --
    ``user_context`` was already resolved once by
    :func:`~components.auth.render_user_panel` a few lines up.
    """
    from authorization.service import authorization_service

    return authorization_service.has_permission(user_context, permission)
