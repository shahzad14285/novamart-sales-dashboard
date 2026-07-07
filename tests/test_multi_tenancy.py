"""Unit tests for the Multi-Tenant Business Intelligence Platform (Sprint 6.3).

This file is the Task 7 deliverable: comprehensive coverage of the
tenancy package itself (model, context, registry, exceptions,
configuration) plus end-to-end proof that every tenant-aware service
in the pipeline -- KPI Engine, Business Insights, Reporting Service, AI
Recommendation Service, PDF Generator, Export Service -- enforces
tenant validation and never leaks one tenant's data into another
tenant's results.

Per-service happy-path and validation-failure behavior already has
dedicated coverage in ``tests/test_kpi_engine.py``,
``tests/test_insights.py``, ``tests/test_reporting_service.py``,
``tests/test_ai_recommendation_service.py``,
``tests/test_pdf_generator_service.py``, and
``tests/test_export_service.py``. This file focuses on the
cross-cutting concerns the ticket calls out explicitly: Valid Tenant,
Missing Tenant, Inactive Tenant, Tenant Isolation, and
configuration-driven onboarding with zero hardcoded tenant logic.
"""

from __future__ import annotations

import logging

import pandas as pd
import pdfplumber
import pytest

from services.ai_recommendation_service import AIRecommendationService, RecommendationContext
from services.export_service import ExportService
from services.pdf_generator_service import PDFGeneratorService
from services.reporting_service import ReportContext, ReportingService, ReportType
from tenancy.context import TenantContext, validate_tenant_context
from tenancy.exceptions import (
    InactiveTenantError,
    MissingTenantContextError,
    TenantContextError,
    TenantNotFoundError,
)
from tenancy.models import Tenant, TenantStatus
from tenancy.registry import TenantRegistry, tenant_registry
from utils.insights import generate_business_insights
from utils.kpi_engine import KPIEngine

# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def tenant_a() -> Tenant:
    """A valid, active tenant representing Organization A."""
    return Tenant(tenant_id="org-a", name="org-a", display_name="Organization A")


@pytest.fixture
def tenant_b() -> Tenant:
    """A valid, active tenant representing Organization B."""
    return Tenant(tenant_id="org-b", name="org-b", display_name="Organization B")


@pytest.fixture
def inactive_tenant() -> Tenant:
    """A tenant that exists but has been deactivated."""
    return Tenant(tenant_id="org-inactive", name="org-inactive", display_name="Suspended Org", status=TenantStatus.INACTIVE)


@pytest.fixture
def df_a() -> pd.DataFrame:
    """Organization A's sales data -- high revenue, one dominant product."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=4, freq="D"),
            "revenue": [10_000.0, 12_000.0, 9_000.0, 11_000.0],
            "orders": [100, 120, 90, 110],
            "product": ["Alpha", "Alpha", "Alpha", "Beta"],
            "region": ["North", "North", "North", "South"],
        }
    )


@pytest.fixture
def df_b() -> pd.DataFrame:
    """Organization B's sales data -- much smaller, entirely different shape."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=3, freq="D"),
            "revenue": [50.0, 75.0, 25.0],
            "orders": [2, 3, 1],
            "product": ["Zeta", "Zeta", "Omega"],
            "region": ["East", "East", "West"],
        }
    )


