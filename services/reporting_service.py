"""Reporting Service for the NovaMart Sales Intelligence Dashboard.

Sprint 6.2 -- Executive Reporting & Export Center, Module 2.

Assembles already-computed business data -- KPI results, business
insights, regional summaries, product summaries -- into a structured
:class:`Report` object for downstream consumers (a future Export
Service call, a PDF renderer, or a Streamlit "Reports" page). This
module has exactly one responsibility -- organizing information into a
well-defined report structure -- and deliberately does nothing else.

The Reporting Service does NOT:
    - Read uploaded files (that's ``utils/data_loader.py``).
    - Calculate KPIs (that's ``utils/kpi_engine.py`` / ``utils/calculations.py``).
    - Generate business insights (that's ``utils/insights.py``).
    - Apply filters (that's ``utils/filters.py``).
    - Export CSV/Excel/JSON (that's ``services/export_service.py``).
    - Generate PDFs (a future, separate service).
    - Send emails (a future, separate service).

It is an orchestrator, not a calculator: every number it puts into a
report was computed elsewhere and simply handed to it via
:class:`ReportContext`.

Architecture
------------
Two registries, configured once in the constructor and extensible
afterward without subclassing (the same pattern already used by
:class:`~utils.kpi_engine.KPIEngine` and
:class:`~services.export_service.ExportService`):

- **Section builders** (``register_section_builder``): a function that
  turns one piece of :class:`ReportContext` data into a
  :class:`ReportSection`, or returns ``None`` if that data wasn't
  provided.
- **Report definitions** (``define_report``): for each
  :class:`ReportType`, an ordered list of :class:`SectionSpec` values
  saying which sections that report type is built from, in what order,
  and whether each one is required.

Adding a brand-new section (Risk Analysis, AI Recommendations,
Forecasts, Charts, ...) later means: add one new optional field to
:class:`ReportContext`, write one new ``_build_<name>_section``
function, and register it. Adding a brand-new report type
(a department-specific report, for example) means: add one new
:class:`ReportType` member and one ``define_report`` call listing which
already-registered sections it uses. Neither change touches
:class:`ReportingService`'s assembly logic itself.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Mapping

from monitoring.service import monitoring_service
from tenancy.context import TenantContext, validate_tenant_context
from utils.insights import BusinessInsights
from utils.kpi_engine import KPIResult


# ==============================================================================
# Exceptions
# ==============================================================================


class ReportingServiceError(Exception):
    """Base class for every error raised by the Reporting Service.

    Catch this type in calling code to handle *any* report-assembly
    failure with a single ``except`` clause, e.g.::

        try:
            report = sales_reporting_service.generate_report("executive", context)
        except ReportingServiceError as exc:
            st.error(str(exc))
    """


class InvalidReportContextError(ReportingServiceError):
    """Raised when ``context`` isn't a :class:`ReportContext` instance."""

    def __init__(self, received: object) -> None:
        """Build a user-friendly "invalid context" message.

        Args:
            received: The value that was passed in place of a
                :class:`ReportContext`.
        """
        self.received_type = type(received)
        message = (
            "ReportingService requires a ReportContext instance, got "
            f"'{self.received_type.__name__}' instead."
        )
        super().__init__(message)


class InvalidReportTypeError(ReportingServiceError):
    """Raised when ``report_type`` isn't a :class:`ReportType` or a string."""

    def __init__(self, received: object) -> None:
        """Build a user-friendly "invalid report type" message.

        Args:
            received: The value that was passed in place of a report
                type.
        """
        self.received_type = type(received)
        message = (
            "ReportingService requires a ReportType (or its string "
            f"value) as the report type, got '{self.received_type.__name__}' instead."
        )
        super().__init__(message)


class UnknownReportTypeError(ReportingServiceError):
    """Raised when ``report_type`` doesn't match any defined report."""

    def __init__(self, requested_type: str, known_types: tuple[str, ...]) -> None:
        """Build a user-friendly "unknown report type" message.

        Args:
            requested_type: The report type string that was requested.
            known_types: The report type values currently defined.
        """
        self.requested_type = requested_type
        known_list = ", ".join(sorted(known_types))
        message = f"'{requested_type}' is not a known report type. Known report types are: {known_list}."
        super().__init__(message)


class UnknownReportSectionError(ReportingServiceError):
    """Raised when a report definition references an unregistered section.

    This is a configuration error (a report type was defined with a
    section key that no builder was ever registered for), not a data
    problem, so it is kept distinct from :class:`MissingReportDataError`.
    """

    def __init__(self, section_key: str, report_type: str) -> None:
        """Build a message identifying the missing builder registration.

        Args:
            section_key: The section key with no registered builder.
            report_type: The report type whose definition referenced it.
        """
        self.section_key = section_key
        self.report_type = report_type
        message = (
            f"Report type '{report_type}' is configured to include section "
            f"'{section_key}', but no section builder is registered under that "
            "key. Call register_section_builder() before defining the report."
        )
        super().__init__(message)


