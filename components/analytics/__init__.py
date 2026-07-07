"""Executive Analytics layer for the NovaMart Dashboard.

Split into one module per analytical view (revenue, products, regions,
executive summary, business insights) so each stays small and
independently maintainable/testable. This package is UI-only, per the
app's layered architecture: every module renders Streamlit/Plotly
against an already-filtered DataFrame and delegates all business
calculations to ``utils/calculations.py``, ``utils/analytics.py``, and
``utils/insights.py``.

``render_executive_analytics()`` is the single entry point pages should
call. It lays the five views out as tabs and hands each the same
already-filtered DataFrame, so every chart/card in every tab updates
the instant a filter changes upstream -- there is nothing to re-wire
per tab.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.analytics.executive_summary import render_executive_summary
from components.analytics.insights import render_business_insights, render_business_insights_from_value
from components.analytics.products import render_product_analytics
from components.analytics.regions import render_region_analytics
from components.analytics.revenue import render_revenue_analytics
from tenancy.context import TenantContext

__all__ = [
    "render_executive_analytics",
    "render_business_insights",
    "render_business_insights_from_value",
    "render_executive_summary",
    "render_product_analytics",
    "render_region_analytics",
    "render_revenue_analytics",
]


def render_executive_analytics(df: pd.DataFrame, *, tenant_context: TenantContext | None = None) -> None:
    """Render the full Executive Analytics layer as a tabbed section.

    Args:
        df: The (already filtered) dataset to analyze -- typically the
            DataFrame returned by the Dashboard's filter panel.
        tenant_context: The active tenant this analytics view is
            scoped to (Multi-Tenant Sprint 6.3). Only the Business
            Insights tab currently needs it (the only tab backed by a
            tenant-aware calculation); the other four tabs are
            unaffected and receive ``df`` exactly as before.
    """
    st.markdown('<p class="nm-section-title">🧭 Executive Analytics</p>', unsafe_allow_html=True)

    summary_tab, insights_tab, revenue_tab, products_tab, regions_tab = st.tabs(
        ["🧾 Executive Summary", "💡 Business Insights", "💰 Revenue", "📦 Products", "🌍 Regions"]
    )

    with summary_tab:
        render_executive_summary(df)
    with insights_tab:
        render_business_insights(df, tenant_context=tenant_context)
    with revenue_tab:
        render_revenue_analytics(df)
    with products_tab:
        render_product_analytics(df)
    with regions_tab:
        render_region_analytics(df)
