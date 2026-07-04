"""Reusable global filter panel component for the NovaMart Dashboard.

Renders Streamlit widgets for whichever filters apply to the current
dataset (Date Range, Product, Customer, Region), delegating all
detection and filtering logic to ``utils/filters.py``. Following the
app's layered architecture, this module is UI-only: it never inspects
DataFrame contents itself beyond what ``utils/filters.py`` already
described for it.

If a column isn't present in the uploaded dataset (or has no usable
values), its widget is simply not rendered -- no error, no empty
dropdown.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components.empty_state import render_empty_state
from utils.filters import DEFAULT_FILTER_COLUMNS, FilterField, apply_filters, detect_available_filters


def render_filter_panel(
    df: pd.DataFrame,
    columns: dict[str, str] | None = None,
    key_prefix: str = "dashboard_filters",
) -> pd.DataFrame:
    """Render the filter panel and return the filtered DataFrame.

    Args:
        df: The dataset to filter (typically the DataFrame returned by
            the Upload Center / ``DataLoader``).
        columns: Optional override of which column name each filter
            key maps to. Defaults to
            :data:`~utils.filters.DEFAULT_FILTER_COLUMNS`.
        key_prefix: Prefix for Streamlit widget keys, so multiple
            filter panels can coexist on different pages without key
            collisions.

    Returns:
        The filtered DataFrame -- feed this into the KPI engine and
        any charts so they automatically reflect the active filters.
        Returns ``df`` unchanged if no filters are available/applied.
    """
    columns = columns or DEFAULT_FILTER_COLUMNS
    fields = detect_available_filters(df, columns)
    available_fields = {key: f for key, f in fields.items() if f.available}

    st.markdown('<p class="nm-section-title">🔍 Filters</p>', unsafe_allow_html=True)

    if not available_fields:
        render_empty_state(
            "No filterable columns (date, product, customer, region) "
            "were found in this dataset.",
            icon="🔍",
        )
        return df

    date_field = available_fields.get("date")
    categorical_fields = [f for key, f in available_fields.items() if key != "date"]

    date_range = _render_date_range_widget(date_field, key_prefix) if date_field else None
    selected_values = _render_categorical_widgets(categorical_fields, key_prefix)

    filtered_df = apply_filters(df, columns=columns, date_range=date_range, selected_values=selected_values)
    _render_filter_summary(df, filtered_df)

    return filtered_df


def _render_date_range_widget(date_field: FilterField, key_prefix: str) -> tuple | None:
    """Render the date-range picker and return the selected range.

    Args:
        date_field: The detected date filter field (already known to
            be available, with ``min_value``/``max_value`` set).
        key_prefix: Prefix for the widget's Streamlit key.

    Returns:
        A ``(start, end)`` tuple once both ends of the range are
        selected, otherwise ``None`` (e.g. while the user has only
        picked a start date so far).
    """
    selected = st.date_input(
        date_field.label,
        value=(date_field.min_value, date_field.max_value),
        min_value=date_field.min_value,
        max_value=date_field.max_value,
        key=f"{key_prefix}_date",
        help="Only rows within this date range are included.",
    )
    if isinstance(selected, tuple) and len(selected) == 2:
        return selected
    return None


def _render_categorical_widgets(fields: list[FilterField], key_prefix: str) -> dict[str, list[str]]:
    """Render one multiselect per available categorical filter.

    Args:
        fields: The detected categorical filter fields to render
            (already known to be available, with ``options`` set).
        key_prefix: Prefix for each widget's Streamlit key.

    Returns:
        A mapping of filter key -> the values the user selected (an
        empty list means "no filter applied for that field").
    """
    selected_values: dict[str, list[str]] = {}
    if not fields:
        return selected_values

    widget_columns = st.columns(len(fields))
    for widget_column, field in zip(widget_columns, fields):
        with widget_column:
            selected_values[field.key] = st.multiselect(
                field.label,
                options=field.options,
                default=[],
                key=f"{key_prefix}_{field.key}",
                help=f"Filter by {field.label.lower()}. Leave empty to include all.",
            )
    return selected_values


def _render_filter_summary(original_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    """Show a small "X of Y rows" caption when filters narrow the data.

    Args:
        original_df: The dataset before filtering.
        filtered_df: The dataset after filtering.
    """
    total_rows = len(original_df)
    shown_rows = len(filtered_df)
    if shown_rows != total_rows:
        st.caption(f"Showing {shown_rows:,} of {total_rows:,} rows after filtering.")