class MissingReportDataError(ReportingServiceError):
    """Raised when a required section has no data in the given context."""

    def __init__(self, report_type: str, section_key: str) -> None:
        """Build a message identifying which required data was missing.

        Args:
            report_type: The report type being generated.
            section_key: The required section whose data was absent.
        """
        self.report_type = report_type
        self.section_key = section_key
        message = (
            f"Cannot generate a '{report_type}' report: the required "
            f"'{section_key}' section has no data in the provided ReportContext."
        )
        super().__init__(message)


# ==============================================================================
# Report type
# ==============================================================================


class ReportType(str, Enum):
    """The report types this module supports out of the box.

    A plain ``str`` subclass so a ``ReportType`` member compares equal
    to, and can be constructed from, its underlying string
    (``ReportType("executive") is ReportType.EXECUTIVE``), which keeps
    call sites that receive a report type as a UI dropdown value simple.
    """

    EXECUTIVE = "executive"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    REGIONAL = "regional"


# The set of report type values ReportType already defines. Used to
# decide whether a resolved report type key should be returned as a
# real ReportType member or as a plain string (see
# ReportingService.generate_report) -- kept as a module-level constant
# so it's computed once rather than on every call.
_KNOWN_REPORT_TYPE_VALUES: frozenset[str] = frozenset(rt.value for rt in ReportType)


# ==============================================================================
# Value objects
# ==============================================================================


@dataclass(frozen=True)
class ReportMetadata:
    """Descriptive information about a report, separate from its content.

    Attributes:
        title: Display title, e.g. ``"Executive Report"``.
        generated_at: When the report was assembled (UTC).
        period_label: Optional human-readable period description, e.g.
            ``"Week of Jul 1-7, 2026"``.
        prepared_for: Optional audience/recipient description.
        notes: Optional free-text notes about the report.
    """

    title: str
    generated_at: datetime
    period_label: str | None = None
    prepared_for: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ReportSection:
    """One section of an assembled report.

    Attributes:
        key: Stable identifier matching the section builder that
            produced it (e.g. ``"kpi_summary"``).
        title: Human-readable section heading.
        content: The section's data, passed through unchanged from
            :class:`ReportContext` (e.g. a ``dict[str, KPIResult]`` or
            a :class:`~utils.insights.BusinessInsights` instance). The
            Reporting Service never transforms this data -- only
            organizes it -- so downstream consumers see exactly what
            the originating service computed.
        order: Zero-based position of this section within its report,
            assigned by :meth:`ReportingService.generate_report`.
    """

    key: str
    title: str
    content: object
    order: int


@dataclass(frozen=True)
class Report:
    """A fully assembled, structured report ready for a downstream consumer.

    Attributes:
        report_type: Which report type this is.
        metadata: Descriptive information about the report.
        sections: The report's sections, in display order. Optional
            sections whose data wasn't available in the
            :class:`ReportContext` are simply absent from this tuple.
    """

    report_type: ReportType | str
    metadata: ReportMetadata
    sections: tuple[ReportSection, ...]

    def get_section(self, key: str) -> ReportSection | None:
        """Look up a section by key.

        Args:
            key: The section key to find (e.g. ``"kpi_summary"``).

        Returns:
            The matching :class:`ReportSection`, or ``None`` if this
            report doesn't include a section with that key.
        """
        for section in self.sections:
            if section.key == key:
                return section
        return None

    def section_keys(self) -> tuple[str, ...]:
        """Return the keys of every section included in this report, in order."""
        return tuple(section.key for section in self.sections)

    def is_empty(self) -> bool:
        """Return ``True`` if this report has no sections at all.

        A report can end up empty if every one of its sections was
        optional and none of the relevant data was present in the
        :class:`ReportContext`. Downstream consumers can check this to
        show a "nothing to report" state instead of an empty document.
        """
        return len(self.sections) == 0


