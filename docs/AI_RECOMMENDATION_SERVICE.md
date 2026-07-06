# AI Recommendation Service

Sprint 6.2 -- Executive Reporting & Export Center, Module 3.

A business-consultant layer: it interprets already-computed business
information -- KPI results, business insights, and assembled report
summaries -- into structured, actionable recommendations. It computes
nothing itself and calls no AI provider directly; every bit of
analysis is delegated to a swappable **provider**.

## Architecture

```
services/ai_recommendation_service.py
    AIRecommendationServiceError (base exception)
        InvalidRecommendationContextError   -- context isn't a RecommendationContext
        InvalidRecommendationProviderError  -- provider doesn't satisfy the interface
        RecommendationProviderError         -- the active provider raised during generate()
    RecommendationPriority(str, Enum)        -- LOW / MEDIUM / HIGH
    Recommendation      (title, observation, suggested_action, priority, category)
    RecommendationContext (kpi_results, business_insights, report)
    RecommendationBatch (recommendations, provider_name, generated_at)
        + is_empty() / filter_by_priority() / filter_by_category() / highest_priority_first()
    RecommendationProvider (typing.Protocol)  -- name: str, generate(context) -> Iterable[Recommendation]
    RuleBasedRecommendationProvider           -- default provider, 8 deterministic rules
    AIRecommendationService
        .generate_recommendations(context) -> RecommendationBatch
        .set_provider(provider)
        .provider_name
sales_ai_recommendation_service = AIRecommendationService()  # shared, ready-to-use instance
```

### Why this shape

- **The service never analyzes anything itself.** `AIRecommendationService`
  validates its inputs, calls `self._provider.generate(context)`, and
  packages the result. Every business rule lives in
  `RuleBasedRecommendationProvider` (or a future provider) -- not in
  the service class -- which is what keeps the service provider-agnostic.
- **`RecommendationProvider` is a structural `Protocol`, not a base
  class.** A class satisfies it just by having a `name` property/attribute
  and a `generate(context)` method -- no inheritance, no shared parent
  class, no registration step. This is deliberately the loosest
  possible coupling: the service's constructor and `set_provider()`
  both call `isinstance(provider, RecommendationProvider)` (enabled by
  `@runtime_checkable`) to validate structurally, never checking for a
  specific class.
- **One rule-based provider is shipped this sprint,
  `RuleBasedRecommendationProvider`,** built from 8 independent rule
  functions (`RuleFunction = Callable[[RecommendationContext],
  Recommendation | None]`), each inspecting `RecommendationContext`
  and returning a `Recommendation` or `None`. Adding a 9th rule later
  means writing one new function and adding it to `_rules()` -- no
  change to `generate()` itself. This mirrors the registry-style
  extensibility already used by `KPIEngine`, `ExportService`, and
  `ReportingService`.
- **Provider failures never leak provider-specific exception types.**
  `generate_recommendations()` wraps anything the active provider
  raises (a bug in a rule, or -- for a future AI provider -- a network
  timeout, rate limit, or invalid API key) into the single
  `RecommendationProviderError`, preserving the original exception via
  `raise ... from exc`. Callers only ever need to catch
  `AIRecommendationServiceError` and its three subclasses, regardless
  of which provider is active.
- **No business data is calculated or modified.** The module imports
  only the *value objects* `KPIResult` (`utils/kpi_engine.py`) and
  `BusinessInsights` (`utils/insights.py`), and (for typing only,
  behind `TYPE_CHECKING`) `Report` (`services/reporting_service.py`) --
  never their calculation functions. Every rule reads fields that are
  already computed; none of them sum, average, or recompute anything.

### The 8 built-in rules

| Rule | Fires when | Priority | Uses |
|---|---|---|---|
| Overall Performance Summary | `business_insights` present with revenue > 0 | LOW | `business_insights` |
| Headline KPI Snapshot | `business_insights` absent but `kpi_results` present | LOW | `kpi_results` (fallback only) |
| Revenue Concentration Risk | Top-3-products share of revenue >= 60% | HIGH | `business_insights` |
| Underperforming Product Identified | Worst product earns < 15% of the best product | MEDIUM | `business_insights` |
| Regional Performance Imbalance | Worst region earns < 15% of the best region | MEDIUM | `business_insights` |
| High Day-to-Day Revenue Volatility | Best day's revenue >= 5x the worst day's | MEDIUM | `business_insights` |
| Sparse Sales Activity | Fewer than 1.5 transactions per active day | LOW | `business_insights` |
| Reporting Period Context | A `Report` with a period label is present | LOW | `report` |

