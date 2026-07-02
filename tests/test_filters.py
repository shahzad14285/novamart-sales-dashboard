"""Unit tests for utils/filters.py.

utils/filters.py has no Streamlit dependency, so these tests run
against the real module -- no mocking/stubbing required.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from utils.filters import DEFAULT_FILTER_COLUMNS, apply_filters, detect_available_filters


@pytest.fixture
def full_df() -> pd.DataFrame:
    """A dataset that has every filterable column populated."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
            ),
            "revenue": [100.0, 200.0, 300.0, 400.0],
            "orders": [1, 2, 3, 4],
            "product": ["Widget", "Gadget", "Widget", "Gizmo"],
            "customer": ["Acme", "Acme", "Globex", "Globex"],
            "region": ["North", "South", "North", "East"],
        }
    )


@pytest.fixture
def minimal_df() -> pd.DataFrame:
    """A dataset with only the required sales columns -- no product/customer/region."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "revenue": [100.0, 200.0],
            "orders": [1, 2],
        }
    )


# --------------------------------------------------------------------------
# detect_available_filters
# --------------------------------------------------------------------------


def test_detect_available_filters_all_present(full_df: pd.DataFrame) -> None:
    fields = detect_available_filters(full_df)

    assert set(fields.keys()) == set(DEFAULT_FILTER_COLUMNS.keys())
    assert all(f.available for f in fields.values())


def test_detect_available_filters_date_bounds(full_df: pd.DataFrame) -> None:
    fields = detect_available_filters(full_df)
    date_field = fields["date"]

    assert date_field.kind == "date_range"
    assert date_field.min_value == date(2026, 1, 1)
    assert date_field.max_value == date(2026, 1, 4)


def test_detect_available_filters_categorical_options(full_df: pd.DataFrame) -> None:
    fields = detect_available_filters(full_df)

    assert fields["product"].options == ("Gadget", "Gizmo", "Widget")
    assert fields["customer"].options == ("Acme", "Globex")
    assert fields["region"].options == ("East", "North", "South")


def test_detect_available_filters_missing_columns_hidden(minimal_df: pd.DataFrame) -> None:
    fields = detect_available_filters(minimal_df)

    assert fields["date"].available is True
    assert fields["product"].available is False
    assert fields["customer"].available is False
    assert fields["region"].available is False


def test_detect_available_filters_all_null_column_is_unavailable() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "revenue": [100.0, 200.0],
            "product": [None, None],
        }
    )
    fields = detect_available_filters(df)
    assert fields["product"].available is False


def test_detect_available_filters_empty_dataframe() -> None:
    fields = detect_available_filters(pd.DataFrame())
    assert all(not f.available for f in fields.values())


def test_detect_available_filters_none_dataframe() -> None:
    fields = detect_available_filters(None)
    assert all(not f.available for f in fields.values())


def test_detect_available_filters_custom_columns() -> None:
    df = pd.DataFrame({"order_date": pd.to_datetime(["2026-01-01"]), "sku": ["A"]})
    fields = detect_available_filters(df, columns={"date": "order_date", "product": "sku"})

    assert fields["date"].available is True
    assert fields["product"].available is True
    assert fields["product"].label == "Product"


# --------------------------------------------------------------------------
# apply_filters
# --------------------------------------------------------------------------


def test_apply_filters_no_filters_returns_all_rows(full_df: pd.DataFrame) -> None:
    result = apply_filters(full_df)
    assert len(result) == len(full_df)


def test_apply_filters_date_range_inclusive(full_df: pd.DataFrame) -> None:
    result = apply_filters(full_df, date_range=(date(2026, 1, 2), date(2026, 1, 3)))
    assert len(result) == 2
    assert set(result["product"]) == {"Gadget", "Widget"}


def test_apply_filters_date_range_excludes_missing_dates() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", None]),
            "revenue": [100.0, 200.0],
        }
    )
    result = apply_filters(df, date_range=(date(2026, 1, 1), date(2026, 1, 5)))
    assert len(result) == 1


def test_apply_filters_single_categorical(full_df: pd.DataFrame) -> None:
    result = apply_filters(full_df, selected_values={"product": ["Widget"]})
    assert len(result) == 2
    assert set(result["product"]) == {"Widget"}


def test_apply_filters_empty_selection_matches_everything(full_df: pd.DataFrame) -> None:
    result = apply_filters(full_df, selected_values={"product": []})
    assert len(result) == len(full_df)


def test_apply_filters_combined_date_and_categorical(full_df: pd.DataFrame) -> None:
    result = apply_filters(
        full_df,
        date_range=(date(2026, 1, 1), date(2026, 1, 3)),
        selected_values={"region": ["North"]},
    )
    assert len(result) == 2
    assert set(result["date"].dt.strftime("%Y-%m-%d")) == {"2026-01-01", "2026-01-03"}


def test_apply_filters_multiple_categorical_fields_are_anded(full_df: pd.DataFrame) -> None:
    result = apply_filters(
        full_df,
        selected_values={"customer": ["Globex"], "region": ["North"]},
    )
    # Globex rows are index 2 (North) and 3 (East); only row 2 matches both.
    assert len(result) == 1
    assert result.loc[0, "region"] == "North"
    assert result.loc[0, "customer"] == "Globex"


def test_apply_filters_unknown_key_is_ignored(full_df: pd.DataFrame) -> None:
    result = apply_filters(full_df, selected_values={"not_a_real_filter": ["x"]})
    assert len(result) == len(full_df)


def test_apply_filters_missing_column_is_ignored(minimal_df: pd.DataFrame) -> None:
    # minimal_df has no 'product' column; filtering by it should be a no-op.
    result = apply_filters(minimal_df, selected_values={"product": ["Widget"]})
    assert len(result) == len(minimal_df)


def test_apply_filters_empty_dataframe_returns_unchanged() -> None:
    df = pd.DataFrame()
    result = apply_filters(df, selected_values={"product": ["Widget"]})
    assert result.empty


def test_apply_filters_none_dataframe_returns_none() -> None:
    assert apply_filters(None) is None


def test_apply_filters_result_has_reset_index(full_df: pd.DataFrame) -> None:
    result = apply_filters(full_df, selected_values={"product": ["Widget"]})
    assert list(result.index) == list(range(len(result)))
