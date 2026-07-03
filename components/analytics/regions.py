"""Region analytics module.

Shows revenue share by region, if -- and only if -- the uploaded
dataset includes a ``region`` column with at least one usable value.
Hides itself with an informational message otherwise, mirroring
``components/analytics/products.py``.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import CHART_COLOR_SEQUENCE, THEME_COLORS
from utils.analytics import calculate_revenue_by_group, calculate_top_group
from utils.filters import detect_available_filters
from utils.formatting import format_currency


def render_region_analytics(df: pd.DataFrame, region_col: str = "region", revenue_col: str = "revenue") -> None:
    """Render region-level revenue analytics, if a region column exists.

    Args:
        df: The (already filtered) dataset to analyze.
        region_col: Column holding region names.
        revenue_col: Column holding revenue values.
    """
    fields = detect_available_filters(df, columns={"region": region_col})
    if not fields["region"].available:
        st.info(
            "This dataset doesn't include a usable 'region' column, so "
            "region analytics aren't available. Upload a file with a "
            "'region' column to see this view.",
            icon="🗺️",
        )
        return

    top_region, top_region_revenue = calculate_top_group(df, region_col, revenue_col)
    with st.container(border=True):
        st.metric(
            label="Top Region",
            value=top_region or "N/A",
            help=f"{format_currency(top_region_revenue)} in revenue",
        )

    revenue_by_region = calculate_revenue_by_group(df, region_col, revenue_col).reset_index()
    revenue_by_region.columns = [region_col, revenue_col]

    # A donut chart suits a "share of revenue by region" story better
    # than a bar chart, and adds visual variety alongside the Product
    # tab's bar chart -- both still use the shared theme palette.
    figure = px.pie(
        revenue_by_region,
        names=region_col,
        values=revenue_col,
        hole=0.45,
        color_discrete_sequence=CHART_COLOR_SEQUENCE,
    )
    figure.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=THEME_COLORS["text"]),
        legend_title_text=region_col.capitalize(),
    )
    st.plotly_chart(figure, use_container_width=True)
