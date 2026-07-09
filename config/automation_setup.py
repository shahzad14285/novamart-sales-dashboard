"""Automation & Notification composition root for the NovaMart platform.

Sprint 6.7 -- Automation & Notification Platform.

This is the **one** module in the entire codebase allowed to import
both ``automation`` and ``notification`` together -- mirroring exactly
the role ``config/credentials.py`` already plays for ``identity`` and
``authorization`` (Sprint 6.6). Neither package imports the other
directly (Task 2: "Notification is one consumer of automation events" --
a consumer the Automation Service knows only as an anonymous
``EventHandler`` callable, never as "the notification package"). Wiring
them together -- "when a REPORT_GENERATED event is published, run
``notification_service.handle_event``" -- is configuration, not
business logic, so it belongs here, at the composition root, exactly
like ``config/credentials.py`` wires identities into the active
authentication provider.

Also registers this sprint's demo scheduled jobs (Task 5) -- a small,
illustrative catalogue (daily/weekly/monthly), each of which simply
publishes an automation event when run, closing the loop described in
the target architecture: ``Scheduler -> (publishes) -> Automation
Service -> Event Handler -> Notification Service``.

Imported once, for its side effect, from ``components/sidebar.py`` (the
one UI module every page in this app imports before any business
service call can run) -- see that module's imports for the exact same
pattern ``components/auth.py`` already uses for
``config.credentials``.
"""

from __future__ import annotations

from automation.models import EventType, ScheduleFrequency
from automation.scheduler import scheduler
from automation.service import automation_service
from notification.service import notification_service

# The event types this sprint's ticket names as needing a notification
# consumer (Task 8's suggested events). A brand-new event type is
# automatically routed once notification.service.NotificationService's
# own routing table (see _register_default_routes there) has an entry
# for it -- registering it as a handler here is what lets it reach that
# routing table at all. Events with no notification route configured
# are handled as a no-op by NotificationService.handle_event, so
# registering a couple of extra, not-yet-routed event types here (e.g.
# USER_LOGOUT) is harmless and future-proofs it for the moment a route
# is added.
_HANDLED_EVENT_TYPES: tuple[EventType, ...] = (
    EventType.DATA_UPLOADED,
    EventType.REPORT_GENERATED,
    EventType.PDF_GENERATED,
    EventType.EXPORT_COMPLETED,
    EventType.AI_ANALYSIS_COMPLETED,
    EventType.KPI_THRESHOLD_REACHED,
    EventType.LOGIN_SUCCESS,
    EventType.LOGIN_FAILED,
    EventType.USER_LOGOUT,
)


def register_default_handlers() -> None:
    """Register :meth:`NotificationService.handle_event` for every known event type.

    Idempotent-in-spirit for this sprint (called exactly once, at
    import time) -- calling it again would register duplicate handlers,
    so it is deliberately not re-invoked elsewhere. A test that needs a
    clean slate constructs its own :class:`~automation.service.AutomationService`
    instance instead of touching the shared one this wires.
    """
    for event_type in _HANDLED_EVENT_TYPES:
        automation_service.register_handler(event_type, notification_service.handle_event)


def _demo_daily_platform_summary() -> dict:
    """Placeholder callback for the demo daily job: publishes an INFO-style event.

    Task 5: "Actual background execution is not required. The objective
    is architectural design." This callback exists to prove the
    Scheduler -> AutomationService round trip works end to end (a real
    deployment would replace it with a call that actually builds and
    emails a platform summary).
    """
    event = automation_service.publish(
        EventType.REPORT_GENERATED,
        source_service="Scheduler",
        payload={"job": "daily_platform_summary", "report_type": "daily_summary"},
    )
    return {"event_id": event.event_id}


def _demo_weekly_executive_report() -> dict:
    """Placeholder callback for the demo weekly job. See :func:`_demo_daily_platform_summary`."""
    event = automation_service.publish(
        EventType.REPORT_GENERATED,
        source_service="Scheduler",
        payload={"job": "weekly_executive_report", "report_type": "weekly"},
    )
    return {"event_id": event.event_id}


def _demo_monthly_platform_report() -> dict:
    """Placeholder callback for the demo monthly job. See :func:`_demo_daily_platform_summary`."""
    event = automation_service.publish(
        EventType.REPORT_GENERATED,
        source_service="Scheduler",
        payload={"job": "monthly_platform_report", "report_type": "monthly"},
    )
    return {"event_id": event.event_id}


def register_default_jobs() -> None:
    """Register this sprint's demo scheduled jobs (Task 5).

    A real deployment would register jobs that call the actual
    Reporting/PDF/Export services with a concrete tenant and dataset;
    these demo jobs illustrate the mechanism -- daily/weekly/monthly
    cadence, manual "Run Now" execution from the Automation Dashboard,
    and a closed loop back through the same event/notification pipeline
    every business service already uses.
    """
    if not scheduler.list_jobs():
        scheduler.register_job(
            "daily_platform_summary", "Daily Platform Summary", ScheduleFrequency.DAILY,
            callback=_demo_daily_platform_summary,
        )
        scheduler.register_job(
            "weekly_executive_report", "Weekly Executive Report", ScheduleFrequency.WEEKLY,
            callback=_demo_weekly_executive_report,
        )
        scheduler.register_job(
            "monthly_platform_report", "Monthly Platform Report", ScheduleFrequency.MONTHLY,
            callback=_demo_monthly_platform_report,
        )


register_default_handlers()
register_default_jobs()
