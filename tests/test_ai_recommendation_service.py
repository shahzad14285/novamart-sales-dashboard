"""Unit tests for services/ai_recommendation_service.py.

Inputs are built from the real utils.kpi_engine / utils.insights /
services.reporting_service modules (with pandas) so the AI
Recommendation Service is exercised against the exact value objects it
will receive in production, not hand-rolled stand-ins.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from services.ai_recommendation_service import (
    AIRecommendationService,
    InvalidRecommendationContextError,
    InvalidRecommendationProviderError,
    Recommendation,
    RecommendationBatch,
    RecommendationContext,
    RecommendationPriority,
    RecommendationProvider,
    RecommendationProviderError,
    RuleBasedRecommendationProvider,
    sales_ai_recommendation_service,
)
from services.reporting_service import ReportContext, ReportingService, ReportMetadata, ReportType
from utils.insights import generate_business_insights
from utils.kpi_engine import sales_kpi_engine


@pytest.fixture
def balanced_df() -> pd.DataFrame:
    """A dataset with no extreme imbalances -- should trigger few/no risk rules.

    Uses 6 distinct, near-equal-revenue products (not 2-3) so the
    top-3-products concentration metric is meaningfully below the risk
    threshold -- with only 2-3 products, "top 3" is trivially ~100% of
    revenue regardless of how evenly it's spread, which would make
    concentration risk fire even in a genuinely diversified business.
    """
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="D"),
            "revenue": [500.0, 510.0, 495.0, 505.0, 490.0, 500.0],
            "orders": [20, 21, 19, 20, 19, 20],
            "product": ["A", "B", "C", "D", "E", "F"],
            "region": ["North", "South", "North", "South", "North", "South"],
        }
    )


@pytest.fixture
def concentrated_df() -> pd.DataFrame:
    """A dataset with heavy product concentration, an underperformer, a weak
    region, and a big single-day revenue spike -- should trigger every rule."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="D"),
            "revenue": [5000.0, 10.0, 4800.0, 15.0, 5200.0, 20.0],
            "orders": [10, 1, 9, 1, 11, 1],
            "product": ["Widget", "Gizmo", "Widget", "Gizmo", "Widget", "Gizmo"],
            "region": ["North", "East", "North", "East", "North", "East"],
        }
    )


@pytest.fixture
def full_context(concentrated_df: pd.DataFrame) -> RecommendationContext:
    kpi_results = sales_kpi_engine.calculate_all(concentrated_df)
    insights = generate_business_insights(concentrated_df)
    return RecommendationContext(kpi_results=kpi_results, business_insights=insights)


# --------------------------------------------------------------------------
# Default provider wiring
# --------------------------------------------------------------------------


def test_default_provider_is_rule_based() -> None:
    service = AIRecommendationService()
    assert service.provider_name == "Rule-Based Engine"
    assert isinstance(service._provider, RuleBasedRecommendationProvider)  # noqa: SLF001


def test_generate_recommendations_returns_batch(full_context: RecommendationContext) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)

    assert isinstance(batch, RecommendationBatch)
    assert batch.provider_name == "Rule-Based Engine"
    assert batch.generated_at is not None
    assert not batch.is_empty()


# --------------------------------------------------------------------------
# Rule-based provider -- individual rule behavior
# --------------------------------------------------------------------------


def test_concentrated_dataset_triggers_high_priority_concentration_risk(
    full_context: RecommendationContext,
) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)

    titles = [r.title for r in batch.recommendations]
    assert "Revenue Concentration Risk" in titles
    concentration_rec = next(r for r in batch.recommendations if r.title == "Revenue Concentration Risk")
    assert concentration_rec.priority == RecommendationPriority.HIGH
    assert concentration_rec.category == "products"
    assert "Widget" in concentration_rec.observation


def test_concentrated_dataset_triggers_underperforming_product(full_context: RecommendationContext) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)

    titles = [r.title for r in batch.recommendations]
    assert "Underperforming Product Identified" in titles
    rec = next(r for r in batch.recommendations if r.title == "Underperforming Product Identified")
    assert "Gizmo" in rec.observation


def test_concentrated_dataset_triggers_regional_imbalance(full_context: RecommendationContext) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)

    titles = [r.title for r in batch.recommendations]
    assert "Regional Performance Imbalance" in titles


def test_concentrated_dataset_triggers_revenue_day_volatility(full_context: RecommendationContext) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)

    titles = [r.title for r in batch.recommendations]
    assert "High Day-to-Day Revenue Volatility" in titles


def test_overall_performance_summary_always_present_when_insights_given(
    full_context: RecommendationContext,
) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)

    titles = [r.title for r in batch.recommendations]
    assert "Overall Performance Summary" in titles


def test_balanced_dataset_does_not_trigger_risk_rules(balanced_df: pd.DataFrame) -> None:
    context = RecommendationContext(
        kpi_results=sales_kpi_engine.calculate_all(balanced_df),
        business_insights=generate_business_insights(balanced_df),
    )
    service = AIRecommendationService()
    batch = service.generate_recommendations(context)

    titles = {r.title for r in batch.recommendations}
    assert "Revenue Concentration Risk" not in titles
    assert "Underperforming Product Identified" not in titles
    assert "Regional Performance Imbalance" not in titles
    assert "High Day-to-Day Revenue Volatility" not in titles
    # The baseline summary should still be present.
    assert "Overall Performance Summary" in titles


