"""Executive Report Center for the NovaMart Sales Intelligence Dashboard.

Sprint 6.2 -- Executive Reporting & Export Center, Module 5.

The orchestration layer that ties the four Sprint 6.2 services into one
screen: assemble the report (Reporting Service), review AI-generated
recommendations (AI Recommendation Service), generate/download a PDF
(PDF Generator Service), and export the underlying data (Export
Service). This module has exactly one responsibility -- coordinating
those services and presenting their output -- and deliberately does
nothing else.

The Executive Report Center does NOT:
    - Calculate KPIs (that's ``utils/kpi_engine.py``).
    - Generate business insights (that's ``utils/insights.py``).
    - Generate AI recommendations (that's ``services/ai_recommendation_service.py``).
    - Assemble reports (that's ``services/reporting_service.py``).
    - Generate PDFs (that's ``services/pdf_generator_service.py``).
    - Export files (that's ``services/export_service.py``).
    - Send emails (a future, separate service).

Every one of those is *invoked* here, never re-implemented. Calling
``sales_kpi_engine.calculate_all(df)`` or
``generate_business_insights(df)`` to build the inputs a service needs
is orchestration (the exact integration pattern
``docs/REPORTING_SERVICE.md`` already documents for a future "Reports"
page) -- not "calculating KPIs" in the sense the ticket means, which is
about never *re-deriving* a formula that already lives in ``utils/``.

Architectural approach
-----------------------
This module is an orchestrator over already-built services, so the
design question worth deciding explicitly is *how much state it
should own*. Two things could have gone either way:

1. **Where does the dataset come from?** Unlike the four services
   (which explicitly must not read uploaded files), this ticket's
   "must NOT" list has no such restriction -- because something has to
   own getting a DataFrame onto the screen, and every existing page in
   this app already owns that itself (the Dashboard page renders its
   own Upload Center + Filter Panel rather than reading from some
   shared store). This module follows that same, already-established
   pattern instead of inventing a new one: it renders the same
   Upload Center and Filter Panel components, with distinct widget
   keys, so it works as a standalone page. A caller that already has a
   filtered DataFrame (e.g. a future page that shares state across
   tabs) can pass it in via the optional ``df`` parameter instead, so
   nothing here is duplicated either way.
2. **Why ``st.session_state`` here, when no other module in this app
   uses it?** Streamlit reruns the whole script on every widget
   interaction. Generating a PDF/export happens in reaction to a
   button click on one run; the resulting ``st.download_button`` must
   still have those bytes available on the *next* run (the one that
   actually renders the button) and survive later, unrelated reruns
   (e.g. typing in a branding text box) until the user downloads it or
   generates a new one. That's a one-screen, self-contained need --
   not a shared app-wide store -- so it's kept to two
   module-prefixed keys, invalidated by a small content fingerprint
   whenever the report type or row count changes underneath it.

Future compatibility
---------------------
- **Notification/Email Service:** once generated, the ``PDFResult``/
  ``ExportResult`` already sit in ``st.session_state`` -- adding an
  "Email this report" button is one new call to a future email
  service with those same bytes, not a redesign.
- **Scheduled report generation:** :func:`_build_report_context` and
  the ``generate_report``/``generate_recommendations``/``generate_pdf``
  calls are plain function calls, not entangled in widget callbacks,
  so a future scheduler can call the same sequence headlessly.
- **Report history / saved templates:** the report type and PDF
  branding are already small, serializable objects (a string key and a
  :class:`~services.pdf_generator_service.PDFBrandingConfig`) --
  persisting "the last N generated reports" or "a named branding
  preset" is additive, not a rework of this module.
- **Additional export formats:** the export format selector reads
  ``sales_export_service.supported_formats()`` rather than a
  hard-coded list, so a new format registered on the Export Service
  appears here automatically.
- **Role-based access:** every action (view report, view
  recommendations, generate PDF, export data) is already a distinct,
  independently callable section -- gating one behind a future
  permission check would mean wrapping that section's call, not
  restructuring the module.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from components.analytics import render_business_insights_from_value
from components.empty_state import render_empty_state
from components.filter_panel import render_filter_panel
from components.kpi_cards import render_kpi_cards
from components.tenant_selector import get_active_tenant_context
from components.upload_center import render_upload_center
from monitoring.service import monitoring_service
from services.ai_recommendation_service import (
    AIRecommendationServiceError,
    Recommendation,
    RecommendationContext,
    RecommendationPriority,
    sales_ai_recommendation_service,
)
from services.export_service import ExportServiceError, sales_export_service
from services.pdf_generator_service import PDFBrandingConfig, PDFGeneratorServiceError, sales_pdf_generator_service
from services.reporting_service import (
    Report,
    ReportContext,
    ReportingServiceError,
    ReportMetadata,
    ReportType,
    sales_reporting_service,
)
from tenancy.context import TenantContext, validate_tenant_context
from tenancy.exceptions import TenantContextError
from utils.analytics import calculate_revenue_by_group
from utils.filters import detect_available_filters
from utils.formatting import format_currency
from utils.insights import BusinessInsights, generate_business_insights
from utils.kpi_engine import KPIResult, sales_kpi_engine

# Widget/session-state keys, all prefixed so this module can never
# collide with another page's Upload Center, Filter Panel, or state.
_UPLOAD_KEY = "executive_report_center_upload"
_FILTER_KEY_PREFIX = "executive_report_center_filters"
_PDF_RESULT_STATE_KEY = "executive_report_center_pdf_result"
_EXPORT_RESULT_STATE_KEY = "executive_report_center_export_result"

_REPORT_TYPE_ICONS: dict[str, str] = {
    ReportType.EXECUTIVE.value: "🧾",
    ReportType.WEEKLY.value: "🗓️",
    ReportType.MONTHLY.value: "📅",
    ReportType.REGIONAL.value: "🌍",
}

_PRIORITY_BADGES: dict[RecommendationPriority, str] = {
    RecommendationPriority.HIGH: "🔴 High priority",
    RecommendationPriority.MEDIUM: "🟡 Medium priority",
    RecommendationPriority.LOW: "🟢 Low priority",
}

# Export formats shown in a sensible, de-duplicated order ("excel" and
# "xlsx" both resolve to the same exporter -- no need to show both). Any
# future format registered on the Export Service that isn't already
# listed here is appended automatically, so new formats need no change here.
_PREFERRED_EXPORT_FORMAT_ORDER: tuple[str, ...] = ("csv", "excel", "json")


def render_executive_report_center(
    df: pd.DataFrame | None = None, *, tenant_context: TenantContext | None = None
) -> None:
    """Render the full Executive Report Center screen.

    Args:
        df: An already-filtered dataset to build the report from. If
            not given, this component renders its own Upload Center
            and Filter Panel (mirroring the Dashboard page) to obtain
            one, so it can be dropped onto a page on its own.
        tenant_context: The active tenant this screen is scoped to
            (Multi-Tenant Sprint 6.3). If not given, resolved from the
            current session via
            :func:`~components.tenant_selector.get_active_tenant_context`
            (the same tenant the sidebar's selector already set),
            mirroring how ``df`` falls back to self-acquisition when
            not supplied. Validated once, up front, before anything --
            including the Upload Center -- is rendered: a missing or
            inactive tenant stops the whole screen with a single,
            business-friendly message rather than failing partway
            through one tab.
    """
    tenant_context = tenant_context if tenant_context is not None else get_active_tenant_context()

    st.markdown('<p class="nm-section-title">📑 Executive Report Center</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Assemble an executive report, review AI-generated '
        "recommendations, and export it as a PDF, CSV, Excel, or JSON file.</p>",
        unsafe_allow_html=True,
    )

    try:
        tenant = validate_tenant_context(
            tenant_context, service_name="ExecutiveReportCenter", operation="render_executive_report_center"
        )
    except TenantContextError as exc:
        st.error(str(exc), icon="🔒")
        return

    st.caption(f"Organization: **{tenant.display_name}**")

    # Sprint 6.4 -- Observability & Monitoring Service: wraps the
    # (unchanged) screen-assembly flow below so a start, completion, and
    # duration are always recorded for the Executive Report Center
    # itself -- distinct from the per-service events each service call
    # inside it already records -- without this module knowing how or
    # where those events are stored. Tenant context is already validated
    # above, so this only ever runs for an active tenant.
    with monitoring_service.time_operation(
        service_name="ExecutiveReportCenter",
        operation="render_executive_report_center",
        tenant_context=tenant_context,
    ):
        working_df = df if df is not None else _acquire_dataset(tenant_context)
        if working_df is None or working_df.empty:
            render_empty_state(
                "Upload a dataset above to build an executive report, review AI "
                "recommendations, and generate PDF/CSV/Excel/JSON exports.",
                icon="📑",
            )
            return

        st.divider()
        report_type, prepared_for = _render_report_controls()

        context = _build_report_context(working_df, report_type, prepared_for, tenant_context)
        try:
            report = sales_reporting_service.generate_report(report_type, context, tenant_context=tenant_context)
        except ReportingServiceError as exc:
            st.error(f"Unable to assemble the report: {exc}", icon="⚠️")
            return

        report_tab, recommendations_tab, pdf_tab, export_tab = st.tabs(
            ["🧾 Executive Report", "🤖 AI Recommendations", "📄 PDF Export", "📤 Data Export"]
        )
        with report_tab:
            _render_report_tab(report)
        with recommendations_tab:
            _render_recommendations_tab(context, report, tenant_context)
        with pdf_tab:
            _render_pdf_export_tab(report, row_count=len(working_df), tenant_context=tenant_context)
        with export_tab:
            _render_data_export_tab(working_df, tenant_context)


# ==============================================================================
# Data acquisition -- reuses the existing Upload Center + Filter Panel as-is
# ==============================================================================


def _acquire_dataset(tenant_context: TenantContext) -> pd.DataFrame | None:
    """Obtain a filtered dataset via the existing Upload Center + Filter Panel.

    Reuses the same two components the Dashboard page already uses,
    with widget keys scoped to this module, so both pages can be open
    in the same session without key collisions. Neither component's
    upload/validation/filtering logic is reimplemented here.

    Args:
        tenant_context: The active tenant this upload belongs to.

    Returns:
        The filtered DataFrame, or ``None`` if nothing has been
        uploaded yet (or the uploaded file failed validation).
    """
    uploaded_df = render_upload_center(
        title="Report Data",
        description="Upload the CSV or Excel file this report should be built from.",
        key=_UPLOAD_KEY,
        tenant_context=tenant_context,
    )
    if uploaded_df is None:
        return None

    st.divider()
    return render_filter_panel(uploaded_df, key_prefix=_FILTER_KEY_PREFIX)


# ==============================================================================
# Report controls + context assembly
# ==============================================================================


def _render_report_controls() -> tuple[str, str]:
    """Render the report type selector and optional "prepared for" field.

    Returns:
        A ``(report_type_key, prepared_for)`` tuple. ``report_type_key``
        is always one of :meth:`~services.reporting_service.ReportingService.report_types`,
        including any custom report type registered later.
        ``prepared_for`` is an empty string when left blank.
    """
    control_col, audience_col = st.columns([2, 3])
    with control_col:
        report_type = st.selectbox(
            "Report type",
            options=sales_reporting_service.report_types(),
            format_func=_report_type_label,
            key="executive_report_center_report_type",
        )
    with audience_col:
        prepared_for = st.text_input(
            "Prepared for (optional)",
            placeholder="e.g. Board of Directors",
            key="executive_report_center_prepared_for",
        )
    return report_type, prepared_for


def _report_type_label(report_type_key: str) -> str:
    """Format a report type key for display (e.g. ``"executive"`` -> ``"🧾 Executive Report"``).

    Works for any report type, including one registered later via
    :meth:`~services.reporting_service.ReportingService.define_report`
    that has no entry in :data:`_REPORT_TYPE_ICONS` -- it just falls
    back to a generic icon instead of failing.
    """
    icon = _REPORT_TYPE_ICONS.get(report_type_key, "📄")
    title = report_type_key.replace("_", " ").title()
    return f"{icon} {title} Report"


def _build_report_context(
    df: pd.DataFrame, report_type_key: str, prepared_for: str, tenant_context: TenantContext
) -> ReportContext:
    """Build a :class:`ReportContext` by invoking existing calculation entry points.

    Every value assembled here comes from a function that already
    existed before this module -- ``sales_kpi_engine.calculate_all``,
    ``generate_business_insights``, and ``calculate_revenue_by_group``
    -- exactly the integration this app's Reporting Service docs
    already describe. This function only calls them and packages their
    results; it never derives a KPI or insight formula itself.

    Args:
        df: The (already filtered) dataset to build the report from.
        report_type_key: The selected report type, used only to build a
            matching metadata title when ``prepared_for`` is set.
        prepared_for: Optional audience text from the report controls.
        tenant_context: The active tenant this context is scoped to.

    Returns:
        A populated :class:`ReportContext`.
    """
    kpi_results = sales_kpi_engine.calculate_all(df, tenant_context=tenant_context)
    business_insights = generate_business_insights(df, tenant_context=tenant_context)

    available = detect_available_filters(df, columns={"product": "product", "region": "region"})
    regional_summary = calculate_revenue_by_group(df, "region") if available["region"].available else None
    product_summary = calculate_revenue_by_group(df, "product") if available["product"].available else None

    return ReportContext(
        kpi_results=kpi_results,
        business_insights=business_insights,
        regional_summary=regional_summary,
        product_summary=product_summary,
        metadata=_build_report_metadata(report_type_key, prepared_for),
    )


def _build_report_metadata(report_type_key: str, prepared_for: str) -> ReportMetadata | None:
    """Build custom metadata only when there's something to customize.

    Returns ``None`` when ``prepared_for`` is blank so
    :meth:`~services.reporting_service.ReportingService.generate_report`
    supplies its own correctly-titled default metadata instead of this
    module needing to duplicate that title logic.
    """
    if not prepared_for.strip():
        return None
    title = f"{report_type_key.replace('_', ' ').title()} Report"
    return ReportMetadata(title=title, generated_at=datetime.now(timezone.utc), prepared_for=prepared_for.strip())


def _report_type_key(report: Report) -> str:
    """Return a report's type as a plain string, regardless of ReportType vs. str."""
    return report.report_type.value if isinstance(report.report_type, ReportType) else str(report.report_type)


# ==============================================================================
# Tab 1 -- Executive Report
# ==============================================================================


def _render_report_tab(report: Report) -> None:
    """Render the assembled report's metadata and every section, in order."""
    _render_report_header(report)

    if report.is_empty():
        render_empty_state(
            "This report type has no data available for the current dataset and filters.",
            icon="🧾",
        )
        return

    for section in report.sections:
        st.markdown(f"#### {section.title}")
        _render_section_content(section.content)
        st.divider()


def _render_report_header(report: Report) -> None:
    """Show the report's title, generation time, audience, and period as a caption."""
    meta = report.metadata
    st.markdown(f"### {meta.title}")

    details = [f"Generated {meta.generated_at:%B %d, %Y at %H:%M UTC}"]
    if meta.period_label:
        details.append(meta.period_label)
    if meta.prepared_for:
        details.append(f"Prepared for: {meta.prepared_for}")
    st.caption("  ·  ".join(details))


def _render_section_content(content: object) -> None:
    """Render one section's already-computed content, dispatching on its type.

    Mirrors the dispatch-by-content-type approach used by
    :mod:`services.pdf_generator_service` for the same reason: a
    section's content shape (KPI results, business insights, a
    name -> revenue mapping) is stable regardless of which report type
    or future section key produced it.
    """
    if isinstance(content, dict) and content and isinstance(next(iter(content.values())), KPIResult):
        render_kpi_cards(content)
    elif isinstance(content, BusinessInsights):
        render_business_insights_from_value(content)
    elif isinstance(content, dict):
        _render_group_summary(content)
    else:
        st.write(content)


def _render_group_summary(summary: dict[str, float]) -> None:
    """Render a name -> revenue mapping (regional/product summary) as a table + bar chart."""
    if not summary:
        render_empty_state("No data available for this section.", icon="📄")
        return

    sorted_items = sorted(summary.items(), key=lambda item: item[1], reverse=True)
    names = [name for name, _ in sorted_items]
    values = [value for _, value in sorted_items]
    chart_table = pd.DataFrame({"Revenue": values}, index=names)

    table_col, chart_col = st.columns([2, 3])
    with table_col:
        display_table = chart_table.copy()
        display_table["Revenue"] = display_table["Revenue"].apply(format_currency)
        st.dataframe(display_table, use_container_width=True)
    with chart_col:
        st.bar_chart(chart_table)


# ==============================================================================
# Tab 2 -- AI Recommendations
# ==============================================================================


def _render_recommendations_tab(context: ReportContext, report: Report, tenant_context: TenantContext) -> None:
    """Render AI-generated recommendations built from the same context as the report."""
    st.caption(
        "Generated by the AI Recommendation Service from the same KPI results "
        "and business insights used to build the report."
    )

    recommendation_context = RecommendationContext(
        kpi_results=context.kpi_results,
        business_insights=context.business_insights,
        report=report,
    )
    try:
        batch = sales_ai_recommendation_service.generate_recommendations(
            recommendation_context, tenant_context=tenant_context
        )
    except AIRecommendationServiceError as exc:
        st.error(f"Unable to generate AI recommendations: {exc}", icon="⚠️")
        return

    st.caption(f"Provider: **{batch.provider_name}**")

    if batch.is_empty():
        render_empty_state("No recommendations for the current data.", icon="🤖")
        return

    for recommendation in batch.highest_priority_first():
        _render_recommendation_card(recommendation)


def _render_recommendation_card(recommendation: Recommendation) -> None:
    """Render a single recommendation as a bordered card."""
    badge = _PRIORITY_BADGES.get(recommendation.priority, str(recommendation.priority.value).title())
    with st.container(border=True):
        st.markdown(f"**{recommendation.title}**")
        st.caption(badge if recommendation.category is None else f"{badge}  ·  {recommendation.category.title()}")
        st.write(recommendation.observation)
        st.caption(f"Suggested action: {recommendation.suggested_action}")


# ==============================================================================
# Tab 3 -- PDF Export
# ==============================================================================


def _render_pdf_export_tab(report: Report, row_count: int, tenant_context: TenantContext) -> None:
    """Render PDF branding options, a Generate button, and the resulting download."""
    st.caption("Generated by the PDF Generator Service from the report above.")

    with st.expander("Branding options"):
        company_name = st.text_input(
            "Company name", value="NovaMart", key="executive_report_center_pdf_company"
        )
        watermark_text = st.text_input(
            "Watermark text (optional)", value="", key="executive_report_center_pdf_watermark"
        )
        show_table_of_contents = st.checkbox(
            "Include table of contents", value=False, key="executive_report_center_pdf_toc"
        )

    if st.button("Generate PDF", key="executive_report_center_generate_pdf"):
        branding = PDFBrandingConfig(
            company_name=company_name.strip() or "NovaMart",
            watermark_text=watermark_text.strip() or None,
            show_table_of_contents=show_table_of_contents,
        )
        try:
            pdf_result = sales_pdf_generator_service.generate_pdf(
                report, branding=branding, tenant_context=tenant_context
            )
            st.session_state[_PDF_RESULT_STATE_KEY] = (_cache_tag(report, row_count), pdf_result)
        except PDFGeneratorServiceError as exc:
            st.session_state.pop(_PDF_RESULT_STATE_KEY, None)
            st.error(f"Unable to generate the PDF: {exc}", icon="⚠️")

    stored = st.session_state.get(_PDF_RESULT_STATE_KEY)
    if stored is not None and stored[0] == _cache_tag(report, row_count):
        _, pdf_result = stored
        st.success(f"PDF ready -- {pdf_result.page_count} page(s).", icon="✅")
        st.download_button(
            "Download PDF",
            data=pdf_result.content,
            file_name=f"novamart_{_report_type_key(report)}_report.pdf",
            mime=pdf_result.mime_type,
            key="executive_report_center_download_pdf",
        )
    elif stored is not None:
        # The report type or underlying data changed since this PDF was
        # generated -- drop the stale artifact rather than offering a
        # download that no longer matches what's on screen.
        st.session_state.pop(_PDF_RESULT_STATE_KEY, None)


# ==============================================================================
# Tab 4 -- Data Export
# ==============================================================================


def _render_data_export_tab(df: pd.DataFrame, tenant_context: TenantContext) -> None:
    """Render an export-format selector, an Export button, and the resulting download."""
    st.caption("Generated by the Export Service from the filtered dataset used to build the report.")

    export_format = st.selectbox(
        "Export format",
        options=_display_export_formats(),
        format_func=str.upper,
        key="executive_report_center_export_format",
    )

    if st.button("Export data", key="executive_report_center_export_button"):
        try:
            export_result = sales_export_service.export(df, export_format, tenant_context=tenant_context)
            st.session_state[_EXPORT_RESULT_STATE_KEY] = ((export_format, len(df)), export_result)
        except ExportServiceError as exc:
            st.session_state.pop(_EXPORT_RESULT_STATE_KEY, None)
            st.error(f"Unable to export the data: {exc}", icon="⚠️")

    stored = st.session_state.get(_EXPORT_RESULT_STATE_KEY)
    if stored is not None and stored[0] == (export_format, len(df)):
        _, export_result = stored
        st.success(f"Export ready -- {len(export_result.content):,} bytes.", icon="✅")
        st.download_button(
            "Download file",
            data=export_result.content,
            file_name=f"novamart_sales_data.{export_result.file_extension}",
            mime=export_result.mime_type,
            key="executive_report_center_download_export",
        )
    elif stored is not None:
        st.session_state.pop(_EXPORT_RESULT_STATE_KEY, None)


def _display_export_formats() -> tuple[str, ...]:
    """Return export format keys for the selector, de-duplicating known aliases.

    ``"excel"`` and ``"xlsx"`` both resolve to the same exporter, so
    only ``"excel"`` is shown. Any future format registered on the
    Export Service is appended automatically -- no change needed here
    when a new format arrives.
    """
    available = sales_export_service.supported_formats()
    ordered = [fmt for fmt in _PREFERRED_EXPORT_FORMAT_ORDER if fmt in available]
    extra = sorted(fmt for fmt in available if fmt not in _PREFERRED_EXPORT_FORMAT_ORDER and fmt != "xlsx")
    return tuple(ordered + extra)


def _cache_tag(report: Report, row_count: int) -> tuple:
    """Build a lightweight fingerprint used to detect a stale generated PDF.

    Not a full content hash -- comparing the report type, section keys,
    and row count catches the common cases (switching report type,
    uploading a new file, changing a filter) without the cost of
    hashing the whole report. Two distinct datasets with the exact same
    row count and section keys could in principle collide; a full
    content hash would be a one-line change here if that ever matters.
    """
    return (_report_type_key(report), row_count, report.section_keys())
