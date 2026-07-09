"""Automation Service for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Tasks 1, 4, 9.

The single entry point every business service uses to announce that
something happened, and the single place a handler (a notification, a
future workflow step) is registered to react to it. This module has
exactly one responsibility -- publishing events and dispatching them to
registered handlers -- and deliberately does nothing else.

The Automation Service does NOT:
    - Know what a business service's data means (a payload is opaque,
      free-form data -- see :class:`~automation.models.AutomationEvent`).
    - Send emails, Slack messages, or any other notification itself
      (that's :class:`~notification.service.NotificationService`, one
      possible *consumer* registered as a handler -- see
      ``config/automation_setup.py``, the one composition-root module
      allowed to wire the two packages together).
    - Decide *how* events are stored (that's an
      :class:`~automation.provider.AutomationEventStore`, injected in).
    - Ever let a handler's failure, or a storage failure, become a
      business operation's failure. Both are caught, logged, and
      recorded as monitoring events here -- never re-raised to the
      business service that called :meth:`publish` (the same
      resilience guarantee :class:`~monitoring.service.MonitoringService`
      already makes; see ``docs/AUTOMATION_ARCHITECTURE.md``).

Business services never manage automation logic directly (Task 4): they
call :meth:`AutomationService.publish` with a plain event type and
payload, exactly once, and never touch a handler, a provider, or a
notification channel.

Dependency Injection
----------------------
:class:`AutomationService` never hard-codes which event store or
scheduler it uses. Its constructor accepts both as optional arguments;
when omitted, each defaults to the shared, application-wide instance --
mirroring :class:`~identity.service.AuthenticationService` exactly.
"""

from __future__ import annotations

import logging
from typing import Callable, Mapping

from automation.events import build_event
from automation.exceptions import AutomationError
from automation.models import AutomationEvent, EventProcessingStatus, EventType
from automation.provider import AutomationEventStore
from automation.registry import automation_event_store_registry
from automation.scheduler import Scheduler
from automation.scheduler import scheduler as default_scheduler
from monitoring.service import monitoring_service
from tenancy.context import TenantContext

logger = logging.getLogger("novamart.automation")

_SERVICE_NAME = "AutomationService"

# A handler receives the fully-published AutomationEvent (already
# assigned an event_id and timestamp) and returns nothing. Keeping the
# signature uniform is what lets register_handler() work for any future
# consumer -- a notification dispatch, a workflow step, an audit
# exporter -- without AutomationService needing to know what any of
# them actually do.
EventHandler = Callable[[AutomationEvent], None]

# A handler registered under this key runs for every published event,
# regardless of event_type -- the mechanism a future cross-cutting
# consumer (an audit log, a webhook fan-out) would use instead of
# subscribing to each event type individually.
ALL_EVENTS_WILDCARD = "*"


def _tenant_fields(tenant_context: TenantContext | None) -> tuple[str | None, str | None]:
    """Extract ``(tenant_id, tenant_name)`` from a tenant context, defensively.

    Mirrors ``monitoring.service._tenant_fields`` exactly: never
    validates or raises, since an event with no tenant attached is
    still valid, useful information (e.g. a platform-wide scheduled
    job).

    Args:
        tenant_context: The context to read from, or ``None``.

    Returns:
        A ``(tenant_id, tenant_name)`` tuple, either or both ``None``
        if unavailable.
    """
    if tenant_context is None or tenant_context.tenant is None:
        return None, None
    return tenant_context.tenant.tenant_id, tenant_context.tenant.display_name


