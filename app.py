"""NovaMart Sales Intelligence Dashboard -- application entry point.

This is the Home page of the multipage Streamlit app. It is intentionally
thin: page configuration, layout, and composition only. Business logic
lives in ``utils/`` and presentation building blocks live in
``components/``.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.sidebar import render_sidebar
from config.constants import APP_TAGLINE, COMPANY_NAME
from config.settings import CHART_COLOR_SEQUENCE, PAGE_CONFIG, THEME_COLORS
from utils.calculations import calculate_kpi_summary
from utils.data_loader import load_sales_data
from utils.exceptions import DataLoaderError
from utils.formatting import format_currency, format_number_compact, format_percentage
from utils.helpers import get_greeting_by_time


def configure_page() -> None:
    """Apply global Streamlit page configuration and inject shared CSS."""
    st.set_page_config(**PAGE_CONFIG)
    inject_header_styles()

    # Global styling for KPI cards, matching the professional blue theme.
    st.markdown(
        f"""
        <style>
        .nm-kpi-card {{
            background-color: {THEME_COLORS['secondary_background']};
            border: 1px solid {THEME_COLORS['border']};
            border-radius: 0.75rem;
            padding: 1rem 1.25rem;
        }}
        .nm-section-title {{
            color: {THEME_COLORS['primary_dark']};
            font-weight: 600;
            margin-top: 1.5rem;
            margin-bottom: 0.5rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_section() -> None:
    """Render the placeholder KPI (Key Performance Indicator) section.

    Pulls sales data through the ``DataLoader``-backed data layer,
    computes summary metrics via the calculations layer, and displays
    them with ``st.metric`` inside styled cards. Any data-loading
    failure (missing file, bad columns, unreadable file) is caught here
    and shown as a friendly message instead of crashing the page.
    """
    st.markdown('<p class="nm-section-title">Key Performance Indicators</p>', unsafe_allow_html=True)

    try:
        sales_df = load_sales_data()
    except DataLoaderError as exc:
        st.error(f"Unable to load KPI data: {exc}", icon="⚠️")
        return

    kpis = calculate_kpi_summary(sales_df)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        with st.container(border=True):
            st.metric(
                label="Total Revenue",
                value=format_currency(kpis["total_revenue"]),
                delta=format_percentage(kpis["revenue_growth"]),
            )
    with col2:
        with st.container(border=True):
            st.metric(
                label="Total Orders",
                value=format_number_compact(kpis["total_orders"]),
                delta=format_percentage(kpis["orders_growth"]),
            )
    with col3:
        with st.container(border=True):
            st.metric(
                label="Avg. Order Value",
                value=format_currency(kpis["avg_order_value"]),
            )
    with col4:
        with st.container(border=True):
            st.metric(
                label="Active Customers",
                value="1,240",
                delta="+4.2%",
            )


def render_chart_section() -> None:
    """Render the placeholder chart section showing revenue trends.

    This uses sample data as a stand-in until a real analytics pipeline
    is connected. The chart follows the app's blue business theme. Data
    is loaded through the same ``DataLoader``-backed layer as the KPI
    section, with failures shown as a friendly message.
    """
    st.markdown('<p class="nm-section-title">Revenue Trend (Sample Data)</p>', unsafe_allow_html=True)

    try:
        sales_df = load_sales_data()
    except DataLoaderError as exc:
        st.error(f"Unable to load chart data: {exc}", icon="⚠️")
        return

    fig = px.area(
        sales_df,
        x="date",
        y="revenue",
        color_discrete_sequence=CHART_COLOR_SEQUENCE,
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis_title=None,
        yaxis_title="Revenue",
        font=dict(color=THEME_COLORS["text"]),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "This chart uses generated placeholder data. Connect a live data "
        "source in `utils/data_loader.py` to replace it."
    )


def main() -> None:
    """Compose and render the NovaMart home page."""
    configure_page()
    render_sidebar(active_label="Home")
    render_header(title=f"{COMPANY_NAME} Dashboard", subtitle=APP_TAGLINE)

    greeting = get_greeting_by_time()
    st.markdown(
        f"### {greeting} 👋\n"
        f"Welcome to the **{COMPANY_NAME}** Sales Intelligence Dashboard -- "
        "your central hub for tracking revenue, orders, products, and "
        "customer performance. Use the sidebar to explore Dashboard, "
        "Sales, Products, Customers, and Reports."
    )

    render_kpi_section()
    st.divider()
    render_chart_section()

    render_footer()


if __name__ == "__main__":
    main()