def test_headline_kpi_snapshot_used_when_insights_missing() -> None:
    balanced = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "revenue": [100.0, 200.0, 300.0],
            "orders": [1, 2, 3],
        }
    )
    context = RecommendationContext(kpi_results=sales_kpi_engine.calculate_all(balanced))
    service = AIRecommendationService()
    batch = service.generate_recommendations(context)

    titles = [r.title for r in batch.recommendations]
    assert "Headline KPI Snapshot" in titles
    assert "Overall Performance Summary" not in titles  # only used when insights are absent


def test_report_period_context_included_when_report_has_period_label(
    full_context: RecommendationContext,
) -> None:
    report_context = ReportContext(
        kpi_results=full_context.kpi_results,
        business_insights=full_context.business_insights,
        metadata=ReportMetadata(
            title="Weekly Report",
            generated_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
            period_label="Week of Jul 1-7",
        ),
    )
    report = ReportingService().generate_report(ReportType.WEEKLY, report_context)
    context_with_report = RecommendationContext(
        kpi_results=full_context.kpi_results,
        business_insights=full_context.business_insights,
        report=report,
    )
    service = AIRecommendationService()
    batch = service.generate_recommendations(context_with_report)

    titles = [r.title for r in batch.recommendations]
    assert "Reporting Period Context" in titles
    rec = next(r for r in batch.recommendations if r.title == "Reporting Period Context")
    assert "Week of Jul 1-7" in rec.observation


# --------------------------------------------------------------------------
# Empty / missing data handling
# --------------------------------------------------------------------------


def test_completely_empty_context_returns_empty_batch_not_an_error() -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(RecommendationContext())

    assert isinstance(batch, RecommendationBatch)
    assert batch.is_empty()
    assert batch.recommendations == ()


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def test_invalid_context_type_raises() -> None:
    service = AIRecommendationService()
    with pytest.raises(InvalidRecommendationContextError):
        service.generate_recommendations({"kpi_results": {}})  # type: ignore[arg-type]


def test_invalid_provider_in_constructor_raises() -> None:
    with pytest.raises(InvalidRecommendationProviderError):
        AIRecommendationService(provider="not a provider")  # type: ignore[arg-type]


def test_invalid_provider_in_set_provider_raises() -> None:
    service = AIRecommendationService()
    with pytest.raises(InvalidRecommendationProviderError):
        service.set_provider(object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Provider independence -- swapping providers, and provider error wrapping
# --------------------------------------------------------------------------


class _StubProvider:
    """A minimal provider used to prove the service is provider-agnostic."""

    name = "Stub Provider"

    def __init__(self, recommendations: list[Recommendation] | None = None, raise_error: bool = False) -> None:
        self._recommendations = recommendations or []
        self._raise_error = raise_error

    def generate(self, context: RecommendationContext) -> list[Recommendation]:
        if self._raise_error:
            raise RuntimeError("simulated provider failure (e.g. a network timeout)")
        return self._recommendations


def test_custom_provider_satisfies_protocol_via_structural_typing() -> None:
    assert isinstance(_StubProvider(), RecommendationProvider)


def test_swapping_provider_changes_output_with_no_service_changes(full_context: RecommendationContext) -> None:
    custom_recommendation = Recommendation(
        title="Custom Insight",
        observation="Generated by a stand-in for a future GPT/Claude/Gemini provider.",
        suggested_action="Nothing -- this proves the swap worked.",
        priority=RecommendationPriority.LOW,
    )
    service = AIRecommendationService(provider=_StubProvider(recommendations=[custom_recommendation]))
    batch = service.generate_recommendations(full_context)

    assert batch.provider_name == "Stub Provider"
    assert batch.recommendations == (custom_recommendation,)


def test_set_provider_swaps_at_runtime(full_context: RecommendationContext) -> None:
    service = AIRecommendationService()
    assert service.provider_name == "Rule-Based Engine"

    service.set_provider(_StubProvider())
    assert service.provider_name == "Stub Provider"
    batch = service.generate_recommendations(full_context)
    assert batch.recommendations == ()


def test_provider_exception_is_wrapped_in_recommendation_provider_error(
    full_context: RecommendationContext,
) -> None:
    service = AIRecommendationService(provider=_StubProvider(raise_error=True))
    with pytest.raises(RecommendationProviderError) as exc_info:
        service.generate_recommendations(full_context)

    assert exc_info.value.provider_name == "Stub Provider"
    assert isinstance(exc_info.value.original_error, RuntimeError)


# --------------------------------------------------------------------------
# RecommendationBatch convenience methods
# --------------------------------------------------------------------------


def test_filter_by_priority_and_category(full_context: RecommendationContext) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)

    high_priority = batch.filter_by_priority(RecommendationPriority.HIGH)
    assert all(r.priority == RecommendationPriority.HIGH for r in high_priority)
    assert len(high_priority) >= 1

    product_recs = batch.filter_by_category("products")
    assert all(r.category == "products" for r in product_recs)


def test_highest_priority_first_orders_high_before_low(full_context: RecommendationContext) -> None:
    service = AIRecommendationService()
    batch = service.generate_recommendations(full_context)
    ordered = batch.highest_priority_first()

    priorities = [r.priority for r in ordered]
    high_index = priorities.index(RecommendationPriority.HIGH)
    low_indexes = [i for i, p in enumerate(priorities) if p == RecommendationPriority.LOW]
    assert all(high_index < low_index for low_index in low_indexes)


# --------------------------------------------------------------------------
# Shared instance
# --------------------------------------------------------------------------


def test_shared_instance_is_an_ai_recommendation_service() -> None:
    assert isinstance(sales_ai_recommendation_service, AIRecommendationService)


def test_shared_instance_generates_recommendations(full_context: RecommendationContext) -> None:
    batch = sales_ai_recommendation_service.generate_recommendations(full_context)
    assert isinstance(batch, RecommendationBatch)
