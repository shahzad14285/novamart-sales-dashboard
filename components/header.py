"""Reusable page header component.

Renders a consistent, branded banner at the top of every page so the
app feels cohesive without duplicating markup across pages.
"""

from __future__ import annotations

import streamlit as st

from components.theme import inject_global_styles


def render_header(title: str, subtitle: str | None = None) -> None:
    """Render a styled page header with a title and optional subtitle.

    Args:
        title: Main heading text (e.g. the page name).
        subtitle: Optional secondary line shown under the title.

    Returns:
        None. Renders directly into the current Streamlit container.
    """
    subtitle_html = (
        f'<p class="nm-header-subtitle">{subtitle}</p>' if subtitle else ""
    )

    st.markdown(
        f"""
        <div class="nm-header">
            <h1 class="nm-header-title">{title}</h1>
            {subtitle_html}
        </div>
        <hr class="nm-header-rule" />
        """,
        unsafe_allow_html=True,
    )


def inject_header_styles() -> None:
    """Inject the app-wide stylesheet (every page calls this once).

    Every page in the app already calls this function right after
    ``st.set_page_config()``, which makes it the one natural choke
    point for the whole design system, not just the header markup.
    It now delegates to :func:`components.theme.inject_global_styles`
    so there is a single source of truth for every CSS rule the app
    uses -- header, KPI cards, tabs, sidebar, empty states, footer,
    accessibility, and responsiveness -- instead of several modules
    each injecting their own ``<style>`` block.
    """
    inject_global_styles()