def _pdf_text(content: bytes) -> str:
    from io import BytesIO

    with pdfplumber.open(BytesIO(content)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# --------------------------------------------------------------------------
# 1. Valid Tenant
# --------------------------------------------------------------------------


def test_valid_active_tenant_context_resolves_without_error(tenant_a: Tenant) -> None:
    context = TenantContext(tenant=tenant_a)
    resolved = context.require_active_tenant()

    assert resolved is tenant_a
    assert context.has_tenant() is True


def test_validate_tenant_context_returns_the_tenant_for_a_valid_context(tenant_a: Tenant) -> None:
    context = TenantContext(tenant=tenant_a)
    resolved = validate_tenant_context(context, service_name="KPIEngine", operation="calculate_all")

    assert resolved is tenant_a


def test_valid_tenant_flows_through_the_full_kpi_and_insights_pipeline(
    tenant_a: Tenant, df_a: pd.DataFrame
) -> None:
    context = TenantContext(tenant=tenant_a)
    engine = KPIEngine()
    results = engine.calculate_all(df_a, tenant_context=context)
    insights = generate_business_insights(df_a, tenant_context=context)

    assert results["total_revenue"].value == 42_000.0
    assert insights.total_revenue == 42_000.0


# --------------------------------------------------------------------------
# 2. Missing Tenant
# --------------------------------------------------------------------------


def test_empty_tenant_context_raises_missing_tenant_error() -> None:
    context = TenantContext.empty()
    with pytest.raises(MissingTenantContextError):
        context.require_active_tenant()


def test_none_tenant_context_raises_missing_tenant_error() -> None:
    with pytest.raises(MissingTenantContextError):
        validate_tenant_context(None, service_name="KPIEngine", operation="calculate_all")


def test_missing_tenant_error_message_is_business_friendly() -> None:
    context = TenantContext.empty()
    try:
        context.require_active_tenant()
    except MissingTenantContextError as exc:
        assert str(exc) == "Tenant context is missing. Unable to process request."
    else:
        pytest.fail("Expected MissingTenantContextError")


def test_missing_tenant_stops_processing_before_any_kpi_is_calculated(df_a: pd.DataFrame) -> None:
    engine = KPIEngine()
    with pytest.raises(MissingTenantContextError):
        engine.calculate_all(df_a, tenant_context=None)


# --------------------------------------------------------------------------
# 3. Inactive Tenant
# --------------------------------------------------------------------------


def test_inactive_tenant_raises_inactive_tenant_error(inactive_tenant: Tenant) -> None:
    context = TenantContext(tenant=inactive_tenant)
    with pytest.raises(InactiveTenantError):
        context.require_active_tenant()


def test_inactive_tenant_error_message_is_business_friendly(inactive_tenant: Tenant) -> None:
    context = TenantContext(tenant=inactive_tenant)
    try:
        context.require_active_tenant()
    except InactiveTenantError as exc:
        assert str(exc) == "This tenant account is currently inactive. Unable to process request."
        assert "org-inactive" not in str(exc)
    else:
        pytest.fail("Expected InactiveTenantError")


def test_inactive_tenant_stops_processing_before_any_kpi_is_calculated(
    inactive_tenant: Tenant, df_a: pd.DataFrame
) -> None:
    context = TenantContext(tenant=inactive_tenant)
    engine = KPIEngine()
    with pytest.raises(InactiveTenantError):
        engine.calculate_all(df_a, tenant_context=context)


def test_both_missing_and_inactive_are_catchable_as_the_common_base_error(
    inactive_tenant: Tenant,
) -> None:
    for context in (TenantContext.empty(), TenantContext(tenant=inactive_tenant)):
        with pytest.raises(TenantContextError):
            context.require_active_tenant()


# --------------------------------------------------------------------------
# 4. Tenant Isolation
# --------------------------------------------------------------------------


def test_two_tenants_processing_different_data_never_cross_contaminate_kpis(
    tenant_a: Tenant, tenant_b: Tenant, df_a: pd.DataFrame, df_b: pd.DataFrame
) -> None:
    engine = KPIEngine()
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)

    results_a = engine.calculate_all(df_a, tenant_context=context_a)
    results_b = engine.calculate_all(df_b, tenant_context=context_b)

    assert results_a["total_revenue"].value == 42_000.0
    assert results_b["total_revenue"].value == 150.0
    # Re-check A's results after B has been processed -- proves nothing
    # about processing B mutated A's already-returned result objects.
    assert results_a["total_revenue"].value == 42_000.0


def test_two_tenants_processing_different_data_never_cross_contaminate_insights(
    tenant_a: Tenant, tenant_b: Tenant, df_a: pd.DataFrame, df_b: pd.DataFrame
) -> None:
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)

    insights_a = generate_business_insights(df_a, tenant_context=context_a)
    insights_b = generate_business_insights(df_b, tenant_context=context_b)

    assert insights_a.best_product == "Alpha"
    assert insights_b.best_product == "Zeta"
    assert insights_a.total_revenue != insights_b.total_revenue


