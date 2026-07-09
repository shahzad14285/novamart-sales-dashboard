"""Event construction helpers for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Tasks 1, 3.

Mirrors ``monitoring.events.build_event`` exactly: the one place an
:class:`~automation.models.AutomationEvent` is actually constructed, so
``event_id`` generation and timestamping happen identically everywhere,
regardless of which business service published it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Mapping

from automation.models import AutomationEvent, EventProcessingStatus, EventType


def new_event_id() -> str:
    """Generate a new, unique automation event id.

    A UUID4 hex string -- globally unique without coordination, and
    storage-agnostic, mirroring ``monitoring.events.new_event_id``.
    """
    return uuid.uuid4().hex


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``.

    Centralized so every automation event's ``timestamp`` is captured
    the same way, mirroring ``monitoring.events.utc_now``.
    """
    return datetime.now(timezone.utc)


def build_event(
    *,
    event_type: EventType | str,
    source_service: str,
    status: EventProcessingStatus,
    tenant_id: str | None = None,
    tenant_name: str | None = None,
    user_id: str | None = None,
    payload: Mapping[str, object] | None = None,
) -> AutomationEvent:
    """Construct a fully-populated :class:`~automation.models.AutomationEvent`.

    This is the single place ``event_id`` and ``timestamp`` are
    generated -- callers (chiefly
    :class:`~automation.service.AutomationService`) never assign those
    fields themselves.

    Args:
        event_type: What kind of occurrence this is. Accepts a plain
            string as well as an :class:`~automation.models.EventType`
            member (Task 3: "Design for future extensibility") -- a
            brand-new event type needs no change here.
        source_service: The service announcing this event.
        status: The (already-resolved) outcome of dispatching this
            event to its handlers.
        tenant_id: The tenant this event is attributable to, if any.
        tenant_name: That tenant's display name, if any.
        user_id: The identity responsible for triggering this event, if
            known.
        payload: Optional event-type-specific structured data.

    Returns:
        A new, immutable :class:`~automation.models.AutomationEvent`.
    """
    return AutomationEvent(
        event_id=new_event_id(),
        event_type=EventType(event_type) if not isinstance(event_type, EventType) and _is_known(event_type) else event_type,
        source_service=source_service,
        timestamp=utc_now(),
        status=status,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
        user_id=user_id,
        payload=dict(payload) if payload else {},
    )


def _is_known(event_type: str) -> bool:
    """Return ``True`` if ``event_type`` matches one of the built-in :class:`EventType` values.

    Used only to decide whether to normalize a plain string into the
    real :class:`~automation.models.EventType` member (so callers that
    already have the enum keep getting it back, e.g.
    ``event.event_type is EventType.DATA_UPLOADED``) -- a genuinely
    novel, future event type string is stored and returned exactly as
    given, never coerced or rejected.

    Args:
        event_type: The candidate event type string.

    Returns:
        ``True`` if ``event_type`` is one of :class:`EventType`'s
        known values.
    """
    return event_type in {member.value for member in EventType}
