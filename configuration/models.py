"""Configuration value objects for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 1.

Every type here is a plain, immutable value object -- no behavior, no
storage, no Streamlit dependency -- matching the convention already
established by ``tenancy.models.Tenant``, ``integration.models.EndpointDefinition``,
and ``automation.models.ScheduledJob``. :class:`ConfigurationService`
(``configuration/service.py``) and :class:`FeatureFlagService`
(``configuration/feature_flags.py``) are the only things in this
package that hold behavior; everything below is data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class Environment(str, Enum):
    """Which deployment environment the platform is currently running under (Task 4).

    A plain ``str`` subclass (matching ``tenancy.models.TenantStatus``
    and every other enum in this platform), so a member compares equal
    to, and can be constructed from, its underlying string value --
    important here specifically, since the active environment is
    typically resolved from a raw string (an environment variable or a
    config file value), not a Python literal.
    """

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """A logging verbosity level, as declared by an :class:`EnvironmentProfile`."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class EnvironmentProfile:
    """The operational settings one :class:`Environment` provides (Task 4).

    Every environment this platform supports (Development, Testing,
    Production) is declared once as one of these, in
    ``configuration/environments.py`` -- never as scattered
    ``if environment == "production":`` checks throughout the
    application ("Avoid hardcoded production values throughout the
    application").

    Attributes:
        environment: Which :class:`Environment` this profile describes.
        logging_level: The logging verbosity this environment runs at.
        monitoring_enabled: Whether the Monitoring Platform should be
            considered active for this environment. Development can
            still enable it (there is no harm and it is useful for
            local debugging); a future environment could disable it.
        api_rate_limit_requests_per_minute: The default per-minute
            ceiling :class:`~integration.rate_limiter.RateLimiter`
            should use for this environment when an endpoint doesn't
            declare its own policy (a stricter default in Production
            than in Development, for example).
        require_https: Whether the deployment strategy for this
            environment requires HTTPS termination in front of the
            application (a documentation/deployment-checklist flag --
            this platform ships no real HTTP server, see
            ``docs/PRODUCTION_ARCHITECTURE.md``).
        feature_defaults: The default enabled/disabled state of every
            known feature flag under this environment, keyed by flag
            key. :class:`~configuration.feature_flags.FeatureFlagService`
            consults this when neither an explicit runtime override nor
            a configuration-provider value exists for a flag.
        description: A short, human-readable summary shown on the
            Operations Dashboard.
    """

    environment: Environment
    logging_level: LogLevel
    monitoring_enabled: bool
    api_rate_limit_requests_per_minute: int
    require_https: bool
    feature_defaults: Mapping[str, bool] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class ConfigurationValue:
    """One resolved configuration lookup, with provenance (Task 2, Task 10).

    Returned by :meth:`~configuration.service.ConfigurationService.describe`
    so the Operations Dashboard's "Configuration summary" can show not
    just a value but *where it came from* -- important for diagnosing a
    misconfigured deployment ("why is this key still using the
    in-memory default instead of the environment variable I set?").

    Attributes:
        key: The configuration key that was looked up.
        value: The resolved value, or ``None`` if no provider had it.
        source: The name of the provider that supplied ``value`` (see
            :class:`~configuration.registry.ConfigurationProviderRegistry`),
            or ``None`` if the value came from the environment
            profile's defaults, or ``"default"`` if a caller-supplied
            fallback was used, or ``None`` entirely if unresolved.
        found: Whether a value was found at all, at any source.
    """

    key: str
    value: str | None
    source: str | None
    found: bool


@dataclass(frozen=True)
class FeatureFlagDefinition:
    """One capability that can be toggled on or off platform-wide (Task 5).

    Declared once in :data:`~configuration.feature_flags.DEFAULT_FEATURE_FLAGS`,
    mirroring how :class:`~authorization.permissions.Permission` is
    declared once in ``authorization.permissions.DEFAULT_PERMISSIONS`` --
    a brand-new flag is one more entry there, never a hardcoded
    ``if some_condition:`` switch buried inside a business service
    ("Business services should never contain hardcoded feature
    switches").

    Attributes:
        key: The stable identifier used everywhere this flag needs to
            be checked, toggled, or displayed (e.g.
            ``"ai_recommendation"``).
        description: A short, human-readable explanation of what this
            flag controls, suitable for the Operations Dashboard.
        default_enabled: Whether this flag is enabled when neither an
            explicit runtime override nor the active
            :class:`EnvironmentProfile` says otherwise.
    """

    key: str
    description: str
    default_enabled: bool = True


@dataclass(frozen=True)
class DeploymentInfo:
    """A snapshot of what is deployed, where, and how (Task 7, Task 10).

    A plain, read-only summary -- never used to *make* deployment
    decisions (that is a human/CI concern, out of scope for this
    sprint's "the objective is architecture" boundary) -- only to
    *display* them on the Operations Dashboard and to feed
    :class:`~operations.readiness.ReadinessService`'s checks.

    Attributes:
        environment: The active :class:`Environment`.
        version: The running application version (see
            ``configuration/environments.py``'s ``APP_VERSION``).
        deployment_strategy: A short, human-readable description of how
            this environment is deployed (see
            ``docs/PRODUCTION_ARCHITECTURE.md``'s Deployment Strategy
            section for the full explanation this summarizes).
        build_metadata: Optional, free-form extra data (a commit hash,
            a build timestamp, a CI run id) -- mirrors
            ``tenancy.models.Tenant.metadata``'s "future expansion"
            role.
        generated_at: When this snapshot was produced.
    """

    environment: Environment
    version: str
    deployment_strategy: str
    build_metadata: Mapping[str, str] = field(default_factory=dict)
    generated_at: datetime | None = None
