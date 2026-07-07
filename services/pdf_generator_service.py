"""PDF Generator Service for the NovaMart Sales Intelligence Dashboard.

Sprint 6.2 -- Executive Reporting & Export Center, Module 4.

Converts an already-assembled :class:`~services.reporting_service.Report`
into a professional PDF document. This module has exactly one
responsibility -- rendering a report's existing structure as a PDF --
and deliberately does nothing else.

The PDF Generator does NOT:
    - Read uploaded files (that's ``utils/data_loader.py``).
    - Calculate KPIs (that's ``utils/kpi_engine.py`` / ``utils/calculations.py``).
    - Generate business insights (that's ``utils/insights.py``).
    - Generate AI recommendations (that's ``services/ai_recommendation_service.py``).
    - Assemble reports (that's ``services/reporting_service.py``).
    - Export CSV, Excel, or JSON (that's ``services/export_service.py``).
    - Send emails (a future, separate service).

It is a renderer, not a calculator: every value it prints was computed
elsewhere and handed to it, unchanged, inside a ``Report``.

Architectural approach (and why it doesn't mirror Module 3's provider
abstraction)
---------------------------------------------------------------------
Module 3 (AI Recommendation Service) needed a swappable-*provider*
abstraction because its ticket explicitly forbade depending on any one
AI vendor and named several concrete, genuinely interchangeable
backends (GPT, Claude, Gemini). This ticket's future-compatibility list
is different in kind: logo, corporate colors, headers/footers, page
numbers, watermarks, cover page, table of contents. None of that is
"swap the rendering engine" -- it's "add more visual/branding
elements to the same renderer over time." Introducing a
``PDFRenderer`` strategy interface here would add a layer of
indirection to solve a problem nobody asked for (multiple PDF
backends), while leaving the real extensibility need (more branding
knobs, more section content types) no easier to satisfy.

So this module depends directly on one well-established library,
`reportlab <https://www.reportlab.com/>`_ -- the same way
``ExportService`` depends directly on ``pandas``/``openpyxl`` rather
than hiding them behind an interface -- and channels its two *actual*
extension axes into purpose-built seams instead:

1. **Branding/presentation knobs** (the ticket's explicit future list)
   are every field of :class:`PDFBrandingConfig`, a single object
   threaded through every rendering step. Turning on a watermark,
   swapping the corporate color, or supplying a logo image is a config
   change, never a code change.
2. **New section content types** (e.g. a future
   ``RecommendationBatch`` or ``risk_analysis`` section once those are
   added to ``Report``) are handled by a small registry --
   :meth:`PDFGeneratorService.register_content_renderer` -- exactly
   mirroring the registry pattern already used by
   :class:`~utils.kpi_engine.KPIEngine`,
   :class:`~services.export_service.ExportService`, and
   :class:`~services.reporting_service.ReportingService`. Adding a
   renderer for a new content type never requires touching
   :class:`PDFGeneratorService` itself.

Future compatibility items already wired as real, working mechanisms
(not just placeholders) so they need configuration, not a redesign,
when the user is ready to use them:
    - Cover page (``PDFBrandingConfig.show_cover_page``).
    - Corporate colors (``primary_color`` / ``accent_color``).
    - Page numbers and a footer (``show_page_numbers`` / ``footer_text``).
    - Watermark text (``watermark_text``).
    - Table of contents with real page numbers, via reportlab's
      two-pass ``multiBuild`` (``show_table_of_contents``).
    - Company logo (``logo_path``) -- rendered on the cover page when a
      readable image file is supplied; silently omitted otherwise so a
      missing/corrupt logo asset never breaks report generation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Callable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from monitoring.service import monitoring_service
from services.reporting_service import Report, ReportSection
from tenancy.context import TenantContext, validate_tenant_context
from utils.formatting import format_currency, format_date, format_integer
from utils.insights import BusinessInsights
from utils.kpi_engine import KPIResult


# ==============================================================================
# Exceptions
# ==============================================================================


class PDFGeneratorServiceError(Exception):
    """Base class for every error raised by the PDF Generator Service.

    Catch this type in calling code to handle *any* PDF generation
    failure with a single ``except`` clause, e.g.::

        try:
            result = sales_pdf_generator_service.generate_pdf(report)
        except PDFGeneratorServiceError as exc:
            st.error(str(exc))
    """


class InvalidReportInputError(PDFGeneratorServiceError):
    """Raised when the value handed to the service isn't a :class:`Report`."""

    def __init__(self, received: object) -> None:
        """Build a user-friendly "invalid report" message.

        Args:
            received: The value that was passed in place of a
                :class:`~services.reporting_service.Report`.
        """
        self.received_type = type(received)
        message = f"PDFGeneratorService requires a Report instance, got '{self.received_type.__name__}' instead."
        super().__init__(message)


