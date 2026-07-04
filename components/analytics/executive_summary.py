"""Executive Summary module.

A narrative, at-a-glance synthesis of the filtered dataset: total
revenue and growth (always available, since ``date``/``revenue`` are
required columns), plus Top Product / Top Region highlights when those
optional columns exist. A sentence about a dimension that isn't in the
dataset is simply omitted -- never shown as an error.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.empty_state import render_empty_state
from utils.analytics import calculate_revenue_concentration, calculate_top_group
from utils.calculations import calculate_kpi_summary, calculate_total_revenue
from utils.filters import detect_available_filters
from utils.formatting import format_currency, format_percentage


def render_executive_summary(df: pd.DataFrame, product_col: str = "product", region_col: str = "region") -> None:
    """Render a narrative executive summary of the filtered dataset.

    Args:
        df: The (already filtered) dataset to summarize.
        product_col: Column holding product names, if present.
        region_col: Column holding region names, if present.
    """
    if df is None or df.empty:
        render_empty_state("No data available for an executive summary yet.", icon="🧾")
        return

    fields = detect_available_filters(df, columns={"product": product_col, "region": region_col})

    total_revenue = calculate_total_revenue(df)
    revenue_growth = calculate_kpi_summary(df)["revenue_growth"]
    direction = "up" if revenue_growth > 0 else "down" if revenue_growth < 0 else "flat"

    st.markdown(
        f"This period generated **{format_currency(total_revenue)}** in total "
        f"revenue, trending **{direction} {format_percentage(abs(revenue_growth), signed=False)}** "
        "versus the earlier half of the same period."
    )

    highlight_columns = st.columns(2)
    has_highlight = False

    if fields["product"].available:
        _render_top_group_metric(
            highlight_columns[0], df, product_col, label="Top Product",
        )
        has_highlight = True

    if fields["region"].available:
        _render_top_group_metric(
            highlight_columns[1], df, region_col, label="Top Region",
        )
        has_highlight = True

    if not has_highlight:
        st.caption(
            "Upload a dataset with 'product' or 'region' columns to see "
            "additional highlights here."
        )


def _render_top_group_metric(column, df: pd.DataFrame, group_col: str, label: str) -> None:
    """Render a single "Top X" metric card inside a given layout column.

    Args:
        column: The Streamlit column/container to render into.
        df: The (already filtered) dataset.
        group_col: Categorical column to find the top value of.
        label: Metric label, e.g. ``"Top Product"``.
    """
    top_value, top_revenue = calculate_top_group(df, group_col)
    concentration = calculate_revenue_concentration(df, group_col)
    with column:
        with st.container(border=True):
            st.metric(
                label=label,
                value=top_value or "N/A",
                help=f"{format_currency(top_revenue)} ({concentration:.1f}% of revenue)",
            )
