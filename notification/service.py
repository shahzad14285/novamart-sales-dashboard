"""Notification Service for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Tasks 2, 6, 9.

The single entry point that turns an
:class:`~automation.models.AutomationEvent` into an actual (simulated)
notification: selecting a template, selecting a provider, sending, and
handling failures gracefully. This module has exactly one
responsibility -- notification orchestration -- and deliberately does
nothing else.

The Notification Service does NOT:
    - Decide *that* something happened (that's
      :class:`~automation.service.AutomationService`; this service only
      ever reacts to an already-published event).
    - Know how a channel actually delivers a message (that's a
      :class:`~notification.provider.NotificationProvider`, selected
      via :class:`~notification.registry.NotificationProviderRegistry`).
    - Get called directly by a business service. Task 6: "Business
      services should never send notifications directly." The only way
      this class's :meth:`handle_event` runs is as a handler registered
      on :class:`~automation.service.AutomationService` by
      ``config/automation_setup.py`` -- the one composition-root module
      allowed to import both the ``automation`` and ``notification``
      packages together (see ``docs/AUTOMATION_ARCHITECTURE.md``).
    - Ever let a delivery failure propagate. Task 6: "Handle failures
      gracefully." Every failure -- an unknown template, a missing
      route, a provider raising -- is caught and recorded as a
      ``FAILED`` :class:`~notification.models.NotificationMessage`,
      never re-raised.

Routing: which event goes to whom, on which channel
------------------------------------------------------
:class:`NotificationService` keeps a small routing table -- event type
-> ``(channel, recipient)`` -- configured via :meth:`register_route`,
mirroring the registry-based extensibility already used throughout this
platform (``services.reporting_service.ReportingService.define_report``,
``authorization.roles.RoleRegistry.register``). A handful of sensible
demo routes are registered by default (see :meth:`_register_default_routes`);
a real deployment would instead populate this from tenant-specific
notification preferences, entirely without touching this class.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from automation.models import AutomationEvent, EventType
from monitoring.service import monitoring_service
from notification.exceptions import NotificationError
from notification.models import NotificationChannel, NotificationMessage, NotificationStatus
from notification.provider import NotificationProvider
from notification.registry import NotificationProviderRegistry, notification_provider_registry
from notification.templates import TemplateRegistry, template_key_for_event_type
from notification.templates import template_registry as default_template_registry

logger = logging.getLogger("novamart.notification")

_SERVICE_NAME = "NotificationService"
_FALLBACK_TEMPLATE_KEY = "event.generic"

# A recipient resolver receives the triggering AutomationEvent and
# returns the address/channel-target a route should notify. Kept as a
# callable (not a static string) so a real deployment can resolve "the
# tenant's configured executive contact" dynamically, per event, without
# changing NotificationService itself.
RecipientResolver = Callable[[AutomationEvent], str]


def _static(recipient: str) -> RecipientResolver:
    """Build a :data:`RecipientResolver` that always returns the same address.

    A tiny helper used by :meth:`NotificationService._register_default_routes`
    for this sprint's demo routes -- a real deployment would pass a
    resolver that looks up the tenant's configured contact instead.
    """
    return lambda _event: recipient


def _event_type_key(event_type: "EventType | str") -> str:
    """Normalize an event type into a plain string key.

    ``automation.models.EventType`` is a ``str`` subclass, but (unlike
    a plain ``str``) ``str(EventType.REPORT_GENERATED)`` can render as
    ``"EventType.REPORT_GENERATED"`` depending on the Python version,
    not its ``.value``. Every place this module needs a plain string
    key (routing table lookups, template key derivation, the rendered
    ``{event_type}`` placeholder) goes through this helper instead of a
    bare ``str()`` call, so a real :class:`EventType` member and the
    equivalent plain string always resolve to the same key -- mirrors
    the identical normalization ``automation.service.AutomationService.publish``
    already applies when building its handler-lookup key.

    Args:
        event_type: An :class:`~automation.models.EventType` member or
            any other event type string.

    Returns:
        The normalized string key.
    """
    return event_type.value if isinstance(event_type, EventType) else str(event_type)


class NotificationService:
    """Turns automation events into (simulated) notifications.

    Example:
        >>> service = NotificationService()
        >>> from automation.events import build_event
        >>> from automation.models import EventProcessingStatus, EventType
        >>> event = build_event(
        ...     event_type=EventType.REPORT_GENERATED, source_service="ReportingService",
        ...     status=EventProcessingStatus.PUBLISHED, payload={"report_type": "executive"},
        ... )
        >>> messages = service.handle_event(event)
        >>> messages[0].status
        <NotificationStatus.SENT: 'sent'>
    """

    def __init__(
        self,
        provider_registry: NotificationProviderRegistry | None = None,
        template_registry: TemplateRegistry | None = None,
    ) -> None:
        """Create a Notification Service.

        Args:
            provider_registry: The channel -> provider routing table to
                use. Defaults to the shared
                :data:`~notification.registry.notification_provider_registry`.
            template_registry: The template catalogue to use. Defaults
                to the shared
                :data:`~notification.templates.template_registry`.
        """
        self._providers = provider_registry if provider_registry is not None else notification_provider_registry
        self._templates = template_registry if template_registry is not None else default_template_registry
        self._routes: dict[str, tuple[NotificationChannel, RecipientResolver]] = {}
        self._history: list[NotificationMessage] = []
        self._register_default_routes()

    # ------------------------------------------------------------------
    # Routing configuration -- extensibility without touching this class
    # ------------------------------------------------------------------
    def register_route(
        self, event_type: str, channel: NotificationChannel, recipient: str | RecipientResolver
    ) -> None:
        """Configure which channel/recipient an event type notifies.

        Calling this again for an already-routed event type replaces
        its route, which is how a tenant-specific or future admin
        settings screen would customize routing without subclassing
        this service.

        Args:
            event_type: The automation event type this route applies
                to (an ``automation.models.EventType`` value or any
                other event type string).
            channel: Which channel to notify on.
            recipient: Either a static address/target string, or a
                :data:`RecipientResolver` callable for dynamic
                resolution per event.
        """
        resolver = recipient if callable(recipient) else _static(recipient)
        self._routes[_event_type_key(event_type)] = (channel, resolver)

    def _register_default_routes(self) -> None:
        """Register this sprint's demo routing table (Task 8's suggested events).

        A real deployment would replace or extend this via
        :meth:`register_route` from tenant-configured notification
        preferences -- these defaults exist so the platform has a
        working, end-to-end notification path (Business Goal: "Notify
        executives when KPIs fall below thresholds") the moment this
        module is imported.
        """
        self.register_route("data_uploaded", NotificationChannel.EMAIL, "operations@novamart.demo")
        self.register_route("report_generated", NotificationChannel.EMAIL, "executives@novamart.demo")
        self.register_route("pdf_generated", NotificationChannel.EMAIL, "executives@novamart.demo")
        self.register_route("export_completed", NotificationChannel.EMAIL, "operations@novamart.demo")
        self.register_route("ai_analysis_completed", NotificationChannel.SLACK, "#novamart-insights")
        self.register_route("kpi_threshold_reached", NotificationChannel.SLACK, "#novamart-executives")
        self.register_route("login_failed", NotificationChannel.EMAIL, "security@novamart.demo")

    # ------------------------------------------------------------------
    # Automation event handler -- Task 6 ("receive automation events")
    # ------------------------------------------------------------------
    def handle_event(self, event: AutomationEvent) -> tuple[NotificationMessage, ...]:
        """React to a published automation event by sending its routed notification(s).

        This is the method registered as an
        :data:`~automation.service.EventHandler` on
        :class:`~automation.service.AutomationService` (by
        ``config/automation_setup.py``) -- it is never called directly
        by a business service (Task 6). An event type with no
        configured route is silently ignored (not every event needs a
        notification), which is not an error.

        Args:
            event: The published automation event to react to.

        Returns:
            The :class:`~notification.models.NotificationMessage`
            values produced (zero if this event type has no route, one
            per routed event today -- a future multi-channel fan-out
            for one event type is additive here).
        """
        route = self._routes.get(_event_type_key(event.event_type))
        if route is None:
            return ()

        channel, resolve_recipient = route
        recipient = resolve_recipient(event)
        message = self.notify(event, channel=channel, recipient=recipient)
        return (message,)

    # ------------------------------------------------------------------
    # Sending -- Task 6 ("select template", "select provider", "send", "handle failures gracefully")
    # ------------------------------------------------------------------
    def notify(
        self,
        event: AutomationEvent,
        *,
        channel: NotificationChannel,
        recipient: str,
        template_key: str | None = None,
    ) -> NotificationMessage:
        """Render a template for ``event`` and attempt delivery on ``channel``.

        Args:
            event: The automation event this notification is about.
            channel: Which channel to send on.
            recipient: Who/where to send to.
            template_key: Which template to render. Defaults to the
                template matching ``event.event_type`` (via
                :func:`~notification.templates.template_key_for_event_type`),
                falling back to a generic template if none is
                registered for that specific event type.

        Returns:
            The resulting :class:`~notification.models.NotificationMessage`,
            with ``status=SENT`` on success or ``status=FAILED`` (with
            ``error`` populated) on any failure -- this method never
            raises.
        """
        event_type_key = _event_type_key(event.event_type)
        key = template_key or template_key_for_event_type(event_type_key)
        if not self._templates.exists(key):
            key = _FALLBACK_TEMPLATE_KEY

        context = {
            "event_type": event_type_key,
            "source_service": event.source_service,
            "tenant_name": event.tenant_name or "the platform",
            "user_id": event.user_id or "unknown",
            **dict(event.payload),
        }

        try:
            subject, body = self._templates.render(key, context)
        except NotificationError as exc:
            return self._record_failure(event, channel, recipient, str(exc))

        pending = NotificationMessage(
            notification_id=uuid.uuid4().hex,
            event_id=event.event_id,
            channel=channel,
            recipient=recipient,
            subject=subject,
            body=body,
            status=NotificationStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            metadata={"template_key": key, "event_type": event_type_key},
        )

        try:
            provider = self._providers.get(channel)
        except NotificationError as exc:
            return self._record_failure(event, channel, recipient, str(exc), pending=pending)

        try:
            delivered = provider.send(pending)
        except Exception as exc:  # noqa: BLE001 - deliberately caught, see module docstring
            return self._record_failure(event, channel, recipient, str(exc), pending=pending)

        self._history.append(delivered)
        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="send_notification",
            message=f"notification sent via {channel.value} to {recipient}",
            metadata={
                "notification_id": delivered.notification_id,
                "channel": channel.value,
                "event_id": event.event_id,
                "event_type": event_type_key,
            },
        )
        return delivered

    def _record_failure(
        self,
        event: AutomationEvent,
        channel: NotificationChannel,
        recipient: str,
        error: str,
        *,
        pending: NotificationMessage | None = None,
    ) -> NotificationMessage:
        """Build a ``FAILED`` message, record it, and log a monitoring failure event.

        The one place every notification failure -- an unknown
        template, an unregistered channel, or a provider raising -- is
        turned into a stable, storable result (Task 6: "Handle failures
        gracefully").

        Args:
            event: The originating automation event.
            channel: The channel delivery was attempted on.
            recipient: The intended recipient.
            error: A short, human-readable failure description.
            pending: The ``PENDING`` message already built, if delivery
                failed after template rendering succeeded. A fresh one
                is built if template rendering itself failed.

        Returns:
            The resulting ``FAILED``
            :class:`~notification.models.NotificationMessage`.
        """
        from dataclasses import replace

        event_type_key = _event_type_key(event.event_type)

        if pending is None:
            pending = NotificationMessage(
                notification_id=uuid.uuid4().hex,
                event_id=event.event_id,
                channel=channel,
                recipient=recipient,
                subject="(template unavailable)",
                body="(template unavailable)",
                status=NotificationStatus.PENDING,
                created_at=datetime.now(timezone.utc),
            )

        failed = replace(pending, status=NotificationStatus.FAILED, sent_at=datetime.now(timezone.utc), error=error)
        self._history.append(failed)

        logger.warning("Notification delivery failed for event %s on %s: %s", event.event_id, channel.value, error)
        monitoring_service.record_failure(
            service_name=_SERVICE_NAME,
            operation="send_notification",
            error=error,
            metadata={
                "notification_id": failed.notification_id,
                "channel": channel.value,
                "event_id": event.event_id,
                "event_type": event_type_key,
            },
        )
        return failed

    # ------------------------------------------------------------------
    # Querying -- Task 10 ("notification history", "delivery status")
    # ------------------------------------------------------------------
    def get_history(
        self,
        *,
        channel: NotificationChannel | None = None,
        status: NotificationStatus | None = None,
        limit: int | None = None,
    ) -> tuple[NotificationMessage, ...]:
        """Return sent/attempted notifications matching every given filter, most recent first.

        Args:
            channel: If given, only notifications sent on this channel.
            status: If given, only notifications with this delivery status.
            limit: If given, return at most this many notifications.

        Returns:
            A tuple of matching :class:`~notification.models.NotificationMessage`
            values, newest first -- the source of the Automation
            Dashboard's "Notification History" (Task 10).
        """
        results = list(reversed(self._history))
        if channel is not None:
            results = [m for m in results if m.channel == channel]
        if status is not None:
            results = [m for m in results if m.status == status]
        if limit is not None:
            results = results[:limit]
        return tuple(results)

    def clear_history(self) -> None:
        """Remove every recorded notification.

        Primarily useful for tests that need a clean history rather
        than the shared, application-wide instance.
        """
        self._history.clear()


# A shared, ready-to-use instance -- mirrors
# ``automation.service.automation_service``. Registered as an
# automation event handler by ``config/automation_setup.py``, never
# called directly by a business service.
notification_service = NotificationService()
