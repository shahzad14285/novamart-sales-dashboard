"""Environment Profile declarations for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 4.

This is the *only* place an environment's operational settings are
declared -- onboarding, or adjusting, an environment means editing one
:class:`~configuration.models.EnvironmentProfile` entry in
:data:`DEFAULT_ENVIRONMENT_PROFILES` below. No other file in the
codebase branches on ``if environment == "production":`` ("Avoid
hardcoded production values throughout the application") -- every
consumer resolves settings through
:class:`~configuration.service.ConfigurationService`, which reads from
the active profile here, exactly mirroring how ``config/tenants.py``
is the single declaration point every tenant-aware service reads
through via ``tenancy.registry.tenant_registry`` instead of branching
on a tenant id directly.
"""

from __future__ import annotations

from configuration.exceptions import UnknownEnvironmentError
from configuration.models import Environment, EnvironmentProfile, LogLevel

# The running application version, shown on the Operations Dashboard
# and included in every :class:`~configuration.models.DeploymentInfo`
# snapshot. Bump this once per release.
APP_VERSION = "0.8.0"


class EnvironmentProfileRegistry:
    """A registry of every environment profile known to the platform.

    Mirrors the registry pattern already used throughout this codebase
    -- ``tenancy.registry.TenantRegistry``,
    ``authorization.permissions.PermissionRegistry`` -- so declaring a
    new environment is the same kind of operation as onboarding a new
    tenant or permission: one ``register()`` call with a plain data
    object, never a hardcoded ``if environment == "...":`` branch
    anywhere in the codebase.

    Example:
        >>> registry = EnvironmentProfileRegistry()
        >>> registry.register(EnvironmentProfile(environment=Environment.DEVELOPMENT, ...))
        >>> registry.get(Environment.DEVELOPMENT).logging_level
        <LogLevel.DEBUG: 'debug'>
    """

    def __init__(self) -> None:
        """Create an empty environment profile registry."""
        self._profiles: dict[str, EnvironmentProfile] = {}

    def register(self, profile: EnvironmentProfile) -> None:
        """Register (or replace) a profile under its ``environment``.

        Args:
            profile: The environment profile to register.
        """
        self._profiles[profile.environment.value] = profile

    def register_many(self, profiles: "tuple[EnvironmentProfile, ...] | list[EnvironmentProfile]") -> None:
        """Register every profile in ``profiles``."""
        for profile in profiles:
            self.register(profile)

    def get(self, environment: Environment | str) -> EnvironmentProfile:
        """Look up a profile by environment.

        Args:
            environment: The environment to look up, as an
                :class:`~configuration.models.Environment` member or
                its underlying string value.

        Returns:
            The matching :class:`~configuration.models.EnvironmentProfile`.

        Raises:
            UnknownEnvironmentError: If ``environment`` doesn't match
                any registered profile.
        """
        key = environment.value if isinstance(environment, Environment) else str(environment).strip().lower()
        try:
            return self._profiles[key]
        except KeyError:
            raise UnknownEnvironmentError(key, tuple(sorted(self._profiles.keys()))) from None

    def exists(self, environment: Environment | str) -> bool:
        """Return ``True`` if ``environment`` matches a registered profile."""
        key = environment.value if isinstance(environment, Environment) else str(environment).strip().lower()
        return key in self._profiles

    def all_profiles(self) -> tuple[EnvironmentProfile, ...]:
        """Return every registered profile, in registration order."""
        return tuple(self._profiles.values())

    def clear(self) -> None:
        """Remove every registered profile.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._profiles.clear()


# --------------------------------------------------------------------------
# The three environment profiles this sprint's ticket calls out by name
# (Task 4: Development, Testing, Production). Adding a fourth later is one
# new EnvironmentProfile(...) entry here -- never a change to any business
# service or platform component, none of which reference this tuple
# directly.
# --------------------------------------------------------------------------
DEFAULT_ENVIRONMENT_PROFILES: tuple[EnvironmentProfile, ...] = (
    EnvironmentProfile(
        environment=Environment.DEVELOPMENT,
        logging_level=LogLevel.DEBUG,
        monitoring_enabled=True,
        api_rate_limit_requests_per_minute=1000,
        require_https=False,
        feature_defaults={
            "ai_recommendation": True,
            "pdf_generation": True,
            "export_service": True,
            "automation": True,
            "monitoring_dashboard": True,
            "integration_dashboard": True,
        },
        description="Local development -- verbose logging, generous rate limits, HTTPS not required.",
    ),
    EnvironmentProfile(
        environment=Environment.TESTING,
        logging_level=LogLevel.INFO,
        monitoring_enabled=True,
        api_rate_limit_requests_per_minute=300,
        require_https=False,
        feature_defaults={
            "ai_recommendation": True,
            "pdf_generation": True,
            "export_service": True,
            "automation": True,
            "monitoring_dashboard": True,
            "integration_dashboard": True,
        },
        description="Automated test runs and staging -- moderate logging, tighter rate limits than Development.",
    ),
    EnvironmentProfile(
        environment=Environment.PRODUCTION,
        logging_level=LogLevel.WARNING,
        monitoring_enabled=True,
        api_rate_limit_requests_per_minute=60,
        require_https=True,
        feature_defaults={
            "ai_recommendation": True,
            "pdf_generation": True,
            "export_service": True,
            "automation": True,
            "monitoring_dashboard": True,
            "integration_dashboard": True,
        },
        description="Live enterprise deployment -- warnings-and-above logging only, strict rate limits, HTTPS required.",
    ),
)


def register_default_environment_profiles(registry: "EnvironmentProfileRegistry") -> None:
    """Register every profile in :data:`DEFAULT_ENVIRONMENT_PROFILES` into ``registry``.

    Called once, below, at import time against the shared
    :data:`environment_profile_registry` -- mirroring
    ``config.tenants.register_default_tenants()``. A test that needs a
    clean registry can call this against its own fresh
    :class:`EnvironmentProfileRegistry` instance instead.

    Args:
        registry: The registry to populate.
    """
    registry.register_many(DEFAULT_ENVIRONMENT_PROFILES)


# A shared, ready-to-use registry -- mirrors ``tenancy.registry.tenant_registry``.
# Pre-populated with every environment profile this sprint's ticket
# requires, so the platform has a working environment catalogue the
# moment this module is imported, with zero configuration required.
environment_profile_registry = EnvironmentProfileRegistry()
register_default_environment_profiles(environment_profile_registry)
