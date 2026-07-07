"""Event construction and performance timing for the NovaMart Observability & Monitoring Service.

Sprint 6.4 -- Observability & Monitoring Service, Tasks 2, 6.

Two small, single-purpose pieces live here:

- :func:`build_event` -- the one place a :class:`~monitoring.models.MonitoringEvent`
  is actually constructed, so ``event_id`` generation and timestamping
  happen identically everywhere, not once per call site.
- :class:`OperationTimer` -- the one reusable wall-clock timer every
  service's duration measurement goes through (Task 6: "Do not
  duplicate timing logic across services. Prefer reusable
  abstractions."). :class:`~monitoring.service.MonitoringService.time_operation`
  is built directly on top of it.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Mapping

from monitoring.models import EventStatus, EventType, MonitoringEvent


def new_event_id() -> str:
    """Generate a new, unique event id.

    A UUID4 hex string -- globally unique without coordination, and
    storage-agnostic (works equally well as an in-memory list key, a
    SQL primary key, or a Prometheus exemplar id for a future
    provider).
    """
    return uuid.uuid4().hex


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``.

    Centralized so every event's ``timestamp`` is captured the same
    way (mirrors ``tenancy.context.validate_tenant_context``'s use of
    ``datetime.now(timezone.utc)`` for its own log lines).
    """
    return datetime.now(timezone.utc)


def build_event(
    *,
    service_name: str,
    operation: str,
    event_type: EventType,
    status: EventStatus,
    tenant_id: str | None = None,
    tenant_name: str | None = None,
    duration_ms: float | None = None,
    message: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> MonitoringEvent:
    """Construct a fully-populated :class:`~monitoring.models.MonitoringEvent`.

    This is the single place ``event_id`` and ``timestamp`` are
    generated -- callers (chiefly
    :class:`~monitoring.service.MonitoringService`) never assign those
    fields themselves, which is what guarantees every event in the
    system is uniquely and consistently identified regardless of which
    service produced it.

    Args:
        service_name: The service producing this event.
        operation: The operation within that service.
        event_type: What kind of event this is.
        status: The outcome this event reports.
        tenant_id: The tenant this event is attributable to, if any.
        tenant_name: That tenant's display name, if any.
        duration_ms: Measured duration in milliseconds, if any.
        message: A short human-readable note, if any.
        metadata: Optional extra structured data.

    Returns:
        A new, immutable :class:`~monitoring.models.MonitoringEvent`.
    """
    return MonitoringEvent(
        event_id=new_event_id(),
        timestamp=utc_now(),
        service_name=service_name,
        operation=operation,
        event_type=event_type,
        status=status,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        duration_ms=duration_ms,
        message=message,
        metadata=dict(metadata) if metadata else {},
    )


class OperationTimer:
    """A small, reusable wall-clock timer (Task 6).

    The single implementation of "measure how long something took" in
    this platform -- every duration reported by
    :class:`~monitoring.service.MonitoringService` (directly, or via
    its ``time_operation`` context manager) is produced by an instance
    of this class, so no service ever writes its own
    ``start = time.perf_counter()`` / ``end = time.perf_counter()``
    pair.

    Uses :func:`time.perf_counter` (a monotonic clock unaffected by
    system clock adjustments), which is what makes it suitable for
    measuring elapsed *duration* -- as opposed to :func:`utc_now`,
    which is for *when* an event happened, not how long it took.

    Example:
        >>> timer = OperationTimer().start()
        >>> # ... do work ...
        >>> timer.stop()  # doctest: +SKIP
        12.4

        Or as a context manager:

        >>> with OperationTimer() as timer:
        ...     pass  # do work
        >>> timer.duration_ms is not None
        True
    """

    def __init__(self) -> None:
        """Create a timer that has not yet been started."""
        self._start: float | None = None
        self.duration_ms: float | None = None

    def start(self) -> "OperationTimer":
        """Start (or restart) the timer.

        Returns:
            ``self``, so ``OperationTimer().start()`` can be written
            in one expression.
        """
        self._start = time.perf_counter()
        self.duration_ms = None
        return self

    def stop(self) -> float:
        """Stop the timer and record the elapsed duration.

        Returns:
            The elapsed duration in milliseconds (also stored on
            :attr:`duration_ms`).

        Raises:
            RuntimeError: If :meth:`start` was never called.
        """
        if self._start is None:
            raise RuntimeError("OperationTimer.stop() called before start()")
        self.duration_ms = (time.perf_counter() - self._start) * 1000.0
        return self.duration_ms

    def __enter__(self) -> "OperationTimer":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.stop()
        return False
