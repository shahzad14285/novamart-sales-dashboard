"""Tenant-related exceptions for the NovaMart Multi-Tenant platform.

Sprint 6.3 -- Multi-Tenant Business Intelligence Platform, Task 4.

Every message on these exceptions is written to be shown directly to
an end user (e.g. via ``st.error``) -- professional and
business-friendly, with no tenant IDs, service names, stack traces, or
other implementation detail included in the message text itself. That
detail (tenant id, service, operation, timestamp) is still captured,
but only in the structured log line
:func:`~tenancy.context.validate_tenant_context` writes -- never in
text that reaches the screen.

Mirrors the ``<Service>Error`` base-class convention already used by
every Sprint 6.2 service (``ExportServiceError``,
``ReportingServiceError``, ``AIRecommendationServiceError``,
``PDFGeneratorServiceError``): catch :class:`TenantContextError` in
calling code to handle *any* tenant-validation failure with a single
``except`` clause.
"""

from __future__ import annotations


class TenantContextError(Exception):
    """Base class for every tenant-context validation failure.

    Catch this type in calling code (typically the UI layer) to handle
    *any* tenant-validation failure the same way::

        try:
            report = sales_reporting_service.generate_report(
                report_type, context, tenant_context=tenant_context
            )
        except TenantContextError as exc:
            st.error(str(exc), icon="🔒")
    """


class MissingTenantContextError(TenantContextError):
    """Raised when no :class:`~tenancy.context.TenantContext` was supplied at all."""

    def __init__(self) -> None:
        super().__init__("Tenant context is missing. Unable to process request.")


class TenantNotFoundError(TenantContextError):
    """Raised when a tenant id doesn't match any tenant known to the platform."""

    def __init__(self, tenant_id: str) -> None:
        """Build a business-friendly "tenant not found" message.

        Args:
            tenant_id: The tenant id that couldn't be resolved. Kept on
                the exception instance for logging -- never included in
                the message shown to the user.
        """
        self.tenant_id = tenant_id
        super().__init__("The requested tenant could not be found. Unable to process request.")


class InactiveTenantError(TenantContextError):
    """Raised when the tenant resolved successfully but is not active."""

    def __init__(self, tenant_id: str) -> None:
        """Build a business-friendly "tenant inactive" message.

        Args:
            tenant_id: The inactive tenant's id. Kept on the exception
                instance for logging -- never included in the message
                shown to the user.
        """
        self.tenant_id = tenant_id
        super().__init__("This tenant account is currently inactive. Unable to process request.")
