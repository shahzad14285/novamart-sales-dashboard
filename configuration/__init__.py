"""Configuration Platform for the NovaMart Sales Intelligence Dashboard.

Sprint 6.9 -- Production Readiness Platform.

A small, framework-agnostic package (no Streamlit dependency anywhere
in it) that becomes the single source of configuration, environment
profiles, and feature flags for every platform component. See
``docs/PRODUCTION_ARCHITECTURE.md`` for the full design rationale.

Typical usage from any platform component (never a business service --
see Task 8 in the architecture doc)::

    from configuration.service import configuration_service
    from configuration.feature_flags import feature_flag_service

    if feature_flag_service.is_enabled("pdf_generation"):
        ...

    api_rate_limit = configuration_service.environment_profile.api_rate_limit_requests_per_minute

Typical usage from a composition-root wiring module (never from a
business service)::

    from configuration.provider import EnvironmentVariableConfigurationProvider
    from configuration.registry import configuration_provider_registry

    configuration_provider_registry.register(
        "environment", EnvironmentVariableConfigurationProvider(prefix="NOVAMART_"), make_active=True
    )
"""

from __future__ import annotations

from configuration.environments import (
    APP_VERSION,
    DEFAULT_ENVIRONMENT_PROFILES,
    EnvironmentProfileRegistry,
    environment_profile_registry,
)
from configuration.exceptions import (
    ConfigurationError,
    MissingConfigurationKeyError,
    NoActiveProviderError,
    ProviderNotRegisteredError,
    UnknownEnvironmentError,
    UnknownFeatureFlagError,
)
from configuration.feature_flags import (
    DEFAULT_FEATURE_FLAGS,
    FeatureFlagRegistry,
    FeatureFlagService,
    feature_flag_registry,
    feature_flag_service,
)
from configuration.models import (
    ConfigurationValue,
    DeploymentInfo,
    Environment,
    EnvironmentProfile,
    FeatureFlagDefinition,
    LogLevel,
)
from configuration.provider import (
    ConfigurationProvider,
    EnvironmentVariableConfigurationProvider,
    InMemoryConfigurationProvider,
)
from configuration.registry import ConfigurationProviderRegistry, configuration_provider_registry
from configuration.service import ConfigurationService, configuration_service

__all__ = [
    "APP_VERSION",
    "DEFAULT_ENVIRONMENT_PROFILES",
    "DEFAULT_FEATURE_FLAGS",
    "ConfigurationError",
    "ConfigurationProvider",
    "ConfigurationProviderRegistry",
    "ConfigurationService",
    "ConfigurationValue",
    "DeploymentInfo",
    "Environment",
    "EnvironmentProfile",
    "EnvironmentProfileRegistry",
    "EnvironmentVariableConfigurationProvider",
    "FeatureFlagDefinition",
    "FeatureFlagRegistry",
    "FeatureFlagService",
    "InMemoryConfigurationProvider",
    "LogLevel",
    "MissingConfigurationKeyError",
    "NoActiveProviderError",
    "ProviderNotRegisteredError",
    "UnknownEnvironmentError",
    "UnknownFeatureFlagError",
    "configuration_provider_registry",
    "configuration_service",
    "environment_profile_registry",
    "feature_flag_registry",
    "feature_flag_service",
]