class AutomationService:
    """Centralized event publication and handler dispatch point.

    Example:
        >>> service = AutomationService()
        >>> service.register_handler(EventType.DATA_UPLOADED, lambda event: print(event.event_id))
        >>> event = service.publish(
        ...     EventType.DATA_UPLOADED, source_service="DataLoader", payload={"row_count": 120},
        ... )
        >>> event.status
        <EventProcessingStatus.HANDLED: 'handled'>
    """

    def __init__(
        self,
        store: AutomationEventStore | None = None,
        scheduler: Scheduler | None = None,
    ) -> None:
        """Create an Automation Service.

        Args:
            store: The event storage backend to use. When omitted (the
                normal case for application code), the currently active
                store from
                :data:`~automation.registry.automation_event_store_registry`
                is used. Tests inject a fresh, isolated store instead.
            scheduler: The :class:`~automation.scheduler.Scheduler`
                instance this service delegates
                :meth:`trigger_scheduled_job` to. Defaults to the
                shared :data:`~automation.scheduler.scheduler`.
        """
        self._store: AutomationEventStore = store if store is not None else automation_event_store_registry.get_active()
        self._scheduler: Scheduler = scheduler if scheduler is not None else default_scheduler
        self._handlers: dict[str, list[EventHandler]] = {}

    # ------------------------------------------------------------------
    # Handler registration -- Task 4 ("register handlers")
    # ------------------------------------------------------------------
    def register_handler(self, event_type: EventType | str, handler: EventHandler) -> None:
        """Register a handler to run whenever an event of ``event_type`` is published.

        Multiple handlers may be registered for the same event type;
        every one of them runs on each matching :meth:`publish` call.
        Pass :data:`ALL_EVENTS_WILDCARD` to subscribe to every event
        type at once.

        Args:
            event_type: The event type to subscribe to (a
                :class:`~automation.models.EventType` member, any other
                string, or :data:`ALL_EVENTS_WILDCARD`).
            handler: A callable matching :data:`EventHandler`'s
                signature: takes the published
                :class:`~automation.models.AutomationEvent`, returns
                nothing.
        """
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        self._handlers.setdefault(key, []).append(handler)

    def registered_event_types(self) -> tuple[str, ...]:
        """Return every event type with at least one registered handler, sorted."""
        return tuple(sorted(key for key in self._handlers if key != ALL_EVENTS_WILDCARD))

    # ------------------------------------------------------------------
    # Publication + dispatch -- Task 4 ("publish events", "execute handlers", "forward events")
    # ------------------------------------------------------------------
    def publish(
        self,
        event_type: EventType | str,
        *,
        source_service: str,
        payload: Mapping[str, object] | None = None,
        tenant_context: TenantContext | None = None,
        user_id: str | None = None,
    ) -> AutomationEvent:
        """Announce that something happened, and run every handler registered for it.

        This is the *entire* automation surface a business service ever
        touches (Task 4: "Business services should simply announce that
        something happened. Automation should decide what to do next.").
        The caller never learns which handlers exist, whether any
        notification was sent, or whether a handler failed -- all of
        that is this method's responsibility, recorded to monitoring
        (Task 9) and to the event store for the Automation Dashboard
        (Task 10), never raised back to the caller.

        Args:
            event_type: What kind of occurrence this is.
            source_service: The service announcing this event (e.g.
                ``"ReportingService"``).
            payload: Optional event-type-specific structured data.
            tenant_context: The active tenant, if any.
            user_id: The identity responsible for triggering this
                event, if known.

        Returns:
            The published :class:`~automation.models.AutomationEvent`,
            with its final :attr:`~automation.models.AutomationEvent.status`
            already resolved (``HANDLED`` if every registered handler
            ran without raising, ``FAILED`` if at least one did,
            ``PUBLISHED`` if no handler was registered at all). This
            method never raises for a handler or storage failure --
            only :meth:`register_handler` misuse (an invalid callable)
            would surface as a ``TypeError`` at call time, never a
            silently swallowed automation-specific exception.
        """
        tenant_id, tenant_name = _tenant_fields(tenant_context)
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)

        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="publish_event",
            tenant_context=tenant_context,
            message=f"{key} published by {source_service}",
            metadata={"event_type": key, "source_service": source_service, "user_id": user_id},
        )

        handlers = [*self._handlers.get(key, []), *self._handlers.get(ALL_EVENTS_WILDCARD, [])]

        # The event is built (and its final status resolved) before it
        # is stored -- automation events are an append-only log of
        # already-finished occurrences, exactly like
        # monitoring.models.MonitoringEvent, never a mutable record
        # updated in place after the fact.
        event = build_event(
            event_type=event_type,
            source_service=source_service,
            status=EventProcessingStatus.PUBLISHED,
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            user_id=user_id,
            payload=payload,
        )

        if handlers:
            all_succeeded = True
            for handler in handlers:
                all_succeeded &= self._run_handler(handler, event, tenant_context=tenant_context)
            status = EventProcessingStatus.HANDLED if all_succeeded else EventProcessingStatus.FAILED
            event = _with_status(event, status)

        self._store_event(event)
        return event

    def _run_handler(
        self, handler: EventHandler, event: AutomationEvent, *, tenant_context: TenantContext | None
    ) -> bool:
        """Run one handler for one event, recording success/failure, never raising.

        Args:
            handler: The handler to run.
            event: The event being dispatched.
            tenant_context: The active tenant, if any, for monitoring
                attribution.

        Returns:
            ``True`` if the handler completed without raising,
            ``False`` otherwise.
        """
        handler_name = getattr(handler, "__qualname__", repr(handler))
        try:
            handler(event)
        except Exception as exc:  # noqa: BLE001 - a handler failure must never break publish()
            logger.warning("Automation handler '%s' failed for event %s: %s", handler_name, event.event_id, exc)
            monitoring_service.record_failure(
                service_name=_SERVICE_NAME,
                operation="handle_event",
                error=exc,
                tenant_context=tenant_context,
                metadata={"event_id": event.event_id, "event_type": str(event.event_type), "handler": handler_name},
            )
            return False

        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="handle_event",
            tenant_context=tenant_context,
            message=f"handled by {handler_name}",
            metadata={"event_id": event.event_id, "event_type": str(event.event_type), "handler": handler_name},
        )
        return True

    def _store_event(self, event: AutomationEvent) -> None:
        """Persist ``event`` via the configured store, never raising.

        Mirrors ``monitoring.service.MonitoringService._store`` exactly:
        a storage failure must never break the business operation that
        published the event.

        Args:
            event: The already-finalized event to store.
        """
        try:
            self._store.record(event)
        except Exception as exc:  # noqa: BLE001 - a storage failure must never break the caller
            logger.warning("Automation event store failed to record event %s: %s", event.event_id, exc)

    # ------------------------------------------------------------------
    # Querying -- Task 10 ("recent events", "event history")
    # ------------------------------------------------------------------
    def get_events(
        self,
        *,
        tenant_id: str | None = None,
        event_type: EventType | str | None = None,
        status: EventProcessingStatus | None = None,
        source_service: str | None = None,
        limit: int | None = None,
    ) -> tuple[AutomationEvent, ...]:
        """Return published events matching every given filter, most recent first.

        Args:
            tenant_id: If given, only events for this tenant.
            event_type: If given, only events of this type.
            status: If given, only events with this status.
            source_service: If given, only events from this service.
            limit: If given, return at most this many events.

        Returns:
            A tuple of matching events, newest first.
        """
        return self._store.list_events(
            tenant_id=tenant_id, event_type=event_type, status=status, source_service=source_service, limit=limit
        )

    # ------------------------------------------------------------------
    # Scheduled jobs -- Task 4 ("trigger scheduled jobs"), Task 9
    # ------------------------------------------------------------------
    def trigger_scheduled_job(self, job_id: str, *, tenant_context: TenantContext | None = None):
        """Run a scheduled job immediately, recording the outcome to monitoring (Task 9).

        A thin pass-through to :meth:`~automation.scheduler.Scheduler.run_job`
        that adds the one thing the scheduler itself doesn't know how to
        do: recording a "Scheduled job executed" monitoring event. Kept
        on :class:`AutomationService` (rather than requiring the
        Automation Dashboard to call the scheduler and monitoring
        separately) so every automation-triggered side effect --
        publishing, handling, and scheduled execution -- is observable
        through the same, single service.

        Args:
            job_id: The job to run.
            tenant_context: The active tenant, if any, for monitoring
                attribution.

        Returns:
            The :class:`~automation.models.JobExecutionResult`.

        Raises:
            UnknownJobError: If no job is registered under ``job_id``.
        """
        result = self._scheduler.run_job(job_id)

        if result.error is None:
            monitoring_service.record_completed(
                service_name=_SERVICE_NAME,
                operation="run_scheduled_job",
                duration_ms=result.duration_ms,
                tenant_context=tenant_context,
                message=f"job '{job_id}' executed",
                metadata={"job_id": job_id},
            )
        else:
            monitoring_service.record_failure(
                service_name=_SERVICE_NAME,
                operation="run_scheduled_job",
                error=result.error,
                duration_ms=result.duration_ms,
                tenant_context=tenant_context,
                metadata={"job_id": job_id},
            )
        return result


def _with_status(event: AutomationEvent, status: EventProcessingStatus) -> AutomationEvent:
    """Return a copy of ``event`` with its ``status`` replaced.

    A tiny local helper (rather than importing ``dataclasses.replace``
    at every call site) since :class:`~automation.models.AutomationEvent`
    is frozen and :meth:`AutomationService.publish` needs to resolve the
    final status only after running handlers.

    Args:
        event: The event to copy.
        status: The new status.

    Returns:
        A new :class:`~automation.models.AutomationEvent` with every
        field identical except ``status``.
    """
    from dataclasses import replace

    return replace(event, status=status)


# A shared, ready-to-use instance -- mirrors
# ``monitoring.service.monitoring_service`` and
# ``identity.service.authentication_service``. Every business service
# imports this directly rather than constructing its own
# AutomationService, so every published event and registered handler is
# resolved against the same store and scheduler.
automation_service = AutomationService()
