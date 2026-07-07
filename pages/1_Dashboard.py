"""Dashboard page.

Hosts the Upload Center (bring your own CSV/Excel data), a global
Filter Panel (Date Range / Product / Customer / Region -- whichever
columns the uploaded dataset actually has), the Key Performance
Indicators, and the Executive Analytics layer (Executive Summary /
Revenue / Products / Regions tabs), all calculated from the same
*filtered* dataset via ``utils/kpi_engine.py`` and
``components/analytics/``.

There are no hard-coded placeholder values anywhere on this page: an
empty state with guidance is shown until a file is uploaded, and every
number/chart shown afterward is recalculated automatically whenever a
new file is uploaded or a filter is changed, since Streamlit re-runs
the page top-to-bottom on every widget interaction.

Note: the standalone "Revenue Trend" chart previously shown directly on
this page now lives inside Executive Analytics' Revenue tab (alongside
a growth metric), instead of being duplicated in two places.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is importable when Streamlit runs this page
# as a standalone script inside pages/.
sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from components.analytics import render_executive_analytics
from components.empty_state import render_empty_state
from components.filter_panel import render_filter_panel
from components.footer import render_footer
from components.header import inject_header_styles, render_header
from components.kpi_cards import render_kpi_cards
from components.sidebar import render_sidebar
from components.upload_center import render_upload_center
from config.settings import PAGE_CONFIG
from utils.kpi_engine import sales_kpi_engine

st.set_page_config(**{**PAGE_CONFIG, "page_title": "NovaMart | Dashboard"})
inject_header_styles()

# render_sidebar() also renders the Sprint 6.3 tenant selector and
# returns the TenantContext resolved from it, so every KPI/insights
# calculation below is scoped to whichever organization is active in
# this browser session.
tenant_context = render_sidebar(active_label="Dashboard")
render_header(title="Dashboard", subtitle="Cross-functional overview of business performance")

st.caption(
    "Upload a CSV or Excel file below to calculate live KPIs and analytics "
    "from your own sales data."
)

# render_upload_center() returns the cleaned DataFrame for the file
# currently uploaded (or None if nothing is uploaded / validation
# failed, including a missing/inactive tenant). Streamlit re-runs this
# whole script top-to-bottom on every widget interaction -- including a
# new file being dropped into the uploader or a filter value changing
# -- so simply recomputing everything below from these return values on
# every run is what makes the page "automatically refresh": there is no
# stale state to invalidate and nothing extra to wire up.
uploaded_df = render_upload_center(tenant_context=tenant_context)

filtered_df = None
if uploaded_df is not None:
    st.divider()
    # render_filter_panel() only shows widgets for columns that are
    # actually present in the uploaded dataset (date/product/customer/
    # region), and returns the dataset narrowed to the user's current
    # selections -- everything below reads from this, never from
    # uploaded_df directly, so KPIs and every analytics tab always match
    # the active filters.
    filtered_df = render_filter_panel(uploaded_df)

st.divider()
st.markdown('<p class="nm-section-title">📊 Key Performance Indicators</p>', unsafe_allow_html=True)

if filtered_df is None:
    # No hard-coded numbers here -- just guidance. Real KPI values only
    # ever come from an uploaded, validated dataset.
    render_empty_state(
        "Upload a dataset above to see your KPIs calculated live. This "
        "section updates automatically as soon as a file is uploaded or "
        "a filter is changed.",
        icon="📄",
    )
else:
    st.caption("Recalculated automatically from the file uploaded above and any filters applied.")
    try:
        kpi_results = sales_kpi_engine.calculate_all(filtered_df, tenant_context=tenant_context)
        render_kpi_cards(kpi_results)
    except Exception as exc:  # noqa: BLE001 - defensive: a KPI bug must never crash the dashboard
        st.error(f"Unable to calculate KPIs for the uploaded file: {exc}", icon="⚠️")

if filtered_df is not None:
    st.divider()
    try:
        render_executive_analytics(filtered_df, tenant_context=tenant_context)
    except Exception as exc:  # noqa: BLE001 - defensive: an analytics bug must never crash the dashboard
        st.error(f"Unable to render executive analytics: {exc}", icon="⚠️")

render_footer()
