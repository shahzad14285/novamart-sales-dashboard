"""Monitoring-related exceptions for the NovaMart Observability & Monitoring Service.

Sprint 6.4 -- Observability & Monitoring Service.

Mirrors the ``<Package>Error`` base-class convention already used by
``tenancy.exceptions.TenantContextError`` and every Sprint 6.2 service
(``ExportServiceError``, ``ReportingServiceError``, ...): catch
:class:`MonitoringError` in calling code to handle any monitoring
failure with a single ``except`` clause.

These exceptions are raised only for genuine *misuse* of the
monitoring API (a missing required field, an unknown provider name) --
never for a storage/provider failure. A provider failing to persist an
event is logged and swallowed by
:class:`~monitoring.service.MonitoringService` instead of raised, since
a monitoring outage must never be able to break a business operation.
See ``docs/OBSERVABILITY_ARCHITECTURE.md`` for the full rationale.
"""

from __future__ import annotations


class MonitoringError(Exception):
    """Base class for every error raised by the monitoring package."""


class InvalidMonitoringEventError(MonitoringError):
    """Raised when a monitoring event is requested with missing/invalid required fields."""

    def __init__(self, reason: str) -> None:
        """Build a clear "why this event couldn't be built" message.

        Args:
            reason: A short description of what was missing or invalid
                (e.g. ``"service_name is required"``).
        """
        self.reason = reason
        super().__init__(f"Unable to record monitoring event: {reason}.")


class ProviderNotRegisteredError(MonitoringError):
    """Raised when a monitoring provider name doesn't match any registered provider."""

    def __init__(self, name: str, registered: tuple[str, ...]) -> None:
        """Build a message listing what *is* registered, for easy debugging.

        Args:
            name: The provider name that was requested.
            registered: The provider names currently registered.
        """
        self.name = name
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(
            f"No monitoring provider named '{name}' is registered. "
            f"Registered providers: {registered_list}."
        )


class NoActiveProviderError(MonitoringError):
    """Raised when no monitoring provider has been marked active yet."""

    def __init__(self) -> None:
        super().__init__(
            "No active monitoring provider is configured. Register at least one "
            "provider (see monitoring.registry.MonitoringProviderRegistry.register)."
        )
