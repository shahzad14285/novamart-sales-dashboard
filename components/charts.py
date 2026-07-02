"""Reusable chart components for the NovaMart Dashboard.

UI-only: builds Plotly figures from a DataFrame and renders them via
Streamlit. No aggregation logic beyond a simple groupby-sum lives here
that isn't trivial charting prep; anything resembling a business
calculation belongs in ``utils/calculations.py`` instead. Styling is
pulled from ``config/settings.py`` so charts match the app's
professional blue business theme wherever they appear (this mirrors
the chart styling already used on the Home page).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from config.settings import CHART_COLOR_SEQUENCE, THEME_COLORS


def render_revenue_trend_chart(df: pd.DataFrame, date_col: str = "date", revenue_col: str = "revenue") -> None:
    """Render a revenue-over-time area chart for the given DataFrame.

    Intended to be fed the *filtered* DataFrame from the Dashboard's
    filter panel, so the chart automatically reflects whatever Date
    Range / Product / Customer / Region filters are active.

    Args:
        df: The dataset to chart (typically already filtered).
        date_col: Column holding dates.
        revenue_col: Column holding revenue values.
    """
    st.markdown("#### 📈 Revenue Trend")

    if df is None or df.empty or date_col not in df.columns or revenue_col not in df.columns:
        st.caption("No data available to chart yet.")
        return

    chart_data = df.dropna(subset=[date_col]).groupby(date_col, as_index=False)[revenue_col].sum()
    if chart_data.empty:
        st.caption("No data available to chart yet.")
        return

    figure = px.area(
        chart_data,
        x=date_col,
        y=revenue_col,
        color_discrete_sequence=CHART_COLOR_SEQUENCE,
    )
    figure.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis_title=None,
        yaxis_title="Revenue",
        font=dict(color=THEME_COLORS["text"]),
    )
    st.plotly_chart(figure, use_container_width=True)
