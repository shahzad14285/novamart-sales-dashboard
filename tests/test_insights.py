"""Unit tests for utils/insights.py.

utils/insights.py has no Streamlit dependency, so these tests run
against the real module -- no mocking/stubbing required.
"""

from __future__ import annotations

import pandas as pd
import pytest

from utils.insights import (
    BusinessInsights,
    calculate_active_sales_days,
    calculate_average_daily_revenue,
    calculate_average_orders_per_day,
    calculate_best_worst_group,
    calculate_total_transactions,
    generate_business_insights,
)


@pytest.fixture
def full_df() -> pd.DataFrame:
    """A dataset with product and region columns, and one repeated date."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
            ),
            "revenue": [500.0, 300.0, 700.0, 200.0, 900.0, 100.0],
            "orders": [10, 8, 15, 5, 20, 4],
            "product": ["Widget", "Gadget", "Widget", "Gizmo", "Widget", "Gadget"],
            "region": ["North", "South", "North", "East", "North", "South"],
        }
    )


@pytest.fixture
def minimal_df() -> pd.DataFrame:
    """A dataset with only the required columns -- no product/region."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=4, freq="D"),
            "revenue": [100.0, 200.0, 300.0, 400.0],
            "orders": [5, 10, 15, 20],
        }
    )


# --------------------------------------------------------------------------
# calculate_active_sales_days
# --------------------------------------------------------------------------


def test_calculate_active_sales_days_counts_distinct_dates(full_df: pd.DataFrame) -> None:
    # Jan 1 appears twice -> 5 distinct days across 6 rows.
    assert calculate_active_sales_days(full_df) == 5


def test_calculate_active_sales_days_ignores_missing_dates() -> None:
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", None, "2026-01-02"])})
    assert calculate_active_sales_days(df) == 2


def test_calculate_active_sales_days_missing_column() -> None:
    assert calculate_active_sales_days(pd.DataFrame({"revenue": [1.0]})) == 0


def test_calculate_active_sales_days_empty_or_none() -> None:
    assert calculate_active_sales_days(pd.DataFrame()) == 0
    assert calculate_active_sales_days(None) == 0


# --------------------------------------------------------------------------
# calculate_average_daily_revenue / calculate_average_orders_per_day
# --------------------------------------------------------------------------


def test_calculate_average_daily_revenue(full_df: pd.DataFrame) -> None:
    # Total revenue = 2700.0 across 5 active days -> 540.0.
    assert calculate_average_daily_revenue(full_df) == pytest.approx(540.0)


def test_calculate_average_daily_revenue_no_days() -> None:
    assert calculate_average_daily_revenue(pd.DataFrame()) == 0.0


def test_calculate_average_orders_per_day(full_df: pd.DataFrame) -> None:
    # Total orders = 62 across 5 active days -> 12.4.
    assert calculate_average_orders_per_day(full_df) == pytest.approx(12.4)


def test_calculate_average_orders_per_day_no_days() -> None:
    assert calculate_average_orders_per_day(pd.DataFrame()) == 0.0


# --------------------------------------------------------------------------
# calculate_total_transactions
# --------------------------------------------------------------------------


def test_calculate_total_transactions(full_df: pd.DataFrame) -> None:
    assert calculate_total_transactions(full_df) == 6


def test_calculate_total_transactions_empty_or_none() -> None:
    assert calculate_total_transactions(pd.DataFrame()) == 0
    assert calculate_total_transactions(None) == 0


# --------------------------------------------------------------------------
# calculate_best_worst_group
# --------------------------------------------------------------------------


def test_calculate_best_worst_group(full_df: pd.DataFrame) -> None:
    # Product revenue: Widget=2100 (500+700+900), Gadget=400 (300+100), Gizmo=200.
    best_name, best_revenue, worst_name, worst_revenue = calculate_best_worst_group(full_df, "product")
    assert best_name == "Widget"
    assert best_revenue == 2100.0
    assert worst_name == "Gizmo"
    assert worst_revenue == 200.0


