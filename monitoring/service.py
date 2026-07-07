"""Monitoring Service for the NovaMart Observability & Monitoring Service.

Sprint 6.4 -- Observability & Monitoring Service, Tasks 3, 6, 7, 8.

The single entry point every business service uses to record
operational events and every dashboard reads aggregated statistics
from. This module has exactly one responsibility -- collecting,
validating, and querying monitoring events -- and deliberately does
nothing else.

The Monitoring Service does NOT:
    - Decide *how* events are stored (that's a
      :class:`~monitoring.provider.MonitoringProvider`, injected in --
      see "Dependency Injection" below).
    - Validate or resolve tenants (that's ``tenancy.context``); it only
      *records* whichever tenant id/name a caller's
      :class:`~tenancy.context.TenantContext` currently holds, valid
      or not.
    - Ever raise a storage failure back into a business service. A
      provider failing to persist an event is logged and swallowed --
      see :meth:`MonitoringService._store` -- because an observability
      outage must never be able to cause a business outage.
    - Change, gate, or slow down business logic. Every business
      service call site adds monitoring calls *around* its existing,
      unchanged logic; nothing here can prevent that logic from
      running (unlike :func:`tenancy.context.validate_tenant_context`,
      which legitimately can).

Dependency Injection
----------------------
:class:`MonitoringService` never hard-codes which provider it uses. Its
constructor accepts an optional
:class:`~monitoring.provider.MonitoringProvider`; when omitted, it asks
:data:`monitoring.registry.monitoring_provider_registry` for whichever
provider is currently active. This is what lets:

- Tests inject a fresh, isolated provider instead of sharing the
  application-wide one.
- A future deployment swap from :class:`~monitoring.provider.InMemoryMonitoringProvider`
  to a SQLite/PostgreSQL/Prometheus/Grafana/Azure Monitor/AWS
  CloudWatch-backed provider by registering it and calling
  :meth:`~monitoring.registry.MonitoringProviderRegistry.set_active` --
  zero changes to this class or to any business service that calls it.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Mapping

from monitoring.events import OperationTimer, build_event
from monitoring.exceptions import InvalidMonitoringEventError
from monitoring.models import EventStatus, EventType, MonitoringEvent, PlatformStats, ServiceHealth, TenantActivity
from monitoring.provider import MonitoringProvider
from monitoring.registry import monitoring_provider_registry
from tenancy.context import TenantContext

logger = logging.getLogger("novamart.monitoring")


def _tenant_fields(tenant_context: TenantContext | None) -> tuple[str | None, str | None]:
    """Extract ``(tenant_id, tenant_name)`` from a tenant context, defensively.

    Deliberately never validates or raises -- monitoring must be able
    to record *something* useful (e.g. "this call had no tenant at
    all", which is itself valuable operational information) even when
    the tenant context is missing or inactive. Tenant *validation* is
    ``tenancy.context.validate_tenant_context``'s job, not this one's.

    Args:
        tenant_context: The context to read from, or ``None``.

    Returns:
        A ``(tenant_id, tenant_name)`` tuple, either or both ``None``
        if unavailable.
    """
    if tenant_context is None or tenant_context.tenant is None:
        return None, None
    return tenant_context.tenant.tenant_id, tenant_context.tenant.display_name


class MonitoringService:
    """Centralized collection point for operational events and statistics.

    Example:
        >>> service = MonitoringService()
        >>> service.record_completed(service_name="KPIEngine", operation="calculate_all", duration_ms=8.2)
        MonitoringEvent(...)

        Or, letting the service measure duration and outcome automatically:

        >>> with service.time_operation(service_name="KPIEngine", operation="calculate_all"):
        ...     pass  # existing business logic, unchanged
    """

    def __init__(self, provider: MonitoringProvider | None = None) -> None:
        """Create a Monitoring Service.

        Args:
            provider: The storage backend to record events into. When
                omitted (the normal case for application code), the
                currently active provider from
                :data:`~monitoring.registry.monitoring_provider_registry`
                is used. Tests and future callers can inject any other
                object satisfying :class:`~monitoring.provider.MonitoringProvider`.
        """
        self._provider: MonitoringProvider = provider if provider is not None else monitoring_provider_registry.get_active()

    # ------------------------------------------------------------------
    # Recording -- Task 3 ("record events/errors/duration/warnings/info")
    # ------------------------------------------------------------------
    def record_event(
        self,
        *,
        service_name: str,
        operation: str,
        event_type: EventType,
        status: EventStatus,
        tenant_context: TenantContext | None = None,
        duration_ms: float | None = None,
        message: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MonitoringEvent:
        """Build, validate, and store one monitoring event.

        The low-level primitive every ``record_*`` convenience method
        below is built on. Most callers should prefer those instead;
        this exists for the rare case of a custom event type/status
        combination.

        Args:
            service_name: The service recording this event. Required.
            operation: The operation within that service. Required.
            event_type: What kind of event this is.
            status: The outcome this event reports.
            tenant_context: The active tenant, if any (Task 8). Read
                defensively -- an invalid or empty context simply
                results in a tenant-less event, never an error here.
            duration_ms: Measured duration in milliseconds, if any.
            message: A short human-readable note, if any.
            metadata: Optional extra structured data.

        Returns:
            The recorded :class:`~monitoring.models.MonitoringEvent`.

        Raises:
            InvalidMonitoringEventError: If ``service_name`` or
                ``operation`` is empty. This is a caller bug (a
                business service's own instrumentation is
                misconfigured), distinct from a storage failure, so it
                is raised rather than swallowed.
        """
        if not service_name or not service_name.strip():
            raise InvalidMonitoringEventError("service_name is required")
        if not operation or not operation.strip():
            raise InvalidMonitoringEventError("operation is required")

        tenant_id, tenant_name = _tenant_fields(tenant_context)
        event = build_event(
            service_name=service_name,
            operation=operation,
            event_type=event_type,
            status=status,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            duration_ms=duration_ms,
            message=message,
            metadata=metadata,
        )
        self._store(event)
        return event

    def record_started(
        self,
        *,
        service_name: str,
        operation: str,
        tenant_context: TenantContext | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MonitoringEvent:
        """Record that an operation has begun.

        Args:
            service_name: The service starting work.
            operation: The operation being started.
            tenant_context: The active tenant, if any.
            metadata: Optional extra structured data.

        Returns:
            The recorded event.
        """
        return self.record_event(
            service_name=service_name,
            operation=operation,
            event_type=EventType.OPERATION_STARTED,
            status=EventStatus.IN_PROGRESS,
            tenant_context=tenant_context,
            metadata=metadata,
        )

    def record_completed(
        self,
        *,
        service_name: str,
        operation: str,
        duration_ms: float | None = None,
        tenant_context: TenantContext | None = None,
        message: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MonitoringEvent:
        """Record that an operation finished successfully.

        Args:
            service_name: The service that completed work.
            operation: The operation that completed.
            duration_ms: How long it took, in milliseconds, if measured.
            tenant_context: The active tenant, if any.
            message: An optional short note.
            metadata: Optional extra structured data.

        Returns:
            The recorded event.
        """
        return self.record_event(
            service_name=service_name,
            operation=operation,
            event_type=EventType.OPERATION_COMPLETED,
            status=EventStatus.SUCCESS,
            tenant_context=tenant_context,
            duration_ms=duration_ms,
            message=message,
            metadata=metadata,
        )

    def record_failure(
        self,
        *,
        service_name: str,
        operation: str,
        error: BaseException | str | None = None,
        duration_ms: float | None = None,
        tenant_context: TenantContext | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MonitoringEvent:
        """Record that an operation failed.

        Args:
            service_name: The service that failed.
            operation: The operation that failed.
            error: The exception (or a plain string) describing the
                failure. Its ``str()`` becomes the event's ``message``,
                and (for an exception) its type name is recorded in
                ``metadata["error_type"]`` for easy filtering.
            duration_ms: How long it ran before failing, in
                milliseconds, if measured.
            tenant_context: The active tenant, if any.
            metadata: Optional extra structured data.

        Returns:
            The recorded event.
        """
        message = str(error) if error is not None else None
        error_metadata: dict[str, object] = dict(metadata) if metadata else {}
        if isinstance(error, BaseException):
            error_metadata.setdefault("error_type", type(error).__name__)

        return self.record_event(
            service_name=service_name,
            operation=operation,
            event_type=EventType.OPERATION_FAILED,
            status=EventStatus.FAILURE,
            tenant_context=tenant_context,
            duration_ms=duration_ms,
            message=message,
            metadata=error_metadata,
        )

    def record_warning(
        self,
        *,
        service_name: str,
        operation: str,
        message: str,
        tenant_context: TenantContext | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MonitoringEvent:
        """Record a warning that doesn't represent an operation failure.

        Args:
            service_name: The service raising the warning.
            operation: The operation it concerns.
            message: A human-readable description of the warning.
            tenant_context: The active tenant, if any.
            metadata: Optional extra structured data.

        Returns:
            The recorded event.
        """
        return self.record_event(
            service_name=service_name,
            operation=operation,
            event_type=EventType.WARNING,
            status=EventStatus.WARNING,
            tenant_context=tenant_context,
            message=message,
            metadata=metadata,
        )

    def record_info(
        self,
        *,
        service_name: str,
        operation: str,
        message: str,
        tenant_context: TenantContext | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> MonitoringEvent:
        """Record a purely informational event.

        Args:
            service_name: The service recording the note.
            operation: The operation it concerns.
            message: A human-readable informational message.
            tenant_context: The active tenant, if any.
            metadata: Optional extra structured data.

        Returns:
            The recorded event.
        """
        return self.record_event(
            service_name=service_name,
            operation=operation,
            event_type=EventType.INFO,
            status=EventStatus.INFO,
            tenant_context=tenant_context,
            message=message,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Performance measurement -- Task 6 ("reusable abstraction, no duplication")
    # ------------------------------------------------------------------
    @contextmanager
    def time_operation(
        self,
        *,
        service_name: str,
        operation: str,
        tenant_context: TenantContext | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Iterator[OperationTimer]:
        """Time a block of code, recording started/completed/failed automatically.

        This is the one reusable abstraction every tenant-aware service
        wraps its existing (unchanged) business logic in, to satisfy
        Task 5 and Task 6 in a single line at each call site::

            with monitoring_service.time_operation(
                service_name="KPIEngine", operation="calculate_all", tenant_context=tenant_context
            ):
                ...  # existing business logic, unchanged

        Records an ``OPERATION_STARTED`` event on entry, and exactly
        one of ``OPERATION_COMPLETED`` (with the measured duration) or
        ``OPERATION_FAILED`` (with the measured duration and the
        exception) on exit -- then re-raises the original exception
        unchanged, so callers see exactly the same errors they always
        did.

        Args:
            service_name: The service performing the timed operation.
            operation: The operation being timed.
            tenant_context: The active tenant, if any.
            metadata: Optional extra structured data attached to all
                three recorded events.

        Yields:
            The :class:`~monitoring.events.OperationTimer` in use, in
            case a caller wants to inspect ``duration_ms`` after the
            block completes (mainly useful for tests).
        """
        self.record_started(
            service_name=service_name, operation=operation, tenant_context=tenant_context, metadata=metadata
        )
        timer = OperationTimer().start()
        try:
            yield timer
        except Exception as exc:
            timer.stop()
            self.record_failure(
                service_name=service_name,
                operation=operation,
                error=exc,
                duration_ms=timer.duration_ms,
                tenant_context=tenant_context,
                metadata=metadata,
            )
            raise
        else:
            timer.stop()
            self.record_completed(
                service_name=service_name,
                operation=operation,
                duration_ms=timer.duration_ms,
                tenant_context=tenant_context,
                metadata=metadata,
            )

    # ------------------------------------------------------------------
    # Querying -- Tasks 7, 8, 9 ("health", "stats", "tenant activity")
    # ------------------------------------------------------------------
    def get_events(
        self,
        *,
        tenant_id: str | None = None,
        service_name: str | None = None,
        event_type: EventType | None = None,
        status: EventStatus | None = None,
        limit: int | None = None,
    ) -> tuple[MonitoringEvent, ...]:
        """Return recorded events matching every given filter, most recent first.

        The source of the Administration / Monitoring page's "Recent
        Events" log.

        Args:
            tenant_id: If given, only events for this tenant.
            service_name: If given, only events from this service.
            event_type: If given, only events of this type.
            status: If given, only events with this status.
            limit: If given, return at most this many events.

        Returns:
            A tuple of matching events, newest first.
        """
        return self._provider.list_events(
            tenant_id=tenant_id, service_name=service_name, event_type=event_type, status=status, limit=limit
        )

    def get_service_health(self, service_name: str) -> ServiceHealth:
        """Compute operational health for one service (Task 7).

        Args:
            service_name: The service to summarize.

        Returns:
            A :class:`~monitoring.models.ServiceHealth` snapshot,
            computed live from every event currently recorded for that
            service (an empty snapshot -- all zero counts, ``None``
            timestamps/averages -- if it has never recorded one).
        """
        events = self._provider.list_events(service_name=service_name)
        return _build_service_health(service_name, events)

    def get_all_service_health(self) -> tuple[ServiceHealth, ...]:
        """Compute operational health for every service that has recorded an event.

        Returns:
            A tuple of :class:`~monitoring.models.ServiceHealth`
            snapshots, one per distinct ``service_name`` seen,
            alphabetically ordered -- the source of the Administration
            / Monitoring page's "Service Statistics" table.
        """
        events = self._provider.list_events()
        by_service: dict[str, list[MonitoringEvent]] = {}
        for event in events:
            by_service.setdefault(event.service_name, []).append(event)
        return tuple(_build_service_health(name, evts) for name, evts in sorted(by_service.items()))

    def get_platform_stats(self) -> PlatformStats:
        """Compute platform-wide operational stats across every service.

        Returns:
            A :class:`~monitoring.models.PlatformStats` snapshot -- the
            source of the Administration / Monitoring page's "Platform
            Overview" section.
        """
        events = self._provider.list_events()
        successful = [e for e in events if e.status == EventStatus.SUCCESS]
        failed = [e for e in events if e.status == EventStatus.FAILURE]
        durations = [e.duration_ms for e in (*successful, *failed) if e.duration_ms is not None]
        average_duration_ms = sum(durations) / len(durations) if durations else None

        return PlatformStats(
            total_operations=len(successful) + len(failed),
            successful_operations=len(successful),
            failed_operations=len(failed),
            average_duration_ms=average_duration_ms,
        )

    def get_tenant_activity(self) -> tuple[TenantActivity, ...]:
        """Compute per-tenant operational activity across every service (Task 8).

        Returns:
            A tuple of :class:`~monitoring.models.TenantActivity`
            summaries, one per distinct tenant id seen, ordered by
            tenant id -- the source of the Administration / Monitoring
            page's "Operations per Tenant" view. Events with no tenant
            id (e.g. a call made with a missing tenant context) are
            excluded, since there is no tenant to attribute them to.
        """
        events = self._provider.list_events()
        by_tenant: dict[str, list[MonitoringEvent]] = {}
        for event in events:
            if event.tenant_id is None:
                continue
            by_tenant.setdefault(event.tenant_id, []).append(event)

        activities = []
        for tenant_id, tenant_events in by_tenant.items():
            finished = [e for e in tenant_events if e.status in (EventStatus.SUCCESS, EventStatus.FAILURE)]
            # Most recent non-empty tenant_name wins, so a later rename
            # is reflected even though earlier events kept their
            # original (also correct-at-the-time) name.
            newest_first = sorted(tenant_events, key=lambda e: e.timestamp, reverse=True)
            tenant_name = next((e.tenant_name for e in newest_first if e.tenant_name), tenant_id)
            last_activity = newest_first[0].timestamp if newest_first else None
            activities.append(
                TenantActivity(
                    tenant_id=tenant_id,
                    tenant_name=tenant_name,
                    operation_count=len(finished),
                    last_activity=last_activity,
                )
            )
        return tuple(sorted(activities, key=lambda a: a.tenant_id))

    def most_active_tenant(self) -> TenantActivity | None:
        """Return the tenant with the most completed/failed operations.

        Returns:
            The busiest :class:`~monitoring.models.TenantActivity`, or
            ``None`` if no tenant-attributed event has been recorded
            yet. Ties are broken by the most recent activity.
        """
        activities = self.get_tenant_activity()
        if not activities:
            return None
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        return max(activities, key=lambda a: (a.operation_count, a.last_activity or epoch))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _store(self, event: MonitoringEvent) -> None:
        """Persist ``event`` via the configured provider, never raising.

        A monitoring/storage failure must never break the business
        operation that triggered it -- so any exception the provider
        raises is caught and logged as a warning here instead of
        propagating. This is the one place that guarantee is enforced,
        rather than every call site needing its own try/except.

        Args:
            event: The already-validated event to store.
        """
        try:
            self._provider.record(event)
        except Exception as exc:  # noqa: BLE001 - a storage failure must never break the caller
            logger.warning("Monitoring provider failed to record event %s: %s", event.event_id, exc)


def _build_service_health(service_name: str, events: "list[MonitoringEvent] | tuple[MonitoringEvent, ...]") -> ServiceHealth:
    """Aggregate a service's events into a :class:`~monitoring.models.ServiceHealth` snapshot.

    Shared by :meth:`MonitoringService.get_service_health` and
    :meth:`MonitoringService.get_all_service_health` so the aggregation
    rules (what counts as "successful", how the average is computed)
    are defined exactly once.

    Args:
        service_name: The service these events belong to.
        events: Every recorded event for that service.

    Returns:
        The computed :class:`~monitoring.models.ServiceHealth`.
    """
    events = list(events)
    successful = [e for e in events if e.status == EventStatus.SUCCESS]
    failed = [e for e in events if e.status == EventStatus.FAILURE]
    warnings = [e for e in events if e.status == EventStatus.WARNING]
    durations = [e.duration_ms for e in (*successful, *failed) if e.duration_ms is not None]
    average_duration_ms = sum(durations) / len(durations) if durations else None
    last_execution = max((e.timestamp for e in events), default=None)

    return ServiceHealth(
        service_name=service_name,
        total_executions=len(successful) + len(failed),
        successful_executions=len(successful),
        failed_executions=len(failed),
        warning_count=len(warnings),
        average_duration_ms=average_duration_ms,
        last_execution=last_execution,
    )


# A shared, ready-to-use instance -- mirrors ``tenancy.registry.tenant_registry``
# and every Sprint 6.2 service's ``sales_*_service`` singleton. Every
# business service imports this directly rather than constructing its
# own MonitoringService, so all recorded events land in the same place.
monitoring_service = MonitoringService()