class InvalidBrandingConfigError(PDFGeneratorServiceError):
    """Raised when ``branding`` isn't a :class:`PDFBrandingConfig` instance."""

    def __init__(self, received: object) -> None:
        """Build a user-friendly "invalid branding config" message.

        Args:
            received: The value that was passed in place of a
                :class:`PDFBrandingConfig`.
        """
        self.received_type = type(received)
        message = (
            "PDFGeneratorService requires a PDFBrandingConfig instance for "
            f"'branding', got '{self.received_type.__name__}' instead."
        )
        super().__init__(message)


class PDFRenderingError(PDFGeneratorServiceError):
    """Raised when rendering a report's content into the PDF unexpectedly fails.

    Wraps the original exception so the underlying cause (e.g. a
    malformed value inside a custom, third-party content renderer) is
    never silently swallowed.
    """

    def __init__(self, section_key: str, original_error: Exception) -> None:
        """Build a message identifying which section failed to render.

        Args:
            section_key: The report section being rendered when the
                failure occurred (``"document"`` for a failure that
                isn't tied to one specific section).
            original_error: The exception raised while rendering.
        """
        self.section_key = section_key
        self.original_error = original_error
        message = f"Failed to render the PDF for section '{section_key}': {original_error}"
        super().__init__(message)


# ==============================================================================
# Value objects
# ==============================================================================


@dataclass(frozen=True)
class PDFBrandingConfig:
    """Presentation/branding options for a generated PDF.

    Every field has a sensible default, so calling
    :meth:`PDFGeneratorService.generate_pdf` with no ``branding``
    argument already produces a clean, professional document. Every
    future branding enhancement named in this module's ticket -- a
    logo, corporate colors, headers/footers, page numbers, a
    watermark, a cover page, a table of contents -- is a field here,
    so turning one on (or restyling it) is a configuration change, not
    a code change.

    Attributes:
        company_name: Shown on the cover page and, unless
            ``footer_text`` overrides it, in the footer of every page.
        logo_path: Path to a logo image file. Rendered on the cover
            page when the path points to a readable image; silently
            omitted otherwise (a missing or corrupt logo never breaks
            report generation).
        primary_color: Hex color used for titles and section headings.
        accent_color: Hex color used for secondary cover-page text.
        footer_text: Custom footer text. Defaults to
            ``"{company_name} Sales Intelligence Dashboard"`` when not set.
        watermark_text: When set, this text is stamped diagonally
            across every page (e.g. ``"DRAFT"`` or ``"CONFIDENTIAL"``).
        show_cover_page: Whether to generate a title/cover page.
        show_page_numbers: Whether to print "Page N" in the footer.
        show_table_of_contents: Whether to generate a table of
            contents listing each section and its starting page.
        page_size: ``"A4"`` or ``"letter"``.
    """

    company_name: str = "NovaMart"
    logo_path: str | None = None
    primary_color: str = "#1F3864"
    accent_color: str = "#2E75B6"
    footer_text: str | None = None
    watermark_text: str | None = None
    show_cover_page: bool = True
    show_page_numbers: bool = True
    show_table_of_contents: bool = False
    page_size: str = "A4"


@dataclass(frozen=True)
class PDFResult:
    """Immutable bundle describing one PDF's output.

    Mirrors the shape of :class:`~services.export_service.ExportResult`
    so downstream consumers -- the Executive Report Center, a future
    Notification/Email Service, or a Streamlit ``st.download_button``
    -- can handle a PDF result the same way they already handle an
    export result.

    Attributes:
        content: The generated PDF as raw ``bytes``.
        file_extension: Always ``"pdf"``.
        mime_type: Always ``"application/pdf"``.
        page_count: Total number of pages generated.
    """

    content: bytes
    file_extension: str = "pdf"
    mime_type: str = "application/pdf"
    page_count: int = 0


