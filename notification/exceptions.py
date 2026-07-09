"""Notification-related exceptions for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 2.

Mirrors the ``<Package>Error`` base-class convention already used by
``automation.exceptions.AutomationError`` and
``monitoring.exceptions.MonitoringError``. These exceptions are raised
only for genuine *misuse* of the notification API (an unknown template,
an unregistered channel) -- never for a delivery failure. A provider
failing to "deliver" a notification is caught by
:class:`~notification.service.NotificationService`, recorded as a
``NotificationMessage`` with :attr:`~notification.models.NotificationStatus.FAILED`,
and never raised, since Task 6 explicitly requires the service to
"handle failures gracefully."
"""

from __future__ import annotations


class NotificationError(Exception):
    """Base class for every error raised by the notification package."""


class UnknownTemplateError(NotificationError):
    """Raised when a template key doesn't match any registered template."""

    def __init__(self, template_key: str, registered: tuple[str, ...]) -> None:
        """Build a message listing what *is* registered, for easy debugging.

        Args:
            template_key: The template key that was requested.
            registered: The template keys currently registered.
        """
        self.template_key = template_key
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(f"No notification template '{template_key}' is registered. Registered: {registered_list}.")


class InvalidNotificationRequestError(NotificationError):
    """Raised when a notification is requested with missing/invalid required fields."""

    def __init__(self, reason: str) -> None:
        """Build a clear "why this notification couldn't be built" message.

        Args:
            reason: A short description of what was missing or invalid.
        """
        self.reason = reason
        super().__init__(f"Unable to send notification: {reason}.")


class ProviderNotRegisteredError(NotificationError):
    """Raised when a requested notification channel has no registered provider."""

    def __init__(self, channel: str, registered: tuple[str, ...]) -> None:
        """Build a message listing what *is* registered, for easy debugging.

        Args:
            channel: The channel key that was requested.
            registered: The channel keys currently registered.
        """
        self.channel = channel
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(
            f"No notification provider is registered for channel '{channel}'. "
            f"Registered channels: {registered_list}."
        )
