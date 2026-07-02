"""Reusable page footer component.

Renders a consistent footer (copyright + tagline) at the bottom of
every page.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from config.constants import APP_TAGLINE, COMPANY_NAME
from config.settings import THEME_COLORS


def render_footer() -> None:
    """Render the shared application footer.

    Returns:
        None. Renders directly into the current Streamlit container.
    """
    year = datetime.now().year

    st.markdown(
        f"""
        <style>
        .nm-footer {{
            margin-top: 3rem;
            padding: 1.25rem 0;
            border-top: 1px solid {THEME_COLORS['border']};
            text-align: center;
            color: {THEME_COLORS['muted_text']};
            font-size: 0.85rem;
        }}
        .nm-footer strong {{
            color: {THEME_COLORS['primary_dark']};
        }}
        </style>
        <div class="nm-footer">
            <p>© {year} <strong>{COMPANY_NAME}</strong> &middot; {APP_TAGLINE}</p>
            <p>Built with Streamlit &middot; Internal use only</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