def test_report_generated_for_one_tenant_does_not_contain_the_others_data(
    tenant_a: Tenant, tenant_b: Tenant, df_a: pd.DataFrame, df_b: pd.DataFrame
) -> None:
    engine = KPIEngine()
    reporting_service = ReportingService()
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)

    report_a = reporting_service.generate_report(
        ReportType.WEEKLY,
        ReportContext(kpi_results=engine.calculate_all(df_a, tenant_context=context_a)),
        tenant_context=context_a,
    )
    report_b = reporting_service.generate_report(
        ReportType.WEEKLY,
        ReportContext(kpi_results=engine.calculate_all(df_b, tenant_context=context_b)),
        tenant_context=context_b,
    )

    kpi_section_a = report_a.get_section("kpi_summary")
    kpi_section_b = report_b.get_section("kpi_summary")
    assert kpi_section_a is not None and kpi_section_b is not None
    assert kpi_section_a.content["total_revenue"].value == 42_000.0
    assert kpi_section_b.content["total_revenue"].value == 150.0
    assert kpi_section_a.content["total_revenue"].value != kpi_section_b.content["total_revenue"].value


def test_export_of_one_tenants_dataframe_never_includes_the_others_rows(
    tenant_a: Tenant, tenant_b: Tenant, df_a: pd.DataFrame, df_b: pd.DataFrame
) -> None:
    service = ExportService()
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)

    result_a = service.export(df_a, "csv", tenant_context=context_a)
    result_b = service.export(df_b, "csv", tenant_context=context_b)

    text_a = result_a.content.decode("utf-8")
    text_b = result_b.content.decode("utf-8")
    assert "Alpha" in text_a and "Zeta" not in text_a
    assert "Zeta" in text_b and "Alpha" not in text_b


def test_validate_tenant_context_logs_the_correct_tenant_id_for_each_call(
    tenant_a: Tenant, tenant_b: Tenant, caplog: pytest.LogCaptureFixture
) -> None:
    """Traceability check: the log line for each call must name the
    tenant that was actually processed, never the other tenant --
    otherwise an audit trail could misattribute one tenant's activity
    to another."""
    caplog.set_level(logging.INFO, logger="novamart.tenancy")

    validate_tenant_context(TenantContext(tenant=tenant_a), service_name="KPIEngine", operation="calculate_all")
    validate_tenant_context(TenantContext(tenant=tenant_b), service_name="KPIEngine", operation="calculate_all")

    messages = [record.message for record in caplog.records]
    assert any("tenant_id=org-a" in message and "outcome=OK" in message for message in messages)
    assert any("tenant_id=org-b" in message and "outcome=OK" in message for message in messages)


def test_rejected_validation_logs_a_dash_not_the_other_tenants_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="novamart.tenancy")

    with pytest.raises(MissingTenantContextError):
        validate_tenant_context(None, service_name="ExportService", operation="export")

    messages = [record.message for record in caplog.records]
    assert any("tenant_id=-" in message and "outcome=REJECTED" in message for message in messages)


def test_tenant_context_instances_are_independent_objects(tenant_a: Tenant, tenant_b: Tenant) -> None:
    """Constructing a context for tenant B must never affect an
    already-existing context bound to tenant A (no shared mutable
    state, no global singleton)."""
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)

    assert context_a.tenant is tenant_a
    assert context_b.tenant is tenant_b
    assert context_a.tenant.tenant_id != context_b.tenant.tenant_id


# --------------------------------------------------------------------------
# 5. Report Generation (tenant-gated)
# --------------------------------------------------------------------------


def test_report_generation_requires_tenant_context() -> None:
    service = ReportingService()
    with pytest.raises(MissingTenantContextError):
        service.generate_report(ReportType.WEEKLY, ReportContext())


