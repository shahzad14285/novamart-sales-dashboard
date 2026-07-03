"""Unit tests for utils/analytics.py.

utils/analytics.py has no Streamlit dependency, so these tests run
against the real module -- no mocking/stubbing required.
"""

from __future__ import annotations

import pandas as pd
import pytest

from utils.analytics import (
    calculate_revenue_by_group,
    calculate_revenue_concentration,
    calculate_top_group,
    calculate_transaction_count_by_group,
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """A dataset with a categorical 'product' column for grouping tests."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5, freq="D"),
            "revenue": [100.0, 200.0, 300.0, 50.0, 350.0],
            "product": ["Widget", "Gadget", "Widget", "Gizmo", "Widget"],
        }
    )


# --------------------------------------------------------------------------
# calculate_revenue_by_group
# --------------------------------------------------------------------------


def test_calculate_revenue_by_group_sums_and_sorts_descending(sample_df: pd.DataFrame) -> None:
    result = calculate_revenue_by_group(sample_df, "product")
    assert list(result.index) == ["Widget", "Gadget", "Gizmo"]
    assert result.loc["Widget"] == 750.0
    assert result.loc["Gadget"] == 200.0
    assert result.loc["Gizmo"] == 50.0


def test_calculate_revenue_by_group_missing_column_returns_empty(sample_df: pd.DataFrame) -> None:
    result = calculate_revenue_by_group(sample_df, "customer")
    assert result.empty


def test_calculate_revenue_by_group_empty_dataframe() -> None:
    assert calculate_revenue_by_group(pd.DataFrame(), "product").empty


def test_calculate_revenue_by_group_none_dataframe() -> None:
    assert calculate_revenue_by_group(None, "product").empty


# --------------------------------------------------------------------------
# calculate_transaction_count_by_group
# --------------------------------------------------------------------------


def test_calculate_transaction_count_by_group(sample_df: pd.DataFrame) -> None:
    result = calculate_transaction_count_by_group(sample_df, "product")
    assert result.loc["Widget"] == 3
    assert result.loc["Gadget"] == 1
    assert result.loc["Gizmo"] == 1


def test_calculate_transaction_count_by_group_missing_column() -> None:
    df = pd.DataFrame({"revenue": [1.0, 2.0]})
    assert calculate_transaction_count_by_group(df, "product").empty


# --------------------------------------------------------------------------
# calculate_top_group
# --------------------------------------------------------------------------


def test_calculate_top_group(sample_df: pd.DataFrame) -> None:
    top_value, top_revenue = calculate_top_group(sample_df, "product")
    assert top_value == "Widget"
    assert top_revenue == 750.0


def test_calculate_top_group_empty_dataframe() -> None:
    top_value, top_revenue = calculate_top_group(pd.DataFrame(), "product")
    assert top_value is None
    assert top_revenue == 0.0


def test_calculate_top_group_missing_column(sample_df: pd.DataFrame) -> None:
    top_value, top_revenue = calculate_top_group(sample_df, "region")
    assert top_value is None
    assert top_revenue == 0.0


# --------------------------------------------------------------------------
# calculate_revenue_concentration
# --------------------------------------------------------------------------


def test_calculate_revenue_concentration_top_one(sample_df: pd.DataFrame) -> None:
    # Total revenue = 1000.0; Widget = 750.0 -> 75%.
    concentration = calculate_revenue_concentration(sample_df, "product", top_n=1)
    assert concentration == pytest.approx(75.0)


def test_calculate_revenue_concentration_top_two(sample_df: pd.DataFrame) -> None:
    # Widget (750) + Gadget (200) = 950 of 1000 -> 95%.
    concentration = calculate_revenue_concentration(sample_df, "product", top_n=2)
    assert concentration == pytest.approx(95.0)


def test_calculate_revenue_concentration_no_data() -> None:
    assert calculate_revenue_concentration(pd.DataFrame(), "product") == 0.0


def test_calculate_revenue_concentration_zero_revenue() -> None:
    df = pd.DataFrame({"revenue": [0.0, 0.0], "product": ["A", "B"]})
    assert calculate_revenue_concentration(df, "product") == 0.0
