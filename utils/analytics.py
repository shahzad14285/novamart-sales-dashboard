"""Business logic for grouping revenue and transactions by a category.

Pure, framework-agnostic functions that power the Product and Region
analytics modules in ``components/analytics/``. Both dimensions boil
down to the same question -- "total revenue/transactions grouped by
some categorical column" -- so this module defines that logic once and
both UI modules reuse it with a different column name, instead of
duplicating the same groupby twice.

Revenue trend and period-over-period growth logic already lives in
``utils/calculations.py`` (``calculate_revenue_by_day``,
``calculate_kpi_summary``, etc.) and is reused as-is by
``components/analytics/revenue.py``; it is intentionally not
redefined here.

This module has no Streamlit dependency, so it can be unit tested
directly.
"""

from __future__ import annotations

import pandas as pd


def calculate_revenue_by_group(df: pd.DataFrame, group_col: str, revenue_col: str = "revenue") -> pd.Series:
    """Aggregate total revenue by an arbitrary categorical column.

    Args:
        df: DataFrame containing sales records.
        group_col: Name of the categorical column to group by (e.g.
            ``"product"`` or ``"region"``).
        revenue_col: Name of the column holding revenue values.

    Returns:
        A ``Series`` indexed by group value, holding total revenue for
        that group, sorted descending by revenue. Empty if ``df`` is
        ``None``/empty or is missing either column.
    """
    if df is None or df.empty or group_col not in df.columns or revenue_col not in df.columns:
        return pd.Series(dtype=float)
    return df.groupby(group_col)[revenue_col].sum().sort_values(ascending=False)


def calculate_transaction_count_by_group(df: pd.DataFrame, group_col: str) -> pd.Series:
    """Count records (rows) per group value.

    Args:
        df: DataFrame containing sales records.
        group_col: Name of the categorical column to group by.

    Returns:
        A ``Series`` indexed by group value, holding the row count for
        that group, sorted descending. Empty if ``df`` is ``None``/empty
        or is missing ``group_col``.
    """
    if df is None or df.empty or group_col not in df.columns:
        return pd.Series(dtype=int)
    return df.groupby(group_col).size().sort_values(ascending=False)


def calculate_top_group(df: pd.DataFrame, group_col: str, revenue_col: str = "revenue") -> tuple[str | None, float]:
    """Return the group value with the highest total revenue.

    Args:
        df: DataFrame containing sales records.
        group_col: Name of the categorical column to group by.
        revenue_col: Name of the column holding revenue values.

    Returns:
        A ``(group_value, revenue)`` tuple. ``group_value`` is ``None``
        (and revenue ``0.0``) if there is no data to compare.
    """
    revenue_by_group = calculate_revenue_by_group(df, group_col, revenue_col)
    if revenue_by_group.empty:
        return None, 0.0
    top_value = revenue_by_group.index[0]
    return str(top_value), float(revenue_by_group.iloc[0])


def calculate_revenue_concentration(
    df: pd.DataFrame, group_col: str, revenue_col: str = "revenue", top_n: int = 1
) -> float:
    """Return the percentage of total revenue contributed by the top N groups.

    Useful for an executive-style callout like "the top product drives
    42% of revenue."

    Args:
        df: DataFrame containing sales records.
        group_col: Name of the categorical column to group by.
        revenue_col: Name of the column holding revenue values.
        top_n: How many top groups to include in the concentration
            figure. Defaults to 1 (just the single top group).

    Returns:
        A percentage (0-100). Returns ``0.0`` if there is no revenue to
        compare against.
    """
    revenue_by_group = calculate_revenue_by_group(df, group_col, revenue_col)
    total = float(revenue_by_group.sum())
    if total == 0.0 or revenue_by_group.empty:
        return 0.0
    top_sum = float(revenue_by_group.iloc[:top_n].sum())
    return top_sum / total * 100