def test_report_generation_succeeds_for_a_valid_active_tenant(tenant_a: Tenant, df_a: pd.DataFrame) -> None:
    context = TenantContext(tenant=tenant_a)
    engine = KPIEngine()
    service = ReportingService()
    report = service.generate_report(
        ReportType.WEEKLY,
        ReportContext(kpi_results=engine.calculate_all(df_a, tenant_context=context)),
        tenant_context=context,
    )
    assert not report.is_empty()


def test_report_generation_rejects_inactive_tenant(inactive_tenant: Tenant) -> None:
    context = TenantContext(tenant=inactive_tenant)
    service = ReportingService()
    with pytest.raises(InactiveTenantError):
        service.generate_report(ReportType.WEEKLY, ReportContext(), tenant_context=context)


# --------------------------------------------------------------------------
# 6. AI Recommendation Generation (tenant-gated)
# --------------------------------------------------------------------------


def test_ai_recommendation_generation_requires_tenant_context() -> None:
    service = AIRecommendationService()
    with pytest.raises(MissingTenantContextError):
        service.generate_recommendations(RecommendationContext())


def test_ai_recommendation_generation_succeeds_for_a_valid_active_tenant(
    tenant_a: Tenant, df_a: pd.DataFrame
) -> None:
    context = TenantContext(tenant=tenant_a)
    engine = KPIEngine()
    service = AIRecommendationService()
    batch = service.generate_recommendations(
        RecommendationContext(
            kpi_results=engine.calculate_all(df_a, tenant_context=context),
            business_insights=generate_business_insights(df_a, tenant_context=context),
        ),
        tenant_context=context,
    )
    assert not batch.is_empty()


def test_ai_recommendation_generation_rejects_inactive_tenant(inactive_tenant: Tenant) -> None:
    context = TenantContext(tenant=inactive_tenant)
    service = AIRecommendationService()
    with pytest.raises(InactiveTenantError):
        service.generate_recommendations(RecommendationContext(), tenant_context=context)


# --------------------------------------------------------------------------
# 7. PDF Generation (tenant-gated)
# --------------------------------------------------------------------------


def test_pdf_generation_requires_tenant_context() -> None:
    from services.reporting_service import Report, ReportMetadata
    from datetime import datetime, timezone

    service = PDFGeneratorService()
    empty_report = Report(
        report_type="weekly", metadata=ReportMetadata("Weekly", datetime.now(timezone.utc)), sections=()
    )
    with pytest.raises(MissingTenantContextError):
        service.generate_pdf(empty_report)


def test_pdf_generation_succeeds_for_a_valid_active_tenant(tenant_a: Tenant, df_a: pd.DataFrame) -> None:
    context = TenantContext(tenant=tenant_a)
    engine = KPIEngine()
    reporting_service = ReportingService()
    pdf_service = PDFGeneratorService()

    report = reporting_service.generate_report(
        ReportType.WEEKLY,
        ReportContext(kpi_results=engine.calculate_all(df_a, tenant_context=context)),
        tenant_context=context,
    )
    result = pdf_service.generate_pdf(report, tenant_context=context)

    assert result.content[:4] == b"%PDF"
    assert "Organization A" not in _pdf_text(result.content)  # tenant name isn't itself report content


def test_pdf_generation_rejects_inactive_tenant(inactive_tenant: Tenant) -> None:
    from services.reporting_service import Report, ReportMetadata
    from datetime import datetime, timezone

    context = TenantContext(tenant=inactive_tenant)
    service = PDFGeneratorService()
    empty_report = Report(
        report_type="weekly", metadata=ReportMetadata("Weekly", datetime.now(timezone.utc)), sections=()
    )
    with pytest.raises(InactiveTenantError):
        service.generate_pdf(empty_report, tenant_context=context)


# --------------------------------------------------------------------------
# 8. Export Generation (tenant-gated)
# --------------------------------------------------------------------------


def test_export_generation_requires_tenant_context(df_a: pd.DataFrame) -> None:
    service = ExportService()
    with pytest.raises(MissingTenantContextError):
        service.export(df_a, "csv")


