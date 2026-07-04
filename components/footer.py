"""Reusable page footer component.

Renders a consistent footer (copyright + tagline) at the bottom of
every page. Its ``.nm-footer`` styling lives in
``components/theme.py`` alongside every other shared CSS class, so
this module only ever renders markup, never a ``<style>`` block.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from config.constants import APP_TAGLINE, COMPANY_NAME


def render_footer() -> None:
    """Render the shared application footer.

    Returns:
        None. Renders directly into the current Streamlit container.
    """
    year = datetime.now().year

    st.markdown(
        f"""
        <div class="nm-footer">
            <p>© {year} <strong>{COMPANY_NAME}</strong> &middot; {APP_TAGLINE}</p>
            <p>Built with Streamlit &middot; Internal use only</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
