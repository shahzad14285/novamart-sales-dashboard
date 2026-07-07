"""Unit tests for services/reporting_service.py.

services/reporting_service.py has no Streamlit/pandas dependency of its
own, but these tests build realistic inputs using the real
utils.kpi_engine / utils.insights modules (with pandas) so the
Reporting Service is exercised against the exact value objects it will
receive in production, not hand-rolled stand-ins.

Multi-Tenant Sprint 6.3 note: every ``calculate_all`` / ``generate_business_insights``
/ ``generate_report`` call below now requires a ``tenant_context`` keyword
argument -- see the ``tenant_context`` fixture -- since tenant
validation is now mandatory before any of these services will process
a request. Business-logic assertions are otherwise unchanged from
before the multi-tenant sprint.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from services.reporting_service import (
    InvalidReportContextError,
    InvalidReportTypeError,
    MissingReportDataError,
    Report,
    ReportContext,
    ReportingService,
    ReportMetadata,
    ReportSection,
    ReportType,
    SectionSpec,
    UnknownReportSectionError,
    UnknownReportTypeError,
    sales_reporting_service,
)
from tenancy.context import TenantContext
from tenancy.exceptions import InactiveTenantError, MissingTenantContextError
from tenancy.models import Tenant, TenantStatus
from utils.insights import generate_business_insights
from utils.kpi_engine import sales_kpi_engine


@pytest.fixture
def tenant_context() -> TenantContext:
    """A valid, active TenantContext shared by every test in this file."""
    return TenantContext(tenant=Tenant(tenant_id="test-tenant", name="test-tenant", display_name="Test Tenant"))


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """A small, realistic sales DataFrame with product/region columns."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5, freq="D"),
            "revenue": [500.0, 300.0, 700.0, 200.0, 900.0],
            "orders": [10, 8, 15, 5, 20],
            "product": ["Widget", "Gadget", "Widget", "Gizmo", "Widget"],
            "region": ["North", "South", "North", "East", "North"],
        }
    )


@pytest.fixture
def full_context(sample_df: pd.DataFrame, tenant_context: TenantContext) -> ReportContext:
    """A context with every field populated, built from real business data."""
    kpi_results = sales_kpi_engine.calculate_all(sample_df, tenant_context=tenant_context)
    insights = generate_business_insights(sample_df, tenant_context=tenant_context)
    regional_summary = sample_df.groupby("region")["revenue"].sum()
    product_summary = sample_df.groupby("product")["revenue"].sum()
    return ReportContext(
        kpi_results=kpi_results,
        business_insights=insights,
        regional_summary=regional_summary,
        product_summary=product_summary,
    )


# --------------------------------------------------------------------------
# generate_report -- happy paths for each required report type
# --------------------------------------------------------------------------


