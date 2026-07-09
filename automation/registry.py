"""Automation Event Store Registry for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 1.

Mirrors ``monitoring.registry.MonitoringProviderRegistry`` exactly: a
registry of every automation event store known to the platform, plus
which one is active. Swapping the active store is the same kind of
operation as adding a new KPI, export format, or monitoring backend --
one ``register()`` call, never a code change to
:class:`~automation.service.AutomationService`.
"""

from __future__ import annotations

from automation.exceptions import NoActiveProviderError, ProviderNotRegisteredError
from automation.provider import AutomationEventStore, InMemoryAutomationEventStore


class AutomationEventStoreRegistry:
    """A registry of every automation event store known to the platform, plus which one is active.

    Example:
        >>> registry = AutomationEventStoreRegistry()
        >>> registry.register("memory", InMemoryAutomationEventStore(), make_active=True)
        >>> registry.active_name
        'memory'

        # Adding a future backend later, without touching this class or AutomationService:
        >>> registry.register("kafka", KafkaAutomationEventStore("events-topic"))
        >>> registry.set_active("kafka")
    """

    def __init__(self) -> None:
        """Create an empty registry with no active store."""
        self._stores: dict[str, AutomationEventStore] = {}
        self._active_name: str | None = None

    def register(self, name: str, store: AutomationEventStore, *, make_active: bool = False) -> None:
        """Register (or replace) a store under ``name``.

        Args:
            name: A short, stable key for this store (e.g.
                ``"memory"``, ``"kafka"``, ``"sqlite"``).
            store: An object satisfying the
                :class:`~automation.provider.AutomationEventStore`
                interface.
            make_active: If ``True``, immediately make this the active
                store. The very first store ever registered also
                becomes active automatically.
        """
        self._stores[name] = store
        if make_active or self._active_name is None:
            self._active_name = name

    def get(self, name: str) -> AutomationEventStore:
        """Look up a registered store by name.

        Args:
            name: The store name to look up.

        Returns:
            The matching store.

        Raises:
            ProviderNotRegisteredError: If no store is registered under
                ``name``.
        """
        try:
            return self._stores[name]
        except KeyError:
            raise ProviderNotRegisteredError(name, tuple(self._stores.keys())) from None

    def set_active(self, name: str) -> None:
        """Make the store registered under ``name`` the active one.

        Args:
            name: The store name to activate.

        Raises:
            ProviderNotRegisteredError: If no store is registered under
                ``name``.
        """
        self.get(name)  # validates existence before switching
        self._active_name = name

    def get_active(self) -> AutomationEventStore:
        """Return the currently active store.

        Returns:
            The active :class:`~automation.provider.AutomationEventStore`.

        Raises:
            NoActiveProviderError: If no store has ever been
                registered.
        """
        if self._active_name is None:
            raise NoActiveProviderError()
        return self._stores[self._active_name]

    @property
    def active_name(self) -> str | None:
        """The name of the currently active store, or ``None`` if none is set."""
        return self._active_name

    def registered_providers(self) -> tuple[str, ...]:
        """Return every registered store name, sorted."""
        return tuple(sorted(self._stores.keys()))

    def clear(self) -> None:
        """Unregister every store and clear the active selection.

        Primarily useful for tests that need a pristine registry rather
        than the shared, application-wide instance.
        """
        self._stores.clear()
        self._active_name = None


# A shared, ready-to-use registry -- mirrors
# ``monitoring.registry.monitoring_provider_registry``. Pre-populated
# with the default in-memory store so the platform has a working
# automation backend the moment this module is imported.
automation_event_store_registry = AutomationEventStoreRegistry()
automation_event_store_registry.register("memory", InMemoryAutomationEventStore(), make_active=True)
