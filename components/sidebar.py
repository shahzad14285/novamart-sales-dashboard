"""Reusable sidebar navigation component.

Centralizes the app's navigation so links stay consistent across the
Home page and every page in ``pages/``.
"""

from __future__ import annotations

import streamlit as st

from config.constants import APP_TAGLINE, COMPANY_NAME, NAV_ITEMS
from config.settings import APP_ICON


def render_sidebar(active_label: str = "Home") -> None:
    """Render the shared sidebar: branding, navigation links, and info.

    Args:
        active_label: The label (from ``NAV_ITEMS``) of the currently
            active page, used to visually highlight it in the nav.

    Returns:
        None. Renders directly into ``st.sidebar``.
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