def test_export_generation_succeeds_for_a_valid_active_tenant(tenant_a: Tenant, df_a: pd.DataFrame) -> None:
    context = TenantContext(tenant=tenant_a)
    service = ExportService()
    result = service.export(df_a, "csv", tenant_context=context)
    assert result.file_extension == "csv"


def test_export_generation_rejects_inactive_tenant(inactive_tenant: Tenant, df_a: pd.DataFrame) -> None:
    context = TenantContext(tenant=inactive_tenant)
    service = ExportService()
    with pytest.raises(InactiveTenantError):
        service.export(df_a, "csv", tenant_context=context)


# --------------------------------------------------------------------------
# 9. Configuration-driven tenant registration (Task 6) -- no hardcoded logic
# --------------------------------------------------------------------------


def test_registry_starts_empty_and_registers_a_tenant() -> None:
    registry = TenantRegistry()
    assert registry.all_tenants() == ()

    tenant = Tenant(tenant_id="new-co", name="new-co", display_name="New Co")
    registry.register(tenant)

    assert registry.get("new-co") is tenant
    assert registry.all_tenants() == (tenant,)


def test_registering_a_brand_new_tenant_requires_no_conditional_code() -> None:
    """Onboarding a tenant that has never existed before is a single
    ``register()`` call with a plain data object -- proving Task 6's
    'adding a new tenant should require configuration only' requirement.
    No ``if tenant == ...`` branch is written anywhere to make this work."""
    registry = TenantRegistry()
    future_tenants = [
        Tenant(tenant_id=f"future-tenant-{i}", name=f"future-tenant-{i}", display_name=f"Future Tenant {i}")
        for i in range(5)
    ]

    registry.register_many(future_tenants)

    for tenant in future_tenants:
        assert registry.get(tenant.tenant_id) is tenant
        # Immediately usable by a validating service, with zero new code.
        context = TenantContext(tenant=tenant)
        resolved = validate_tenant_context(context, service_name="KPIEngine", operation="calculate_all")
        assert resolved.tenant_id == tenant.tenant_id


def test_get_or_raise_raises_business_friendly_error_for_unknown_tenant() -> None:
    registry = TenantRegistry()
    with pytest.raises(TenantNotFoundError) as exc_info:
        registry.get_or_raise("does-not-exist")
    assert str(exc_info.value) == "The requested tenant could not be found. Unable to process request."


def test_active_tenants_excludes_inactive_ones() -> None:
    registry = TenantRegistry()
    active = Tenant(tenant_id="active-1", name="active-1", display_name="Active One")
    inactive = Tenant(tenant_id="inactive-1", name="inactive-1", display_name="Inactive One", status=TenantStatus.INACTIVE)
    registry.register_many([active, inactive])

    result = registry.active_tenants()
    assert active in result
    assert inactive not in result


def test_registering_under_the_same_id_replaces_the_previous_record() -> None:
    registry = TenantRegistry()
    original = Tenant(tenant_id="acme", name="acme", display_name="Acme v1")
    updated = Tenant(tenant_id="acme", name="acme", display_name="Acme v2", status=TenantStatus.INACTIVE)

    registry.register(original)
    registry.register(updated)

    assert registry.get("acme").display_name == "Acme v2"
    assert registry.get("acme").is_active is False


def test_shared_application_registry_is_populated_from_config_tenants() -> None:
    """``config/tenants.py`` registers its declarations into the shared
    ``tenant_registry`` at import time -- this test proves that
    happened, without hardcoding any service-level conditional logic."""
    import config.tenants  # noqa: F401 -- imported for its registration side effect

    assert tenant_registry.get("novamart-hq") is not None
    assert tenant_registry.get("acme-retail") is not None
    globex = tenant_registry.get("globex-demo")
    assert globex is not None
    assert globex.is_active is False


def test_tenant_model_supports_optional_metadata_without_any_service_change() -> None:
    tenant = Tenant(
        tenant_id="meta-co",
        name="meta-co",
        display_name="Metadata Co",
        metadata={"plan": "enterprise", "feature_flags": ["beta_reports"]},
    )
    assert tenant.metadata["plan"] == "enterprise"
    assert "beta_reports" in tenant.metadata["feature_flags"]
