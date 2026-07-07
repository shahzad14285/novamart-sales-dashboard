"""Export Service for the NovaMart Sales Intelligence Dashboard.

Sprint 6.2 -- Executive Reporting & Export Center, Module 1.

Converts an already-processed pandas DataFrame into common export
formats (CSV, Excel, JSON) and hands the raw exported bytes back to
the caller. This module has exactly one responsibility -- format
conversion -- and deliberately does nothing else.

The Export Service does NOT:
    - Read uploaded files (that's ``utils/data_loader.py``).
    - Calculate KPIs (that's ``utils/kpi_engine.py`` / ``utils/calculations.py``).
    - Modify business data -- every exporter is read-only; rows,
      columns, and values are exported exactly as received.
    - Apply filters (that's ``utils/filters.py``).
    - Generate reports or PDFs (a future, separate service).
    - Perform AI recommendations (a future, separate service).

Extensibility: new formats (``export_xml``, ``export_parquet``,
``export_api_payload``, ...) can be added later by writing one new
method with the same signature as the existing exporters and
registering it via :meth:`ExportService.register` -- no changes are
required to ``ExportService`` itself or to any existing caller. This
mirrors the registry pattern already used by ``utils/kpi_engine.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Callable

import pandas as pd

from tenancy.context import TenantContext, validate_tenant_context


# ==============================================================================
# Exceptions
# ==============================================================================


class ExportServiceError(Exception):
    """Base class for every error raised by the Export Service.

    Catch this type in calling code to handle *any* export failure
    with a single ``except`` clause, e.g.::

        try:
            result = sales_export_service.export(df, "csv")
        except ExportServiceError as exc:
            st.error(str(exc))
    """


class InvalidExportInputError(ExportServiceError):
    """Raised when the value handed to the Export Service isn't a DataFrame."""

    def __init__(self, received: object) -> None:
        """Build a user-friendly "invalid input" message.

        Args:
            received: The value that was passed in place of a
                pandas DataFrame.
        """
        self.received_type = type(received)
        message = (
            "ExportService requires a pandas DataFrame as input, got "
            f"'{self.received_type.__name__}' instead."
        )
        super().__init__(message)


class UnsupportedExportFormatError(ExportServiceError):
    """Raised when :meth:`ExportService.export` is asked for an unknown format."""

    def __init__(self, requested_format: str, supported: tuple[str, ...]) -> None:
        """Build a user-friendly "unsupported format" message.

        Args:
            requested_format: The format string that was requested.
            supported: The format keys currently registered.
        """
        self.requested_format = requested_format
        supported_list = ", ".join(sorted(supported))
        message = (
            f"'{requested_format}' is not a supported export format. "
            f"Supported formats are: {supported_list}."
        )
        super().__init__(message)


# ==============================================================================
# Value object
# ==============================================================================


@dataclass(frozen=True)
class ExportResult:
    """Immutable bundle describing one export's output.

    Returned by every exporter method so callers -- a Streamlit
    ``st.download_button``, an HTTP response, a script writing to disk
    -- always get the same shape back, regardless of format.

    Attributes:
        content: The exported content as raw ``bytes``. Text-based
            formats (CSV, JSON) are UTF-8 encoded before being placed
            here, so every ``ExportResult`` can be handed straight to
            a file write or an HTTP response body without the caller
            needing to know which format it came from.
        file_extension: Suggested file extension, without the leading
            dot (e.g. ``"csv"``, ``"xlsx"``, ``"json"``).
        mime_type: MIME type suitable for an HTTP response or a
            Streamlit ``st.download_button``.
    """

    content: bytes
    file_extension: str
    mime_type: str


# Every registered exporter receives a validated DataFrame and returns
# an ExportResult. Keeping the signature uniform is what makes the
# registry pattern below work for any future format without changing
# ExportService itself.
ExporterFunction = Callable[[pd.DataFrame], ExportResult]


# ==============================================================================
# Export Service
# ==============================================================================


