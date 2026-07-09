"""Static constants for the NovaMart Sales Intelligence Dashboard.

This module holds values that do not change at runtime: navigation
labels, KPI keys, date formats, and other fixed strings. Keeping them
here avoids "magic strings" scattered across the codebase.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------
# Each entry maps a page's display name to its file path relative to the
# project root, as required by ``st.page_link`` / ``st.navigation``.
NAV_ITEMS: list[dict[str, str | None]] = [
    {"label": "Home", "path": "app.py", "icon": "🏠", "required_permission": None},
    {"label": "Dashboard", "path": "pages/1_Dashboard.py", "icon": "📊", "required_permission": "view_dashboard"},
    {"label": "Sales", "path": "pages/2_Sales.py", "icon": "💰", "required_permission": None},
    {"label": "Products", "path": "pages/3_Products.py", "icon": "📦", "required_permission": None},
    {"label": "Customers", "path": "pages/4_Customers.py", "icon": "🧑‍🤝‍🧑", "required_permission": None},
    {"label": "Reports", "path": "pages/5_Reports.py", "icon": "📑", "required_permission": "view_reports"},
    {"label": "Monitoring", "path": "pages/6_Monitoring.py", "icon": "🩺", "required_permission": "view_monitoring"},
    {"label": "Tenant Configuration", "path": "pages/7_Tenant_Configuration.py", "icon": "🏢", "required_permission": "manage_tenants"},
    {"label": "Automation", "path": "pages/8_Automation.py", "icon": "🤖", "required_permission": "view_automation"},
]

# --------------------------------------------------------------------------
# KPI keys (used consistently across data_loader / calculations / UI)
# --------------------------------------------------------------------------
KPI_TOTAL_REVENUE = "total_revenue"
KPI_TOTAL_ORDERS = "total_orders"
KPI_AVG_ORDER_VALUE = "avg_order_value"
KPI_ACTIVE_CUSTOMERS = "active_customers"

# KPI keys computed by utils/kpi_engine.py from an uploaded dataset.
# Kept alongside the keys above so every KPI label used anywhere in the
# app (Home page placeholders or the Dashboard's live KPI engine) comes
# from this single dictionary instead of being hard-coded per-caller.
KPI_AVG_REVENUE_PER_ORDER = "avg_revenue_per_order"
KPI_TOTAL_TRANSACTIONS = "total_transactions"
KPI_HIGHEST_REVENUE_DAY = "highest_revenue_day"
KPI_LOWEST_REVENUE_DAY = "lowest_revenue_day"

KPI_LABELS: dict[str, str] = {
    KPI_TOTAL_REVENUE: "Total Revenue",
    KPI_TOTAL_ORDERS: "Total Orders",
    KPI_AVG_ORDER_VALUE: "Avg. Order Value",
    KPI_ACTIVE_CUSTOMERS: "Active Customers",
    KPI_AVG_REVENUE_PER_ORDER: "Avg. Revenue / Order",
    KPI_TOTAL_TRANSACTIONS: "Total Transactions",
    KPI_HIGHEST_REVENUE_DAY: "Highest Revenue Day",
    KPI_LOWEST_REVENUE_DAY: "Lowest Revenue Day",
}

# Icons shown alongside each KPI card. Presentation-only, kept next to
# KPI_LABELS so both live in one place instead of being duplicated
# across components.
KPI_ICONS: dict[str, str] = {
    KPI_TOTAL_REVENUE: "💰",
    KPI_TOTAL_ORDERS: "📦",
    KPI_AVG_ORDER_VALUE: "🧾",
    KPI_ACTIVE_CUSTOMERS: "🧑‍🤝‍🧑",
    KPI_AVG_REVENUE_PER_ORDER: "🧾",
    KPI_TOTAL_TRANSACTIONS: "🔢",
    KPI_HIGHEST_REVENUE_DAY: "📈",
    KPI_LOWEST_REVENUE_DAY: "📉",
}

# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------
DEFAULT_CURRENCY_SYMBOL = "$"
DEFAULT_DATE_FORMAT = "%Y-%m-%d"
DEFAULT_DISPLAY_DATE_FORMAT = "%b %d, %Y"

# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
COMPANY_NAME = "NovaMart"
APP_TAGLINE = "Sales Intelligence Dashboard"
PLACEHOLDER_NOTICE = (
    "This page is a placeholder. Data wiring and visualizations will be "
    "added in a future iteration."
)
