"""Automation Platform for the NovaMart Sales Intelligence Dashboard.

Sprint 6.7 -- Automation & Notification Platform.

A small, framework-agnostic package (no Streamlit dependency anywhere
in it) that lets every business service in the existing pipeline
announce that something happened -- and lets registered handlers (a
notification dispatch, a future workflow step) react, without either
side knowing anything about the other's implementation. See
``docs/AUTOMATION_ARCHITECTURE.md`` for the full design rationale.

Typical usage from a business service::

    from automation.service import automation_service
    from automation.models import EventType

    def generate_report(self, report_type, context, *, tenant_context=None):
        ...  # existing business logic, unchanged
        automation_service.publish(
            EventType.REPORT_GENERATED, source_service="ReportingService",
            payload={"report_type": key}, tenant_context=tenant_context,
        )

Typical usage from a composition-root wiring module (never from a
business service)::

    from automation.service import automation_service
    from automation.models import EventType
    from notification.service import notification_service

    automation_service.register_handler(EventType.REPORT_GENERATED, notification_service.handle_event)
"""

from __future__ import annotations

from automation.events import build_event
from automation.exceptions import (
    AutomationError,
    InvalidEventError,
    JobAlreadyRegisteredError,
    NoActiveProviderError,
    ProviderNotRegisteredError,
    SchedulerError,
    UnknownJobError,
)
from automation.models import (
    AutomationEvent,
    EventProcessingStatus,
    EventType,
    JobExecutionResult,
    JobStatus,
    ScheduledJob,
    ScheduleFrequency,
)
from automation.provider import AutomationEventStore, InMemoryAutomationEventStore
from automation.registry import AutomationEventStoreRegistry, automation_event_store_registry
from automation.scheduler import Scheduler, scheduler
from automation.service import ALL_EVENTS_WILDCARD, AutomationService, automation_service

__all__ = [
    "ALL_EVENTS_WILDCARD",
    "AutomationError",
    "AutomationEvent",
    "AutomationEventStore",
    "AutomationEventStoreRegistry",
    "AutomationService",
    "EventProcessingStatus",
    "EventType",
    "InMemoryAutomationEventStore",
    "InvalidEventError",
    "JobAlreadyRegisteredError",
    "JobExecutionResult",
    "JobStatus",
    "NoActiveProviderError",
    "ProviderNotRegisteredError",
    "ScheduleFrequency",
    "ScheduledJob",
    "Scheduler",
    "SchedulerError",
    "UnknownJobError",
    "automation_event_store_registry",
    "automation_service",
    "build_event",
    "scheduler",
]
