"""Monitoring value objects for the NovaMart Observability & Monitoring Service.

Sprint 6.4 -- Observability & Monitoring Service, Task 2.

Every type here is a plain, immutable value object -- no behavior, no
storage, no Streamlit dependency -- matching the convention already
established by ``tenancy.models.Tenant``, ``utils.kpi_engine.KPIResult``,
and ``services.reporting_service.Report``. :class:`MonitoringEvent` is
the single record every monitoring-aware service produces;
:class:`ServiceHealth`, :class:`PlatformStats`, and
:class:`TenantActivity` are the aggregated views the Monitoring Service
computes from a collection of events for the Administration /
Monitoring dashboard (Task 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class EventType(str, Enum):
    """What kind of thing a :class:`MonitoringEvent` represents.

    A plain ``str`` subclass (matching ``tenancy.models.TenantStatus``
    and ``services.reporting_service.ReportType``), so a member compares
    equal to, and can be constructed from, its underlying string value.
    """

    OPERATION_STARTED = "operation_started"
    OPERATION_COMPLETED = "operation_completed"
    OPERATION_FAILED = "operation_failed"
    WARNING = "warning"
    INFO = "info"


class EventStatus(str, Enum):
    """The outcome/state a :class:`MonitoringEvent` reports.

    Kept distinct from :class:`EventType` on purpose: ``event_type``
    answers "what kind of event is this" (a lifecycle marker, a
    warning, an informational note), while ``status`` answers "how did
    it go" -- the axis :class:`ServiceHealth` aggregates over.
    """

    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class MonitoringEvent:
    """One immutable record of something a service did.

    Attributes:
        event_id: A unique identifier for this event (a UUID4 hex
            string), assigned once at creation time -- see
            :func:`monitoring.events.build_event`. Never reused, so
            events remain individually addressable across any future
            provider (a database primary key, a Prometheus exemplar id).
        timestamp: When the event was recorded, in UTC.
        service_name: The service that produced this event (e.g.
            ``"KPIEngine"``, ``"ReportingService"``) -- matches the
            ``service_name`` values already used by
            :func:`tenancy.context.validate_tenant_context` for the
            same services, so the two logging channels stay
            cross-referenceable.
        operation: The specific operation within that service (e.g.
            ``"calculate_all"``, ``"generate_report"``).
        event_type: What kind of event this is. See :class:`EventType`.
        status: The outcome this event reports. See :class:`EventStatus`.
        tenant_id: The tenant this event is attributable to, or
            ``None`` if no tenant context was available (Task 8:
            tenant-aware monitoring). Kept separate from
            ``tenant_name`` since it's the stable key used for
            filtering/grouping.
        tenant_name: The tenant's human-readable display name at the
            time of the event, or ``None`` alongside ``tenant_id``.
            Captured redundantly (rather than looked up later) so a
            historical event still reads correctly even if a tenant is
            later renamed.
        duration_ms: How long the operation took, in milliseconds, for
            ``OPERATION_COMPLETED``/``OPERATION_FAILED`` events.
            ``None`` for events that don't represent a measured
            duration (e.g. ``OPERATION_STARTED``, ``WARNING``, ``INFO``).
        message: A short, human-readable note -- an error message, a
            warning detail, an informational note. ``None`` when there
            is nothing beyond the structured fields to say.
        metadata: Optional, free-form extra data (mirrors
            ``tenancy.models.Tenant.metadata``'s "future expansion"
            role) -- e.g. row counts, report types, export formats --
            that lets a specific integration attach extra context
            without requiring a change to this model or to
            :class:`~monitoring.service.MonitoringService`.

    Example:
        >>> from monitoring.events import build_event
        >>> event = build_event(
        ...     service_name="KPIEngine",
        ...     operation="calculate_all",
        ...     event_type=EventType.OPERATION_COMPLETED,
        ...     status=EventStatus.SUCCESS,
        ...     duration_ms=12.4,
        ... )
        >>> event.status
        <EventStatus.SUCCESS: 'success'>
    """

    event_id: str
    timestamp: datetime
    service_name: str
    operation: str
    event_type: EventType
    status: EventStatus
    tenant_id: str | None = None
    tenant_name: str | None = None
    duration_ms: float | None = None
    message: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceHealth:
    """Aggregated operational health for one service (Task 7).

    Computed on demand by :meth:`~monitoring.service.MonitoringService.get_service_health`
    from that service's recorded events -- never stored directly, so it
    always reflects the current event history without a separate
    running-total to keep in sync.

    Attributes:
        service_name: Which service this snapshot describes.
        total_executions: Completed operations, successful or failed
            (``successful_executions + failed_executions``). Excludes
            ``OPERATION_STARTED``/``WARNING``/``INFO`` events, which
            aren't finished operations.
        successful_executions: Count of ``OPERATION_COMPLETED`` events.
        failed_executions: Count of ``OPERATION_FAILED`` events.
        warning_count: Count of ``WARNING`` events.
        average_duration_ms: Mean ``duration_ms`` across every completed
            or failed event that recorded one, or ``None`` if no timed
            event exists yet for this service.
        last_execution: The timestamp of the most recent event of any
            kind for this service, or ``None`` if it has never recorded
            one.
    """

    service_name: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    warning_count: int
    average_duration_ms: float | None
    last_execution: datetime | None


@dataclass(frozen=True)
class PlatformStats:
    """Platform-wide operational overview across every service (Task 9).

    The same aggregation :class:`ServiceHealth` performs per service,
    rolled up across all of them -- the numbers behind the
    Administration / Monitoring page's "Platform Overview" section.
    """

    total_operations: int
    successful_operations: int
    failed_operations: int
    average_duration_ms: float | None


@dataclass(frozen=True)
class TenantActivity:
    """Aggregated operational activity for one tenant (Tasks 8, 9).

    Attributes:
        tenant_id: The tenant this activity summary describes.
        tenant_name: That tenant's most recently observed display name.
        operation_count: Completed operations (successful or failed)
            attributable to this tenant, across every service.
        last_activity: Timestamp of the most recent event of any kind
            attributable to this tenant, or ``None``.
    """

    tenant_id: str
    tenant_name: str
    operation_count: int
    last_activity: datetime | None
