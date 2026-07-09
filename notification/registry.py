"""Notification Provider Registry for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 7.

A registry of every notification provider known to the platform, keyed
by :class:`~notification.models.NotificationChannel`. Unlike
``monitoring.registry.MonitoringProviderRegistry`` (a single active
backend for one kind of data), this registry is a **routing table**: a
notification's target channel (email, Slack, Teams, ...) selects which
provider handles it, and every channel can be registered, replaced, or
added independently -- which is what "Providers are interchangeable"
(Task 11) means for a platform that has to send *different kinds* of
notifications through *different* transports at the same time, not
just one swappable backend.

Registering a real channel-specific provider later (a
``SendGridEmailProvider`` under ``"email"``, a
``SlackWebAPIProvider`` under ``"slack"``) is one ``register()`` call,
never a code change to :class:`~notification.service.NotificationService`.
"""

from __future__ import annotations

from notification.exceptions import ProviderNotRegisteredError
from notification.models import NotificationChannel
from notification.provider import InMemoryNotificationProvider, NotificationProvider


class NotificationProviderRegistry:
    """A registry mapping each notification channel to its delivery provider.

    Example:
        >>> registry = NotificationProviderRegistry()
        >>> registry.register(NotificationChannel.EMAIL, InMemoryNotificationProvider())
        >>> registry.registered_channels()
        ('email',)

        # Swapping in a real provider for one channel later, without
        # touching this class or NotificationService:
        >>> registry.register(NotificationChannel.EMAIL, SendGridEmailProvider(api_key="..."))
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._providers: dict[str, NotificationProvider] = {}

    def register(self, channel: NotificationChannel | str, provider: NotificationProvider) -> None:
        """Register (or replace) the provider used for ``channel``.

        Args:
            channel: The channel this provider delivers for.
            provider: An object satisfying the
                :class:`~notification.provider.NotificationProvider`
                interface.
        """
        key = channel.value if isinstance(channel, NotificationChannel) else str(channel)
        self._providers[key] = provider

    def get(self, channel: NotificationChannel | str) -> NotificationProvider:
        """Look up the provider registered for ``channel``.

        Args:
            channel: The channel to look up.

        Returns:
            The matching provider.

        Raises:
            ProviderNotRegisteredError: If no provider is registered
                for ``channel``.
        """
        key = channel.value if isinstance(channel, NotificationChannel) else str(channel)
        try:
            return self._providers[key]
        except KeyError:
            raise ProviderNotRegisteredError(key, tuple(self._providers.keys())) from None

    def registered_channels(self) -> tuple[str, ...]:
        """Return every channel key with a registered provider, sorted."""
        return tuple(sorted(self._providers.keys()))

    def clear(self) -> None:
        """Unregister every provider.

        Primarily useful for tests that need a pristine registry rather
        than the shared, application-wide instance.
        """
        self._providers.clear()


# A shared, ready-to-use registry -- mirrors
# ``automation.registry.automation_event_store_registry``. Pre-populated
# with a single InMemoryNotificationProvider instance registered under
# every channel this sprint's ticket names, so the platform can deliver
# (simulated) notifications on every channel the moment this module is
# imported, with zero configuration required. Each channel remains
# independently swappable later -- see the class docstring above.
notification_provider_registry = NotificationProviderRegistry()
_default_provider = InMemoryNotificationProvider()
for _channel in NotificationChannel:
    notification_provider_registry.register(_channel, _default_provider)
