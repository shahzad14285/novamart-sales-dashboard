"""Shared visual design system for the NovaMart dashboard.

Centralizes every global CSS rule the app injects into one place,
built entirely from ``config/settings.py``'s ``THEME_COLORS`` -- no new
colors are introduced anywhere in this module. Other components that
need custom styling (``header.py``, ``footer.py``, ``sidebar.py``)
reuse the CSS classes defined here instead of rolling their own
``<style>`` blocks, so the app injects exactly one stylesheet per page
instead of several scattered, occasionally duplicated ones.

This module is purely presentational: it contains no data access, no
calculations, and no filtering logic, and it changes nothing about
*what* any page renders -- only how it looks.
"""

from __future__ import annotations

import streamlit as st

from config.settings import THEME_COLORS


def inject_global_styles() -> None:
    """Inject the app-wide stylesheet.

    Every page already calls this indirectly via
    ``components.header.inject_header_styles()``, so it only needs to
    run once per page load. Safe to call more than once if needed --
    Streamlit just renders another identical ``<style>`` tag.
    """
    st.markdown(_build_css(), unsafe_allow_html=True)


def _build_css() -> str:
    """Assemble the full app stylesheet as an HTML ``<style>`` block.

    Returns:
        A ``<style>...</style>`` string ready to pass to
        ``st.markdown(..., unsafe_allow_html=True)``.
    """
    c = THEME_COLORS
    return f"""
    <style>
    /* ================================================================
       Design tokens -- mirrors config/settings.py THEME_COLORS exactly.
       Every rule below references one of these variables rather than a
       hard-coded color, so the whole app re-themes from one source.
       ================================================================ */
    :root {{
        --nm-primary: {c['primary']};
        --nm-primary-dark: {c['primary_dark']};
        --nm-primary-light: {c['primary_light']};
        --nm-bg: {c['background']};
        --nm-bg-secondary: {c['secondary_background']};
        --nm-text: {c['text']};
        --nm-muted: {c['muted_text']};
        --nm-success: {c['success']};
        --nm-warning: {c['warning']};
        --nm-danger: {c['danger']};
        --nm-border: {c['border']};
    }}

    /* ================================================================
       Typography hierarchy
       ================================================================ */
    h1 {{ font-weight: 700; letter-spacing: -0.01em; }}
    h2 {{ font-weight: 700; color: var(--nm-primary-dark); }}
    h3 {{ font-weight: 650; color: var(--nm-primary-dark); }}
    h4, h5 {{ font-weight: 600; color: var(--nm-text); }}

    .nm-eyebrow {{
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 0.72rem;
        font-weight: 700;
        color: var(--nm-primary);
        margin: 0 0 0.15rem 0;
    }}

    .nm-section-title {{
        color: var(--nm-primary-dark);
        font-weight: 700;
        font-size: 1.3rem;
        margin: 1.75rem 0 0.2rem 0;
        line-height: 1.3;
    }}
    .nm-section-subtitle {{
        color: var(--nm-muted);
        font-size: 0.92rem;
        margin: 0 0 0.85rem 0;
    }}

    /* Gives every st.divider() a bit more breathing room and a color
       that matches the theme, without touching any page's call sites. */
    hr {{
        margin: 1.6rem 0 !important;
        border-top: 1px solid var(--nm-border) !important;
    }}

    /* ================================================================
       Header (components/header.py)
       ================================================================ */
    .nm-header-title {{ color: var(--nm-primary-dark); margin-bottom: 0; }}
    .nm-header-subtitle {{ color: var(--nm-muted); font-size: 1.05rem; margin-top: 0.2rem; }}
    .nm-header-rule {{ border: none; border-top: 2px solid var(--nm-border); margin: 0.5rem 0 1.5rem 0; }}

    /* ================================================================
       KPI / metric cards -- targets Streamlit's own bordered-container
       markup (the div st.container(border=True) renders), so every
       existing "with st.container(border=True): st.metric(...)" card
       across kpi_cards.py, upload_center.py, and components/analytics/
       picks up the polish automatically with no per-file changes.
       ================================================================ */
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 0.85rem !important;
        transition: box-shadow 0.18s ease, transform 0.18s ease, border-color 0.18s ease;
    }}
    div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
        box-shadow: 0 4px 18px rgba(21, 101, 192, 0.14);
        border-color: var(--nm-primary-light) !important;
        transform: translateY(-2px);
    }}
    div[data-testid="stMetricLabel"] {{
        color: var(--nm-muted);
        font-weight: 600;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }}
    div[data-testid="stMetricValue"] {{
        color: var(--nm-text);
        font-weight: 700;
    }}

    /* ================================================================
       Tabs (st.tabs -- Executive Analytics, Sales, etc.)
       ================================================================ */
    button[data-baseweb="tab"] {{
        font-weight: 600;
        color: var(--nm-muted);
        transition: color 0.15s ease, background-color 0.15s ease;
        border-radius: 0.5rem 0.5rem 0 0;
    }}
    button[data-baseweb="tab"]:hover {{
        color: var(--nm-primary-dark);
        background-color: var(--nm-bg-secondary);
    }}
    button[aria-selected="true"][data-baseweb="tab"] {{
        color: var(--nm-primary-dark) !important;
    }}
    div[data-baseweb="tab-highlight"] {{
        background-color: var(--nm-primary) !important;
        height: 3px;
    }}

    /* ================================================================
       Sidebar (components/sidebar.py)
       ================================================================ */
    section[data-testid="stSidebar"] {{
        border-right: 1px solid var(--nm-border);
    }}
    .nm-sidebar-brand {{
        text-align: center;
        padding-bottom: 0.5rem;
    }}
    .nm-sidebar-brand-icon {{ font-size: 2.2rem; }}
    .nm-sidebar-brand-name {{ margin: 0.25rem 0 0 0; color: var(--nm-primary-dark); }}
    .nm-sidebar-brand-tagline {{ color: var(--nm-muted); font-size: 0.85rem; margin-top: 0; }}

    section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {{
        border-radius: 0.5rem;
        transition: background-color 0.15s ease, color 0.15s ease;
    }}
    section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {{
        background-color: var(--nm-bg-secondary);
    }}

    /* The custom NAV_ITEMS menu below the brand block already links to
       every page in the app, so Streamlit's auto-generated multipage
       nav would otherwise show the exact same links a second time.
       Hiding it removes that duplication -- no page becomes
       unreachable, since every one of them is already in NAV_ITEMS. */
    div[data-testid="stSidebarNav"] {{ display: none; }}

    /* ================================================================
       Empty states (components/empty_state.py)
       ================================================================ */
    .nm-empty-state {{
        text-align: center;
        padding: 2rem 1.5rem;
        background-color: var(--nm-bg-secondary);
        border: 1px dashed var(--nm-border);
        border-radius: 0.85rem;
        margin: 0.5rem 0 1rem 0;
    }}
    .nm-empty-state-icon {{ font-size: 1.8rem; margin-bottom: 0.4rem; }}
    .nm-empty-state-text {{ color: var(--nm-muted); font-size: 0.95rem; margin: 0; }}

    /* Built-in st.info/st.warning/st.error/st.success alerts also get a
       slightly softer, more modern shape (rounded corners only --
       their color coding is left exactly as Streamlit renders it, so
       warnings/errors stay clearly distinguishable). */
    div[data-testid="stAlertContainer"] {{
        border-radius: 0.75rem;
    }}

    /* ================================================================
       Footer (components/footer.py)
       ================================================================ */
    .nm-footer {{
        margin-top: 3rem;
        padding: 1.25rem 0;
        border-top: 1px solid var(--nm-border);
        text-align: center;
        color: var(--nm-muted);
        font-size: 0.85rem;
    }}
    .nm-footer strong {{ color: var(--nm-primary-dark); }}

    /* ================================================================
       Accessibility -- visible keyboard-focus outlines everywhere.
       ================================================================ */
    button:focus-visible, a:focus-visible, input:focus-visible,
    textarea:focus-visible, [tabindex]:focus-visible {{
        outline: 2px solid var(--nm-primary) !important;
        outline-offset: 2px;
    }}

    /* ================================================================
       Responsiveness -- smaller screens (narrow desktop / tablet width).
       Streamlit already stacks st.columns() vertically below ~640px;
       this just keeps typography and card padding proportionate once
       that happens.
       ================================================================ */
    @media (max-width: 640px) {{
        .nm-header-title {{ font-size: 1.6rem; }}
        .nm-section-title {{ font-size: 1.1rem; }}
        div[data-testid="stMetricValue"] {{ font-size: 1.35rem; }}
        .nm-empty-state {{ padding: 1.5rem 1rem; }}
    }}
    </style>
    """
