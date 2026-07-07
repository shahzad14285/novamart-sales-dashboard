"""Monitoring Provider Registry for the NovaMart Observability & Monitoring Service.

Sprint 6.4 -- Observability & Monitoring Service, Task 4.

Mirrors the registry pattern already used throughout this codebase --
``utils.kpi_engine.KPIEngine.register``,
``services.export_service.ExportService.register``,
``services.pdf_generator_service.PDFGeneratorService.register_content_renderer``,
and ``tenancy.registry.TenantRegistry`` -- so swapping the active
monitoring backend is the same kind of operation as adding a new KPI,
export format, or tenant: one ``register()`` call with a plain object,
never a code change to :class:`~monitoring.service.MonitoringService`
or to any of the business services it instruments.
"""

from __future__ import annotations

from monitoring.exceptions import NoActiveProviderError, ProviderNotRegisteredError
from monitoring.provider import InMemoryMonitoringProvider, MonitoringProvider


class MonitoringProviderRegistry:
    """A registry of every monitoring provider known to the platform, plus which one is active.

    Exactly one provider is "active" at a time -- the one
    :class:`~monitoring.service.MonitoringService` uses by default when
    it isn't given an explicit provider via dependency injection (see
    :class:`~monitoring.service.MonitoringService`'s constructor).
    Registering additional providers doesn't switch to them
    automatically; call :meth:`set_active` (or pass ``make_active=True``
    to :meth:`register`) to do that explicitly.

    Example:
        >>> registry = MonitoringProviderRegistry()
        >>> registry.register("memory", InMemoryMonitoringProvider(), make_active=True)
        >>> registry.active_name
        'memory'

        # Adding a future backend later, without touching this class or
        # MonitoringService:
        >>> registry.register("sqlite", SQLiteMonitoringProvider("monitoring.db"))
        >>> registry.set_active("sqlite")
    """

    def __init__(self) -> None:
        """Create an empty registry with no active provider."""
        self._providers: dict[str, MonitoringProvider] = {}
        self._active_name: str | None = None

    def register(self, name: str, provider: MonitoringProvider, *, make_active: bool = False) -> None:
        """Register (or replace) a provider under ``name``.

        Args:
            name: A short, stable key for this provider (e.g.
                ``"memory"``, ``"sqlite"``, ``"prometheus"``).
            provider: An object satisfying the
                :class:`~monitoring.provider.MonitoringProvider`
                interface.
            make_active: If ``True``, immediately make this the active
                provider. The very first provider ever registered also
                becomes active automatically, so a single-provider
                setup (this sprint's default) needs no explicit
                activation call.
        """
        self._providers[name] = provider
        if make_active or self._active_name is None:
            self._active_name = name

    def get(self, name: str) -> MonitoringProvider:
        """Look up a registered provider by name.

        Args:
            name: The provider name to look up.

        Returns:
            The matching provider.

        Raises:
            ProviderNotRegisteredError: If no provider is registered
                under ``name``.
        """
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderNotRegisteredError(name, tuple(self._providers.keys())) from None

    def set_active(self, name: str) -> None:
        """Make the provider registered under ``name`` the active one.

        Args:
            name: The provider name to activate.

        Raises:
            ProviderNotRegisteredError: If no provider is registered
                under ``name``.
        """
        self.get(name)  # validates existence before switching
        self._active_name = name

    def get_active(self) -> MonitoringProvider:
        """Return the currently active provider.

        Returns:
            The active :class:`~monitoring.provider.MonitoringProvider`.

        Raises:
            NoActiveProviderError: If no provider has ever been
                registered.
        """
        if self._active_name is None:
            raise NoActiveProviderError()
        return self._providers[self._active_name]

    @property
    def active_name(self) -> str | None:
        """The name of the currently active provider, or ``None`` if none is set."""
        return self._active_name

    def registered_providers(self) -> tuple[str, ...]:
        """Return every registered provider name, sorted."""
        return tuple(sorted(self._providers.keys()))


# A shared, ready-to-use registry -- mirrors ``tenancy.registry.tenant_registry``.
# Pre-populated with the default in-memory provider so the platform has
# a working monitoring backend the moment this module is imported, with
# zero configuration required for this sprint's requirements.
monitoring_provider_registry = MonitoringProviderRegistry()
monitoring_provider_registry.register("memory", InMemoryMonitoringProvider(), make_active=True)
