"""Configuration Service for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 2.

The single centralized point every platform component resolves
configuration through -- "Platform components should never own
configuration." Delegates every actual value lookup to whichever
:class:`~configuration.provider.ConfigurationProvider` is currently
active (Task 3), and every environment-specific default to the active
:class:`~configuration.models.EnvironmentProfile` (Task 4); this
service itself holds no configuration values of its own, only the
orchestration logic to resolve them consistently.

Mirrors the shape of :class:`~identity.service.AuthenticationService`
and :class:`~authorization.service.AuthorizationService` exactly:
constructor-injected dependencies defaulting to shared, module-level
singletons, a resilience guarantee (a missing provider or key never
raises out to a caller -- it resolves to ``None``/a supplied default),
and every meaningful action recorded to the existing
:data:`~monitoring.service.monitoring_service` (Task 9).
"""

from __future__ import annotations

import logging

from configuration.environments import environment_profile_registry as default_environment_registry
from configuration.exceptions import NoActiveProviderError
from configuration.models import ConfigurationValue, Environment, EnvironmentProfile
from configuration.registry import ConfigurationProviderRegistry, configuration_provider_registry as default_provider_registry
from monitoring.service import monitoring_service

logger = logging.getLogger("novamart.configuration.service")

_SERVICE_NAME = "ConfigurationService"
_ENVIRONMENT_KEY = "NOVAMART_ENVIRONMENT"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class ConfigurationService:
    """Centralized configuration resolution point (Task 2).

    Example:
        >>> service = ConfigurationService()
        >>> service.environment
        <Environment.DEVELOPMENT: 'development'>
        >>> service.get("APP_NAME", default="NovaMart")
        'NovaMart'
    """

    def __init__(
        self,
        *,
        provider_registry: ConfigurationProviderRegistry | None = None,
        environment_registry=None,
        environment: Environment | str | None = None,
    ) -> None:
        """Create a Configuration Service.

        Args:
            provider_registry: The provider catalogue to resolve values
                against. Defaults to the shared
                :data:`~configuration.registry.configuration_provider_registry`.
            environment_registry: The environment profile catalogue.
                Defaults to the shared
                :data:`~configuration.environments.environment_profile_registry`.
            environment: An explicit environment to use, overriding
                whatever the active provider says. Tests and a future
                CLI flag use this; application code normally omits it
                and lets the active provider's ``NOVAMART_ENVIRONMENT``
                value (or the ``DEVELOPMENT`` default) decide.
        """
        self._provider_registry = provider_registry if provider_registry is not None else default_provider_registry
        self._environment_registry = environment_registry if environment_registry is not None else default_environment_registry
        self._environment = self._resolve_environment(environment)
        self._record_configuration_loaded()

    # ------------------------------------------------------------------
    # Environment resolution -- Task 2 ("load environment settings")
    # ------------------------------------------------------------------
    def _resolve_environment(self, explicit: Environment | str | None) -> Environment:
        """Resolve which :class:`~configuration.models.Environment` is active."""
        if explicit is not None:
            return explicit if isinstance(explicit, Environment) else Environment(str(explicit).strip().lower())

        raw = self._safe_get_raw(_ENVIRONMENT_KEY)
        if not raw:
            return Environment.DEVELOPMENT
        try:
            return Environment(raw.strip().lower())
        except ValueError:
            logger.warning("Unknown environment '%s' from configuration -- defaulting to development.", raw)
            return Environment.DEVELOPMENT

    @property
    def environment(self) -> Environment:
        """The currently resolved deployment environment."""
        return self._environment

    @property
    def environment_profile(self) -> EnvironmentProfile:
        """The :class:`~configuration.models.EnvironmentProfile` for the current environment."""
        return self._environment_registry.get(self._environment)

    # ------------------------------------------------------------------
    # Value resolution -- Task 2 ("provide configuration", "resolve
    # configuration values")
    # ------------------------------------------------------------------
    def _safe_get_raw(self, key: str) -> str | None:
        """Look up ``key`` on the active provider, never raising for a missing provider or key."""
        try:
            provider = self._provider_registry.get_active()
        except NoActiveProviderError:
            return None
        return provider.get(key)

    def get(self, key: str, default: str | None = None) -> str | None:
        """Resolve a raw string configuration value.

        Args:
            key: The configuration key to look up.
            default: The value to return if no provider has ``key``.

        Returns:
            The resolved value, or ``default``.
        """
        value = self._safe_get_raw(key)
        return value if value is not None else default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Resolve a configuration value as a boolean (``"true"``/``"1"``/``"yes"``/``"on"``, case-insensitive)."""
        raw = self._safe_get_raw(key)
        if raw is None:
            return default
        return raw.strip().lower() in _TRUE_VALUES

    def get_int(self, key: str, default: int = 0) -> int:
        """Resolve a configuration value as an integer, falling back to ``default`` if unset or unparsable."""
        raw = self._safe_get_raw(key)
        if raw is None:
            return default
        try:
            return int(raw.strip())
        except ValueError:
            logger.warning("Configuration key '%s' has a non-integer value '%s' -- using default %s.", key, raw, default)
            return default

    def describe(self, key: str) -> ConfigurationValue:
        """Resolve ``key`` with provenance, for the Operations Dashboard's configuration summary.

        Args:
            key: The configuration key to describe.

        Returns:
            A :class:`~configuration.models.ConfigurationValue` showing
            the resolved value and which provider supplied it (or that
            it wasn't found at all).
        """
        try:
            provider = self._provider_registry.get_active()
        except NoActiveProviderError:
            return ConfigurationValue(key=key, value=None, source=None, found=False)
        value = provider.get(key)
        if value is not None:
            return ConfigurationValue(key=key, value=value, source=provider.name, found=True)
        return ConfigurationValue(key=key, value=None, source=None, found=False)

    def active_provider_name(self) -> str | None:
        """The name of the currently active configuration provider, or ``None`` if none is active."""
        return self._provider_registry.active_name

    def registered_provider_names(self) -> tuple[str, ...]:
        """Every configuration provider name currently registered, sorted."""
        return self._provider_registry.registered_providers()

    # ------------------------------------------------------------------
    # Monitoring integration -- Task 9 ("Record: Configuration loading,
    # Environment selection")
    # ------------------------------------------------------------------
    def _record_configuration_loaded(self) -> None:
        """Record that configuration was loaded and an environment was selected (Task 9).

        Two distinct monitoring events -- ``load_configuration`` and
        ``select_environment`` -- so the Operations Dashboard and tests
        can filter on either independently, mirroring how
        :class:`~integration.gateway.APIGateway` records each lifecycle
        step as its own operation rather than one combined event.
        """
        try:
            active_provider = self._provider_registry.active_name
        except Exception:  # noqa: BLE001 - never let a monitoring lookup break configuration loading
            active_provider = None

        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="load_configuration",
            message="Configuration loaded.",
            metadata={"active_provider": active_provider, "registered_providers": list(self.registered_provider_names())},
        )
        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="select_environment",
            message=f"Environment resolved to '{self._environment.value}'.",
            metadata={"environment": self._environment.value},
        )


# A shared, ready-to-use instance -- mirrors
# ``identity.service.authentication_service`` and
# ``authorization.service.authorization_service``. Every platform
# component that needs configuration and doesn't have one explicitly
# injected uses this instance.
configuration_service = ConfigurationService()
