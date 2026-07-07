"""AI Recommendation Service for the NovaMart Sales Intelligence Dashboard.

Sprint 6.2 -- Executive Reporting & Export Center, Module 3.

Analyzes already-computed business information -- KPI results, business
insights, and assembled report summaries -- and produces structured,
actionable recommendations for the Executive Report Center or a future
PDF report. This module has exactly one responsibility -- interpreting
existing business information into recommendations -- and deliberately
does nothing else.

The AI Recommendation Service does NOT:
    - Read uploaded files (that's ``utils/data_loader.py``).
    - Calculate KPIs (that's ``utils/kpi_engine.py`` / ``utils/calculations.py``).
    - Generate business insights (that's ``utils/insights.py``).
    - Apply filters (that's ``utils/filters.py``).
    - Export files (that's ``services/export_service.py``).
    - Generate PDFs (a future, separate service).
    - Send emails (a future, separate service).
    - Depend on any specific AI provider (OpenAI, Claude, Gemini, ...).

Think of :class:`AIRecommendationService` as a business consultant: it
never generates business data itself, it interprets data that other
services already computed and hands back an opinion.

Provider independence
----------------------
:class:`AIRecommendationService` never analyzes data itself -- it
delegates every bit of analysis to a **provider** satisfying the
:class:`RecommendationProvider` interface (a structural
``typing.Protocol``: a ``name`` property and a
``generate(context) -> Iterable[Recommendation]`` method). The service
depends only on that interface, never on a concrete implementation.

This sprint ships :class:`RuleBasedRecommendationProvider`, a
deterministic, production-ready default that reasons over
:class:`~utils.insights.BusinessInsights` and
:class:`~utils.kpi_engine.KPIResult` values using plain business rules
(no external AI call, no network, no API key). Future providers --
``OpenAIRecommendationProvider``, ``ClaudeRecommendationProvider``,
``GeminiRecommendationProvider``, an Azure OpenAI variant, or a custom
enterprise model -- are added by writing one new class that satisfies
:class:`RecommendationProvider` and passing an instance of it to
``AIRecommendationService(provider=...)`` or
:meth:`AIRecommendationService.set_provider`. Nothing in this module
needs to change: the same :class:`RecommendationContext` goes in, the
same :class:`RecommendationBatch` comes out, and any provider-specific
failure (a network error, a rate limit, an invalid API key) is caught
and re-raised as the single, stable :class:`RecommendationProviderError`
-- so calling code never needs to know or care which provider is
active.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Callable, Iterable, Mapping, Protocol, runtime_checkable

from tenancy.context import TenantContext, validate_tenant_context
from utils.formatting import format_currency
from utils.insights import BusinessInsights
from utils.kpi_engine import KPIResult

if TYPE_CHECKING:
    # Imported only for type checkers -- avoids a hard import-time
    # dependency on services/reporting_service.py for callers that only
    # need this module's own recommendation types.
    from services.reporting_service import Report


# ==============================================================================
# Exceptions
# ==============================================================================


class AIRecommendationServiceError(Exception):
    """Base class for every error raised by the AI Recommendation Service.

    Catch this type in calling code to handle *any* recommendation
    failure with a single ``except`` clause, regardless of which
    provider (rule-based today, an LLM tomorrow) produced it::

        try:
            batch = sales_ai_recommendation_service.generate_recommendations(context)
        except AIRecommendationServiceError as exc:
            st.error(str(exc))
    """


class InvalidRecommendationContextError(AIRecommendationServiceError):
    """Raised when ``context`` isn't a :class:`RecommendationContext` instance."""

    def __init__(self, received: object) -> None:
        """Build a user-friendly "invalid context" message.

        Args:
            received: The value that was passed in place of a
                :class:`RecommendationContext`.
        """
        self.received_type = type(received)
        message = (
            "AIRecommendationService requires a RecommendationContext instance, got "
            f"'{self.received_type.__name__}' instead."
        )
        super().__init__(message)


