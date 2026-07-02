"""Unit tests for utils/calculations.py."""

from __future__ import annotations

import pandas as pd
import pytest

from utils.calculations import (
    calculate_average_order_value,
    calculate_growth_rate,
    calculate_kpi_summary,
    calculate_revenue_by_day,
    calculate_total_orders,
    calculate_total_revenue,
    find_highest_revenue_day,
    find_lowest_revenue_day,
    split_period_in_half,
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Return a small, deterministic sales DataFrame for testing."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-06-01", periods=4, freq="D"),
            "revenue": [100.0, 200.0, 300.0, 400.0],
            "orders": [10, 20, 30, 40],
        }
    )


def test_calculate_total_revenue(sample_df: pd.DataFrame) -> None:
    assert calculate_total_revenue(sample_df) == 1000.0


def test_calculate_total_revenue_empty() -> None:
    assert calculate_total_revenue(pd.DataFrame()) == 0.0


def test_calculate_total_orders(sample_df: pd.DataFrame) -> None:
    assert calculate_total_orders(sample_df) == 100


def test_calculate_average_order_value(sample_df: pd.DataFrame) -> None:
    assert calculate_average_order_value(sample_df) == pytest.approx(10.0)


def test_calculate_average_order_value_zero_orders() -> None:
    df = pd.DataFrame({"revenue": [100.0], "orders": [0]})
    assert calculate_average_order_value(df) == 0.0


def test_calculate_growth_rate() -> None:
    assert calculate_growth_rate(150, 100) == pytest.approx(50.0)
    assert calculate_growth_rate(50, 100) == pytest.approx(-50.0)


def test_calculate_growth_rate_zero_previous() -> None:
    assert calculate_growth_rate(100, 0) == 0.0


def test_split_period_in_half(sample_df: pd.DataFrame) -> None:
    earlier, later = split_period_in_half(sample_df)
    assert len(earlier) == 2
    assert len(later) == 2


def test_calculate_kpi_summary(sample_df: pd.DataFrame) -> None:
    summary = calculate_kpi_summary(sample_df)
    assert summary["total_revenue"] == 1000.0
    assert summary["total_orders"] == 100
    assert "revenue_growth" in summary
    assert "orders_growth" in summary


def test_calculate_revenue_by_day(sample_df: pd.DataFrame) -> None:
    daily = calculate_revenue_by_day(sample_df)
    assert list(daily.values) == [100.0, 200.0, 300.0, 400.0]


def test_calculate_revenue_by_day_aggregates_same_date() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-01", "2026-06-02"]),
            "revenue": [100.0, 50.0, 300.0],
        }
    )
    daily = calculate_revenue_by_day(df)
    assert len(daily) == 2
    assert daily.loc[pd.Timestamp("2026-06-01")] == 150.0


def test_calculate_revenue_by_day_empty() -> None:
    assert calculate_revenue_by_day(pd.DataFrame()).empty


def test_find_highest_revenue_day(sample_df: pd.DataFrame) -> None:
    day, revenue = find_highest_revenue_day(sample_df)
    assert day == pd.Timestamp("2026-06-04")
    assert revenue == 400.0


def test_find_lowest_revenue_day(sample_df: pd.DataFrame) -> None:
    day, revenue = find_lowest_revenue_day(sample_df)
    assert day == pd.Timestamp("2026-06-01")
    assert revenue == 100.0


def test_find_highest_revenue_day_empty() -> None:
    day, revenue = find_highest_revenue_day(pd.DataFrame())
    assert day is None
    assert revenue == 0.0


def test_find_revenue_day_ignores_missing_dates() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", None, "2026-06-02"]),
            "revenue": [100.0, 999.0, 50.0],
        }
    )
    # The 999.0 row has no valid date and must never win "highest day".
    day, revenue = find_highest_revenue_day(df)
    assert day == pd.Timestamp("2026-06-01")
    assert revenue == 100.0
