"""Automation Event Store abstraction for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 1.

:class:`~automation.service.AutomationService` never stores an event
itself -- it delegates every bit of persistence to an **event store**
satisfying the :class:`AutomationEventStore` interface (a structural
``typing.Protocol``, mirroring
:class:`monitoring.provider.MonitoringProvider` and
:class:`identity.provider.AuthenticationProvider` exactly). The service
depends only on that interface, never on a concrete storage
implementation -- which is what lets the Automation Dashboard's "Recent
Events" / "Event History" (Task 10) work against any backend without
knowing which one is active.

This sprint ships :class:`InMemoryAutomationEventStore`, a
process-local, dependency-free default sufficient for a single-process
Streamlit deployment. Future stores -- SQLite, a message queue (Kafka,
RabbitMQ, AWS SQS), Redis Streams -- are added by writing one new class
that satisfies :class:`AutomationEventStore` and registering it via
:meth:`~automation.registry.AutomationEventStoreRegistry.register`.
Nothing in :class:`~automation.service.AutomationService` needs to
change.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from automation.models import AutomationEvent, EventProcessingStatus, EventType


@runtime_checkable
class AutomationEventStore(Protocol):
    """Interface every automation event storage backend must satisfy.

    A structural ``Protocol``, so a class satisfies this interface
    simply by having compatible ``record``/``list_events``/``clear``
    methods -- no inheritance required, exactly like
    :class:`~monitoring.provider.MonitoringProvider`.
    """

    def record(self, event: AutomationEvent) -> None:
        """Persist one automation event.

        Args:
            event: The event to store. Implementations should treat
                this as opaque, immutable data.
        """
        ...

    def list_events(
        self,
        *,
        tenant_id: str | None = None,
        event_type: EventType | str | None = None,
        status: EventProcessingStatus | None = None,
        source_service: str | None = None,
        limit: int | None = None,
    ) -> tuple[AutomationEvent, ...]:
        """Return stored events matching every given filter, most recent first.

        Args:
            tenant_id: If given, only events with this exact tenant id.
            event_type: If given, only events of this exact type.
            status: If given, only events with this exact status.
            source_service: If given, only events from this exact
                source service.
            limit: If given, return at most this many events (the most
                recent ones).

        Returns:
            A tuple of matching events, ordered newest first.
        """
        ...

    def clear(self) -> None:
        """Remove every stored event.

        Primarily useful for tests that need a clean store rather than
        one accumulating events across an entire test run.
        """
        ...


class InMemoryAutomationEventStore:
    """Default automation event store: keeps events in process memory.

    Sufficient for a single-process Streamlit deployment and for tests.
    Thread-safe (guarded by a simple lock), mirroring
    :class:`~monitoring.provider.InMemoryMonitoringProvider`.

    Example:
        >>> store = InMemoryAutomationEventStore()
        >>> from automation.events import build_event
        >>> event = build_event(
        ...     event_type=EventType.DATA_UPLOADED, source_service="DataLoader",
        ...     status=EventProcessingStatus.PUBLISHED,
        ... )
        >>> store.record(event)
        >>> len(store.list_events())
        1
    """

    def __init__(self) -> None:
        """Create an empty in-memory event store."""
        self._events: list[AutomationEvent] = []
        self._lock = threading.Lock()

    def record(self, event: AutomationEvent) -> None:
        """Append ``event`` to the in-memory list.

        Args:
            event: The event to store.
        """
        with self._lock:
            self._events.append(event)

    def list_events(
        self,
        *,
        tenant_id: str | None = None,
        event_type: EventType | str | None = None,
        status: EventProcessingStatus | None = None,
        source_service: str | None = None,
        limit: int | None = None,
    ) -> tuple[AutomationEvent, ...]:
        """Return stored events matching every given filter, most recent first.

        Args:
            tenant_id: If given, only events with this exact tenant id.
            event_type: If given, only events of this exact type.
            status: If given, only events with this exact status.
            source_service: If given, only events from this exact
                source service.
            limit: If given, return at most this many events (the most
                recent ones).

        Returns:
            A tuple of matching events, ordered newest first.
        """
        with self._lock:
            events = list(self._events)

        if tenant_id is not None:
            events = [e for e in events if e.tenant_id == tenant_id]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if status is not None:
            events = [e for e in events if e.status == status]
        if source_service is not None:
            events = [e for e in events if e.source_service == source_service]

        events.sort(key=lambda e: e.timestamp, reverse=True)
        if limit is not None:
            events = events[:limit]
        return tuple(events)

    def clear(self) -> None:
        """Remove every stored event."""
        with self._lock:
            self._events.clear()