# A content renderer turns one ReportSection's content into a list of
# reportlab flowables. Keeping this signature uniform is what makes
# register_content_renderer() work for any future content type
# (a risk analysis object, an AI recommendation batch, ...) without
# changing PDFGeneratorService itself.
ContentRenderer = Callable[[ReportSection, PDFBrandingConfig, dict], list]


# ==============================================================================
# Internal rendering helpers (module-level: no service state needed)
# ==============================================================================


def _build_styles(branding: PDFBrandingConfig) -> dict:
    """Build the paragraph styles used throughout a single PDF, from branding."""
    base = getSampleStyleSheet()
    primary = colors.HexColor(branding.primary_color)
    accent = colors.HexColor(branding.accent_color)
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle", parent=base["Title"], textColor=primary, fontSize=26, alignment=TA_CENTER, spaceAfter=14
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle", parent=base["Normal"], textColor=accent, fontSize=14, alignment=TA_CENTER, spaceAfter=8
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta", parent=base["Normal"], fontSize=10, alignment=TA_CENTER, textColor=colors.grey
        ),
        "section_heading": ParagraphStyle(
            "SectionHeading", parent=base["Heading2"], textColor=primary, spaceBefore=14, spaceAfter=8
        ),
        "toc_heading": ParagraphStyle("TOCHeading", parent=base["Heading1"], textColor=primary),
        "toc_entry": ParagraphStyle("TOCEntry", parent=base["Normal"], fontSize=11, leftIndent=16),
        "body": base["Normal"],
    }


def _format_timestamp(value: datetime) -> str:
    """Format a report's ``generated_at`` datetime for the cover page."""
    return format_date(value, "%B %d, %Y at %H:%M UTC")


def _format_day(value: object | None, revenue: float) -> str:
    """Format a ``(day, revenue)`` pair for display, tolerating odd input."""
    if value is None:
        return "N/A"
    day_text = format_date(value) if hasattr(value, "strftime") else str(value)
    return f"{day_text} ({format_currency(revenue)})"


def _styled_table(rows: list[list[str]], branding: PDFBrandingConfig) -> Table:
    """Build a two-column table styled with the report's branding colors."""
    table = Table(rows, hAlign="LEFT", colWidths=[8 * cm, 7 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(branding.primary_color)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ]
        )
    )
    return table


def _section_heading(section: ReportSection, styles: dict) -> Paragraph:
    """Build the heading paragraph shown at the top of every rendered section."""
    return Paragraph(section.title, styles["section_heading"])


def _render_mapping_section(section: ReportSection, branding: PDFBrandingConfig, styles: dict) -> list:
    """Render a ``dict``-shaped section: KPI results, or a name -> revenue mapping.

    Covers both ``kpi_summary`` (``dict[str, KPIResult]``) and
    ``regional_summary``/``product_summary``
    (``dict[str, float]``) -- the two ``dict``-shaped section content
    types the Reporting Service currently produces -- by inspecting the
    first value's type rather than the section's key, so it keeps
    working unchanged if a future section reuses either shape.
    """
    content: dict = section.content
    flowables: list = [_section_heading(section, styles)]
    if not content:
        flowables.append(Paragraph("No data available for this section.", styles["body"]))
        return flowables

    first_value = next(iter(content.values()))
    if isinstance(first_value, KPIResult):
        # kpi.icon is deliberately not included here: KPI_ICONS are
        # emoji, and the base-14 PDF fonts reportlab uses have no
        # emoji glyphs -- printing them would render as broken tofu
        # boxes instead of a clean, professional label.
        rows = [["KPI", "Value"]]
        for kpi in content.values():
            rows.append([kpi.label, kpi.formatted])
    else:
        rows = [["Name", "Revenue"]]

        def _sort_key(item: tuple) -> float:
            value = item[1]
            return value if isinstance(value, (int, float)) else 0

        for name, value in sorted(content.items(), key=_sort_key, reverse=True):
            formatted_value = format_currency(value) if isinstance(value, (int, float)) else str(value)
            rows.append([str(name), formatted_value])

    flowables.append(_styled_table(rows, branding))
    return flowables


