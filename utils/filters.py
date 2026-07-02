"""Reusable filtering utilities for the NovaMart Sales Dashboard.

Pure, framework-agnostic functions for detecting which filterable
columns exist in a dataset and applying user-selected filter values to
a DataFrame. This module has no Streamlit dependency, so it can be
unit tested directly and reused by any future page that needs the same
"detect columns, then filter" pattern -- the UI layer for the
Dashboard's filter panel lives separately in
``components/filter_panel.py``.

Filtering never mutates the input DataFrame in place; every function
here returns a new DataFrame (or a description object), leaving the
caller's original data untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

# Which column each filter looks for by default. Kept as a single
# source of truth so detection and application always agree, and so a
# caller can override just the columns they need without redefining
# the whole mapping.
DEFAULT_FILTER_COLUMNS: dict[str, str] = {
    "date": "date",
    "product": "product",
    "customer": "customer",
    "region": "region",
}

# Display labels for the built-in filter keys. Any custom key passed
# via a ``columns`` override that isn't listed here falls back to
# ``key.capitalize()`` (see :func:`detect_available_filters`).
_DEFAULT_LABELS: dict[str, str] = {
    "date": "Date Range",
    "product": "Product",
    "customer": "Customer",
    "region": "Region",
}


@dataclass(frozen=True)
class FilterField:
    """Describes one potential filter and whether it can be shown.

    Attributes:
        key: Stable identifier for the filter (e.g. ``"product"``).
        column: The DataFrame column name this filter operates on.
        label: Human-readable label for the filter widget.
        kind: Either ``"date_range"`` or ``"categorical"``.
        available: Whether ``column`` exists in the inspected
            DataFrame *and* has at least one usable (non-null) value.
        options: For categorical filters, the sorted distinct values
            found in the column. Empty for date-range filters or when
            unavailable.
        min_value: For date-range filters, the earliest valid date
            found in the column. ``None`` otherwise.
        max_value: For date-range filters, the latest valid date found
            in the column. ``None`` otherwise.
    """

    key: str
    column: str
    label: str
    kind: str
    available: bool
    options: tuple[str, ...] = field(default_factory=tuple)
    min_value: date | None = None
    max_value: date | None = None


def detect_available_filters(
    df: pd.DataFrame | None, columns: dict[str, str] | None = None
) -> dict[str, FilterField]:
    """Inspect a DataFrame and describe which filters can be shown.

    A filter is only marked ``available`` when its column is present
    in ``df`` *and* contains at least one non-null value -- an empty or
    all-null column is treated the same as a missing one, so the UI
    layer never has to render a filter with zero usable options.

    Args:
        df: The (already validated/cleaned) DataFrame to inspect. May
            be ``None`` or empty, in which case every filter is marked
            unavailable.
        columns: Mapping of filter key -> column name to look for.
            Defaults to :data:`DEFAULT_FILTER_COLUMNS` (date, product,
            customer, region).

    Returns:
        A dict keyed by filter key, each value a :class:`FilterField`
        describing whether that column is present and, if so, its
        selectable options (categorical) or date bounds (date range).
    """
    columns = columns or DEFAULT_FILTER_COLUMNS
    has_data = df is not None and not df.empty
    fields: dict[str, FilterField] = {}

    for key, column in columns.items():
        label = _DEFAULT_LABELS.get(key, key.capitalize())
        column_present = has_data and column in df.columns

        if key == "date":
            fields[key] = _build_date_range_field(df, key, column, label, column_present)
        else:
            fields[key] = _build_categorical_field(df, key, column, label, column_present)

    return fields


def _build_date_range_field(
    df: pd.DataFrame | None, key: str, column: str, label: str, column_present: bool
) -> FilterField:
    """Build the :class:`FilterField` describing a date-range filter."""
    min_value: date | None = None
    max_value: date | None = None
    available = column_present

    if available:
        valid_dates = df[column].dropna()
        if valid_dates.empty:
            available = False
        else:
            min_value = pd.Timestamp(valid_dates.min()).date()
            max_value = pd.Timestamp(valid_dates.max()).date()

    return FilterField(key=key, column=column, label=label, kind="date_range", available=available, min_value=min_value, max_value=max_value)


def _build_categorical_field(
    df: pd.DataFrame | None, key: str, column: str, label: str, column_present: bool
) -> FilterField:
    """Build the :class:`FilterField` describing a categorical filter."""
    options: tuple[str, ...] = ()
    available = column_present

    if available:
        options = tuple(sorted(str(value) for value in df[column].dropna().unique()))
        if not options:
            available = False

    return FilterField(key=key, column=column, label=label, kind="categorical", available=available, options=options)


def apply_filters(
    df: pd.DataFrame,
    columns: dict[str, str] | None = None,
    date_range: tuple[date, date] | None = None,
    selected_values: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Apply a set of user-selected filter values to a DataFrame.

    Args:
        df: The DataFrame to filter.
        columns: Mapping of filter key -> column name, matching the
            mapping used with :func:`detect_available_filters`.
            Defaults to :data:`DEFAULT_FILTER_COLUMNS`.
        date_range: An optional ``(start, end)`` date pair to filter
            the date column by (inclusive on both ends). Ignored if
            ``None`` or if the date column isn't present in ``df``.
            Rows with a missing/unparseable date never match an active
            date-range filter.
        selected_values: An optional mapping of filter key (e.g.
            ``"product"``) -> selected values. A key with an empty
            list, or a key missing entirely, means "no filter applied
            for that field" (matches every row for that column).

    Returns:
        A filtered copy of ``df`` with a reset index. Returns ``df``
        unchanged if it is ``None`` or empty.
    """
    if df is None or df.empty:
        return df

    columns = columns or DEFAULT_FILTER_COLUMNS
    selected_values = selected_values or {}

    filtered = df.copy()

    date_column = columns.get("date")
    if date_range is not None and date_column and date_column in filtered.columns:
        start, end = date_range
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        filtered = filtered[(filtered[date_column] >= start_ts) & (filtered[date_column] <= end_ts)]

    for key, values in selected_values.items():
        if not values:
            continue
        column = columns.get(key)
        if not column or column not in filtered.columns:
            continue
        filtered = filtered[filtered[column].astype(str).isin(values)]

    return filtered.reset_index(drop=True)
