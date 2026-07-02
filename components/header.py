"""Reusable page header component.

Renders a consistent, branded banner at the top of every page so the
app feels cohesive without duplicating markup across pages.
"""

from __future__ import annotations

import streamlit as st

from config.settings import THEME_COLORS


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
    """Inject the CSS used by :func:`render_header`.

    Kept separate from ``render_header`` so it can be called once per
    page (or once globally) without duplicating <style> blocks.
    """
    st.markdown(
        f"""
        <style>
        .nm-header-title {{
            color: {THEME_COLORS['primary_dark']};
            font-weight: 700;
            margin-bottom: 0;
        }}
        .nm-header-subtitle {{
            color: {THEME_COLORS['muted_text']};
            font-size: 1.05rem;
            margin-top: 0.25rem;
        }}
        .nm-header-rule {{
            border: none;
            border-top: 2px solid {THEME_COLORS['border']};
            margin: 0.5rem 0 1.5rem 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
