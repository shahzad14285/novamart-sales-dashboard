"""Business Insights panel module.

Renders executive-level observation cards -- revenue/order pacing,
best/worst single day, best/worst product or region, and top-product
revenue concentration -- from a :class:`~utils.insights.BusinessInsights`
value object. Like every other module in ``components/analytics/``,
this file is UI-only: it never computes a metric itself, it only lays
out ``st.metric`` cards using the same bordered-card styling already
established by ``components/kpi_cards.py`` and the rest of the
analytics package.

Product and region cards are shown only when
``utils.insights.generate_business_insights`` marks that dimension as
available, so a dataset without a ``product``/``region`` column simply
shows fewer cards -- never an error.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.empty_state import render_empty_state
from utils.formatting import format_currency, format_date, format_integer, format_percentage
from utils.insights import BusinessInsights, generate_business_insights


def render_business_insights(
    df: pd.DataFrame,
    date_col: str = "date",
    revenue_col: str = "revenue",
    orders_col: str = "orders",
    product_col: str = "product",
    region_col: str = "region",
) -> None:
    """Render the Business Insights panel for the filtered dataset.

    Args:
        df: The (already filtered) dataset to analyze.
        date_col: Column holding dates.
        revenue_col: Column holding revenue values.
        orders_col: Column holding order counts.
        product_col: Column holding product names, if present.
        region_col: Column holding region names, if present.
    """
    if df is None or df.empty:
        render_empty_state("No data available for business insights yet.", icon="💡")
        return

    insights = generate_business_insights(
        df,
        date_col=date_col,
        revenue_col=revenue_col,
        orders_col=orders_col,
        product_col=product_col,
        region_col=region_col,
    )

    st.caption("Executive-level observations calculated automatically from the filtered dataset.")
    render_business_insights_from_value(insights)


def render_business_insights_from_value(insights: BusinessInsights) -> None:
    """Render the Business Insights cards from an already-computed value object.

    Split out from :func:`render_business_insights` so a caller that
    already has a :class:`BusinessInsights` instance -- e.g. the
    Executive Report Center rendering a
    :class:`~services.reporting_service.Report`'s ``business_insights``
    section -- can reuse the exact same card layout without calling
    :func:`~utils.insights.generate_business_insights` a second time.

    Args:
        insights: An already-computed :class:`BusinessInsights` value object.
    """
    _render_pacing_cards(insights)
    _render_day_cards(insights)
    _render_volume_cards(insights)

    has_optional_section = insights.product_insights_available or insights.region_insights_available

    if insights.product_insights_available:
        _render_product_cards(insights)

    if insights.region_insights_available:
        _render_region_cards(insights)

    if not has_optional_section:
        st.caption(
            "Upload a dataset with 'product' or 'region' columns to see "
            "best/worst product and region insights here."
        )


def _render_pacing_cards(insights: BusinessInsights) -> None:
    """Render Total Revenue / Average Daily Revenue / Total Orders / Average Orders per Day."""
    columns = st.columns(4)
    cards = [
        ("💰 Total Revenue", format_currency(insights.total_revenue), None),
        ("📅 Average Daily Revenue", format_currency(insights.average_daily_revenue), "Total revenue divided by active sales days."),
        ("📦 Total Orders", format_integer(insights.total_orders), None),
        ("🧾 Average Orders / Day", f"{insights.average_orders_per_day:,.1f}", "Total orders divided by active sales days."),
    ]
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            with st.container(border=True):
                st.metric(label=label, value=value, help=help_text)


def _render_day_cards(insights: BusinessInsights) -> None:
    """Render Highest Revenue Day / Lowest Revenue Day."""
    columns = st.columns(2)
    day_cards = [
        ("📈 Highest Revenue Day", insights.highest_revenue_day),
        ("📉 Lowest Revenue Day", insights.lowest_revenue_day),
    ]
    for column, (label, (day, revenue)) in zip(columns, day_cards):
        with column:
            with st.container(border=True):
                value = format_date(day) if day is not None else "N/A"
                st.metric(label=label, value=value, help=format_currency(revenue) if day is not None else None)


def _render_volume_cards(insights: BusinessInsights) -> None:
    """Render Total Transactions / Active Sales Days."""
    columns = st.columns(2)
    with columns[0]:
        with st.container(border=True):
            st.metric(label="🔢 Total Transactions", value=format_integer(insights.total_transactions))
    with columns[1]:
        with st.container(border=True):
            st.metric(label="🗓️ Active Sales Days", value=format_integer(insights.active_sales_days))


def _render_product_cards(insights: BusinessInsights) -> None:
    """Render Best Product / Worst Product / Top 3 Product Concentration."""
    columns = st.columns(3)
    with columns[0]:
        with st.container(border=True):
            st.metric(
                label="🏆 Best Product",
                value=insights.best_product or "N/A",
                help=format_currency(insights.best_product_revenue),
            )
    with columns[1]:
        with st.container(border=True):
            st.metric(
                label="⚠️ Worst Product",
                value=insights.worst_product or "N/A",
                help=format_currency(insights.worst_product_revenue),
            )
    with columns[2]:
        with st.container(border=True):
            st.metric(
                label="🎯 Revenue Concentration (Top 3)",
                value=format_percentage(insights.top_product_concentration, signed=False),
                help="Share of total revenue driven by the top 3 products.",
            )


def _render_region_cards(insights: BusinessInsights) -> None:
    """Render Best Region / Worst Region."""
    columns = st.columns(2)
    with columns[0]:
        with st.container(border=True):
            st.metric(
                label="🌍 Best Region",
                value=insights.best_region or "N/A",
                help=format_currency(insights.best_region_revenue),
            )
    with columns[1]:
        with st.container(border=True):
            st.metric(
                label="📍 Worst Region",
                value=insights.worst_region or "N/A",
                help=format_currency(insights.worst_region_revenue),
            )