def test_executive_report_includes_all_sections_when_data_present(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    report = service.generate_report(ReportType.EXECUTIVE, full_context, tenant_context=tenant_context)

    assert isinstance(report, Report)
    assert report.report_type is ReportType.EXECUTIVE
    assert report.section_keys() == ("kpi_summary", "business_insights", "product_summary", "regional_summary")
    assert not report.is_empty()


def test_executive_report_accepts_string_report_type(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    report = service.generate_report("executive", full_context, tenant_context=tenant_context)
    assert report.report_type is ReportType.EXECUTIVE


def test_executive_report_string_is_case_insensitive_and_trims_whitespace(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    report = service.generate_report("  EXECUTIVE  ", full_context, tenant_context=tenant_context)
    assert report.report_type is ReportType.EXECUTIVE


def test_weekly_report_omits_optional_missing_business_insights(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    kpi_only_context = ReportContext(kpi_results=full_context.kpi_results)
    report = service.generate_report(ReportType.WEEKLY, kpi_only_context, tenant_context=tenant_context)

    assert report.section_keys() == ("kpi_summary",)


def test_monthly_report_requires_product_summary(full_context: ReportContext, tenant_context: TenantContext) -> None:
    service = ReportingService()
    missing_product_context = ReportContext(
        kpi_results=full_context.kpi_results,
        business_insights=full_context.business_insights,
    )
    with pytest.raises(MissingReportDataError) as exc_info:
        service.generate_report(ReportType.MONTHLY, missing_product_context, tenant_context=tenant_context)

    assert exc_info.value.section_key == "product_summary"
    assert exc_info.value.report_type == "monthly"


def test_regional_report_requires_regional_summary(tenant_context: TenantContext) -> None:
    service = ReportingService()
    with pytest.raises(MissingReportDataError) as exc_info:
        service.generate_report(ReportType.REGIONAL, ReportContext(), tenant_context=tenant_context)

    assert exc_info.value.section_key == "regional_summary"


def test_regional_report_succeeds_with_only_regional_summary(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    regional_only_context = ReportContext(regional_summary=full_context.regional_summary)
    report = service.generate_report(ReportType.REGIONAL, regional_only_context, tenant_context=tenant_context)

    assert report.section_keys() == ("regional_summary",)


# --------------------------------------------------------------------------
# Section content fidelity -- Reporting Service must not transform data
# --------------------------------------------------------------------------


def test_kpi_summary_section_content_matches_input_kpi_results(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    report = service.generate_report(ReportType.EXECUTIVE, full_context, tenant_context=tenant_context)

    section = report.get_section("kpi_summary")
    assert section is not None
    assert section.content == dict(full_context.kpi_results)


def test_business_insights_section_content_is_the_same_object(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    report = service.generate_report(ReportType.EXECUTIVE, full_context, tenant_context=tenant_context)

    section = report.get_section("business_insights")
    assert section is not None
    assert section.content is full_context.business_insights


def test_regional_summary_section_normalizes_pandas_series_to_dict(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    report = service.generate_report(ReportType.EXECUTIVE, full_context, tenant_context=tenant_context)

    section = report.get_section("regional_summary")
    assert section is not None
    assert isinstance(section.content, dict)
    assert section.content["North"] == 2100.0


def test_sections_are_ordered_contiguously_skipping_omitted_optionals(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    context_without_product = ReportContext(
        kpi_results=full_context.kpi_results,
        business_insights=full_context.business_insights,
        regional_summary=full_context.regional_summary,
    )
    report = service.generate_report(ReportType.EXECUTIVE, context_without_product, tenant_context=tenant_context)

    orders = [section.order for section in report.sections]
    assert orders == list(range(len(report.sections)))
    assert "product_summary" not in report.section_keys()


# --------------------------------------------------------------------------
# Empty report data
# --------------------------------------------------------------------------


def test_weekly_report_with_totally_empty_context_raises_for_required_kpi_section(
    tenant_context: TenantContext,
) -> None:
    service = ReportingService()
    with pytest.raises(MissingReportDataError) as exc_info:
        service.generate_report(ReportType.WEEKLY, ReportContext(), tenant_context=tenant_context)

    assert exc_info.value.section_key == "kpi_summary"


def test_empty_mapping_is_treated_the_same_as_none(tenant_context: TenantContext) -> None:
    service = ReportingService()
    context = ReportContext(regional_summary={})
    with pytest.raises(MissingReportDataError):
        service.generate_report(ReportType.REGIONAL, context, tenant_context=tenant_context)


def test_report_is_empty_when_every_section_is_optional_and_absent(tenant_context: TenantContext) -> None:
    service = ReportingService()
    service.define_report(ReportType.WEEKLY, (SectionSpec("business_insights", required=False),))
    report = service.generate_report(ReportType.WEEKLY, ReportContext(), tenant_context=tenant_context)

    assert report.is_empty()
    assert report.sections == ()


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def test_invalid_context_type_raises(tenant_context: TenantContext) -> None:
    service = ReportingService()
    with pytest.raises(InvalidReportContextError):
        service.generate_report(ReportType.EXECUTIVE, {"kpi_results": {}}, tenant_context=tenant_context)


def test_invalid_report_type_type_raises(full_context: ReportContext, tenant_context: TenantContext) -> None:
    service = ReportingService()
    with pytest.raises(InvalidReportTypeError):
        service.generate_report(123, full_context, tenant_context=tenant_context)  # type: ignore[arg-type]


def test_unknown_report_type_string_raises(full_context: ReportContext, tenant_context: TenantContext) -> None:
    service = ReportingService()
    with pytest.raises(UnknownReportTypeError):
        service.generate_report("quarterly", full_context, tenant_context=tenant_context)


def test_unregistered_section_key_raises_unknown_section_error(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    service.define_report(ReportType.WEEKLY, (SectionSpec("nonexistent_section", required=True),))
    with pytest.raises(UnknownReportSectionError):
        service.generate_report(ReportType.WEEKLY, full_context, tenant_context=tenant_context)


# --------------------------------------------------------------------------
# Extensibility: new section + new report type, without modifying the class
# --------------------------------------------------------------------------


def test_register_new_section_builder_and_include_it(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()

    def _build_risk_section(context: ReportContext) -> ReportSection | None:
        risk_data = getattr(context, "risk_analysis", None)
        if risk_data is None:
            return None
        return ReportSection(key="risk_analysis", title="Risk Analysis", content=risk_data, order=0)

    service.register_section_builder("risk_analysis", _build_risk_section)
    service.define_report(
        ReportType.EXECUTIVE,
        (SectionSpec("kpi_summary", required=True), SectionSpec("risk_analysis", required=False)),
    )

    # ReportContext doesn't declare risk_analysis, so the builder sees None via getattr and omits it.
    report = service.generate_report(ReportType.EXECUTIVE, full_context, tenant_context=tenant_context)
    assert report.section_keys() == ("kpi_summary",)


def test_define_new_report_type_end_to_end(full_context: ReportContext, tenant_context: TenantContext) -> None:
    service = ReportingService()

    # A brand-new report type key -- e.g. a future department-specific
    # report -- defined purely through define_report() using only
    # already-registered section builders. No ReportType or
    # ReportingService change was needed.
    service.define_report("department", (SectionSpec("product_summary", required=True),))

    report = service.generate_report("department", full_context, tenant_context=tenant_context)
    assert report.section_keys() == ("product_summary",)
    assert report.report_type == "department"


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------


def test_default_metadata_is_generated_when_not_provided(
    full_context: ReportContext, tenant_context: TenantContext
) -> None:
    service = ReportingService()
    report = service.generate_report(ReportType.EXECUTIVE, full_context, tenant_context=tenant_context)

    assert isinstance(report.metadata, ReportMetadata)
    assert report.metadata.title == "Executive Report"
    assert report.metadata.generated_at is not None


def test_custom_metadata_is_preserved(full_context: ReportContext, tenant_context: TenantContext) -> None:
    service = ReportingService()
    custom_metadata = ReportMetadata(
        title="Q1 Executive Briefing",
        generated_at=datetime(2026, 1, 5),
        prepared_for="Board of Directors",
    )
    context_with_metadata = ReportContext(
        kpi_results=full_context.kpi_results,
        business_insights=full_context.business_insights,
        metadata=custom_metadata,
    )
    report = service.generate_report(ReportType.EXECUTIVE, context_with_metadata, tenant_context=tenant_context)

    assert report.metadata.title == "Q1 Executive Briefing"
    assert report.metadata.prepared_for == "Board of Directors"


# --------------------------------------------------------------------------
# report_types() / shared instance
# --------------------------------------------------------------------------


def test_report_types_lists_all_default_types() -> None:
    service = ReportingService()
    assert set(service.report_types()) == {"executive", "weekly", "monthly", "regional"}


def test_shared_instance_is_a_reporting_service() -> None:
    assert isinstance(sales_reporting_service, ReportingService)


def test_shared_instance_generates_a_report(full_context: ReportContext, tenant_context: TenantContext) -> None:
    report = sales_reporting_service.generate_report("weekly", full_context, tenant_context=tenant_context)
    assert report.report_type is ReportType.WEEKLY


# --------------------------------------------------------------------------
# Multi-Tenant Sprint 6.3 -- tenant validation on generate_report()
# --------------------------------------------------------------------------


def test_generate_report_without_tenant_context_raises(full_context: ReportContext) -> None:
    service = ReportingService()
    with pytest.raises(MissingTenantContextError):
        service.generate_report(ReportType.EXECUTIVE, full_context)


def test_generate_report_with_inactive_tenant_raises(full_context: ReportContext) -> None:
    inactive_context = TenantContext(
        tenant=Tenant(
            tenant_id="inactive-tenant", name="inactive-tenant", display_name="Inactive Co", status=TenantStatus.INACTIVE
        )
    )
    service = ReportingService()
    with pytest.raises(InactiveTenantError):
        service.generate_report(ReportType.EXECUTIVE, full_context, tenant_context=inactive_context)


def test_generate_report_error_message_is_business_friendly_and_has_no_technical_detail() -> None:
    service = ReportingService()
    try:
        service.generate_report(ReportType.EXECUTIVE, ReportContext())
    except MissingTenantContextError as exc:
        assert str(exc) == "Tenant context is missing. Unable to process request."
        assert "Traceback" not in str(exc)
        assert "ReportingService" not in str(exc)
    else:
        pytest.fail("Expected MissingTenantContextError")