def _render_business_insights_section(section: ReportSection, branding: PDFBrandingConfig, styles: dict) -> list:
    """Render a :class:`~utils.insights.BusinessInsights` section as a metrics table."""
    insights: BusinessInsights = section.content
    flowables: list = [_section_heading(section, styles)]

    rows = [["Metric", "Value"]]
    rows.append(["Total Revenue", format_currency(insights.total_revenue)])
    rows.append(["Average Daily Revenue", format_currency(insights.average_daily_revenue)])
    rows.append(["Highest Revenue Day", _format_day(*insights.highest_revenue_day)])
    rows.append(["Lowest Revenue Day", _format_day(*insights.lowest_revenue_day)])
    rows.append(["Total Orders", format_integer(insights.total_orders)])
    rows.append(["Average Orders / Day", f"{insights.average_orders_per_day:,.1f}"])
    rows.append(["Total Transactions", format_integer(insights.total_transactions)])
    rows.append(["Active Sales Days", format_integer(insights.active_sales_days)])

    if insights.product_insights_available:
        rows.append(["Best Product", f"{insights.best_product} ({format_currency(insights.best_product_revenue)})"])
        rows.append(
            ["Worst Product", f"{insights.worst_product} ({format_currency(insights.worst_product_revenue)})"]
        )
        rows.append(["Top 3 Products Share of Revenue", f"{insights.top_product_concentration:.1f}%"])

    if insights.region_insights_available:
        rows.append(["Best Region", f"{insights.best_region} ({format_currency(insights.best_region_revenue)})"])
        rows.append(["Worst Region", f"{insights.worst_region} ({format_currency(insights.worst_region_revenue)})"])

    flowables.append(_styled_table(rows, branding))
    return flowables


def _render_fallback_section(section: ReportSection, branding: PDFBrandingConfig, styles: dict) -> list:
    """Render any section content type with no registered renderer.

    Rather than raising for a content type the PDF Generator doesn't
    yet know how to format specially (e.g. a brand-new section type
    added to the Reporting Service before a matching renderer is
    registered here), fall back to a plain text rendering of its
    ``str()``. This keeps report generation working end to end -- new
    data is simply plainer, never missing.
    """
    return [_section_heading(section, styles), Paragraph(str(section.content), styles["body"])]


def _build_cover_page(report: Report, branding: PDFBrandingConfig, styles: dict) -> list:
    """Build the cover page flowables: logo, title, period, audience, timestamp."""
    flowables: list = []

    logo_added = False
    if branding.logo_path and os.path.isfile(branding.logo_path):
        try:
            flowables.append(Image(branding.logo_path, width=3 * cm, height=3 * cm))
            flowables.append(Spacer(1, 1 * cm))
            logo_added = True
        except Exception:
            # A missing/corrupt logo file is a branding-asset problem,
            # not a report-data problem -- skip it rather than failing
            # the whole report.
            logo_added = False
    if not logo_added:
        flowables.append(Spacer(1, 4 * cm))

    flowables.append(Paragraph(branding.company_name, styles["cover_subtitle"]))
    flowables.append(Paragraph(str(report.metadata.title), styles["cover_title"]))
    if report.metadata.period_label:
        flowables.append(Paragraph(report.metadata.period_label, styles["cover_subtitle"]))
    if report.metadata.prepared_for:
        flowables.append(Paragraph(f"Prepared for: {report.metadata.prepared_for}", styles["cover_meta"]))

    flowables.append(Spacer(1, 1.5 * cm))
    flowables.append(Paragraph(f"Generated on {_format_timestamp(report.metadata.generated_at)}", styles["cover_meta"]))
    if report.metadata.notes:
        flowables.append(Spacer(1, 0.5 * cm))
        flowables.append(Paragraph(report.metadata.notes, styles["cover_meta"]))

    return flowables


def _build_table_of_contents(styles: dict) -> list:
    """Build the table-of-contents page flowables.

    The :class:`TableOfContents` flowable itself is populated with real
    page numbers by reportlab's two-pass ``multiBuild`` mechanism (see
    ``_TOCDocTemplate.afterFlowable`` below), not by this function.
    """
    toc = TableOfContents()
    toc.levelStyles = [styles["toc_entry"]]
    return [Paragraph("Table of Contents", styles["toc_heading"]), Spacer(1, 0.5 * cm), toc]


