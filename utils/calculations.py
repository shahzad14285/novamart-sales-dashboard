"""Business/domain calculations for sales intelligence metrics.

These functions operate purely on pandas data structures and plain
numbers. They contain no Streamlit or I/O code, which keeps them easy
to unit test and safe to reuse across pages (Dashboard, Sales, Reports,
etc.).
"""

from __future__ import annotations

import pandas as pd

from utils.helpers import safe_divide


def calculate_total_revenue(df: pd.DataFrame, revenue_col: str = "revenue") -> float:
    """Calculate the sum of a revenue column.

    Args:
        df: DataFrame containing sales records.
        revenue_col: Name of the column holding revenue values.

    Returns:
        The total revenue as a float. Returns 0.0 for an empty frame.
    """
    if df.empty or revenue_col not in df.columns:
        return 0.0
    return float(df[revenue_col].sum())


def calculate_total_orders(df: pd.DataFrame, orders_col: str = "orders") -> int:
    """Calculate the sum of an orders column.

    Args:
        df: DataFrame containing sales records.
        orders_col: Name of the column holding order counts.

    Returns:
        The total number of orders as an int.
    """
    if df.empty or orders_col not in df.columns:
        return 0
    return int(df[orders_col].sum())


def calculate_average_order_value(
    df: pd.DataFrame, revenue_col: str = "revenue", orders_col: str = "orders"
) -> float:
    """Calculate the average order value (revenue / orders).

    Args:
        df: DataFrame containing sales records.
        revenue_col: Name of the column holding revenue values.
        orders_col: Name of the column holding order counts.

    Returns:
        The average order value, or 0.0 if there are no orders.
    """
    total_revenue = calculate_total_revenue(df, revenue_col)
    total_orders = calculate_total_orders(df, orders_col)
    return safe_divide(total_revenue, total_orders)


def calculate_growth_rate(current_value: float, previous_value: float) -> float:
    """Calculate the percentage growth between two values.

    Args:
        current_value: The most recent value.
        previous_value: The prior-period value to compare against.

    Returns:
        The percentage change from ``previous_value`` to
        ``current_value``. Returns 0.0 if ``previous_value`` is zero.
    """
    if not previous_value:
        return 0.0
    return safe_divide(current_value - previous_value, previous_value) * 100


def split_period_in_half(df: pd.DataFrame, date_col: str = "date") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a time-ordered DataFrame into two halves for period comparison.

    Useful for computing period-over-period KPI deltas (e.g. this half
    of the date range vs. the previous half).

    Args:
        df: DataFrame containing a date column.
        date_col: Name of the column holding dates.

    Returns:
        A tuple of ``(earlier_half, later_half)`` DataFrames.
    """
    if df.empty:
        return df, df
    sorted_df = df.sort_values(date_col)
    midpoint = len(sorted_df) // 2
    return sorted_df.iloc[:midpoint], sorted_df.iloc[midpoint:]


def calculate_revenue_by_day(
    df: pd.DataFrame, date_col: str = "date", revenue_col: str = "revenue"
) -> pd.Series:
    """Aggregate revenue by day, summing rows that share the same date.

    Rows with a missing/unparseable date (``NaT``) are dropped by
    ``groupby`` automatically, so they never masquerade as a real "day"
    in downstream KPIs like :func:`find_highest_revenue_day`.

    Args:
        df: DataFrame containing sales records.
        date_col: Name of the column holding dates.
        revenue_col: Name of the column holding revenue values.

    Returns:
        A ``Series`` indexed by date, containing total revenue for that
        date, sorted chronologically. Empty if ``df`` is empty or is
        missing either column.
    """
    if df.empty or date_col not in df.columns or revenue_col not in df.columns:
        return pd.Series(dtype=float)
    return df.groupby(date_col)[revenue_col].sum().sort_index()


def find_highest_revenue_day(
    df: pd.DataFrame, date_col: str = "date", revenue_col: str = "revenue"
) -> tuple[object | None, float]:
    """Find the single day with the highest total revenue.

    Args:
        df: DataFrame containing sales records.
        date_col: Name of the column holding dates.
        revenue_col: Name of the column holding revenue values.

    Returns:
        A ``(day, revenue)`` tuple. ``day`` is ``None`` (and revenue
        ``0.0``) if there is no valid date/revenue data to compare.
    """
    daily_revenue = calculate_revenue_by_day(df, date_col, revenue_col)
    if daily_revenue.empty:
        return None, 0.0
    best_day = daily_revenue.idxmax()
    return best_day, float(daily_revenue.loc[best_day])


def find_lowest_revenue_day(
    df: pd.DataFrame, date_col: str = "date", revenue_col: str = "revenue"
) -> tuple[object | None, float]:
    """Find the single day with the lowest total revenue.

    Args:
        df: DataFrame containing sales records.
        date_col: Name of the column holding dates.
        revenue_col: Name of the column holding revenue values.

    Returns:
        A ``(day, revenue)`` tuple. ``day`` is ``None`` (and revenue
        ``0.0``) if there is no valid date/revenue data to compare.
    """
    daily_revenue = calculate_revenue_by_day(df, date_col, revenue_col)
    if daily_revenue.empty:
        return None, 0.0
    worst_day = daily_revenue.idxmin()
    return worst_day, float(daily_revenue.loc[worst_day])


def calculate_kpi_summary(df: pd.DataFrame) -> dict[str, float]:
    """Compute a dictionary of headline KPIs for a sales DataFrame.

    Compares the latter half of the date range to the earlier half to
    derive growth rates, giving each KPI a value and a delta suitable
    for display in ``st.metric``.

    Args:
        df: DataFrame with ``date``, ``revenue``, and ``orders`` columns.

    Returns:
        A dictionary with keys: ``total_revenue``, ``total_orders``,
        ``avg_order_value``, ``revenue_growth``, ``orders_growth``.
    """
    earlier_half, later_half = split_period_in_half(df)

    total_revenue = calculate_total_revenue(df)
    total_orders = calculate_total_orders(df)
    avg_order_value = calculate_average_order_value(df)

    revenue_growth = calculate_growth_rate(
        calculate_total_revenue(later_half), calculate_total_revenue(earlier_half)
    )
    orders_growth = calculate_growth_rate(
        calculate_total_orders(later_half), calculate_total_orders(earlier_half)
    )

    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "avg_order_value": avg_order_value,
        "revenue_growth": revenue_growth,
        "orders_growth": orders_growth,
    }