class ExportService:
    """Converts a processed DataFrame into common export formats.

    Registry-based, following the same extensibility pattern as
    :class:`~utils.kpi_engine.KPIEngine`: the three required formats
    (CSV, Excel, JSON) are registered by default in the constructor,
    and any future format is added by writing one new method and
    calling :meth:`register` -- existing code never needs to change.

    Example:
        >>> service = ExportService()
        >>> result = service.export(sales_df, "csv")
        >>> result.mime_type
        'text/csv'

        # Registering a new format later, without touching this class:
        >>> def _export_xml(df: pd.DataFrame) -> ExportResult:
        ...     xml_text = df.to_xml(index=False)
        ...     return ExportResult(xml_text.encode("utf-8"), "xml", "application/xml")
        >>> service.register("xml", _export_xml)
    """

    def __init__(self) -> None:
        """Create an Export Service with the default format registry."""
        self._registry: dict[str, ExporterFunction] = {}
        self._register_default_exporters()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def register(self, export_format: str, exporter: ExporterFunction) -> None:
        """Register (or override) the exporter used for ``export_format``.

        Calling this with an already-registered format key replaces
        that exporter, which makes it easy to swap in a custom
        implementation (e.g. a different Excel sheet layout) without
        subclassing :class:`ExportService`.

        Args:
            export_format: The format key callers will pass to
                :meth:`export` (case-insensitive, e.g. ``"csv"``).
            exporter: A callable matching the :data:`ExporterFunction`
                signature: takes a DataFrame, returns an
                :class:`ExportResult`.
        """
        self._registry[export_format.strip().lower()] = exporter

    def export(
        self, df: pd.DataFrame, export_format: str, *, tenant_context: TenantContext | None = None
    ) -> ExportResult:
        """Export ``df`` using the exporter registered for ``export_format``.

        This is the single entry point most callers need -- it looks
        up the right exporter by name so callers don't need to know
        about ``export_csv``/``export_excel``/``export_json``
        individually, and it automatically picks up any format
        registered later via :meth:`register`.

        Args:
            df: The (already processed) DataFrame to export.
            export_format: Which format to export to, e.g. ``"csv"``,
                ``"excel"``, ``"xlsx"``, or ``"json"``. Case-insensitive.
            tenant_context: The tenant this export is scoped to
                (Multi-Tenant Sprint 6.3). Required for the call to
                succeed -- see :func:`~tenancy.context.validate_tenant_context`.
                Export logic itself never varies by tenant; this only
                guarantees every export is attributable to, and gated
                on, an active tenant.

        Returns:
            An :class:`ExportResult` with the exported content.

        Raises:
            MissingTenantContextError: If no tenant context was supplied.
            InactiveTenantError: If the supplied tenant is not active.
            InvalidExportInputError: If ``df`` isn't a pandas DataFrame.
            UnsupportedExportFormatError: If ``export_format`` isn't
                registered.
        """
        validate_tenant_context(tenant_context, service_name="ExportService", operation="export")

        key = export_format.strip().lower()
        exporter = self._registry.get(key)
        if exporter is None:
            raise UnsupportedExportFormatError(export_format, tuple(self._registry.keys()))
        return exporter(df)

    def supported_formats(self) -> tuple[str, ...]:
        """Return every export format key currently registered.

        Returns:
            A sorted tuple of format keys, e.g. ``("csv", "excel", "json", "xlsx")``.
        """
        return tuple(sorted(self._registry.keys()))

    # ------------------------------------------------------------------
    # Built-in exporters (the three formats required by this module)
    # ------------------------------------------------------------------
    def export_csv(self, df: pd.DataFrame) -> ExportResult:
        """Export ``df`` as CSV.

        Args:
            df: The DataFrame to export. May be empty (zero rows);
                a header-only CSV is returned in that case rather than
                raising an error.

        Returns:
            An :class:`ExportResult` with ``file_extension="csv"`` and
            ``mime_type="text/csv"``.

        Raises:
            InvalidExportInputError: If ``df`` isn't a pandas DataFrame.
        """
        validated = self._validate_dataframe(df)
        csv_text = validated.to_csv(index=False)
        return ExportResult(
            content=csv_text.encode("utf-8"),
            file_extension="csv",
            mime_type="text/csv",
        )

    def export_excel(self, df: pd.DataFrame, sheet_name: str = "Data") -> ExportResult:
        """Export ``df`` as an Excel (``.xlsx``) workbook.

        Args:
            df: The DataFrame to export. May be empty (zero rows); a
                workbook containing only the header row is returned in
                that case rather than raising an error.
            sheet_name: Name of the single worksheet written.

        Returns:
            An :class:`ExportResult` with ``file_extension="xlsx"``.

        Raises:
            InvalidExportInputError: If ``df`` isn't a pandas DataFrame.
        """
        validated = self._validate_dataframe(df)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            validated.to_excel(writer, index=False, sheet_name=sheet_name)
        return ExportResult(
            content=buffer.getvalue(),
            file_extension="xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def export_json(self, df: pd.DataFrame, orient: str = "records", indent: int = 2) -> ExportResult:
        """Export ``df`` as JSON.

        Args:
            df: The DataFrame to export. May be empty (zero rows); an
                empty JSON array (``"[]"``) is returned in that case
                rather than raising an error.
            orient: Passed straight through to ``DataFrame.to_json``.
                Defaults to ``"records"`` (a JSON array of row objects),
                the most broadly useful shape for downstream consumers.
            indent: Number of spaces used to pretty-print the JSON.

        Returns:
            An :class:`ExportResult` with ``file_extension="json"``.

        Raises:
            InvalidExportInputError: If ``df`` isn't a pandas DataFrame.
        """
        validated = self._validate_dataframe(df)
        json_text = validated.to_json(orient=orient, indent=indent, date_format="iso")
        return ExportResult(
            content=json_text.encode("utf-8"),
            file_extension="json",
            mime_type="application/json",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _register_default_exporters(self) -> None:
        """Register the three export formats required by this module.

        ``"excel"`` and ``"xlsx"`` are both registered so callers can
        use whichever key reads more naturally; both resolve to the
        same :meth:`export_excel` implementation.
        """
        self.register("csv", self.export_csv)
        self.register("excel", self.export_excel)
        self.register("xlsx", self.export_excel)
        self.register("json", self.export_json)

    @staticmethod
    def _validate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Validate that ``df`` is a pandas DataFrame.

        An empty DataFrame (zero rows) is valid input and is passed
        through unchanged -- pandas' own ``to_csv``/``to_excel``/
        ``to_json`` already produce well-formed, header-only output
        for an empty frame, so no special-casing is needed here to
        handle that "gracefully".

        Args:
            df: The value to validate.

        Returns:
            ``df``, unchanged.

        Raises:
            InvalidExportInputError: If ``df`` isn't a pandas DataFrame
                (this also catches ``None``).
        """
        if not isinstance(df, pd.DataFrame):
            raise InvalidExportInputError(df)
        return df


# A shared, ready-to-use instance -- mirrors
# ``utils.kpi_engine.sales_kpi_engine`` and
# ``utils.data_loader.sales_data_loader``. Callers can import this
# directly instead of constructing their own ExportService.
sales_export_service = ExportService()
