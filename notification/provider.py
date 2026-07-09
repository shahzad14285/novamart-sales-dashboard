"""Notification Provider abstraction for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 7.

:class:`~notification.service.NotificationService` never delivers a
notification itself -- it delegates every bit of transport to a
**provider** satisfying the :class:`NotificationProvider` interface (a
structural ``typing.Protocol``, mirroring
:class:`monitoring.provider.MonitoringProvider` and
:class:`identity.provider.AuthenticationProvider` exactly). The service
depends only on that interface, never on a concrete channel
implementation -- which is what keeps business services (and even
:class:`NotificationService` itself) provider-independent.

This sprint ships :class:`InMemoryNotificationProvider`, which
*simulates* delivery (Task 7: "Implement an in-memory provider that
simulates delivery") -- it never makes a network call, and always
succeeds. Future providers -- a real SMTP/SendGrid email provider, a
Slack Web API provider, a Microsoft Teams/Graph webhook provider, a
Twilio SMS/WhatsApp provider, a push notification (FCM/APNs) provider,
or a generic outbound webhook provider -- are added by writing one new
class that satisfies :class:`NotificationProvider` and registering it
under the appropriate channel key via
:meth:`~notification.registry.NotificationProviderRegistry.register`.
Nothing in :class:`~notification.service.NotificationService` needs to
change.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from notification.models import NotificationMessage


@runtime_checkable
class NotificationProvider(Protocol):
    """Interface every notification delivery backend must satisfy.

    A structural ``Protocol``, so a class satisfies this interface
    simply by having a compatible ``name`` property and ``send``
    method -- no inheritance required, exactly like
    :class:`~identity.provider.AuthenticationProvider`.
    """

    @property
    def name(self) -> str:
        """A short, human-readable name for this provider (for traceability)."""
        ...

    def send(self, message: NotificationMessage) -> NotificationMessage:
        """Attempt to deliver ``message`` and return the result.

        Args:
            message: The notification to deliver, with
                ``status=NotificationStatus.PENDING``.

        Returns:
            A copy of ``message`` with ``status``/``sent_at`` (and
            ``error``, on failure) filled in. Implementations should
            raise only for a genuinely unexpected failure (a network
            error, an invalid recipient) -- :class:`~notification.service.NotificationService`
            catches any exception here and converts it into a
            ``FAILED`` message, so a provider is free to simply return
            a failed message directly instead, whichever is more
            natural for that channel.
        """
        ...


class InMemoryNotificationProvider:
    """Default notification provider: simulates delivery, always succeeding.

    Never makes a network call and never fails -- exactly what Task 7
    asks for ("an in-memory provider that simulates delivery"). Keeps
    every "sent" message in process memory for introspection/tests,
    thread-safe via a simple lock, mirroring
    :class:`~monitoring.provider.InMemoryMonitoringProvider`.

    A single instance of this provider is registered under every
    :class:`~notification.models.NotificationChannel` this sprint ships
    with (see ``notification/registry.py``), so every channel "works"
    today via simulation -- while each channel remains independently
    swappable later (e.g. registering a real ``SendGridEmailProvider``
    under just the ``"email"`` key, leaving Slack/Teams/etc. on
    simulation, requires zero change to this class or to
    :class:`~notification.service.NotificationService`).

    Example:
        >>> provider = InMemoryNotificationProvider()
        >>> from notification.models import NotificationChannel, NotificationMessage, NotificationStatus
        >>> from datetime import datetime, timezone
        >>> pending = NotificationMessage(
        ...     notification_id="1", channel=NotificationChannel.EMAIL, recipient="exec@novamart.demo",
        ...     subject="Hi", body="Body", status=NotificationStatus.PENDING,
        ...     created_at=datetime.now(timezone.utc),
        ... )
        >>> sent = provider.send(pending)
        >>> sent.status
        <NotificationStatus.SENT: 'sent'>
    """

    name = "In-Memory Simulated Provider"

    def __init__(self) -> None:
        """Create a provider with an empty delivery log."""
        self._sent: list[NotificationMessage] = []
        self._lock = threading.Lock()

    def send(self, message: NotificationMessage) -> NotificationMessage:
        """Simulate delivering ``message``: always marks it ``SENT``.

        Args:
            message: The pending notification to "deliver".

        Returns:
            A copy of ``message`` with ``status=NotificationStatus.SENT``
            and ``sent_at`` set to now.
        """
        from dataclasses import replace

        from notification.models import NotificationStatus

        delivered = replace(message, status=NotificationStatus.SENT, sent_at=datetime.now(timezone.utc))
        with self._lock:
            self._sent.append(delivered)
        return delivered

    def sent_messages(self) -> tuple[NotificationMessage, ...]:
        """Return every message this provider has "delivered", newest first.

        Mainly useful for tests that want to assert on provider-level
        delivery without going through
        :meth:`~notification.service.NotificationService.get_history`.
        """
        with self._lock:
            return tuple(reversed(self._sent))

    def clear(self) -> None:
        """Remove every recorded delivery.

        Primarily useful for tests that need a clean provider rather
        than one accumulating messages across an entire test run.
        """
        with self._lock:
            self._sent.clear()
