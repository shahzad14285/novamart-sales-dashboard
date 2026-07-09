"""Automation-related exceptions for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform.

Mirrors the ``<Package>Error`` base-class convention already used by
``monitoring.exceptions.MonitoringError``, ``identity.exceptions.AuthenticationError``,
and ``tenancy.exceptions.TenantContextError``: catch :class:`AutomationError`
in calling code to handle any automation failure with a single ``except``
clause.

These exceptions are raised only for genuine *misuse* of the automation
API (an unknown job id, a duplicate registration) -- never for a
handler or event-store failure. A handler raising, or a provider
failing to persist an event, is logged and swallowed by
:class:`~automation.service.AutomationService` instead of raised, since
an automation outage must never be able to break the business
operation that published the triggering event (the same guarantee
:class:`~monitoring.service.MonitoringService` already makes for
monitoring). See ``docs/AUTOMATION_ARCHITECTURE.md`` for the full
rationale.
"""

from __future__ import annotations


class AutomationError(Exception):
    """Base class for every error raised by the automation package."""


class InvalidEventError(AutomationError):
    """Raised when an event is requested with missing/invalid required fields."""

    def __init__(self, reason: str) -> None:
        """Build a clear "why this event couldn't be built" message.

        Args:
            reason: A short description of what was missing or invalid
                (e.g. ``"source_service is required"``).
        """
        self.reason = reason
        super().__init__(f"Unable to publish automation event: {reason}.")


class ProviderNotRegisteredError(AutomationError):
    """Raised when an automation event store name doesn't match any registered provider."""

    def __init__(self, name: str, registered: tuple[str, ...]) -> None:
        """Build a message listing what *is* registered, for easy debugging.

        Args:
            name: The provider name that was requested.
            registered: The provider names currently registered.
        """
        self.name = name
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(
            f"No automation event store named '{name}' is registered. "
            f"Registered stores: {registered_list}."
        )


class NoActiveProviderError(AutomationError):
    """Raised when no automation event store has been marked active yet."""

    def __init__(self) -> None:
        super().__init__(
            "No active automation event store is configured. Register at least one "
            "store (see automation.registry.AutomationEventStoreRegistry.register)."
        )


class SchedulerError(AutomationError):
    """Base class for every error raised by the Scheduler."""


class UnknownJobError(SchedulerError):
    """Raised when a scheduled job id doesn't match any registered job."""

    def __init__(self, job_id: str, registered: tuple[str, ...]) -> None:
        """Build a message listing what *is* registered, for easy debugging.

        Args:
            job_id: The job id that was requested.
            registered: The job ids currently registered.
        """
        self.job_id = job_id
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(f"No scheduled job '{job_id}' is registered. Registered jobs: {registered_list}.")


class JobAlreadyRegisteredError(SchedulerError):
    """Raised when :meth:`~automation.scheduler.Scheduler.register_job` is called with a duplicate id."""

    def __init__(self, job_id: str) -> None:
        """Build a message identifying the conflicting job id.

        Args:
            job_id: The job id that was already registered.
        """
        self.job_id = job_id
        super().__init__(
            f"A scheduled job with id '{job_id}' is already registered. Use a different "
            "job_id, or call Scheduler.unregister_job() first if replacing it intentionally."
        )