class InvalidRecommendationProviderError(AIRecommendationServiceError):
    """Raised when a value doesn't satisfy the :class:`RecommendationProvider` interface."""

    def __init__(self, received: object) -> None:
        """Build a user-friendly "invalid provider" message.

        Args:
            received: The value that was passed in place of a
                :class:`RecommendationProvider`.
        """
        self.received_type = type(received)
        message = (
            "AIRecommendationService requires a provider implementing the "
            "RecommendationProvider interface (a 'name' property and a "
            f"'generate(context)' method), got '{self.received_type.__name__}' instead."
        )
        super().__init__(message)


class RecommendationProviderError(AIRecommendationServiceError):
    """Raised when the active provider itself fails while generating recommendations.

    Every exception a provider's ``generate()`` raises -- a rule-based
    bug today, or a network timeout, rate limit, or invalid API key
    from a future OpenAI/Claude/Gemini provider -- is caught by
    :meth:`AIRecommendationService.generate_recommendations` and
    re-raised as this single type. This is what keeps the service's
    error contract identical no matter which provider is plugged in.
    """

    def __init__(self, provider_name: str, original_error: Exception) -> None:
        """Build a message identifying the provider and the underlying failure.

        Args:
            provider_name: The failing provider's :attr:`RecommendationProvider.name`.
            original_error: The exception the provider raised.
        """
        self.provider_name = provider_name
        self.original_error = original_error
        message = (
            f"The '{provider_name}' recommendation provider failed to generate "
            f"recommendations ({original_error.__class__.__name__}: {original_error})."
        )
        super().__init__(message)


# ==============================================================================
# Value objects
# ==============================================================================


