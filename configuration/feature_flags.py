"""Feature Flag Service for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 5.

A centralized point to enable, disable, and check the availability of
a platform capability, so "business services should never contain
hardcoded feature switches." Mirrors
``authorization.permissions.PermissionRegistry``'s shape for declaring
known flags, and reads its environment-level defaults from
:class:`~configuration.service.ConfigurationService` /
:class:`~configuration.models.EnvironmentProfile` rather than owning
any configuration of its own -- "Read configuration" (Task 5) means
literally that: this service has no state of its own beyond the
explicit runtime overrides an administrator makes via :meth:`FeatureFlagService.enable`/
:meth:`FeatureFlagService.disable` (e.g. from the Operations Dashboard).
"""

from __future__ import annotations

import logging
import threading

from configuration.exceptions import UnknownFeatureFlagError
from configuration.models import FeatureFlagDefinition
from configuration.service import ConfigurationService, configuration_service as default_configuration_service
from monitoring.service import monitoring_service

logger = logging.getLogger("novamart.configuration.feature_flags")

_SERVICE_NAME = "FeatureFlagService"


class FeatureFlagRegistry:
    """A registry of every feature flag known to the platform.

    Mirrors ``authorization.permissions.PermissionRegistry`` exactly:
    a generic lookup table with no flag-specific behavior baked in --
    *which* flags exist, and what they default to, is declared once via
    :meth:`register` calls (see :data:`DEFAULT_FEATURE_FLAGS` below),
    never a hardcoded ``if flag == "...":`` branch anywhere in the
    codebase.
    """

    def __init__(self) -> None:
        """Create an empty feature flag registry."""
        self._flags: dict[str, FeatureFlagDefinition] = {}

    def register(self, definition: FeatureFlagDefinition) -> None:
        """Register (or replace) a flag under its ``key``."""
        self._flags[definition.key] = definition

    def register_many(self, definitions: "tuple[FeatureFlagDefinition, ...] | list[FeatureFlagDefinition]") -> None:
        """Register every flag in ``definitions``."""
        for definition in definitions:
            self.register(definition)

    def get(self, key: str) -> FeatureFlagDefinition | None:
        """Look up a flag definition by key, or ``None`` if unregistered."""
        return self._flags.get(key)

    def exists(self, key: str) -> bool:
        """Return ``True`` if ``key`` matches a registered flag."""
        return key in self._flags

    def all_flags(self) -> tuple[FeatureFlagDefinition, ...]:
        """Return every registered flag definition, in registration order."""
        return tuple(self._flags.values())

    def all_keys(self) -> tuple[str, ...]:
        """Return every registered flag key, sorted."""
        return tuple(sorted(self._flags.keys()))

    def clear(self) -> None:
        """Remove every registered flag.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._flags.clear()


# The six capabilities this sprint's ticket calls out by name (Task 5).
# Adding a seventh later is one new FeatureFlagDefinition(...) entry
# here -- never a change to any business service, which never
# references this tuple directly.
DEFAULT_FEATURE_FLAGS: tuple[FeatureFlagDefinition, ...] = (
    FeatureFlagDefinition("ai_recommendation", "AI-generated business recommendations.", default_enabled=True),
    FeatureFlagDefinition("pdf_generation", "PDF export of assembled reports.", default_enabled=True),
    FeatureFlagDefinition("export_service", "CSV / Excel / JSON dataset export.", default_enabled=True),
    FeatureFlagDefinition("automation", "Scheduled jobs and event-driven notifications.", default_enabled=True),
    FeatureFlagDefinition("monitoring_dashboard", "The Monitoring administration page.", default_enabled=True),
    FeatureFlagDefinition("integration_dashboard", "The Integrations administration page.", default_enabled=True),
)


def register_default_feature_flags(registry: "FeatureFlagRegistry") -> None:
    """Register every flag in :data:`DEFAULT_FEATURE_FLAGS` into ``registry``."""
    registry.register_many(DEFAULT_FEATURE_FLAGS)


# A shared, ready-to-use registry -- mirrors
# ``authorization.permissions.permission_registry``.
feature_flag_registry = FeatureFlagRegistry()
register_default_feature_flags(feature_flag_registry)


class FeatureFlagService:
    """Centralized enable/disable/check point for every feature flag (Task 5).

    Resolution order for :meth:`is_enabled`, most specific first:

    1. An explicit runtime override set via :meth:`enable`/:meth:`disable`
       (e.g. an administrator toggling a flag from the Operations
       Dashboard).
    2. A boolean configuration value at ``FEATURE_<KEY_UPPERCASE>`` on
       the injected :class:`~configuration.service.ConfigurationService`
       (lets a deployment override a flag via an environment variable
       without any code change or redeploy).
    3. The active :class:`~configuration.models.EnvironmentProfile`'s
       ``feature_defaults`` entry for this key.
    4. The flag's own :attr:`~configuration.models.FeatureFlagDefinition.default_enabled`.

    Example:
        >>> service = FeatureFlagService()
        >>> service.is_enabled("pdf_generation")
        True
        >>> service.disable("pdf_generation")
        >>> service.is_enabled("pdf_generation")
        False
    """

    def __init__(
        self,
        *,
        configuration_service: ConfigurationService | None = None,
        registry: FeatureFlagRegistry | None = None,
    ) -> None:
        """Create a Feature Flag Service.

        Args:
            configuration_service: Used to read configuration-level
                overrides and the active environment profile. Defaults
                to the shared :data:`~configuration.service.configuration_service`.
            registry: The flag catalogue to validate keys and resolve
                defaults against. Defaults to the shared
                :data:`feature_flag_registry`.
        """
        self._configuration_service = configuration_service if configuration_service is not None else default_configuration_service
        self._registry = registry if registry is not None else feature_flag_registry
        self._overrides: dict[str, bool] = {}
        self._lock = threading.Lock()

    def is_enabled(self, key: str) -> bool:
        """Check whether a feature is currently enabled (Task 5: "Check feature availability").

        Args:
            key: The feature flag key to check.

        Returns:
            Whether the feature is currently enabled.

        Raises:
            UnknownFeatureFlagError: If ``key`` isn't a registered flag
                -- a configuration/programming error, not a normal
                "disabled" outcome, exactly like
                ``AuthorizationService.require_permission``'s
                ``UnknownPermissionError``.
        """
        definition = self._registry.get(key)
        if definition is None:
            raise UnknownFeatureFlagError(key, self._registry.all_keys())

        with self._lock:
            if key in self._overrides:
                enabled = self._overrides[key]
                source = "override"
            else:
                enabled = self._resolve_default(key, definition)
                source = "default"

        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="evaluate_feature_flag",
            message=f"Feature flag '{key}' evaluated to {enabled} (source: {source}).",
            metadata={"flag": key, "enabled": enabled, "source": source},
        )
        return enabled

    def _resolve_default(self, key: str, definition: FeatureFlagDefinition) -> bool:
        """Resolve a flag with no runtime override: configuration value, then environment default, then definition default."""
        configured = self._configuration_service.get(f"FEATURE_{key.upper()}")
        if configured is not None:
            return configured.strip().lower() in {"1", "true", "yes", "on"}

        profile = self._configuration_service.environment_profile
        if key in profile.feature_defaults:
            return profile.feature_defaults[key]

        return definition.default_enabled

    def enable(self, key: str) -> None:
        """Enable a feature via an explicit runtime override (Task 5: "Enable features").

        Args:
            key: The feature flag key to enable.

        Raises:
            UnknownFeatureFlagError: If ``key`` isn't a registered flag.
        """
        self._set_override(key, True)

    def disable(self, key: str) -> None:
        """Disable a feature via an explicit runtime override (Task 5: "Disable features").

        Args:
            key: The feature flag key to disable.

        Raises:
            UnknownFeatureFlagError: If ``key`` isn't a registered flag.
        """
        self._set_override(key, False)

    def reset(self, key: str) -> None:
        """Remove any runtime override for ``key``, reverting to configuration/environment/definition defaults."""
        with self._lock:
            self._overrides.pop(key, None)

    def _set_override(self, key: str, enabled: bool) -> None:
        if not self._registry.exists(key):
            raise UnknownFeatureFlagError(key, self._registry.all_keys())
        with self._lock:
            self._overrides[key] = enabled
        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="set_feature_flag_override",
            message=f"Feature flag '{key}' explicitly {'enabled' if enabled else 'disabled'}.",
            metadata={"flag": key, "enabled": enabled},
        )

    def all_flags(self) -> tuple[tuple[str, bool], ...]:
        """Return every registered flag key paired with its current resolved state.

        Used by the Operations Dashboard's "Feature flags" section.
        """
        return tuple((definition.key, self.is_enabled(definition.key)) for definition in self._registry.all_flags())


# A shared, ready-to-use instance -- mirrors
# ``configuration.service.configuration_service``.
feature_flag_service = FeatureFlagService()