All thresholds are named module-level constants
(`_HIGH_CONCENTRATION_THRESHOLD`, `_UNDERPERFORMANCE_RATIO_THRESHOLD`,
`_VOLATILITY_RATIO_THRESHOLD`, `_SPARSE_TRANSACTIONS_PER_DAY_THRESHOLD`)
-- a judgment call on reasonable starting values, easy to tune without
touching rule logic.

## Why this architecture supports multiple AI providers without modifying the core service

1. **The service's only dependency is the `RecommendationProvider`
   Protocol** -- a two-member structural interface (`name`,
   `generate`). It has zero knowledge of HTTP clients, API keys,
   prompt formats, or response parsing. An `OpenAIRecommendationProvider`,
   `ClaudeRecommendationProvider`, `GeminiRecommendationProvider`, an
   Azure OpenAI variant, or a custom enterprise model each become a new
   class, e.g.:

   ```python
   class OpenAIRecommendationProvider:
       name = "OpenAI GPT-4"

       def __init__(self, api_key: str, model: str = "gpt-4") -> None:
           self._client = OpenAI(api_key=api_key)
           self._model = model

       def generate(self, context: RecommendationContext) -> list[Recommendation]:
           prompt = self._build_prompt(context)  # from kpi_results / business_insights / report
           response = self._client.chat.completions.create(model=self._model, messages=[...])
           return self._parse_response(response)  # -> list[Recommendation]
   ```

   None of `AIRecommendationService`, `RecommendationContext`,
   `Recommendation`, `RecommendationBatch`, or the exception hierarchy
   needs to change for this to work.
2. **Activation is a single call:** `AIRecommendationService(provider=
   OpenAIRecommendationProvider(api_key=...))` or
   `service.set_provider(...)` at runtime (e.g. to A/B test rule-based
   vs. GPT-based recommendations, or fail over from GPT to the
   rule-based provider if an API key is missing).
3. **The input/output contract never changes.** Every provider receives
   the same `RecommendationContext` and must return an iterable of
   `Recommendation` objects -- so an LLM provider's job is simply
   "turn this context into recommendations shaped like everyone
   else's," which keeps prompt engineering and response parsing fully
   contained inside that provider's own `generate()` method.
4. **Provider failure modes are normalized.** A future GPT provider
   hitting a rate limit doesn't require new exception-handling code in
   `AIRecommendationService` or in any caller -- it's automatically
   wrapped as `RecommendationProviderError`, exactly like a bug in the
   rule-based provider would be.
5. **Verified directly, not just argued.** `tests/test_ai_recommendation_service.py`
   defines a small `_StubProvider` (unrelated to `RuleBasedRecommendationProvider`,
   sharing no code or base class with it) and proves: it satisfies
   `RecommendationProvider` via `isinstance()`, the service accepts it
   at construction time and via `set_provider()`, its output flows
   through unchanged, and an exception it raises comes out as
   `RecommendationProviderError`.

## Integration changes

**None required.** The service only imports value-object types from
`utils/kpi_engine.py` and `utils/insights.py`, and (for typing only)
from `services/reporting_service.py` -- it doesn't call any of them,
and none of those modules import this one. No existing page or
component was touched. A future "Executive Report Center" page would
look like:

```python
from services.ai_recommendation_service import RecommendationContext, sales_ai_recommendation_service

context = RecommendationContext(
    kpi_results=sales_kpi_engine.calculate_all(filtered_df),
    business_insights=generate_business_insights(filtered_df),
    report=report,  # optional, from services.reporting_service
)
batch = sales_ai_recommendation_service.generate_recommendations(context)
for rec in batch.highest_priority_first():
    st.markdown(f"**{rec.title}** ({rec.priority.value})")
    st.write(rec.observation)
    st.write(f"Suggested action: {rec.suggested_action}")
```

## Confirmation against the agreed architecture

- [x] `services/ai_recommendation_service.py` created; no other
      production file modified.
- [x] Receives already-computed KPI results, business insights, and
      report summaries via `RecommendationContext`; analyzes them and
      returns a structured `RecommendationBatch`.
- [x] Does not read uploaded files, calculate KPIs, generate business
      insights, apply filters, export files, generate PDFs, send
      emails, or depend on a specific AI provider -- confirmed by
      inspection (no imports from `utils/data_loader.py`,
      `utils/calculations.py`, `utils/insights.py`'s
      `generate_business_insights`, `utils/filters.py`,
      `services/export_service.py`; no AI SDK imports anywhere).
- [x] Recommendation generation is delegated to an interchangeable
      provider via the `RecommendationProvider` Protocol; a
      production-ready `RuleBasedRecommendationProvider` is the
      default for this sprint.