class _TOCDocTemplate(SimpleDocTemplate):
    """A ``SimpleDocTemplate`` that also records section positions for a ToC.

    A working table of contents with accurate page numbers requires
    reportlab's two-pass ``multiBuild`` mechanism: each time a section
    heading paragraph is placed, its text and current page number are
    recorded via ``notify("TOCEntry", ...)``; ``multiBuild`` then
    re-renders the document until the recorded positions stabilize.
    Used only when ``PDFBrandingConfig.show_table_of_contents`` is
    ``True`` -- the plain :class:`SimpleDocTemplate` is used otherwise.
    """

    def afterFlowable(self, flowable: Flowable) -> None:
        """Record a table-of-contents entry whenever a section heading is placed."""
        if isinstance(flowable, Paragraph) and flowable.style.name == "SectionHeading":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))


def _make_page_decorator(branding: PDFBrandingConfig) -> Callable[[Canvas, object], None]:
    """Build the ``onFirstPage``/``onLaterPages`` callback: footer, page number, watermark."""

    def _decorate(canvas: Canvas, doc: object) -> None:
        canvas.saveState()
        page_width, _ = doc.pagesize

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        footer_text = branding.footer_text or f"{branding.company_name} Sales Intelligence Dashboard"
        canvas.drawString(2 * cm, 1.2 * cm, footer_text)
        if branding.show_page_numbers:
            canvas.drawRightString(page_width - 2 * cm, 1.2 * cm, f"Page {doc.page}")

        if branding.watermark_text:
            canvas.saveState()
            page_width, page_height = doc.pagesize
            canvas.setFont("Helvetica-Bold", 60)
            canvas.setFillColor(colors.Color(0.85, 0.85, 0.85, alpha=0.45))
            canvas.translate(page_width / 2, page_height / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, branding.watermark_text)
            canvas.restoreState()

        canvas.restoreState()

    return _decorate


# ==============================================================================
# PDF Generator Service
# ==============================================================================


