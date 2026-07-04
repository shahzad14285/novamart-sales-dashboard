"""Revenue analytics module.

Renders a period-over-period revenue growth metric alongside the
revenue trend chart for the (already filtered) dataset. ``date`` and
``revenue`` are required columns validated by ``DataLoader``, so this
view is always shown -- unlike Products/Regions, it never needs to
hide itself for a missing column.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.charts import render_revenue_trend_chart
from components.empty_state import render_empty_state
from utils.calculations import calculate_kpi_summary, calculate_total_revenue
from utils.formatting import format_currency, format_percentage


def render_revenue_analytics(df: pd.DataFrame, date_col: str = "date", revenue_col: str = "revenue") -> None:
    """Render revenue growth and trend analytics for the filtered dataset.

    Args:
        df: The (already filtered) dataset to analyze.
        date_col: Column holding dates.
        revenue_col: Column holding revenue values.
    """
    if df is None or df.empty:
        render_empty_state("No data available for revenue analytics yet.", icon="💰")
        return

    total_revenue = calculate_total_revenue(df, revenue_col)
    revenue_growth = calculate_kpi_summary(df)["revenue_growth"]

    growth_col, total_col = st.columns(2)
    with total_col:
        with st.container(border=True):
            st.metric(label="Total Revenue (filtered)", value=format_currency(total_revenue))
    with growth_col:
        with st.container(border=True):
            st.metric(
                label="Revenue Growth",
                value=format_percentage(revenue_growth),
                help="Second half of the filtered period vs. the first half.",
            )

    # Reuses the existing chart component rather than duplicating its
    # Plotly setup -- this is the same chart previously shown directly
    # on the Dashboard page, now presented alongside its growth context.
    render_revenue_trend_chart(df, date_col=date_col, revenue_col=revenue_col)