def test_calculate_best_worst_group_single_group() -> None:
    df = pd.DataFrame({"revenue": [100.0, 200.0], "product": ["Widget", "Widget"]})
    best_name, best_revenue, worst_name, worst_revenue = calculate_best_worst_group(df, "product")
    assert best_name == worst_name == "Widget"
    assert best_revenue == worst_revenue == 300.0


def test_calculate_best_worst_group_missing_column() -> None:
    result = calculate_best_worst_group(pd.DataFrame({"revenue": [1.0]}), "product")
    assert result == (None, 0.0, None, 0.0)


def test_calculate_best_worst_group_empty_dataframe() -> None:
    assert calculate_best_worst_group(pd.DataFrame(), "product") == (None, 0.0, None, 0.0)


# --------------------------------------------------------------------------
# generate_business_insights
# --------------------------------------------------------------------------


def test_generate_business_insights_full_dataset(full_df: pd.DataFrame) -> None:
    insights = generate_business_insights(full_df)

    assert isinstance(insights, BusinessInsights)
    assert insights.total_revenue == 2700.0
    assert insights.total_orders == 62
    assert insights.total_transactions == 6
    assert insights.active_sales_days == 5
    assert insights.average_daily_revenue == pytest.approx(540.0)
    assert insights.average_orders_per_day == pytest.approx(12.4)

    # Daily revenue: Jan1=800 (500+300), Jan2=700, Jan3=200, Jan4=900, Jan5=100.
    # Highest revenue day: Jan 4 (900.0); lowest: Jan 5 (100.0).
    assert insights.highest_revenue_day[0] == pd.Timestamp("2026-01-04")
    assert insights.highest_revenue_day[1] == 900.0
    assert insights.lowest_revenue_day[0] == pd.Timestamp("2026-01-05")
    assert insights.lowest_revenue_day[1] == 100.0

    assert insights.product_insights_available is True
    assert insights.best_product == "Widget"
    assert insights.best_product_revenue == 2100.0
    assert insights.worst_product == "Gizmo"
    assert insights.worst_product_revenue == 200.0
    # Top 3 products = all 3 products here -> 100% concentration.
    assert insights.top_product_concentration == pytest.approx(100.0)

    assert insights.region_insights_available is True
    assert insights.best_region == "North"
    assert insights.best_region_revenue == 2100.0
    assert insights.worst_region == "East"
    assert insights.worst_region_revenue == 200.0


def test_generate_business_insights_minimal_dataset(minimal_df: pd.DataFrame) -> None:
    insights = generate_business_insights(minimal_df)

    assert insights.total_revenue == 1000.0
    assert insights.product_insights_available is False
    assert insights.best_product is None
    assert insights.worst_product is None
    assert insights.top_product_concentration == 0.0
    assert insights.region_insights_available is False
    assert insights.best_region is None
    assert insights.worst_region is None


def test_generate_business_insights_empty_dataframe() -> None:
    insights = generate_business_insights(pd.DataFrame())
    assert insights.total_revenue == 0.0
    assert insights.total_orders == 0
    assert insights.total_transactions == 0
    assert insights.active_sales_days == 0
    assert insights.highest_revenue_day == (None, 0.0)
    assert insights.lowest_revenue_day == (None, 0.0)
    assert insights.product_insights_available is False
    assert insights.region_insights_available is False


def test_generate_business_insights_none_dataframe() -> None:
    insights = generate_business_insights(None)
    assert insights.total_revenue == 0.0
    assert insights.product_insights_available is False
    assert insights.region_insights_available is False


def test_generate_business_insights_top3_concentration_with_more_than_three_products() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5, freq="D"),
            "revenue": [400.0, 300.0, 200.0, 60.0, 40.0],
            "orders": [1, 1, 1, 1, 1],
            "product": ["A", "B", "C", "D", "E"],
        }
    )
    insights = generate_business_insights(df)
    # Total = 1000; top 3 (A+B+C) = 900 -> 90%.
    assert insights.top_product_concentration == pytest.approx(90.0)
