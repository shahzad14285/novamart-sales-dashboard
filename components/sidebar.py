"""Reusable sidebar navigation component.

Centralizes the app's navigation so links stay consistent across the
Home page and every page in ``pages/``. Since Sprint 6.3 (Multi-Tenant
Business Intelligence Platform), it also renders the tenant selector
(see ``components/tenant_selector.py``) and returns the resolved
:class:`~tenancy.context.TenantContext`, so every page gets tenant
awareness "for free" from the sidebar call it already makes.
"""

from __future__ import annotations

import streamlit as st

from components.tenant_selector import render_tenant_selector
from config.constants import APP_TAGLINE, COMPANY_NAME, NAV_ITEMS
from config.settings import APP_ICON
from tenancy.context import TenantContext


def render_sidebar(active_label: str = "Home") -> TenantContext:
    """Render the shared sidebar: branding, tenant selector, navigation, and info.

    Args:
        active_label: The label (from ``NAV_ITEMS``) of the currently
            active page, used to visually highlight it in the nav.

    Returns:
        The :class:`~tenancy.context.TenantContext` resolved from the
        tenant selector for the current session. Existing call sites
        that don't need it can simply ignore the return value, exactly
        as before this function returned ``None``.
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

        st.markdown('<p class="nm-eyebrow">Navigation</p>', unsafe_allow_html=True)
        for item in NAV_ITEMS:
            # st.page_link renders a native, clickable nav entry that
            # works across the multipage app without manual routing.
            label = f"{item['icon']}  {item['label']}"
            st.page_link(
                item["path"],
                label=label,
                disabled=(item["label"] == active_label),
            )

        st.divider()
        st.caption(f"Signed in as **shahzad.14285@gmail.com**")

    return tenant_context
