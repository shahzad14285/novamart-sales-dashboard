"""Configuration Provider Registry for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 3.

Mirrors the registry pattern already used throughout this codebase --
``identity.registry.AuthenticationProviderRegistry`` above all
(identical shape and API), plus
``monitoring.registry.MonitoringProviderRegistry`` and
``authorization.registry.AuthorizationProviderRegistry`` -- so swapping
the active configuration backend is the same kind of operation as
swapping the active identity, monitoring, or authorization backend:
one ``register()`` call with a plain object, never a code change to
:class:`~configuration.service.ConfigurationService` or to any platform
component it serves.
"""

from __future__ import annotations

from configuration.exceptions import NoActiveProviderError, ProviderNotRegisteredError
from configuration.provider import ConfigurationProvider, InMemoryConfigurationProvider


class ConfigurationProviderRegistry:
    """A registry of every configuration provider known to the platform, plus which one is active.

    Exactly one provider is "active" at a time -- the one
    :class:`~configuration.service.ConfigurationService` uses by
    default when it isn't given an explicit provider via dependency
    injection. Registering additional providers doesn't switch to them
    automatically; call :meth:`set_active` (or pass
    ``make_active=True`` to :meth:`register`) to do that explicitly.

    Example:
        >>> registry = ConfigurationProviderRegistry()
        >>> registry.register("memory", InMemoryConfigurationProvider(), make_active=True)
        >>> registry.active_name
        'memory'

        # Adding a future backend later, without touching this class or
        # ConfigurationService:
        >>> registry.register("azure_key_vault", AzureKeyVaultConfigurationProvider(...))
        >>> registry.set_active("azure_key_vault")
    """

    def __init__(self) -> None:
        """Create an empty registry with no active provider."""
        self._providers: dict[str, ConfigurationProvider] = {}
        self._active_name: str | None = None

    def register(self, name: str, provider: ConfigurationProvider, *, make_active: bool = False) -> None:
        """Register (or replace) a provider under ``name``.

        Args:
            name: A short, stable key for this provider (e.g.
                ``"memory"``, ``"environment"``, ``"azure_key_vault"``,
                ``"aws_secrets_manager"``, ``"google_secret_manager"``,
                ``"vault"``, ``"database"``).
            provider: An object satisfying the
                :class:`~configuration.provider.ConfigurationProvider`
                interface.
            make_active: If ``True``, immediately make this the active
                provider. The very first provider ever registered also
                becomes active automatically, so a single-provider
                setup needs no explicit activation call.
        """
        self._providers[name] = provider
        if make_active or self._active_name is None:
            self._active_name = name

    def get(self, name: str) -> ConfigurationProvider:
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

    def get_active(self) -> ConfigurationProvider:
        """Return the currently active provider.

        Returns:
            The active :class:`~configuration.provider.ConfigurationProvider`.

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

    def clear(self) -> None:
        """Remove every registered provider and reset the active provider to none.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._providers.clear()
        self._active_name = None


# A shared, ready-to-use registry -- mirrors
# ``identity.registry.authentication_provider_registry`` and
# ``monitoring.registry.monitoring_provider_registry``. Pre-populated
# with a default in-memory provider so the platform has a working
# configuration backend the moment this module is imported, with zero
# configuration required. ``config/production_setup.py`` (the
# composition root) registers this platform's real default values and
# an environment-variable provider on top of this.
configuration_provider_registry = ConfigurationProviderRegistry()
configuration_provider_registry.register("memory", InMemoryConfigurationProvider(), make_active=True)
