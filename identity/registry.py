"""Authentication Provider Registry for the NovaMart Identity &
Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Task 6.

Mirrors the registry pattern already used throughout this codebase --
``authorization.registry.AuthorizationProviderRegistry`` above all
(identical shape and API), plus
``monitoring.registry.MonitoringProviderRegistry`` -- so swapping the
active identity backend is the same kind of operation as swapping the
active authorization or monitoring backend: one ``register()`` call
with a plain object, never a code change to
:class:`~identity.service.AuthenticationService` or to any business
service or UI call site it serves.
"""

from __future__ import annotations

from identity.exceptions import NoActiveProviderError, ProviderNotRegisteredError
from identity.provider import AuthenticationProvider, InMemoryAuthenticationProvider


class AuthenticationProviderRegistry:
    """A registry of every authentication provider known to the platform, plus which one is active.

    Exactly one provider is "active" at a time -- the one
    :class:`~identity.service.AuthenticationService` uses by default
    when it isn't given an explicit provider via dependency injection.
    Registering additional providers doesn't switch to them
    automatically; call :meth:`set_active` (or pass
    ``make_active=True`` to :meth:`register`) to do that explicitly.

    Example:
        >>> registry = AuthenticationProviderRegistry()
        >>> registry.register("memory", InMemoryAuthenticationProvider(), make_active=True)
        >>> registry.active_name
        'memory'

        # Adding a future identity backend later, without touching this
        # class or AuthenticationService:
        >>> registry.register("entra_id", EntraIDAuthenticationProvider(...))
        >>> registry.set_active("entra_id")
    """

    def __init__(self) -> None:
        """Create an empty registry with no active provider."""
        self._providers: dict[str, AuthenticationProvider] = {}
        self._active_name: str | None = None

    def register(self, name: str, provider: AuthenticationProvider, *, make_active: bool = False) -> None:
        """Register (or replace) a provider under ``name``.

        Args:
            name: A short, stable key for this provider (e.g.
                ``"memory"``, ``"database"``, ``"ldap"``, ``"entra_id"``,
                ``"google"``, ``"okta"``, ``"auth0"``).
            provider: An object satisfying the
                :class:`~identity.provider.AuthenticationProvider`
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

    def get(self, name: str) -> AuthenticationProvider:
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

    def get_active(self) -> AuthenticationProvider:
        """Return the currently active provider.

        Returns:
            The active :class:`~identity.provider.AuthenticationProvider`.

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


# A shared, ready-to-use registry -- mirrors
# ``authorization.registry.authorization_provider_registry`` and
# ``monitoring.registry.monitoring_provider_registry``. Pre-populated
# with the default in-memory provider so the platform has a working
# authentication backend the moment this module is imported, with zero
# configuration required for this sprint's requirements.
authentication_provider_registry = AuthenticationProviderRegistry()
authentication_provider_registry.register("memory", InMemoryAuthenticationProvider(), make_active=True)