class PDFGeneratorService:
    """Converts an assembled :class:`Report` into a professional PDF document.

    Registry-based for section content types (mirroring the pattern
    already used by :class:`~utils.kpi_engine.KPIEngine`,
    :class:`~services.export_service.ExportService`, and
    :class:`~services.reporting_service.ReportingService`); every other
    extension point -- branding, headers/footers, watermark, cover
    page, table of contents -- is a field on :class:`PDFBrandingConfig`
    rather than a code change.

    Example:
        >>> service = PDFGeneratorService()
        >>> result = service.generate_pdf(report)
        >>> result.mime_type
        'application/pdf'

        # Custom branding, no code change required:
        >>> branding = PDFBrandingConfig(
        ...     company_name="NovaMart Retail Group",
        ...     watermark_text="DRAFT",
        ...     show_table_of_contents=True,
        ... )
        >>> result = service.generate_pdf(report, branding=branding)

        # Registering a renderer for a brand-new section content type
        # later, without touching this class:
        >>> def _render_risk_section(section, branding, styles):
        ...     return [_section_heading(section, styles), Paragraph(str(section.content), styles["body"])]
        >>> service.register_content_renderer(RiskAnalysis, _render_risk_section)
    """

    def __init__(self) -> None:
        """Create a PDF Generator Service with the default content renderers."""
        self._content_renderers: dict[type, ContentRenderer] = {}
        self._register_default_content_renderers()

    # ------------------------------------------------------------------
    # Public API -- extensibility
    # ------------------------------------------------------------------
    def register_content_renderer(self, content_type: type, renderer: ContentRenderer) -> None:
        """Register (or override) the renderer used for a section content type.

        Args:
            content_type: The Python type of ``ReportSection.content``
                this renderer handles (e.g. ``dict`` or
                ``BusinessInsights``).
            renderer: A callable matching the :data:`ContentRenderer`
                signature: takes ``(section, branding, styles)``,
                returns a list of reportlab flowables.
        """
        self._content_renderers[content_type] = renderer

    # ------------------------------------------------------------------
    # Public API -- PDF generation
    # ------------------------------------------------------------------
    def generate_pdf(
        self,
        report: Report,
        branding: PDFBrandingConfig | None = None,
        *,
        tenant_context: TenantContext | None = None,
    ) -> PDFResult:
        """Render ``report`` into a PDF document.

        Args:
            report: An already-assembled :class:`Report`, typically
                produced by :meth:`~services.reporting_service.ReportingService.generate_report`.
                Its content is never modified or recalculated.
            branding: Optional presentation/branding options. Defaults
                to :class:`PDFBrandingConfig`'s defaults (cover page and
                page numbers on, no watermark or table of contents).
            tenant_context: The tenant this PDF is scoped to
                (Multi-Tenant Sprint 6.3). Required for the call to
                succeed -- see :func:`~tenancy.context.validate_tenant_context`.
                Rendering itself never varies by tenant; this only
                guarantees every PDF is attributable to, and gated on,
                an active tenant.

        Returns:
            A :class:`PDFResult` with the generated PDF bytes and page count.

        Raises:
            MissingTenantContextError: If no tenant context was supplied.
            InactiveTenantError: If the supplied tenant is not active.
            InvalidReportInputError: If ``report`` isn't a :class:`Report`.
            InvalidBrandingConfigError: If ``branding`` isn't a
                :class:`PDFBrandingConfig` (when provided).
            PDFRenderingError: If rendering a section's content, or
                building the document itself, unexpectedly fails.
        """
        # Sprint 6.4 -- Observability & Monitoring Service: wraps tenant
        # validation + the (unchanged) rendering below so a start,
        # completion/failure, and duration are always recorded, without
        # PDFGeneratorService knowing how or where those events are stored.
        with monitoring_service.time_operation(
            service_name="PDFGeneratorService", operation="generate_pdf", tenant_context=tenant_context
        ):
            validate_tenant_context(tenant_context, service_name="PDFGeneratorService", operation="generate_pdf")

            if not isinstance(report, Report):
                raise InvalidReportInputError(report)
            if branding is None:
                branding = PDFBrandingConfig()
            elif not isinstance(branding, PDFBrandingConfig):
                raise InvalidBrandingConfigError(branding)

            styles = _build_styles(branding)
            story: list = []

            if branding.show_cover_page:
                story.extend(_build_cover_page(report, branding, styles))
                story.append(PageBreak())

            if branding.show_table_of_contents:
                story.extend(_build_table_of_contents(styles))
                story.append(PageBreak())

            if report.is_empty():
                story.append(Paragraph("No data is available for this report.", styles["body"]))
            else:
                for section in report.sections:
                    story.extend(self._render_section(section, branding, styles))
                    story.append(Spacer(1, 0.6 * cm))

            page_size = A4 if branding.page_size.strip().upper() == "A4" else letter
            buffer = BytesIO()
            doc_cls = _TOCDocTemplate if branding.show_table_of_contents else SimpleDocTemplate
            doc = doc_cls(
                buffer,
                pagesize=page_size,
                leftMargin=2 * cm,
                rightMargin=2 * cm,
                topMargin=2 * cm,
                bottomMargin=2 * cm,
                title=str(report.metadata.title),
                author=branding.company_name,
            )
            decorate_page = _make_page_decorator(branding)

            try:
                if branding.show_table_of_contents:
                    doc.multiBuild(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
                else:
                    doc.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
            except PDFGeneratorServiceError:
                raise
            except Exception as exc:  # noqa: BLE001 -- deliberately wrapped, see PDFRenderingError
                raise PDFRenderingError("document", exc) from exc

            return PDFResult(content=buffer.getvalue(), page_count=doc.page)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _render_section(self, section: ReportSection, branding: PDFBrandingConfig, styles: dict) -> list:
        """Dispatch one section to its registered content renderer.

        Args:
            section: The section to render.
            branding: The active branding configuration.
            styles: The paragraph styles built for this PDF.

        Returns:
            A list of reportlab flowables for this section.

        Raises:
            PDFRenderingError: If the renderer raises for any reason.
        """
        renderer = self._content_renderers.get(type(section.content), _render_fallback_section)
        try:
            return renderer(section, branding, styles)
        except Exception as exc:  # noqa: BLE001 -- deliberately wrapped, see PDFRenderingError
            raise PDFRenderingError(section.key, exc) from exc

    def _register_default_content_renderers(self) -> None:
        """Register renderers for the section content types the Reporting Service produces today."""
        self.register_content_renderer(dict, _render_mapping_section)
        self.register_content_renderer(BusinessInsights, _render_business_insights_section)


# A shared, ready-to-use instance -- mirrors
# ``services.export_service.sales_export_service``,
# ``services.reporting_service.sales_reporting_service``, and
# ``services.ai_recommendation_service.sales_ai_recommendation_service``.
# Callers can import this directly instead of constructing their own
# PDFGeneratorService.
sales_pdf_generator_service = PDFGeneratorService()
