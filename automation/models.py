"""Automation value objects for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 3.

Every type here is a plain, immutable value object -- no behavior, no
storage, no Streamlit dependency -- matching the convention already
established by ``monitoring.models.MonitoringEvent``,
``identity.models.SessionInfo``, and ``authorization.models.User``.
:class:`AutomationEvent` is the single record a business service
produces the moment "something happened"; :class:`ScheduledJob` is the
value object :class:`~automation.scheduler.Scheduler` hands back to
describe one registered job.

Business services never construct an :class:`AutomationEvent` directly
-- :meth:`~automation.service.AutomationService.publish` is the only
place one is built (via :func:`~automation.events.build_event`), which
is what guarantees every event's ``event_id``/``timestamp`` are
generated consistently regardless of which service produced it (the
identical guarantee ``monitoring.events.build_event`` already makes for
monitoring events).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class EventType(str, Enum):
    """What kind of business occurrence an :class:`AutomationEvent` represents.

    A plain ``str`` subclass (matching ``monitoring.models.EventType`` and
    ``identity.models.LoginStatus``), so a member compares equal to, and
    can be constructed from, its underlying string value -- which is
    exactly what lets a business service publish an event type it
    receives as a plain string (e.g. from a future workflow definition)
    without importing this enum at all.

    This is deliberately *not* a closed set business services must be
    hard-coded against: :meth:`~automation.service.AutomationService.publish`
    accepts any :class:`EventType` member *or* any other string, so a
    brand-new event type is one new call site away, never a change to
    this enum (Task 3: "Design for future extensibility"). The members
    below are the eight event types this sprint's ticket names
    explicitly, registered as real handler-routable examples throughout
    this platform.
    """

    DATA_UPLOADED = "data_uploaded"
    REPORT_GENERATED = "report_generated"
    PDF_GENERATED = "pdf_generated"
    EXPORT_COMPLETED = "export_completed"
    AI_ANALYSIS_COMPLETED = "ai_analysis_completed"
    KPI_THRESHOLD_REACHED = "kpi_threshold_reached"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    USER_LOGOUT = "user_logout"


class EventProcessingStatus(str, Enum):
    """The outcome of dispatching an :class:`AutomationEvent` to its handlers.

    Kept distinct from :class:`EventType` on purpose, mirroring
    ``monitoring.models.EventType`` vs. ``monitoring.models.EventStatus``:
    ``event_type`` answers "what happened", ``status`` answers "how did
    handling it go" -- the axis Task 10's "Event status" / "Delivery
    status" dashboard columns read from.

    An :class:`AutomationEvent` is stored exactly once, with its final
    status already resolved (see
    :meth:`~automation.service.AutomationService.publish`), rather than
    as a mutable record updated in place -- consistent with every other
    append-only event log in this platform
    (:class:`~monitoring.models.MonitoringEvent` is never updated after
    it is recorded either).
    """

    PUBLISHED = "published"
    """No handler is registered for this event type -- it was recorded but nothing consumed it."""

    HANDLED = "handled"
    """Every registered handler for this event type ran without raising."""

    FAILED = "failed"
    """At least one registered handler raised while processing this event."""


@dataclass(frozen=True)
class AutomationEvent:
    """One immutable record of a business occurrence a service announced.

    Attributes:
        event_id: A unique identifier for this event (a UUID4 hex
            string), assigned once at publication time -- see
            :func:`automation.events.build_event`.
        event_type: What kind of occurrence this is. See
            :class:`EventType`.
        source_service: The service that announced this event (e.g.
            ``"ReportingService"``, ``"DataLoader"``) -- matches the
            ``service_name`` values already used by
            :data:`~monitoring.service.monitoring_service` for the same
            services, so the two logging channels stay
            cross-referenceable.
        tenant_id: The tenant this event is attributable to, or
            ``None`` if no tenant context was available. Kept separate
            from ``tenant_name`` since it's the stable key used for
            filtering/grouping (mirrors
            ``monitoring.models.MonitoringEvent.tenant_id``).
        tenant_name: The tenant's human-readable display name at the
            time of the event, or ``None`` alongside ``tenant_id``.
        user_id: The identity (Sprint 6.6) responsible for triggering
            this event, if known (e.g. who uploaded the file, who
            signed in). ``None`` for events with no attributable user
            (e.g. a scheduler-triggered job).
        timestamp: When the event was published, in UTC.
        payload: Free-form, event-type-specific data describing what
            happened (e.g. ``{"row_count": 120}`` for
            :attr:`EventType.DATA_UPLOADED`, ``{"kpi_key": "total_revenue",
            "value": 800.0, "threshold": 1000.0}`` for
            :attr:`EventType.KPI_THRESHOLD_REACHED`). Never inspected or
            required by :class:`~automation.service.AutomationService`
            itself -- only by the handlers/templates that choose to read
            specific keys from it, which is what lets a brand-new event
            type carry whatever shape of payload it needs without any
            change to this model.
        status: The outcome of dispatching this event to its handlers.
            See :class:`EventProcessingStatus`.

    Example:
        >>> from automation.events import build_event
        >>> event = build_event(
        ...     event_type=EventType.DATA_UPLOADED,
        ...     source_service="DataLoader",
        ...     status=EventProcessingStatus.PUBLISHED,
        ...     payload={"row_count": 120},
        ... )
        >>> event.event_type
        <EventType.DATA_UPLOADED: 'data_uploaded'>
    """

    event_id: str
    event_type: EventType
    source_service: str
    timestamp: datetime
    status: EventProcessingStatus
    tenant_id: str | None = None
    tenant_name: str | None = None
    user_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)


class ScheduleFrequency(str, Enum):
    """How often a :class:`ScheduledJob` should run (Task 5).

    ``MANUAL`` jobs never run on a cadence at all -- they exist purely
    to be triggered on demand via
    :meth:`~automation.scheduler.Scheduler.run_job`, which is the only
    execution path this sprint actually exercises ("Actual background
    execution is not required. The objective is architectural design.").
    ``DAILY``/``WEEKLY``/``MONTHLY`` jobs additionally expose a computed
    ``next_run_at`` (see :class:`ScheduledJob`) so a future real
    scheduler (an OS cron entry, Celery beat, APScheduler, a cloud
    function timer) has something to read without this module changing.
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MANUAL = "manual"


class JobStatus(str, Enum):
    """The outcome of the most recent execution of a :class:`ScheduledJob`."""

    NEVER_RUN = "never_run"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class ScheduledJob:
    """A named, schedulable unit of automation work (Task 5).

    An immutable snapshot -- :class:`~automation.scheduler.Scheduler`
    itself owns the actual callable this job runs (callables aren't
    meaningfully immutable/displayable value data, so they're kept out
    of this dataclass entirely, mirroring why
    ``services.reporting_service.SectionBuilder`` callables live in a
    registry dict rather than on ``ReportSection``).

    Attributes:
        job_id: Stable identifier for this job (e.g.
            ``"weekly_executive_report"``).
        name: Human-readable display name.
        frequency: How often this job is intended to run. See
            :class:`ScheduleFrequency`.
        enabled: Whether this job is currently eligible to run. A
            disabled job is skipped by
            :meth:`~automation.scheduler.Scheduler.due_jobs` but can
            still be triggered manually.
        last_run_at: When this job last ran (successfully or not), or
            ``None`` if it has never run.
        last_status: The outcome of the most recent run. See
            :class:`JobStatus`.
        next_run_at: When this job is next due to run, computed from
            ``frequency`` and ``last_run_at`` at registration/run time.
            ``None`` for :attr:`ScheduleFrequency.MANUAL` jobs, which
            are never "due" -- only ever triggered explicitly.
    """

    job_id: str
    name: str
    frequency: ScheduleFrequency
    enabled: bool = True
    last_run_at: datetime | None = None
    last_status: JobStatus = JobStatus.NEVER_RUN
    next_run_at: datetime | None = None


@dataclass(frozen=True)
class JobExecutionResult:
    """The outcome of one :meth:`~automation.scheduler.Scheduler.run_job` call.

    Attributes:
        job_id: Which job was executed.
        status: Whether the job's callback completed successfully.
        started_at: When execution began (UTC).
        duration_ms: How long the callback took to run, in
            milliseconds.
        result: The callback's return value, if any -- passed through
            unchanged so a caller (or the Automation Dashboard) can
            show what a job produced.
        error: The callback's exception, as a string, if it failed.
    """

    job_id: str
    status: JobStatus
    started_at: datetime
    duration_ms: float
    result: object = None
    error: str | None = None
