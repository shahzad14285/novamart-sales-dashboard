"""Notification Platform for the NovaMart Sales Intelligence Dashboard.

Sprint 6.7 -- Automation & Notification Platform, Task 2.

A dedicated package for turning an
:class:`~automation.models.AutomationEvent` into an actual notification
-- template selection, provider selection, sending, and graceful
failure handling. Notification is one *consumer* of automation events,
never a producer: business services publish events through
``automation.service.automation_service``; only
``config/automation_setup.py`` (the one composition-root module allowed
to import both packages) wires :class:`~notification.service.NotificationService.handle_event`
in as a registered automation handler. See
``docs/AUTOMATION_ARCHITECTURE.md`` for the full design rationale.
"""

from __future__ import annotations

from notification.exceptions import (
    InvalidNotificationRequestError,
    NotificationError,
    ProviderNotRegisteredError,
    UnknownTemplateError,
)
from notification.models import NotificationChannel, NotificationMessage, NotificationStatus, NotificationTemplate
from notification.provider import InMemoryNotificationProvider, NotificationProvider
from notification.registry import NotificationProviderRegistry, notification_provider_registry
from notification.service import NotificationService, notification_service
from notification.templates import TemplateRegistry, template_key_for_event_type, template_registry

__all__ = [
    "InMemoryNotificationProvider",
    "InvalidNotificationRequestError",
    "NotificationChannel",
    "NotificationError",
    "NotificationMessage",
    "NotificationProvider",
    "NotificationProviderRegistry",
    "NotificationService",
    "NotificationStatus",
    "NotificationTemplate",
    "ProviderNotRegisteredError",
    "TemplateRegistry",
    "UnknownTemplateError",
    "notification_provider_registry",
    "notification_service",
    "template_key_for_event_type",
    "template_registry",
]
