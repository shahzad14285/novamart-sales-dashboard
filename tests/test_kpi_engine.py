"""Unit tests for utils/kpi_engine.py.

utils/kpi_engine.py has no Streamlit dependency, so these tests run
against the real module -- no mocking/stubbing required.
"""

from __future__ import annotations

import pandas as pd
import pytest

from utils.kpi_engine import KPIEngine, KPIResult, sales_kpi_engine


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """A small, deterministic sales DataFrame for testing."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-06-01", periods=4, freq="D"),
            "revenue": [100.0, 200.0, 300.0, 400.0],
            "orders": [10, 20, 30, 40],
        }
    )


def test_calculate_all_returns_minimum_required_kpis(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()
    results = engine.calculate_all(sample_df)

    required_keys = {
        "total_revenue",
        "total_orders",
        "avg_revenue_per_order",
        "total_transactions",
        "highest_revenue_day",
        "lowest_revenue_day",
    }
    assert required_keys.issubset(results.keys())
    assert all(isinstance(result, KPIResult) for result in results.values())


def test_total_revenue_kpi(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()
    result = engine.calculate(sample_df, "total_revenue")
    assert result.value == 1000.0
    assert result.formatted == "$1,000.00"
    assert result.label == "Total Revenue"


def test_total_orders_kpi(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()
    result = engine.calculate(sample_df, "total_orders")
    assert result.value == 100
    assert result.formatted == "100"


def test_avg_revenue_per_order_kpi(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()
    result = engine.calculate(sample_df, "avg_revenue_per_order")
    assert result.value == pytest.approx(10.0)
    assert result.formatted == "$10.00"


def test_total_transactions_kpi_counts_rows(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()
    result = engine.calculate(sample_df, "total_transactions")
    assert result.value == 4
    assert result.formatted == "4"


def test_total_transactions_differs_from_total_orders_when_aggregated() -> None:
    # 2 rows (transactions) but "orders" column sums to more than 2,
    # demonstrating the two KPIs are intentionally distinct metrics.
    df = pd.DataFrame({"date": pd.date_range("2026-06-01", periods=2), "revenue": [10.0, 20.0], "orders": [5, 7]})
    engine = KPIEngine()
    results = engine.calculate_all(df)
    assert results["total_transactions"].value == 2
    assert results["total_orders"].value == 12


def test_highest_and_lowest_revenue_day_kpis(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()
    highest = engine.calculate(sample_df, "highest_revenue_day")
    lowest = engine.calculate(sample_df, "lowest_revenue_day")

    assert highest.value == pd.Timestamp("2026-06-04")
    assert "$400.00" in highest.formatted
    assert lowest.value == pd.Timestamp("2026-06-01")
    assert "$100.00" in lowest.formatted


def test_kpis_degrade_gracefully_on_empty_dataframe() -> None:
    engine = KPIEngine()
    results = engine.calculate_all(pd.DataFrame(columns=["date", "revenue", "orders"]))

    assert results["total_revenue"].value == 0.0
    assert results["highest_revenue_day"].value is None
    assert results["highest_revenue_day"].formatted == "N/A"


def test_register_adds_a_new_kpi_without_modifying_engine(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()

    def _kpi_row_count(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
        return KPIResult(key="row_count", label="Row Count", value=len(df), formatted=str(len(df)))

    engine.register("row_count", _kpi_row_count)
    results = engine.calculate_all(sample_df)

    assert "row_count" in results
    assert results["row_count"].value == 4


def test_register_can_override_an_existing_kpi(sample_df: pd.DataFrame) -> None:
    engine = KPIEngine()

    def _always_zero(df: pd.DataFrame, date_col: str, revenue_col: str, orders_col: str) -> KPIResult:
        return KPIResult(key="total_revenue", label="Total Revenue", value=0.0, formatted="$0.00")

    engine.register("total_revenue", _always_zero)
    result = engine.calculate(sample_df, "total_revenue")

    assert result.value == 0.0


def test_custom_column_names_are_respected() -> None:
    df = pd.DataFrame(
        {
            "order_date": pd.date_range("2026-01-01", periods=2),
            "sales": [50.0, 150.0],
            "units": [5, 15],
        }
    )
    engine = KPIEngine(date_col="order_date", revenue_col="sales", orders_col="units")
    results = engine.calculate_all(df)

    assert results["total_revenue"].value == 200.0
    assert results["total_orders"].value == 20


def test_shared_sales_kpi_engine_is_preconfigured(sample_df: pd.DataFrame) -> None:
    results = sales_kpi_engine.calculate_all(sample_df)
    assert results["total_revenue"].value == 1000.0
