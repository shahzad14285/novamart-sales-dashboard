"""Business-insight calculations for the Executive Analytics layer.

Pure, framework-agnostic functions that turn a (already filtered) sales
DataFrame into a set of executive-level observations: revenue and order
pacing, best/worst single day, best/worst product or region, and how
concentrated revenue is among the top products.

This module deliberately does **not** redefine calculations that
already exist elsewhere -- it composes them instead:

- Total revenue, total orders, and highest/lowest revenue day come from
  ``utils/calculations.py``.
- Best/worst product and best/worst region, plus revenue concentration,
  come from ``utils/analytics.py`` (``calculate_revenue_by_group`` /
  ``calculate_revenue_concentration``), which already implements
  "group by an arbitrary categorical column" once for both dimensions.
- Optional-column availability (does this dataset have a usable
  ``product``/``region`` column) comes from ``utils/filters.py``'s
  ``detect_available_filters``, the same function that decides whether
  the Product/Region *filter* widgets are shown.

The only genuinely new math here is daily pacing (average revenue/
orders per active sales day), active sales day counting, total
transaction counts, and picking the best/worst end of an already
computed group-by series. Everything else is reuse.

This module has no Streamlit dependency, so it can be unit tested
directly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tenancy.context import TenantContext, validate_tenant_context
from utils.analytics import calculate_revenue_by_group, calculate_revenue_concentration
from utils.calculations import (
    calculate_total_orders,
    calculate_total_revenue,
    find_highest_revenue_day,
    find_lowest_revenue_day,
)
from utils.filters import detect_available_filters
from utils.helpers import safe_divide

_TOP_N_PRODUCT_CONCENTRATION = 3


def calculate_active_sales_days(df: pd.DataFrame, date_col: str = "date") -> int:
    """Count the number of distinct days with a valid date value.

    Args:
        df: DataFrame containing sales records.
        date_col: Name of the column holding dates.

    Returns:
        The number of distinct, non-null dates in ``date_col``. ``0``
        if ``df`` is ``None``/empty or is missing ``date_col``.
    """
    if df is None or df.empty or date_col not in df.columns:
        return 0
    return int(df[date_col].dropna().nunique())


def calculate_average_daily_revenue(df: pd.DataFrame, date_col: str = "date", revenue_col: str = "revenue") -> float:
    """Calculate average revenue per active sales day.

    Args:
        df: DataFrame containing sales records.
        date_col: Name of the column holding dates.
        revenue_col: Name of the column holding revenue values.

    Returns:
        Total revenue divided by the number of active sales days, or
        ``0.0`` if there is no data to divide.
    """
    total_revenue = calculate_total_revenue(df, revenue_col) if df is not None and not df.empty else 0.0
    active_days = calculate_active_sales_days(df, date_col)
    return safe_divide(total_revenue, active_days)


def calculate_average_orders_per_day(df: pd.DataFrame, date_col: str = "date", orders_col: str = "orders") -> float:
    """Calculate average order count per active sales day.

    Args:
        df: DataFrame containing sales records.
        date_col: Name of the column holding dates.
        orders_col: Name of the column holding order counts.

    Returns:
        Total orders divided by the number of active sales days, or
        ``0.0`` if there is no data to divide.
    """
    total_orders = calculate_total_orders(df, orders_col) if df is not None and not df.empty else 0
    active_days = calculate_active_sales_days(df, date_col)
    return safe_divide(total_orders, active_days)


def calculate_total_transactions(df: pd.DataFrame) -> int:
    """Count the total number of transaction rows in the dataset.

    Each row in a NovaMart sales dataset represents one transaction
    record, so this is simply the row count -- kept as a named,
    documented function rather than an inline ``len(df)`` scattered
    across UI code.

    Args:
        df: DataFrame containing sales records.

    Returns:
        The number of rows in ``df``, or ``0`` if ``df`` is ``None``.
    """
    if df is None or df.empty:
        return 0
    return int(len(df))


def calculate_best_worst_group(
    df: pd.DataFrame, group_col: str, revenue_col: str = "revenue"
) -> tuple[str | None, float, str | None, float]:
    """Find the highest- and lowest-revenue values of a categorical column.

    Built on top of :func:`utils.analytics.calculate_revenue_by_group`
    rather than grouping again, so "which product/region made the
    most/least revenue" is always consistent with the Products/Regions
    analytics tabs.

    Args:
        df: DataFrame containing sales records.
        group_col: Name of the categorical column to group by (e.g.
            ``"product"`` or ``"region"``).
        revenue_col: Name of the column holding revenue values.

    Returns:
        A ``(best_name, best_revenue, worst_name, worst_revenue)``
        tuple. Names are ``None`` and revenues ``0.0`` if there is no
        data to compare. When only one group exists, best and worst
        are the same group.
    """
    revenue_by_group = calculate_revenue_by_group(df, group_col, revenue_col)
    if revenue_by_group.empty:
        return None, 0.0, None, 0.0

    best_name = str(revenue_by_group.index[0])
    best_revenue = float(revenue_by_group.iloc[0])
    worst_name = str(revenue_by_group.index[-1])
    worst_revenue = float(revenue_by_group.iloc[-1])
    return best_name, best_revenue, worst_name, worst_revenue


@dataclass(frozen=True)
class BusinessInsights:
    """Immutable bundle of executive-level observations about a dataset.

    Produced by :func:`generate_business_insights`. The UI layer
    (``components/analytics/insights.py``) reads this value object and
    never recomputes anything from it -- it only decides how to lay the
    values out and which optional cards to show.

    Attributes:
        total_revenue: Sum of revenue across the dataset.
        average_daily_revenue: Revenue per active sales day.
        highest_revenue_day: ``(day, revenue)`` for the best single day.
        lowest_revenue_day: ``(day, revenue)`` for the worst single day.
        total_orders: Sum of the orders column.
        average_orders_per_day: Orders per active sales day.
        total_transactions: Total row (transaction) count.
        active_sales_days: Number of distinct days with data.
        product_insights_available: Whether a usable ``product`` column
            was found.
        best_product: Highest-revenue product, or ``None``.
        best_product_revenue: Revenue for ``best_product``.
        worst_product: Lowest-revenue product, or ``None``.
        worst_product_revenue: Revenue for ``worst_product``.
        top_product_concentration: Percentage of total revenue driven
            by the top 3 products (``0.0`` when unavailable).
        region_insights_available: Whether a usable ``region`` column
            was found.
        best_region: Highest-revenue region, or ``None``.
        best_region_revenue: Revenue for ``best_region``.
        worst_region: Lowest-revenue region, or ``None``.
        worst_region_revenue: Revenue for ``worst_region``.
    """

    total_revenue: float
    average_daily_revenue: float
    highest_revenue_day: tuple[object | None, float]
    lowest_revenue_day: tuple[object | None, float]
    total_orders: int
    average_orders_per_day: float
    total_transactions: int
    active_sales_days: int
    product_insights_available: bool
    best_product: str | None
    best_product_revenue: float
    worst_product: str | None
    worst_product_revenue: float
    top_product_concentration: float
    region_insights_available: bool
    best_region: str | None
    best_region_revenue: float
    worst_region: str | None
    worst_region_revenue: float


def generate_business_insights(
    df: pd.DataFrame,
    date_col: str = "date",
    revenue_col: str = "revenue",
    orders_col: str = "orders",
    product_col: str = "product",
    region_col: str = "region",
    *,
    tenant_context: TenantContext | None = None,
) -> BusinessInsights:
    """Compute the full set of executive-level insights for a dataset.

    ``date``/``revenue``/``orders`` are required columns (validated by
    ``DataLoader``), so the core insights are always populated. Product
    and region insights are computed only when those optional columns
    are present and usable, exactly as decided by
    ``utils.filters.detect_available_filters`` -- the single source of
    truth for "does this dataset support this dimension" used
    throughout the analytics package.

    Args:
        df: The (already filtered) dataset to analyze.
        date_col: Column holding dates.
        revenue_col: Column holding revenue values.
        orders_col: Column holding order counts.
        product_col: Column holding product names, if present.
        region_col: Column holding region names, if present.
        tenant_context: The tenant these insights are scoped to
            (Multi-Tenant Sprint 6.3). Required for the call to
            succeed -- see :func:`~tenancy.context.validate_tenant_context`.
            The insight formulas themselves never change per tenant;
            this only guarantees every calculation is attributable to,
            and gated on, an active tenant.

    Returns:
        A fully populated :class:`BusinessInsights` value object. If
        ``df`` is ``None`` or empty, every numeric field is zeroed and
        every optional dimension is marked unavailable.

    Raises:
        MissingTenantContextError: If no tenant context was supplied.
        InactiveTenantError: If the supplied tenant is not active.
    """
    validate_tenant_context(tenant_context, service_name="BusinessInsights", operation="generate_business_insights")

    if df is None or df.empty:
        return BusinessInsights(
            total_revenue=0.0,
            average_daily_revenue=0.0,
            highest_revenue_day=(None, 0.0),
            lowest_revenue_day=(None, 0.0),
            total_orders=0,
            average_orders_per_day=0.0,
            total_transactions=0,
            active_sales_days=0,
            product_insights_available=False,
            best_product=None,
            best_product_revenue=0.0,
            worst_product=None,
            worst_product_revenue=0.0,
            top_product_concentration=0.0,
            region_insights_available=False,
            best_region=None,
            best_region_revenue=0.0,
            worst_region=None,
            worst_region_revenue=0.0,
        )

    fields = detect_available_filters(df, columns={"product": product_col, "region": region_col})

    product_available = fields["product"].available
    if product_available:
        best_product, best_product_revenue, worst_product, worst_product_revenue = calculate_best_worst_group(
            df, product_col, revenue_col
        )
        top_product_concentration = calculate_revenue_concentration(
            df, product_col, revenue_col, top_n=_TOP_N_PRODUCT_CONCENTRATION
        )
    else:
        best_product = worst_product = None
        best_product_revenue = worst_product_revenue = 0.0
        top_product_concentration = 0.0

    region_available = fields["region"].available
    if region_available:
        best_region, best_region_revenue, worst_region, worst_region_revenue = calculate_best_worst_group(
            df, region_col, revenue_col
        )
    else:
        best_region = worst_region = None
        best_region_revenue = worst_region_revenue = 0.0

    return BusinessInsights(
        total_revenue=calculate_total_revenue(df, revenue_col),
        average_daily_revenue=calculate_average_daily_revenue(df, date_col, revenue_col),
        highest_revenue_day=find_highest_revenue_day(df, date_col, revenue_col),
        lowest_revenue_day=find_lowest_revenue_day(df, date_col, revenue_col),
        total_orders=calculate_total_orders(df, orders_col),
        average_orders_per_day=calculate_average_orders_per_day(df, date_col, orders_col),
        total_transactions=calculate_total_transactions(df),
        active_sales_days=calculate_active_sales_days(df, date_col),
        product_insights_available=product_available,
        best_product=best_product,
        best_product_revenue=best_product_revenue,
        worst_product=worst_product,
        worst_product_revenue=worst_product_revenue,
        top_product_concentration=top_product_concentration,
        region_insights_available=region_available,
        best_region=best_region,
        best_region_revenue=best_region_revenue,
        worst_region=worst_region,
        worst_region_revenue=worst_region_revenue,
    )