@dataclass(frozen=True)
class ReportContext:
    """Bundles already-computed business data for the Reporting Service.

    Every field is optional because different report types need
    different inputs (a Regional Report needs ``regional_summary``; a
    Weekly Report may not). **None of this data is computed by the
    Reporting Service** -- it is produced elsewhere and simply handed
    in here:

    Attributes:
        kpi_results: KPI results keyed by KPI key, exactly as returned
            by :meth:`~utils.kpi_engine.KPIEngine.calculate_all`.
        business_insights: A :class:`~utils.insights.BusinessInsights`
            value object, exactly as returned by
            :func:`~utils.insights.generate_business_insights`.
        regional_summary: A metric (typically revenue) keyed by region
            name, e.g. from
            ``utils.analytics.calculate_revenue_by_group(df, "region")``.
            Accepts a plain mapping or anything exposing ``.items()``
            (a pandas ``Series`` works without this module importing
            pandas).
        product_summary: Same shape as ``regional_summary``, keyed by
            product name.
        metadata: Report metadata (title, period, audience). If not
            provided, :meth:`ReportingService.generate_report` fills in
            a sensible default automatically.
    """

    kpi_results: Mapping[str, KPIResult] | None = None
    business_insights: BusinessInsights | None = None
    regional_summary: object | None = None
    product_summary: object | None = None
    metadata: ReportMetadata | None = None


# ==============================================================================
# Section definitions
# ==============================================================================


@dataclass(frozen=True)
class SectionSpec:
    """Describes one section a report type includes.

    Attributes:
        key: The section builder key (must match a key registered via
            :meth:`ReportingService.register_section_builder`).
        required: If ``True``, missing data for this section raises
            :class:`MissingReportDataError`. If ``False``, the section
            is silently omitted from the assembled report when its
            data is absent from the :class:`ReportContext`.
    """

    key: str
    required: bool = False


# A section builder inspects ReportContext and either returns the
# ReportSection it can build, or None if the data it needs wasn't
# provided. Builders never decide whether missing data is an error --
# that's ReportingService's job, based on each report type's SectionSpec.
SectionBuilder = Callable[[ReportContext], "ReportSection | None"]

_SECTION_TITLES: dict[str, str] = {
    "kpi_summary": "Key Performance Indicators",
    "business_insights": "Business Insights",
    "regional_summary": "Regional Summary",
    "product_summary": "Product Summary",
}

_DEFAULT_REPORT_TITLES: dict["ReportType", str] = {
    ReportType.EXECUTIVE: "Executive Report",
    ReportType.WEEKLY: "Weekly Report",
    ReportType.MONTHLY: "Monthly Report",
    ReportType.REGIONAL: "Regional Report",
}


def _normalize_mapping(value: object) -> dict:
    """Coerce a mapping-like value into a plain ``dict``.

    Accepts ``None`` (returns ``{}``), any object exposing ``.items()``
    (covers ``dict`` and pandas ``Series`` alike without importing
    pandas here), or a plain iterable of key/value pairs.

    Args:
        value: The mapping-like value to normalize.

    Returns:
        A plain ``dict``, empty if ``value`` was ``None`` or empty.
    """
    if value is None:
        return {}
    if hasattr(value, "items"):
        return dict(value.items())
    return dict(value)


def _build_kpi_summary_section(context: ReportContext) -> ReportSection | None:
    """Build the KPI Summary section from ``context.kpi_results``."""
    if not context.kpi_results:
        return None
    return ReportSection(
        key="kpi_summary",
        title=_SECTION_TITLES["kpi_summary"],
        content=dict(context.kpi_results),
        order=0,
    )


def _build_business_insights_section(context: ReportContext) -> ReportSection | None:
    """Build the Business Insights section from ``context.business_insights``."""
    if context.business_insights is None:
        return None
    return ReportSection(
        key="business_insights",
        title=_SECTION_TITLES["business_insights"],
        content=context.business_insights,
        order=0,
    )


def _build_regional_summary_section(context: ReportContext) -> ReportSection | None:
    """Build the Regional Summary section from ``context.regional_summary``."""
    regional = _normalize_mapping(context.regional_summary)
    if not regional:
        return None
    return ReportSection(
        key="regional_summary",
        title=_SECTION_TITLES["regional_summary"],
        content=regional,
        order=0,
    )


def _build_product_summary_section(context: ReportContext) -> ReportSection | None:
    """Build the Product Summary section from ``context.product_summary``."""
    product = _normalize_mapping(context.product_summary)
    if not product:
        return None
    return ReportSection(
        key="product_summary",
        title=_SECTION_TITLES["product_summary"],
        content=product,
        order=0,
    )


def _default_metadata(report_type: ReportType | str) -> ReportMetadata:
    """Build fallback metadata when a :class:`ReportContext` doesn't supply any."""
    if isinstance(report_type, ReportType):
        title = _DEFAULT_REPORT_TITLES.get(report_type, f"{report_type.value.title()} Report")
    else:
        title = f"{str(report_type).title()} Report"
    return ReportMetadata(title=title, generated_at=datetime.now(timezone.utc))


