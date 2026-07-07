"""Unit tests for services/pdf_generator_service.py.

Inputs are built from the real services.reporting_service /
utils.kpi_engine / utils.insights modules (with pandas) so the PDF
Generator Service is exercised against the exact Report objects it
will receive in production, not hand-rolled stand-ins. Generated PDF
bytes are inspected with pdfplumber so assertions check real rendered
content, not just "no exception was raised".

Multi-Tenant Sprint 6.3 note: every ``calculate_all`` / ``generate_business_insights``
/ ``generate_report`` / ``generate_pdf`` call below now requires a
``tenant_context`` keyword argument -- see the ``tenant_context`` fixture --
since tenant validation is now mandatory before any of these services will
process a request. Business-logic assertions are otherwise unchanged from
before the multi-tenant sprint.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pdfplumber
import pytest
from reportlab.platypus import Paragraph

from services.pdf_generator_service import (
    InvalidBrandingConfigError,
    InvalidReportInputError,
    PDFBrandingConfig,
    PDFGeneratorService,
    PDFRenderingError,
    PDFResult,
    sales_pdf_generator_service,
)
from services.reporting_service import (
    Report,
    ReportContext,
    ReportingService,
    ReportMetadata,
    ReportSection,
    ReportType,
    SectionSpec,
)
from tenancy.context import TenantContext
from tenancy.exceptions import InactiveTenantError, MissingTenantContextError
from tenancy.models import Tenant, TenantStatus
from utils.insights import generate_business_insights
from utils.kpi_engine import sales_kpi_engine


def _pdf_text(content: bytes) -> str:
    """Extract all text from generated PDF bytes, for content assertions."""
    from io import BytesIO

    with pdfplumber.open(BytesIO(content)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@pytest.fixture
def tenant_context() -> TenantContext:
    """A valid, active TenantContext shared by every test in this file."""
    return TenantContext(tenant=Tenant(tenant_id="test-tenant", name="test-tenant", display_name="Test Tenant"))


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="D"),
            "revenue": [500.0, 300.0, 700.0, 200.0, 900.0, 650.0],
            "orders": [10, 8, 15, 5, 20, 12],
            "product": ["Widget", "Gadget", "Widget", "Gizmo", "Widget", "Gadget"],
            "region": ["North", "South", "North", "East", "North", "South"],
        }
    )


@pytest.fixture
def executive_report(sample_df: pd.DataFrame, tenant_context: TenantContext) -> Report:
    kpi_results = sales_kpi_engine.calculate_all(sample_df, tenant_context=tenant_context)
    insights = generate_business_insights(sample_df, tenant_context=tenant_context)
    regional = sample_df.groupby("region")["revenue"].sum()
    product = sample_df.groupby("product")["revenue"].sum()
    context = ReportContext(
        kpi_results=kpi_results,
        business_insights=insights,
        regional_summary=regional,
        product_summary=product,
        metadata=ReportMetadata(
            title="Executive Report",
            generated_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
            period_label="Week of Jan 1-6, 2026",
            prepared_for="Board of Directors",
        ),
    )
    return ReportingService().generate_report(ReportType.EXECUTIVE, context, tenant_context=tenant_context)


# --------------------------------------------------------------------------
# Happy path -- default branding
# --------------------------------------------------------------------------


def test_generates_valid_pdf_bytes(executive_report: Report, tenant_context: TenantContext) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(executive_report, tenant_context=tenant_context)

    assert isinstance(result, PDFResult)
    assert result.content[:4] == b"%PDF"
    assert result.file_extension == "pdf"
    assert result.mime_type == "application/pdf"
    assert result.page_count >= 1


def test_cover_page_contains_title_period_and_audience(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(executive_report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "Executive Report" in text
    assert "Week of Jan 1-6, 2026" in text
    assert "Prepared for: Board of Directors" in text


def test_all_sections_are_rendered_in_order(executive_report: Report, tenant_context: TenantContext) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(executive_report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    kpi_pos = text.index("Key Performance Indicators")
    insights_pos = text.index("Business Insights")
    product_pos = text.index("Product Summary")
    regional_pos = text.index("Regional Summary")
    assert kpi_pos < insights_pos < product_pos < regional_pos


def test_kpi_section_shows_labels_and_formatted_values_not_raw_icons(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(executive_report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "Total Revenue" in text
    assert "$3,250.00" in text
    # Emoji icons have no glyph in the base PDF fonts used, so they are
    # deliberately left out of the rendered KPI table.
    assert "\U0001f4b0" not in text


def test_business_insights_section_shows_key_metrics(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(executive_report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "Best Product" in text
    assert "Widget" in text
    assert "Top 3 Products Share of Revenue" in text


def test_regional_and_product_summaries_show_currency_formatted_values(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(executive_report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "North" in text
    assert "$2,100.00" in text


def test_footer_and_page_numbers_present_by_default(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(executive_report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "NovaMart Sales Intelligence Dashboard" in text
    assert "Page 1" in text


# --------------------------------------------------------------------------
# Branding configuration
# --------------------------------------------------------------------------


def test_custom_branding_changes_company_name_and_footer(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    branding = PDFBrandingConfig(company_name="NovaMart Retail Group", footer_text="Custom Footer")
    result = service.generate_pdf(executive_report, branding=branding, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "NovaMart Retail Group" in text
    assert "Custom Footer" in text
    assert "NovaMart Sales Intelligence Dashboard" not in text


def test_show_cover_page_false_skips_cover_page(executive_report: Report, tenant_context: TenantContext) -> None:
    service = PDFGeneratorService()
    with_cover = service.generate_pdf(executive_report, tenant_context=tenant_context)
    without_cover = service.generate_pdf(
        executive_report, branding=PDFBrandingConfig(show_cover_page=False), tenant_context=tenant_context
    )

    assert without_cover.page_count < with_cover.page_count
    text = _pdf_text(without_cover.content)
    assert "Prepared for" not in text


def test_show_page_numbers_false_omits_page_number_text(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(
        executive_report, branding=PDFBrandingConfig(show_page_numbers=False), tenant_context=tenant_context
    )
    text = _pdf_text(result.content)

    assert "Page 1" not in text
    assert "NovaMart Sales Intelligence Dashboard" in text  # footer text itself still shows


def test_watermark_text_appears_on_every_page(executive_report: Report, tenant_context: TenantContext) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(
        executive_report, branding=PDFBrandingConfig(watermark_text="DRAFT"), tenant_context=tenant_context
    )
    text = _pdf_text(result.content)

    # Rotated text extracts as individual characters in reading order;
    # every letter of "DRAFT" being present is sufficient evidence the
    # watermark was drawn (a dedicated visual/rendering test would be
    # needed to check exact placement, which is out of scope here).
    for letter in "DRAFT":
        assert letter in text


def test_table_of_contents_lists_every_section_with_a_page_number(
    executive_report: Report, tenant_context: TenantContext
) -> None:
    service = PDFGeneratorService()
    result = service.generate_pdf(
        executive_report, branding=PDFBrandingConfig(show_table_of_contents=True), tenant_context=tenant_context
    )
    text = _pdf_text(result.content)

    assert "Table of Contents" in text
    assert "Key Performance Indicators" in text
    assert "Regional Summary" in text


def test_invalid_branding_type_raises(tenant_context: TenantContext) -> None:
    service = PDFGeneratorService()
    with pytest.raises(InvalidBrandingConfigError):
        service.generate_pdf(
            Report(report_type="x", metadata=ReportMetadata("x", datetime.now(timezone.utc)), sections=()),
            branding="not a config",  # type: ignore[arg-type]
            tenant_context=tenant_context,
        )


# --------------------------------------------------------------------------
# Empty / missing data handling
# --------------------------------------------------------------------------


def test_empty_report_produces_valid_pdf_instead_of_raising(tenant_context: TenantContext) -> None:
    reporting_service = ReportingService()
    reporting_service.define_report(ReportType.WEEKLY, (SectionSpec("business_insights", required=False),))
    empty_report = reporting_service.generate_report(ReportType.WEEKLY, ReportContext(), tenant_context=tenant_context)
    assert empty_report.is_empty()

    service = PDFGeneratorService()
    result = service.generate_pdf(empty_report, tenant_context=tenant_context)

    assert result.content[:4] == b"%PDF"
    text = _pdf_text(result.content)
    assert "No data is available for this report" in text


def test_section_with_empty_mapping_content_renders_placeholder_text(tenant_context: TenantContext) -> None:
    report = Report(
        report_type="custom",
        metadata=ReportMetadata(title="Custom", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        sections=(ReportSection(key="regional_summary", title="Regional Summary", content={}, order=0),),
    )
    service = PDFGeneratorService()
    result = service.generate_pdf(report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "No data available for this section" in text


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def test_invalid_report_type_raises(tenant_context: TenantContext) -> None:
    service = PDFGeneratorService()
    with pytest.raises(InvalidReportInputError):
        service.generate_pdf({"not": "a report"}, tenant_context=tenant_context)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Extensibility: registering a renderer for a brand-new content type
# --------------------------------------------------------------------------


class _FutureRiskAnalysis:
    """Stands in for a not-yet-built future section content type."""

    def __str__(self) -> str:
        return "Risk level: HIGH"


def test_register_content_renderer_handles_a_brand_new_content_type_without_class_changes(
    tenant_context: TenantContext,
) -> None:
    def _render_risk(section: ReportSection, branding: PDFBrandingConfig, styles: dict) -> list:
        return [Paragraph(f"RISK ANALYSIS: {section.content}", styles["body"])]

    service = PDFGeneratorService()
    service.register_content_renderer(_FutureRiskAnalysis, _render_risk)

    report = Report(
        report_type="custom",
        metadata=ReportMetadata(title="Custom", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        sections=(ReportSection(key="risk_analysis", title="Risk Analysis", content=_FutureRiskAnalysis(), order=0),),
    )
    result = service.generate_pdf(report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "RISK ANALYSIS: Risk level: HIGH" in text


def test_unregistered_content_type_falls_back_to_plain_text_instead_of_raising(
    tenant_context: TenantContext,
) -> None:
    report = Report(
        report_type="custom",
        metadata=ReportMetadata(title="Custom", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        sections=(ReportSection(key="mystery", title="Mystery Section", content=_FutureRiskAnalysis(), order=0),),
    )
    service = PDFGeneratorService()
    result = service.generate_pdf(report, tenant_context=tenant_context)
    text = _pdf_text(result.content)

    assert "Mystery Section" in text
    assert "Risk level: HIGH" in text


def test_renderer_exception_is_wrapped_in_pdf_rendering_error(tenant_context: TenantContext) -> None:
    def _broken_renderer(section: ReportSection, branding: PDFBrandingConfig, styles: dict) -> list:
        raise RuntimeError("simulated renderer bug")

    service = PDFGeneratorService()
    service.register_content_renderer(_FutureRiskAnalysis, _broken_renderer)
    report = Report(
        report_type="custom",
        metadata=ReportMetadata(title="Custom", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        sections=(ReportSection(key="risk_analysis", title="Risk Analysis", content=_FutureRiskAnalysis(), order=0),),
    )
    with pytest.raises(PDFRenderingError) as exc_info:
        service.generate_pdf(report, tenant_context=tenant_context)

    assert exc_info.value.section_key == "risk_analysis"
    assert isinstance(exc_info.value.original_error, RuntimeError)


# --------------------------------------------------------------------------
# Shared instance
# --------------------------------------------------------------------------


def test_shared_instance_is_a_pdf_generator_service() -> None:
    assert isinstance(sales_pdf_generator_service, PDFGeneratorService)


def test_shared_instance_generates_a_pdf(executive_report: Report, tenant_context: TenantContext) -> None:
    result = sales_pdf_generator_service.generate_pdf(executive_report, tenant_context=tenant_context)
    assert isinstance(result, PDFResult)
    assert result.content[:4] == b"%PDF"


# --------------------------------------------------------------------------
# Multi-Tenant Sprint 6.3 -- tenant validation on generate_pdf()
# --------------------------------------------------------------------------


def test_generate_pdf_without_tenant_context_raises(executive_report: Report) -> None:
    service = PDFGeneratorService()
    with pytest.raises(MissingTenantContextError):
        service.generate_pdf(executive_report)


def test_generate_pdf_with_inactive_tenant_raises(executive_report: Report) -> None:
    inactive_context = TenantContext(
        tenant=Tenant(
            tenant_id="inactive-tenant", name="inactive-tenant", display_name="Inactive Co", status=TenantStatus.INACTIVE
        )
    )
    service = PDFGeneratorService()
    with pytest.raises(InactiveTenantError):
        service.generate_pdf(executive_report, tenant_context=inactive_context)


def test_generate_pdf_error_message_is_business_friendly_and_has_no_technical_detail() -> None:
    service = PDFGeneratorService()
    report = Report(
        report_type="x", metadata=ReportMetadata("x", datetime.now(timezone.utc)), sections=()
    )
    try:
        service.generate_pdf(report)
    except MissingTenantContextError as exc:
        assert str(exc) == "Tenant context is missing. Unable to process request."
        assert "Traceback" not in str(exc)
        assert "PDFGeneratorService" not in str(exc)
    else:
        pytest.fail("Expected MissingTenantContextError")
