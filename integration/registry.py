"""Endpoint Registry and Integration Provider Registry for the NovaMart Integration Platform.

Sprint 6.8 -- Integration Platform & API Gateway, Tasks 3, 7.

Two registries live in this module -- the suggested package layout
allocates one ``registry.py`` slot for the whole package, and both
registries are small, single-purpose lookup tables that belong to the
same "how do we find the right X" concern:

- :class:`EndpointRegistry` (Task 3): resolves an
  ``(endpoint, method, api_version)`` triple to a registered
  :class:`~integration.models.EndpointDefinition` plus the handler
  callable that serves it. Routes are configurable data, never
  hardcoded ``if endpoint == "...":`` branches -- mirrors
  ``authorization.roles.RoleRegistry`` and
  ``notification.templates.TemplateRegistry`` exactly.
- :class:`IntegrationProviderRegistry` (Task 7): a **per-channel
  routing table** mapping each :class:`~integration.models.IntegrationChannel`
  to its :class:`~integration.provider.IntegrationProvider`, mirroring
  ``notification.registry.NotificationProviderRegistry`` exactly (not a
  single "active" backend -- REST, webhook, and every future connector
  channel can all be registered, replaced, or added independently).
"""

from __future__ import annotations

from integration.exceptions import DuplicateEndpointError, EndpointNotFoundError, ProviderNotRegisteredError
from integration.models import EndpointDefinition, IntegrationChannel, RequestMethod

# An endpoint handler receives the fully-validated IntegrationRequest
# and returns any JSON-serializable value the caller should receive
# back as IntegrationResponse.data. Keeping the signature uniform is
# what lets register() work for any future endpoint -- a KPI lookup, a
# report generation, a future workflow trigger -- without EndpointRegistry
# or the Gateway needing to know what any of them actually do.
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from integration.models import IntegrationRequest
    from integration.provider import IntegrationProvider

EndpointHandler = Callable[["IntegrationRequest"], object]


def _key(endpoint: str, method: RequestMethod | str, api_version: str) -> tuple[str, str, str]:
    """Build the composite lookup key an endpoint is registered/resolved under.

    Args:
        endpoint: The endpoint key (e.g. ``"kpi.retrieve"``).
        method: The HTTP-style method.
        api_version: The API version (e.g. ``"v1"``).

    Returns:
        A ``(endpoint, method, api_version)`` tuple, with ``method``
        normalized to its plain string value regardless of whether a
        :class:`~integration.models.RequestMethod` member or a plain
        string was given.
    """
    method_key = method.value if isinstance(method, RequestMethod) else str(method)
    return (endpoint, method_key, api_version)


