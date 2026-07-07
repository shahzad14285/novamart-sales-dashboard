"""Dynamic KPI calculation engine for the NovaMart Sales Dashboard.

Turns a validated sales DataFrame -- typically the one returned by
:class:`~utils.data_loader.DataLoader` -- into a set of ready-to-display
KPI results.

This module deliberately contains **no new numeric business logic** of
its own for totals/averages: those already live in
``utils/calculations.py`` and are reused here so the formula for "total
revenue" (for example) is defined in exactly one place, no matter which
page displays it. This module's job is orchestration and presentation
packaging: decide which KPIs exist, compute each one via the shared
calculation functions, and package the result (value + formatted string
+ label + icon) for the UI layer (``components/kpi_cards.py``) to
render.

It has no Streamlit dependency, so it can be unit tested directly and
reused outside of a Streamlit context if needed.

Adding a new KPI later requires no changes to existing code: write a
function matching the :data:`KPIFunction` signature and call
``engine.register("my_kpi", my_function)``. See docs/KPI_ENGINE.md for
worked examples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from config.constants import KPI_ICONS, KPI_LABELS
from monitoring.service import monitoring_service
from tenancy.context import TenantContext, validate_tenant_context
from utils.calculations import (
    calculate_average_order_value,
    calculate_total_orders,
    calculate_total_revenue,
    find_highest_revenue_day,
    find_lowest_revenue_day,
)
from utils.formatting import format_currency, format_date, format_integer


@dataclass(frozen=True)
class KPIResult:
    """A single, ready-to-display KPI value.

    Attributes:
        key: Stable identifier for the KPI (e.g. ``"total_revenue"``).
        label: Human-readable label shown in the UI.
        value: The raw computed value (float, int, a date-like object,
            or ``None`` when it can't be computed).
        formatted: A display-ready string representation of ``value``.
        icon: Optional emoji/icon shown alongside the label.
        help_text: Optional tooltip text explaining the KPI.
    """

    key: str
    label: str
    value: float | int | object | None
    formatted: str
    icon: str = ""
    help_text: str = ""


# Every registered KPI function receives the DataFrame plus the three
# configured column names and returns a KPIResult. Keeping the
# signature uniform is what makes the registry pattern below work for
# any future KPI without changing KPIEngine itself.
KPIFunction = Callable[[pd.DataFrame, str, str, str], KPIResult]


class KPIEngine:
    """Reusable, registry-based KPI calculation engine.

    Configured once with the column names a dataset uses for date,
    revenue, and orders, then reused to compute the full set of KPIs
    for any DataFrame that shares that shape.

    Example:
        >>> engine = KPIEngine()
        >>> results = engine.calculate_all(sales_df)
        >>> results["total_revenue"].formatted
        '$12,345.67'

        # Registering a new KPI later, without touching this class:
        >>> def _kpi_row_count(df, date_col, revenue_col, orders_col):
        ...     return KPIResult("row_count", "Row Count", len(df), str(len(df)))
        >>> engine.register("row_count", _kpi_row_count)
    """

    def __init__(self, date_col: str = "date", revenue_col: str = "revenue", orders_col: str = "orders") -> None:
        """Configure a KPI engine for a particular dataset shape.

        Args:
            date_col: Column name holding the transaction/record date.
            revenue_col: Column name holding revenue values.
            orders_col: Column name holding order counts.
        """
        self.date_col = date_col
        self.revenue_col = revenue_col
        self.orders_col = orders_col
        self._registry: dict[str, KPIFunction] = {}
        self._register_default_kpis()

    def register(self, key: str, func: KPIFunction) -> None:
        """Register a KPI calculation function under ``key``.

        Calling this with an existing key replaces that KPI, which
        also makes it easy to override a default KPI's formula for a
        specialized dashboard without subclassing.

        Args:
            key: Unique identifier for the KPI.
            func: A callable matching the :data:`KPIFunction` signature.
        """
        self._registry[key] = func

    def calculate_all(
        self, df: pd.DataFrame, *, tenant_context: TenantContext | None = None
    ) -> dict[str, KPIResult]:
        """Compute every registered KPI for ``df``.

        Args:
            df: A validated DataFrame, typically returned by
                :class:`~utils.data_loader.DataLoader`.
            tenant_context: The tenant this calculation is scoped to
                (Multi-Tenant Sprint 6.3). Required for the call to
                succeed -- see :func:`~tenancy.context.validate_tenant_context`.
                The KPI formulas themselves never change per tenant;
                this only guarantees every calculation is attributable
                to, and gated on, an active tenant.

        Returns:
            A dict mapping each KPI's key to its :class:`KPIResult`, in
            registration order (default KPIs first, then any KPIs
            registered afterward).

        Raises:
            MissingTenantContextError: If no tenant context was supplied.
            InactiveTenantError: If the supplied tenant is not active.
        """
        # Sprint 6.4 -- Observability & Monitoring Service: wraps tenant
        # validation + the (unchanged) calculation below so a start,
        # completion/failure, and duration are always recorded, without
        # KPIEngine knowing how or where those events are stored.
        with monitoring_service.time_operation(
            service_name="KPIEngine", operation="calculate_all", tenant_context=tenant_context
        ):
            validate_tenant_context(tenant_context, service_name="KPIEngine", operation="calculate_all")
            return {
                key: func(df, self.date_col, self.revenue_col, self.orders_col)
                for key, func in self._registry.items()
            }

    def calculate(self, df: pd.DataFrame, key: str) -> KPIResult:
        """Compute a single KPI by key.

        Args:
            df: The DataFrame to compute the KPI on.
            key: The registered KPI key.

        Returns:
            The computed :class:`KPIResult`.

        Raises:
            KeyError: If ``key`` isn't registered.
        """
        return self._registry[key](df, self.date_col, self.revenue_col, self.orders_col)

    # ------------------------------------------------------------------
    # Default KPI set (Requirement: minimum 6 KPIs, easily extendable)
    # ------------------------------------------------------------------
    def _register_default_kpis(self) -> None:
        """Register the minimum required KPI set."""
        self.register("total_revenue", _kpi_total_revenue)
        self.register("total_orders", _kpi_total_orders)
        self.register("avg_revenue_per_order", _kpi_avg_revenue_per_order)
        self.register("total_transactions", _kpi_total_transactions)
        self.register("highest_revenue_day", _kpi_highest_revenue_day)
        self.register("lowest_revenue_day", _kpi_lowest_revenue_day)


# --------------------------------------------------------------------------
# Default KPI calculation functions
# --------------------------------------------------------------------------
# Each function follows the KPIFunction signature so it can be swapped
# in/out of the registry uniformly. All numeric business logic is
# delegated to utils/calculations.py -- these functions only call that
# logic and format the result for display via utils/formatting.py.


def _kpi_total_revenue(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
    """Total Revenue = sum of the revenue column."""
    value = calculate_total_revenue(df, revenue_col)
    return KPIResult(
        key="total_revenue",
        label=KPI_LABELS["total_revenue"],
        value=value,
        formatted=format_currency(value),
        icon=KPI_ICONS["total_revenue"],
        help_text="Sum of all revenue in the uploaded dataset.",
    )


def _kpi_total_orders(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
    """Total Orders = sum of the orders column."""
    value = calculate_total_orders(df, orders_col)
    return KPIResult(
        key="total_orders",
        label=KPI_LABELS["total_orders"],
        value=value,
        formatted=format_integer(value),
        icon=KPI_ICONS["total_orders"],
        help_text="Sum of the orders column across all rows.",
    )


def _kpi_avg_revenue_per_order(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
    """Average Revenue per Order = total revenue / total orders."""
    value = calculate_average_order_value(df, revenue_col, orders_col)
    return KPIResult(
        key="avg_revenue_per_order",
        label=KPI_LABELS["avg_revenue_per_order"],
        value=value,
        formatted=format_currency(value),
        icon=KPI_ICONS["avg_revenue_per_order"],
        help_text="Total revenue divided by total orders.",
    )


def _kpi_total_transactions(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
    """Total Transactions = number of records (rows) in the dataset."""
    value = int(len(df))
    return KPIResult(
        key="total_transactions",
        label=KPI_LABELS["total_transactions"],
        value=value,
        formatted=format_integer(value),
        icon=KPI_ICONS["total_transactions"],
        help_text="Number of records (rows) in the uploaded dataset -- "
        "distinct from Total Orders, which sums the orders column.",
    )


def _kpi_highest_revenue_day(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
    """Highest Revenue Day = the date whose summed revenue is largest."""
    day, revenue = find_highest_revenue_day(df, date_col, revenue_col)
    return KPIResult(
        key="highest_revenue_day",
        label=KPI_LABELS["highest_revenue_day"],
        value=day,
        formatted=_format_day_with_revenue(day, revenue),
        icon=KPI_ICONS["highest_revenue_day"],
        help_text="The single day with the highest total revenue.",
    )


def _kpi_lowest_revenue_day(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
    """Lowest Revenue Day = the date whose summed revenue is smallest."""
    day, revenue = find_lowest_revenue_day(df, date_col, revenue_col)
    return KPIResult(
        key="lowest_revenue_day",
        label=KPI_LABELS["lowest_revenue_day"],
        value=day,
        formatted=_format_day_with_revenue(day, revenue),
        icon=KPI_ICONS["lowest_revenue_day"],
        help_text="The single day with the lowest total revenue.",
    )


def _format_day_with_revenue(day: object | None, revenue: float) -> str:
    """Format a ``(day, revenue)`` pair for display, tolerating odd input.

    Args:
        day: A date-like value (usually a ``pandas.Timestamp``), or
            ``None`` if no valid day could be determined.
        revenue: The revenue total for that day.

    Returns:
        e.g. ``"Jul 02, 2026 ($1,234.56)"``, or ``"N/A"`` if ``day`` is
        ``None``. Falls back to ``str(day)`` if ``day`` doesn't support
        ``strftime`` (e.g. the date column wasn't parsed as a date).
    """
    if day is None:
        return "N/A"
    day_text = format_date(day) if hasattr(day, "strftime") else str(day)
    return f"{day_text} ({format_currency(revenue)})"


# A shared, ready-to-use engine configured for the sales dataset shape
# (date/revenue/orders), mirroring utils.data_loader.sales_data_loader.
# Pages can import this directly instead of constructing their own
# KPIEngine when the default sales shape applies.
sales_kpi_engine = KPIEngine(date_col="date", revenue_col="revenue", orders_col="orders")