# ==============================================================================
# Reporting Service
# ==============================================================================


class ReportingService:
    """Assembles already-computed business data into structured reports.

    Two registries make this class extensible without modification
    (Open/Closed Principle), mirroring the pattern already established
    by :class:`~utils.kpi_engine.KPIEngine` and
    :class:`~services.export_service.ExportService`:

    - :meth:`register_section_builder` adds a new kind of section.
    - :meth:`define_report` declares which sections (and in what order,
      required or optional) make up a report type.

    Example:
        >>> service = ReportingService()
        >>> context = ReportContext(kpi_results=my_kpis, business_insights=my_insights)
        >>> report = service.generate_report("executive", context)
        >>> report.section_keys()
        ('kpi_summary', 'business_insights')

        # Adding a brand-new section later, without touching this class:
        >>> def _build_risk_section(ctx: ReportContext) -> ReportSection | None:
        ...     if ctx.risk_analysis is None:  # a new ReportContext field
        ...         return None
        ...     return ReportSection("risk_analysis", "Risk Analysis", ctx.risk_analysis, 0)
        >>> service.register_section_builder("risk_analysis", _build_risk_section)
        >>> service.define_report(
        ...     ReportType.EXECUTIVE,
        ...     (SectionSpec("kpi_summary", required=True), SectionSpec("risk_analysis")),
        ... )
    """

    def __init__(self) -> None:
        """Create a Reporting Service with the default sections and report types."""
        self._section_builders: dict[str, SectionBuilder] = {}
        self._report_definitions: dict[str, tuple[SectionSpec, ...]] = {}
        self._register_default_section_builders()
        self._define_default_reports()

    # ------------------------------------------------------------------
    # Public API -- extensibility
    # ------------------------------------------------------------------
    def register_section_builder(self, key: str, builder: SectionBuilder) -> None:
        """Register (or override) the builder used for a section key.

        Args:
            key: The section key report definitions will reference
                (e.g. ``"risk_analysis"``).
            builder: A callable matching the :data:`SectionBuilder`
                signature: takes a :class:`ReportContext`, returns a
                :class:`ReportSection` or ``None`` if its data is absent.
        """
        self._section_builders[key] = builder

    def define_report(self, report_type: ReportType | str, sections: tuple[SectionSpec, ...]) -> None:
        """Define (or redefine) which sections make up a report type.

        ``report_type`` isn't limited to the four built-in
        :class:`ReportType` members -- passing any other string (e.g.
        ``"department"``) defines a brand-new report type on the fly,
        which is how department-specific or other future report types
        can be added without changing :class:`ReportType` or this class.

        Calling this with an already-defined report type replaces its
        definition, which makes it easy to customize a built-in report
        type's section order without subclassing.

        Args:
            report_type: The report type being defined -- a
                :class:`ReportType` member or any string key.
            sections: An ordered tuple of :class:`SectionSpec` values
                describing which sections this report type includes,
                in display order, and whether each is required.
        """
        key = self._normalize_report_type_key(report_type)
        self._report_definitions[key] = sections

    def report_types(self) -> tuple[str, ...]:
        """Return every report type currently defined.

        Returns:
            A sorted tuple of report type keys, e.g.
            ``("executive", "monthly", "regional", "weekly")``.
        """
        return tuple(sorted(self._report_definitions))

    # ------------------------------------------------------------------
    # Public API -- report generation
    # ------------------------------------------------------------------
    def generate_report(
        self,
        report_type: ReportType | str,
        context: ReportContext,
        *,
        tenant_context: TenantContext | None = None,
    ) -> Report:
        """Assemble a :class:`Report` of the requested type from ``context``.

        Args:
            report_type: Which report to build, e.g. ``ReportType.EXECUTIVE``
                or the equivalent string ``"executive"`` (case-insensitive).
            context: The already-computed business data to assemble.
            tenant_context: The tenant this report is scoped to
                (Multi-Tenant Sprint 6.3). Required for the call to
                succeed -- see :func:`~tenancy.context.validate_tenant_context`.
                Report assembly itself never varies by tenant; this
                only guarantees every report is attributable to, and
                gated on, an active tenant.

        Returns:
            A fully assembled :class:`Report`. Optional sections whose
            data wasn't present in ``context`` are simply omitted; the
            report may be empty (see :meth:`Report.is_empty`) if every
            section for this report type was optional and none of them
            had data.

        Raises:
            MissingTenantContextError: If no tenant context was supplied.
            InactiveTenantError: If the supplied tenant is not active.
            InvalidReportContextError: If ``context`` isn't a
                :class:`ReportContext` instance.
            InvalidReportTypeError: If ``report_type`` isn't a
                :class:`ReportType` or a string.
            UnknownReportTypeError: If ``report_type`` doesn't match any
                report type defined via :meth:`define_report`.
            UnknownReportSectionError: If the report type's definition
                references a section key with no registered builder
                (a configuration error, not a data problem).
            MissingReportDataError: If a *required* section has no data
                in ``context``.
        """
        # Sprint 6.4 -- Observability & Monitoring Service: wraps tenant
        # validation + the (unchanged) assembly below so a start,
        # completion/failure, and duration are always recorded, without
        # ReportingService knowing how or where those events are stored.
        with monitoring_service.time_operation(
            service_name="ReportingService", operation="generate_report", tenant_context=tenant_context
        ):
            validate_tenant_context(tenant_context, service_name="ReportingService", operation="generate_report")

            if not isinstance(context, ReportContext):
                raise InvalidReportContextError(context)

            key = self._normalize_report_type_key(report_type)
            section_specs = self._report_definitions.get(key)
            if section_specs is None:
                raise UnknownReportTypeError(key, tuple(self._report_definitions))

            # Prefer returning a real ReportType member for the four
            # built-ins (so callers can still do `report.report_type is
            # ReportType.EXECUTIVE`); any other, future-defined report type
            # is returned as the plain string key it was defined under.
            resolved_type: ReportType | str = ReportType(key) if key in _KNOWN_REPORT_TYPE_VALUES else key

            sections: list[ReportSection] = []
            for spec in section_specs:
                builder = self._section_builders.get(spec.key)
                if builder is None:
                    raise UnknownReportSectionError(spec.key, key)

                section = builder(context)
                if section is None:
                    if spec.required:
                        raise MissingReportDataError(key, spec.key)
                    continue  # Optional and absent: omit gracefully, no error.

                sections.append(replace(section, order=len(sections)))

            metadata = context.metadata or _default_metadata(resolved_type)
            return Report(report_type=resolved_type, metadata=metadata, sections=tuple(sections))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_report_type_key(report_type: ReportType | str) -> str:
        """Normalize ``report_type`` into a plain, lowercase string key.

        ``ReportType`` is itself a ``str`` subclass, so this accepts
        both a ``ReportType`` member and an arbitrary string
        (including report types defined later via :meth:`define_report`
        that aren't one of the four built-ins) uniformly.

        Args:
            report_type: A :class:`ReportType` member or a string.

        Returns:
            The normalized (stripped, lowercased) string key.

        Raises:
            InvalidReportTypeError: If ``report_type`` is neither a
                :class:`ReportType` nor a string.
        """
        if isinstance(report_type, str):
            return report_type.strip().lower()
        raise InvalidReportTypeError(report_type)

    def _register_default_section_builders(self) -> None:
        """Register the four built-in section builders."""
        self.register_section_builder("kpi_summary", _build_kpi_summary_section)
        self.register_section_builder("business_insights", _build_business_insights_section)
        self.register_section_builder("regional_summary", _build_regional_summary_section)
        self.register_section_builder("product_summary", _build_product_summary_section)

    def _define_default_reports(self) -> None:
        """Define the four required report types and their section order.

        These defaults are a reasonable starting point, not a fixed
        business rule -- call :meth:`define_report` to change any
        report type's sections, order, or required/optional status
        without modifying this class.
        """
        self.define_report(
            ReportType.EXECUTIVE,
            (
                SectionSpec("kpi_summary", required=True),
                SectionSpec("business_insights", required=True),
                SectionSpec("product_summary", required=False),
                SectionSpec("regional_summary", required=False),
            ),
        )
        self.define_report(
            ReportType.WEEKLY,
            (
                SectionSpec("kpi_summary", required=True),
                SectionSpec("business_insights", required=False),
            ),
        )
        self.define_report(
            ReportType.MONTHLY,
            (
                SectionSpec("kpi_summary", required=True),
                SectionSpec("business_insights", required=True),
                SectionSpec("product_summary", required=True),
                SectionSpec("regional_summary", required=False),
            ),
        )
        self.define_report(
            ReportType.REGIONAL,
            (
                SectionSpec("regional_summary", required=True),
                SectionSpec("kpi_summary", required=False),
                SectionSpec("product_summary", required=False),
            ),
        )


# A shared, ready-to-use instance -- mirrors
# ``utils.kpi_engine.sales_kpi_engine``, ``utils.data_loader.sales_data_loader``,
# and ``services.export_service.sales_export_service``. Callers can
# import this directly instead of constructing their own ReportingService.
sales_reporting_service = ReportingService()