- [x] New providers (GPT, Claude, Gemini, Azure OpenAI, custom
      enterprise models) can be added with zero changes to
      `AIRecommendationService` -- verified with a stand-in provider in
      the test suite.
- [x] Single Responsibility Principle (the service only orchestrates;
      each rule function does one check), DRY (shared
      `format_currency` reuse, one `generate()` loop for all rules),
      clean architecture (`services/` depends on `utils/` value
      objects only), small reusable methods, thorough docstrings, same
      quality bar as `ExportService`/`ReportingService`.
- [x] Validates input types (`InvalidRecommendationContextError`,
      `InvalidRecommendationProviderError`).
- [x] Handles missing business data gracefully (each rule independently
      no-ops on `None`/absent fields; a leaner context falls back to a
      simpler KPI-only summary instead of nothing).
- [x] Handles empty recommendations gracefully (`RecommendationBatch`
      can legitimately be empty; `is_empty()` lets callers detect this
      without it being an error).
- [x] Meaningful, typed custom exceptions (three, all subclassing
      `AIRecommendationServiceError`), including a dedicated
      `RecommendationProviderError` that normalizes any provider
      failure.

## Automated tests

`tests/test_ai_recommendation_service.py` (22 tests) builds inputs from
the real `utils.kpi_engine`/`utils.insights`/`services.reporting_service`
modules and covers: each of the 8 rules firing on a deliberately
concentrated/imbalanced/volatile dataset, the same rules *not* firing
on a genuinely diversified 6-product dataset, the KPI-only fallback
when business insights are absent, report period context inclusion, a
fully empty context producing an empty (not erroring) batch, all three
input-validation error paths, a stand-in provider proving structural
Protocol conformance, provider swapping via the constructor and
`set_provider()`, provider-exception wrapping, and the
`RecommendationBatch` convenience methods (`filter_by_priority`,
`filter_by_category`, `highest_priority_first`). Verified via
`python3 -m py_compile` across the whole project plus a 35-assertion
battery run directly against the real `pandas`/`utils.kpi_engine`/
`utils.insights`/`services.reporting_service` code (pytest itself isn't
installed in this offline sandbox) -- all passed. One test fixture bug
was caught and fixed during verification: a 2-product "balanced"
dataset trivially yields ~100% top-3 concentration (there's nothing
else for the top 3 to be), so the fixture was widened to 6 near-equal
products to genuinely represent a diversified business.

## Manual test cases

| # | Steps | Expected result |
|---|-------|------------------|
| 1 | Build a `RecommendationContext` from a dataset where one product/region dominates and one sales day spikes far above the rest, call `generate_recommendations()` | Returns a `RecommendationBatch` including Revenue Concentration Risk (HIGH), Underperforming Product Identified, Regional Performance Imbalance, High Day-to-Day Revenue Volatility, and Overall Performance Summary. |
| 2 | Build a context from a dataset with several near-equal products/regions and steady daily revenue | None of the four risk-flag recommendations appear; Overall Performance Summary still does. |
| 3 | Build a context with only `kpi_results` (no `business_insights`) | Batch includes "Headline KPI Snapshot" instead of "Overall Performance Summary". |
| 4 | Build a context that also includes a `Report` (from `services.reporting_service`) with a `period_label` set | Batch includes "Reporting Period Context" naming that period. |
| 5 | Call `generate_recommendations(RecommendationContext())` (everything `None`) | Returns an empty `RecommendationBatch` (`is_empty()` is `True`) -- no exception. |
| 6 | Call `generate_recommendations()` with a plain `dict` instead of a `RecommendationContext` | Raises `InvalidRecommendationContextError`. |
| 7 | Construct `AIRecommendationService(provider=object())` or call `service.set_provider("not a provider")` | Both raise `InvalidRecommendationProviderError`. |
| 8 | Write a minimal custom class with a `name` attribute and a `generate(context)` method (no inheritance from anything), pass it to `AIRecommendationService(provider=...)` | Works immediately; `service.provider_name` reflects the custom provider's name and its recommendations flow through unchanged. |
| 9 | Give a custom provider whose `generate()` raises a plain `RuntimeError` | `generate_recommendations()` raises `RecommendationProviderError` naming the provider and wrapping the original error (`.original_error`). |
| 10 | Call `batch.filter_by_priority(RecommendationPriority.HIGH)`, `batch.filter_by_category("products")`, and `batch.highest_priority_first()` on a batch with mixed priorities | Each returns the expected filtered/sorted subset without mutating the original batch. |