class RecommendationPriority(str, Enum):
    """How urgently a recommendation should be acted on."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Recommendation:
    """A single, structured business recommendation.

    Attributes:
        title: Short, human-readable headline (e.g. ``"Revenue
            Concentration Risk"``).
        observation: What the data shows -- the factual basis for the
            recommendation.
        suggested_action: What the business could do about it.
        priority: How urgent this recommendation is. Defaults to
            :attr:`RecommendationPriority.MEDIUM`.
        category: Optional grouping label (e.g. ``"products"``,
            ``"regions"``, ``"revenue"``, ``"general"``), useful for a
            future Executive Report Center that groups recommendations
            by theme.
    """

    title: str
    observation: str
    suggested_action: str
    priority: RecommendationPriority = RecommendationPriority.MEDIUM
    category: str | None = None


@dataclass(frozen=True)
class RecommendationContext:
    """Bundles already-computed business data for a provider to analyze.

    **None of this data is computed by the AI Recommendation Service**
    -- it is produced elsewhere and simply handed in here.

    Attributes:
        kpi_results: KPI results keyed by KPI key, exactly as returned
            by :meth:`~utils.kpi_engine.KPIEngine.calculate_all`.
        business_insights: A :class:`~utils.insights.BusinessInsights`
            value object, exactly as returned by
            :func:`~utils.insights.generate_business_insights`.
        report: An assembled :class:`~services.reporting_service.Report`,
            if one is available. Lets a provider consider report-level
            context (e.g. its period label) without needing to know how
            the report was built.
    """

    kpi_results: Mapping[str, KPIResult] | None = None
    business_insights: BusinessInsights | None = None
    report: "Report | None" = None


@dataclass(frozen=True)
class RecommendationBatch:
    """A structured set of recommendations returned by the service.

    Attributes:
        recommendations: The recommendations produced, in the order
            the provider returned them.
        provider_name: Which provider produced this batch (e.g.
            ``"Rule-Based Engine"``), for traceability and display.
        generated_at: When this batch was generated (UTC).
    """

    recommendations: tuple[Recommendation, ...]
    provider_name: str
    generated_at: datetime

    def is_empty(self) -> bool:
        """Return ``True`` if the provider produced no recommendations at all.

        This is not an error -- a context with too little data, or a
        genuinely healthy business with nothing to flag, can
        legitimately produce an empty batch. Downstream consumers can
        check this to show a "no recommendations at this time" state.
        """
        return len(self.recommendations) == 0

    def filter_by_priority(self, priority: RecommendationPriority) -> tuple[Recommendation, ...]:
        """Return only the recommendations at a given priority level.

        Args:
            priority: The priority to filter by.

        Returns:
            A tuple of matching recommendations, preserving order.
        """
        return tuple(r for r in self.recommendations if r.priority == priority)

    def filter_by_category(self, category: str) -> tuple[Recommendation, ...]:
        """Return only the recommendations tagged with a given category.

        Args:
            category: The category to filter by (e.g. ``"products"``).

        Returns:
            A tuple of matching recommendations, preserving order.
        """
        return tuple(r for r in self.recommendations if r.category == category)

    def highest_priority_first(self) -> tuple[Recommendation, ...]:
        """Return all recommendations sorted with HIGH priority first, LOW last."""
        order = {RecommendationPriority.HIGH: 0, RecommendationPriority.MEDIUM: 1, RecommendationPriority.LOW: 2}
        return tuple(sorted(self.recommendations, key=lambda r: order.get(r.priority, 99)))


# ==============================================================================
# Provider interface
# ==============================================================================


@runtime_checkable
class RecommendationProvider(Protocol):
    """Interface every recommendation provider must satisfy.

    This is the single seam :class:`AIRecommendationService` depends
    on. It is a structural ``Protocol`` (Python's "duck typing with
    static-typing support"), so a class satisfies this interface simply
    by having a compatible ``name`` property and ``generate`` method --
    no inheritance required. That's what lets a future
    ``OpenAIRecommendationProvider``, ``ClaudeRecommendationProvider``,
    or ``GeminiRecommendationProvider`` plug in without touching this
    module or subclassing anything defined here.
    """

    @property
    def name(self) -> str:
        """A short, human-readable name for this provider (for traceability)."""
        ...

    def generate(self, context: RecommendationContext) -> Iterable[Recommendation]:
        """Analyze ``context`` and return the recommendations it produces.

        Args:
            context: The already-computed business data to analyze.

        Returns:
            Any iterable of :class:`Recommendation` values (a list, a
            tuple, or a generator are all acceptable) -- possibly empty.
        """
        ...


# ==============================================================================
# Default provider: rule-based (production-ready, no external dependency)
# ==============================================================================

# Tunable thresholds for the built-in rules. Kept as named module-level
# constants (rather than inline magic numbers) so they're easy to find
# and adjust without hunting through rule logic.
_HIGH_CONCENTRATION_THRESHOLD = 60.0  # top-3-products % of revenue considered concentrated
_UNDERPERFORMANCE_RATIO_THRESHOLD = 0.15  # worst/best revenue ratio considered "underperforming"
_VOLATILITY_RATIO_THRESHOLD = 5.0  # highest-day/lowest-day revenue ratio considered volatile
_SPARSE_TRANSACTIONS_PER_DAY_THRESHOLD = 1.5  # transactions/active-day considered sparse

# A single rule function's signature: inspect the context, return the
# Recommendation it produces, or None if the condition it checks for
# doesn't apply (missing data, or the underlying metric doesn't warrant
# a recommendation). Every rule is independent and order-agnostic.
RuleFunction = Callable[[RecommendationContext], "Recommendation | None"]


def _rule_product_concentration_risk(context: RecommendationContext) -> Recommendation | None:
    """Flag when the top products drive an outsized share of revenue."""
    insights = context.business_insights
    if insights is None or not insights.product_insights_available:
        return None
    if insights.top_product_concentration < _HIGH_CONCENTRATION_THRESHOLD:
        return None
    return Recommendation(
        title="Revenue Concentration Risk",
        observation=(
            f"The top 3 products drive {insights.top_product_concentration:.1f}% of total "
            f"revenue, led by '{insights.best_product}'."
        ),
        suggested_action=(
            "Diversify the product mix -- invest in marketing or inventory for secondary "
            "products to reduce dependency on a small number of top sellers."
        ),
        priority=RecommendationPriority.HIGH,
        category="products",
    )


def _rule_underperforming_product(context: RecommendationContext) -> Recommendation | None:
    """Flag a product earning far less revenue than the top product."""
    insights = context.business_insights
    if insights is None or not insights.product_insights_available:
        return None
    if insights.best_product_revenue <= 0 or insights.worst_product == insights.best_product:
        return None
    ratio = insights.worst_product_revenue / insights.best_product_revenue
    if ratio >= _UNDERPERFORMANCE_RATIO_THRESHOLD:
        return None
    return Recommendation(
        title="Underperforming Product Identified",
        observation=(
            f"'{insights.worst_product}' generated only "
            f"{format_currency(insights.worst_product_revenue)}, versus "
            f"{format_currency(insights.best_product_revenue)} for the top product "
            f"'{insights.best_product}'."
        ),
        suggested_action=(
            f"Review pricing, promotion, or placement for '{insights.worst_product}', or "
            "consider phasing it out if performance doesn't improve."
        ),
        priority=RecommendationPriority.MEDIUM,
        category="products",
    )


def _rule_regional_imbalance(context: RecommendationContext) -> Recommendation | None:
    """Flag a region earning far less revenue than the top region."""
    insights = context.business_insights
    if insights is None or not insights.region_insights_available:
        return None
    if insights.best_region_revenue <= 0 or insights.worst_region == insights.best_region:
        return None
    ratio = insights.worst_region_revenue / insights.best_region_revenue
    if ratio >= _UNDERPERFORMANCE_RATIO_THRESHOLD:
        return None
    return Recommendation(
        title="Regional Performance Imbalance",
        observation=(
            f"'{insights.worst_region}' generated only "
            f"{format_currency(insights.worst_region_revenue)}, versus "
            f"{format_currency(insights.best_region_revenue)} for the top region "
            f"'{insights.best_region}'."
        ),
        suggested_action=(
            f"Investigate demand, staffing, or marketing coverage in '{insights.worst_region}' "
            f"and consider applying tactics that are working well in '{insights.best_region}'."
        ),
        priority=RecommendationPriority.MEDIUM,
        category="regions",
    )


def _rule_sparse_sales_activity(context: RecommendationContext) -> Recommendation | None:
    """Flag unusually low transaction volume per active sales day."""
    insights = context.business_insights
    if insights is None or insights.active_sales_days <= 0:
        return None
    transactions_per_day = insights.total_transactions / insights.active_sales_days
    if transactions_per_day >= _SPARSE_TRANSACTIONS_PER_DAY_THRESHOLD:
        return None
    return Recommendation(
        title="Sparse Sales Activity",
        observation=(
            f"Only {transactions_per_day:.1f} transactions per active sales day on average "
            f"({insights.total_transactions} transactions across {insights.active_sales_days} day(s))."
        ),
        suggested_action=(
            "Increase promotional frequency or marketing outreach to build more consistent "
            "day-to-day sales activity."
        ),
        priority=RecommendationPriority.LOW,
        category="general",
    )


def _rule_revenue_day_volatility(context: RecommendationContext) -> Recommendation | None:
    """Flag a large swing between the best and worst single sales day."""
    insights = context.business_insights
    if insights is None:
        return None
    _, highest_revenue = insights.highest_revenue_day
    _, lowest_revenue = insights.lowest_revenue_day
    if highest_revenue <= 0 or lowest_revenue <= 0:
        return None
    ratio = highest_revenue / lowest_revenue
    if ratio < _VOLATILITY_RATIO_THRESHOLD:
        return None
    return Recommendation(
        title="High Day-to-Day Revenue Volatility",
        observation=(
            f"Revenue swung from {format_currency(lowest_revenue)} on the lowest day to "
            f"{format_currency(highest_revenue)} on the highest day -- a {ratio:.1f}x difference."
        ),
        suggested_action=(
            "Investigate what drove the peak (a promotion, seasonality, large orders) and "
            "evaluate whether it can be replicated, or whether low-revenue days need attention."
        ),
        priority=RecommendationPriority.MEDIUM,
        category="revenue",
    )


def _rule_overall_performance_summary(context: RecommendationContext) -> Recommendation | None:
    """Provide a baseline revenue/pacing summary whenever business insights are available.

    Unlike the risk-flagging rules above, this one always fires when
    there's revenue to report -- a business consultant's report opens
    with a summary before listing specific concerns.
    """
    insights = context.business_insights
    if insights is None or insights.total_revenue <= 0:
        return None
    return Recommendation(
        title="Overall Performance Summary",
        observation=(
            f"Total revenue of {format_currency(insights.total_revenue)} across "
            f"{insights.active_sales_days} active sales day(s), averaging "
            f"{format_currency(insights.average_daily_revenue)} per day."
        ),
        suggested_action="Continue monitoring KPIs regularly; no immediate action required.",
        priority=RecommendationPriority.LOW,
        category="general",
    )


def _rule_headline_kpi_snapshot(context: RecommendationContext) -> Recommendation | None:
    """Fall back to a KPI-only summary when business insights weren't provided.

    This only fires when ``business_insights`` is absent -- when it's
    present, :func:`_rule_overall_performance_summary` already covers
    this ground with richer detail. This is the "handle missing
    business data gracefully" case: a provider given a leaner context
    should still produce something useful, not nothing.
    """
    if context.business_insights is not None:
        return None
    kpi_results = context.kpi_results
    if not kpi_results:
        return None
    total_revenue_kpi = kpi_results.get("total_revenue")
    total_orders_kpi = kpi_results.get("total_orders")
    if total_revenue_kpi is None or total_orders_kpi is None:
        return None
    return Recommendation(
        title="Headline KPI Snapshot",
        observation=f"{total_revenue_kpi.label}: {total_revenue_kpi.formatted}. {total_orders_kpi.label}: {total_orders_kpi.formatted}.",
        suggested_action="Use these figures as the baseline reference point for this reporting period.",
        priority=RecommendationPriority.LOW,
        category="general",
    )


def _rule_report_period_context(context: RecommendationContext) -> Recommendation | None:
    """Add period framing when an assembled Report with a period label is available."""
    report = context.report
    if report is None or report.metadata.period_label is None:
        return None
    return Recommendation(
        title="Reporting Period Context",
        observation=f"These recommendations are based on data for: {report.metadata.period_label}.",
        suggested_action=(
            "Compare this period's recommendations against the prior period to track whether "
            "flagged issues are improving."
        ),
        priority=RecommendationPriority.LOW,
        category="general",
    )


class RuleBasedRecommendationProvider:
    """Default, production-ready recommendation provider: deterministic business rules.

    Satisfies :class:`RecommendationProvider` structurally (a ``name``
    attribute and a ``generate`` method) -- it doesn't inherit from
    anything, which is exactly the point: any future provider class can
    do the same without needing a shared base class.

    Adding a new rule later means writing one new function matching
    :data:`RuleFunction` and adding it to :meth:`_rules` -- no changes
    to :meth:`generate` itself.
    """

    name = "Rule-Based Engine"

    def generate(self, context: RecommendationContext) -> list[Recommendation]:
        """Run every registered rule against ``context`` and collect the results.

        Args:
            context: The already-computed business data to analyze.

        Returns:
            A list of :class:`Recommendation` objects, one per rule
            that found something worth flagging. Empty if no rule
            applied (e.g. an entirely empty context) -- not an error.
        """
        recommendations: list[Recommendation] = []
        for rule in self._rules():
            recommendation = rule(context)
            if recommendation is not None:
                recommendations.append(recommendation)
        return recommendations

    @staticmethod
    def _rules() -> tuple[RuleFunction, ...]:
        """Return every rule this provider evaluates, in evaluation order."""
        return (
            _rule_overall_performance_summary,
            _rule_headline_kpi_snapshot,
            _rule_product_concentration_risk,
            _rule_underperforming_product,
            _rule_regional_imbalance,
            _rule_revenue_day_volatility,
            _rule_sparse_sales_activity,
            _rule_report_period_context,
        )


# ==============================================================================
# AI Recommendation Service
# ==============================================================================


class AIRecommendationService:
    """Generates business recommendations by delegating analysis to a pluggable provider.

    The service itself never analyzes anything -- it validates its
    inputs, delegates to whichever :class:`RecommendationProvider` is
    active, and wraps the result (or any failure) into a stable,
    provider-agnostic shape (:class:`RecommendationBatch` /
    :class:`RecommendationProviderError`).

    Example:
        >>> service = AIRecommendationService()  # defaults to RuleBasedRecommendationProvider
        >>> batch = service.generate_recommendations(context)
        >>> batch.provider_name
        'Rule-Based Engine'

        # Swapping in a different provider later, without touching this class:
        >>> class EchoProvider:
        ...     name = "Echo"
        ...     def generate(self, context):
        ...         return []
        >>> service.set_provider(EchoProvider())
    """

    def __init__(self, provider: RecommendationProvider | None = None) -> None:
        """Create an AI Recommendation Service.

        Args:
            provider: The recommendation provider to use. Defaults to
                :class:`RuleBasedRecommendationProvider` when omitted.

        Raises:
            InvalidRecommendationProviderError: If ``provider`` is given
                but doesn't satisfy :class:`RecommendationProvider`.
        """
        self._provider: RecommendationProvider = provider if provider is not None else RuleBasedRecommendationProvider()
        self._validate_provider(self._provider)

    def set_provider(self, provider: RecommendationProvider) -> None:
        """Swap the active provider at runtime.

        This is the whole story for adding a new AI provider: construct
        it and hand it here (or to the constructor) -- no other change
        is required anywhere in this module.

        Args:
            provider: The new provider to use.

        Raises:
            InvalidRecommendationProviderError: If ``provider`` doesn't
                satisfy :class:`RecommendationProvider`.
        """
        self._validate_provider(provider)
        self._provider = provider

    @property
    def provider_name(self) -> str:
        """The active provider's display name."""
        return self._provider.name

    def generate_recommendations(
        self, context: RecommendationContext, *, tenant_context: TenantContext | None = None
    ) -> RecommendationBatch:
        """Analyze ``context`` and return a structured batch of recommendations.

        Args:
            context: The already-computed business data to analyze.
            tenant_context: The tenant these recommendations are scoped
                to (Multi-Tenant Sprint 6.3). Required for the call to
                succeed -- see :func:`~tenancy.context.validate_tenant_context`.
                Never passed to the provider itself; recommendation
                logic never varies by tenant, only which tenant's data
                it was asked to analyze.

        Returns:
            A :class:`RecommendationBatch`. It may be empty (see
            :meth:`RecommendationBatch.is_empty`) if the provider found
            nothing to recommend -- that is not an error.

        Raises:
            MissingTenantContextError: If no tenant context was supplied.
            InactiveTenantError: If the supplied tenant is not active.
            InvalidRecommendationContextError: If ``context`` isn't a
                :class:`RecommendationContext` instance.
            RecommendationProviderError: If the active provider raises
                while generating recommendations.
        """
        validate_tenant_context(tenant_context, service_name="AIRecommendationService", operation="generate_recommendations")

        if not isinstance(context, RecommendationContext):
            raise InvalidRecommendationContextError(context)

        try:
            recommendations = list(self._provider.generate(context))
        except AIRecommendationServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - re-raised as a domain exception below
            raise RecommendationProviderError(self.provider_name, exc) from exc

        return RecommendationBatch(
            recommendations=tuple(recommendations),
            provider_name=self.provider_name,
            generated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _validate_provider(provider: object) -> None:
        """Ensure ``provider`` satisfies the :class:`RecommendationProvider` interface.

        Args:
            provider: The value to validate.

        Raises:
            InvalidRecommendationProviderError: If ``provider`` doesn't
                have both a ``name`` property/attribute and a callable
                ``generate`` method.
        """
        if not isinstance(provider, RecommendationProvider):
            raise InvalidRecommendationProviderError(provider)


# A shared, ready-to-use instance -- mirrors
# ``utils.kpi_engine.sales_kpi_engine``, ``utils.data_loader.sales_data_loader``,
# ``services.export_service.sales_export_service``, and
# ``services.reporting_service.sales_reporting_service``. Callers can
# import this directly instead of constructing their own service.
sales_ai_recommendation_service = AIRecommendationService()
