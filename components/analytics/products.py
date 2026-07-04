"""Product analytics module.

Shows revenue and transaction volume by product, if -- and only if --
the uploaded dataset includes a ``product`` column with at least one
usable value. Hides itself with an informational message otherwise;
a column that was never required in the first place is never treated
as an error.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from components.empty_state import render_empty_state
from config.settings import CHART_COLOR_SEQUENCE, THEME_COLORS
from utils.analytics import (
    calculate_revenue_by_group,
    calculate_top_group,
    calculate_transaction_count_by_group,
)
from utils.filters import detect_available_filters
from utils.formatting import format_currency

_TOP_N_PRODUCTS = 10


def render_product_analytics(df: pd.DataFrame, product_col: str = "product", revenue_col: str = "revenue") -> None:
    """Render product-level revenue analytics, if a product column exists.

    Args:
        df: The (already filtered) dataset to analyze.
        product_col: Column holding product names.
        revenue_col: Column holding revenue values.
    """
    # Reuses the same column-detection logic the filter panel uses, so
    # "does this dataset support product analytics" is answered exactly
    # the same way everywhere in the app.
    fields = detect_available_filters(df, columns={"product": product_col})
    if not fields["product"].available:
        render_empty_state(
            "This dataset doesn't include a usable 'product' column, so "
            "product analytics aren't available. Upload a file with a "
            "'product' column to see this view.",
            icon="📦",
        )
        return

    top_product, top_product_revenue = calculate_top_group(df, product_col, revenue_col)
    with st.container(border=True):
        st.metric(
            label="Top Product",
            value=top_product or "N/A",
            help=f"{format_currency(top_product_revenue)} in revenue",
        )

    revenue_by_product = calculate_revenue_by_group(df, product_col, revenue_col).head(_TOP_N_PRODUCTS)
    chart_data = revenue_by_product.reset_index()
    chart_data.columns = [product_col, revenue_col]

    figure = px.bar(chart_data, x=product_col, y=revenue_col, color_discrete_sequence=CHART_COLOR_SEQUENCE)
    figure.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis_title=None,
        yaxis_title="Revenue",
        font=dict(color=THEME_COLORS["text"]),
    )
    st.plotly_chart(figure, use_container_width=True)

    transactions_by_product = calculate_transaction_count_by_group(df, product_col)
    with st.expander("Transaction counts by product"):
        st.dataframe(
            transactions_by_product.rename("transactions").reset_index(),
            use_container_width=True,
        )
