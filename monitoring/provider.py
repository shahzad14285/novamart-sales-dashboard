"""Monitoring Provider abstraction for the NovaMart Observability & Monitoring Service.

Sprint 6.4 -- Observability & Monitoring Service, Task 4.

:class:`MonitoringService` never stores an event itself -- it delegates
every bit of persistence to a **provider** satisfying the
:class:`MonitoringProvider` interface (a structural ``typing.Protocol``,
mirroring :class:`services.ai_recommendation_service.RecommendationProvider`).
The service depends only on that interface, never on a concrete
storage implementation -- which is exactly what lets business services
"simply record monitoring events" with zero awareness of *how* or
*where* those events end up.

This sprint ships :class:`InMemoryMonitoringProvider`, a
process-local, dependency-free default sufficient for a single-process
Streamlit deployment. Future providers -- SQLite, PostgreSQL,
Prometheus, Grafana, Azure Monitor, AWS CloudWatch -- are added by
writing one new class that satisfies :class:`MonitoringProvider` and
registering it via
:meth:`~monitoring.registry.MonitoringProviderRegistry.register`.
Nothing in :class:`~monitoring.service.MonitoringService`, or in any of
the nine business services it instruments, needs to change.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from monitoring.models import EventStatus, EventType, MonitoringEvent


@runtime_checkable
class MonitoringProvider(Protocol):
    """Interface every monitoring storage backend must satisfy.

    A structural ``Protocol`` (Python's "duck typing with static-typing
    support"), so a class satisfies this interface simply by having
    compatible ``record``/``list_events``/``clear`` methods -- no
    inheritance required. That's what lets a future
    ``SQLiteMonitoringProvider`` or ``PrometheusMonitoringProvider``
    plug in without touching this module or subclassing anything
    defined here.
    """

    def record(self, event: MonitoringEvent) -> None:
        """Persist one monitoring event.

        Args:
            event: The event to store. Implementations should treat
                this as opaque, immutable data -- no validation is
                expected here; :class:`~monitoring.service.MonitoringService`
                already validated it before calling this method.
        """
        ...

    def list_events(
        self,
        *,
        tenant_id: str | None = None,
        service_name: str | None = None,
        event_type: EventType | None = None,
        status: EventStatus | None = None,
        limit: int | None = None,
    ) -> tuple[MonitoringEvent, ...]:
        """Return stored events matching every given filter, most recent first.

        Args:
            tenant_id: If given, only events with this exact tenant id.
            service_name: If given, only events from this exact service.
            event_type: If given, only events of this exact type.
            status: If given, only events with this exact status.
            limit: If given, return at most this many events (the most
                recent ones).

        Returns:
            A tuple of matching events, ordered newest first.
        """
        ...

    def clear(self) -> None:
        """Remove every stored event.

        Primarily useful for tests that need a clean provider rather
        than one accumulating events across an entire test run.
        """
        ...


class InMemoryMonitoringProvider:
    """Default monitoring provider: stores events in process memory.

    Sufficient for a single-process Streamlit deployment and for
    tests. Thread-safe (guarded by a simple lock) since a Streamlit
    server may serve multiple sessions -- and therefore multiple
    monitored operations -- concurrently on the same process.

    Not persisted across restarts and not shared across multiple
    server processes -- exactly the gap a future ``SQLiteMonitoringProvider``
    or a hosted backend (Prometheus, Azure Monitor, AWS CloudWatch) is
    meant to close, with zero change required to
    :class:`~monitoring.service.MonitoringService` or the business
    services that call it.

    Example:
        >>> provider = InMemoryMonitoringProvider()
        >>> from monitoring.events import build_event
        >>> event = build_event(
        ...     service_name="KPIEngine", operation="calculate_all",
        ...     event_type=EventType.OPERATION_COMPLETED, status=EventStatus.SUCCESS,
        ... )
        >>> provider.record(event)
        >>> len(provider.list_events())
        1
    """

    def __init__(self) -> None:
        """Create an empty in-memory provider."""
        self._events: list[MonitoringEvent] = []
        self._lock = threading.Lock()

    def record(self, event: MonitoringEvent) -> None:
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
        service_name: str | None = None,
        event_type: EventType | None = None,
        status: EventStatus | None = None,
        limit: int | None = None,
    ) -> tuple[MonitoringEvent, ...]:
        """Return stored events matching every given filter, most recent first.

        Args:
            tenant_id: If given, only events with this exact tenant id.
            service_name: If given, only events from this exact service.
            event_type: If given, only events of this exact type.
            status: If given, only events with this exact status.
            limit: If given, return at most this many events (the most
                recent ones).

        Returns:
            A tuple of matching events, ordered newest first.
        """
        with self._lock:
            events = list(self._events)

        if tenant_id is not None:
            events = [e for e in events if e.tenant_id == tenant_id]
        if service_name is not None:
            events = [e for e in events if e.service_name == service_name]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if status is not None:
            events = [e for e in events if e.status == status]

        events.sort(key=lambda e: e.timestamp, reverse=True)
        if limit is not None:
            events = events[:limit]
        return tuple(events)

    def clear(self) -> None:
        """Remove every stored event."""
        with self._lock:
            self._events.clear()
