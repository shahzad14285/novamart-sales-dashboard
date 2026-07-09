"""Notification value objects for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 2.

Every type here is a plain, immutable value object, matching the
convention already established by ``automation.models.AutomationEvent``
and ``monitoring.models.MonitoringEvent``. :class:`NotificationMessage`
is the single record produced every time
:class:`~notification.service.NotificationService` attempts to deliver
something -- the source of the Automation Dashboard's "Notification
History" and "Delivery Status" (Task 10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class NotificationChannel(str, Enum):
    """Which delivery channel a notification is sent through (Task 7).

    A plain ``str`` subclass, matching every other enum in this
    platform, so a member compares equal to, and can be constructed
    from, its underlying string value. Every channel this sprint's
    ticket names as a future integration target has a member here --
    only :attr:`EMAIL` (see
    :data:`notification.provider.InMemoryNotificationProvider`... note:
    this sprint's one shipped provider *simulates* delivery for every
    channel below, not just email) is exercised by a demo call site
    this sprint, but every future channel already has somewhere to
    plug in via :class:`~notification.registry.NotificationProviderRegistry`.
    """

    EMAIL = "email"
    SLACK = "slack"
    TEAMS = "teams"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    PUSH = "push"
    WEBHOOK = "webhook"


class NotificationStatus(str, Enum):
    """The delivery outcome of one :class:`NotificationMessage`."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


@dataclass(frozen=True)
class NotificationTemplate:
    """A reusable subject/body template for one kind of notification (Task 6).

    Attributes:
        template_key: Stable identifier (e.g.
            ``"event.report_generated"``), typically matching the
            :class:`~automation.models.EventType` value it is the
            default template for.
        subject_template: A ``str.format_map``-style template string
            for the notification's subject/title (e.g. ``"Report ready:
            {report_type}"``).
        body_template: A ``str.format_map``-style template string for
            the notification's body.
        description: A short, human-readable note about when this
            template is used, for an admin-facing template management
            screen.
    """

    template_key: str
    subject_template: str
    body_template: str
    description: str = ""


@dataclass(frozen=True)
class NotificationMessage:
    """One immutable record of a single notification delivery attempt.

    Attributes:
        notification_id: A unique identifier for this notification (a
            UUID4 hex string).
        event_id: The originating
            :class:`~automation.models.AutomationEvent`'s id, if this
            notification was triggered by one. ``None`` for a
            notification sent outside the automation event pipeline
            (e.g. a future direct "send test notification" admin
            action).
        channel: Which delivery channel this notification was sent
            through. See :class:`NotificationChannel`.
        recipient: Who/where this notification was sent to (an email
            address, a Slack channel name, a webhook URL -- channel-
            dependent, always a plain string so this model never needs
            to change shape per channel).
        subject: The rendered notification subject/title.
        body: The rendered notification body.
        status: The delivery outcome. See :class:`NotificationStatus`.
        created_at: When this notification was first constructed (UTC).
        sent_at: When delivery was attempted (successfully or not), or
            ``None`` if it hasn't been attempted yet.
        error: A short, business-friendly description of why delivery
            failed, or ``None`` on success/pending.
        metadata: Optional extra structured data (e.g. the originating
            event's type, the template key used).
    """

    notification_id: str
    channel: NotificationChannel
    recipient: str
    subject: str
    body: str
    status: NotificationStatus
    created_at: datetime
    event_id: str | None = None
    sent_at: datetime | None = None
    error: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