class EndpointRegistry:
    """A registry of every endpoint known to the platform, plus the handler each one dispatches to.

    Example:
        >>> registry = EndpointRegistry()
        >>> registry.register(
        ...     EndpointDefinition(
        ...         endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1",
        ...     ),
        ...     handler=lambda request: {"total_revenue": 1000.0},
        ... )
        >>> registry.find("kpi.retrieve", RequestMethod.GET, "v1").endpoint_key
        'kpi.retrieve'

        # Registering a future v2 of the same logical endpoint, without
        # touching or removing v1, or changing this class:
        >>> registry.register(
        ...     EndpointDefinition(
        ...         endpoint_key="kpi.retrieve", path="/api/v2/kpi", method=RequestMethod.GET, api_version="v2",
        ...     ),
        ...     handler=lambda request: {"total_revenue": 1000.0, "currency": "USD"},
        ... )
    """

    def __init__(self) -> None:
        """Create an empty endpoint registry."""
        self._definitions: dict[tuple[str, str, str], EndpointDefinition] = {}
        self._handlers: dict[tuple[str, str, str], "EndpointHandler"] = {}

    def register(
        self, definition: EndpointDefinition, *, handler: "EndpointHandler"
    ) -> None:
        """Register a new endpoint and the handler that serves it.

        Args:
            definition: The endpoint's metadata (Task 3/4).
            handler: A callable matching :data:`EndpointHandler`'s
                signature, invoked by
                :class:`~integration.router.Router` once a request has
                passed validation, authentication, authorization, and
                rate limiting.

        Raises:
            DuplicateEndpointError: If this exact
                ``(endpoint_key, method, api_version)`` combination is
                already registered.
        """
        key = _key(definition.endpoint_key, definition.method, definition.api_version)
        if key in self._definitions:
            raise DuplicateEndpointError(definition.endpoint_key, definition.method.value, definition.api_version)
        self._definitions[key] = definition
        self._handlers[key] = handler

    def unregister(self, endpoint: str, method: RequestMethod | str, api_version: str) -> None:
        """Remove a registered endpoint. A no-op if it isn't registered.

        Args:
            endpoint: The endpoint key to remove.
            method: The method to remove.
            api_version: The API version to remove.
        """
        key = _key(endpoint, method, api_version)
        self._definitions.pop(key, None)
        self._handlers.pop(key, None)

    def find(
        self, endpoint: str, method: RequestMethod | str, api_version: str
    ) -> EndpointDefinition | None:
        """Look up an endpoint's definition, without raising if unresolved.

        A non-raising lookup used by
        :class:`~integration.validation.RequestValidator` so an
        "unknown endpoint" is reported as a normal validation failure
        rather than an exception the Gateway has to catch separately.

        Args:
            endpoint: The endpoint key to resolve.
            method: The method to resolve.
            api_version: The API version to resolve.

        Returns:
            The matching :class:`~integration.models.EndpointDefinition`,
            or ``None`` if nothing matches.
        """
        return self._definitions.get(_key(endpoint, method, api_version))

    def resolve(
        self, endpoint: str, method: RequestMethod | str, api_version: str
    ) -> tuple[EndpointDefinition, "EndpointHandler"]:
        """Look up an endpoint's definition and handler, raising if unresolved.

        Used by :class:`~integration.router.Router` -- by the time
        routing happens, :class:`~integration.validation.RequestValidator`
        has already confirmed the endpoint exists, so an
        :class:`~integration.exceptions.EndpointNotFoundError` here
        would indicate a genuine bug, not ordinary caller error.

        Args:
            endpoint: The endpoint key to resolve.
            method: The method to resolve.
            api_version: The API version to resolve.

        Returns:
            A ``(definition, handler)`` tuple.

        Raises:
            EndpointNotFoundError: If no endpoint matches.
        """
        key = _key(endpoint, method, api_version)
        definition = self._definitions.get(key)
        handler = self._handlers.get(key)
        if definition is None or handler is None:
            method_value = method.value if isinstance(method, RequestMethod) else str(method)
            raise EndpointNotFoundError(endpoint, method_value, api_version)
        return definition, handler

    def list_endpoints(self) -> tuple[EndpointDefinition, ...]:
        """Return every registered endpoint's definition, ordered for stable display.

        The source of the Integration Dashboard's "Registered
        endpoints" table (Task 10) and of future endpoint discovery
        (Task 3: "Enable future endpoint discovery").
        """
        return tuple(
            sorted(self._definitions.values(), key=lambda d: (d.endpoint_key, d.api_version, d.method.value))
        )

    def all_versions(self) -> tuple[str, ...]:
        """Return every distinct API version with at least one registered endpoint, sorted."""
        return tuple(sorted({definition.api_version for definition in self._definitions.values()}))

    def clear(self) -> None:
        """Remove every registered endpoint.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._definitions.clear()
        self._handlers.clear()


class IntegrationProviderRegistry:
    """A registry mapping each integration channel to its provider (Task 7, Provider Pattern).

    Deliberately a routing table, not a single "active" backend --
    mirrors :class:`notification.registry.NotificationProviderRegistry`
    exactly, and for the identical reason: a REST adapter and a
    Salesforce connector are never interchangeable "the current
    backend," they're simultaneously-active, independent channels.

    Example:
        >>> registry = IntegrationProviderRegistry()
        >>> registry.register(IntegrationChannel.REST_API, InMemoryIntegrationProvider())
        >>> registry.registered_channels()
        ('rest_api',)

        # Registering a real channel-specific provider later, without
        # touching this class or APIGateway:
        >>> registry.register(IntegrationChannel.SALESFORCE, SalesforceConnectorProvider(api_key="..."))
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._providers: dict[str, "IntegrationProvider"] = {}

    def register(self, channel: IntegrationChannel | str, provider: "IntegrationProvider") -> None:
        """Register (or replace) the provider used for ``channel``.

        Args:
            channel: The channel this provider represents.
            provider: An object satisfying the
                :class:`~integration.provider.IntegrationProvider`
                interface.
        """
        key = channel.value if isinstance(channel, IntegrationChannel) else str(channel)
        self._providers[key] = provider

    def get(self, channel: IntegrationChannel | str) -> "IntegrationProvider":
        """Look up the provider registered for ``channel``.

        Args:
            channel: The channel to look up.

        Returns:
            The matching provider.

        Raises:
            ProviderNotRegisteredError: If no provider is registered
                for ``channel``.
        """
        key = channel.value if isinstance(channel, IntegrationChannel) else str(channel)
        try:
            return self._providers[key]
        except KeyError:
            raise ProviderNotRegisteredError(key, tuple(self._providers.keys())) from None

    def registered_channels(self) -> tuple[str, ...]:
        """Return every channel key with a registered provider, sorted.

        The source of the Integration Dashboard's "Integration provider
        status" section (Task 10).
        """
        return tuple(sorted(self._providers.keys()))

    def clear(self) -> None:
        """Unregister every provider.

        Primarily useful for tests that need a pristine registry rather
        than the shared, application-wide instance.
        """
        self._providers.clear()


# Shared, ready-to-use registries -- mirror
# ``automation.registry.automation_event_store_registry`` and
# ``notification.registry.notification_provider_registry``. Populated
# with the platform's default endpoints/providers by
# ``config/integration_setup.py`` (endpoints) and at import time below
# (the in-memory provider, registered under every channel this sprint's
# ticket names, exactly like NotificationProviderRegistry's default
# population -- see notification/registry.py for the identical
# rationale).
endpoint_registry = EndpointRegistry()

integration_provider_registry = IntegrationProviderRegistry()


def _register_default_providers() -> None:
    """Populate :data:`integration_provider_registry` with the default in-memory provider.

    Deferred into a function (rather than inline module-level code) so
    the provider import -- which itself imports this module for
    :class:`IntegrationProviderRegistry` -- never creates a circular
    import at module-load time; called once, at the bottom of this
    module.
    """
    from integration.provider import InMemoryIntegrationProvider

    default_provider = InMemoryIntegrationProvider()
    for channel in IntegrationChannel:
        integration_provider_registry.register(channel, default_provider)


_register_default_providers()
