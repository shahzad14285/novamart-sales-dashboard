"""Unit tests for the Production Platform's Configuration package (Sprint 6.9).

This file is part of the Task 11 deliverable: comprehensive coverage of
the ``configuration/`` package -- value objects, the Configuration
Provider abstraction (in-memory and environment-variable providers,
including provider swapping), the Configuration Provider Registry,
Environment Profiles (including environment switching), the
Configuration Service, and the Feature Flag Service, plus monitoring
integration.

Following the convention already established by ``tests/test_integration.py``
and ``tests/test_automation.py``, this file does not import
``streamlit`` or anything from ``components/``/``ui/``/``pages/``, and
never imports ``config/production_setup.py`` -- proving
``configuration/`` is usable entirely on its own. Every test constructs
its own :class:`~configuration.service.ConfigurationService` and
:class:`~configuration.feature_flags.FeatureFlagService` backed by
fresh, isolated registries via Dependency Injection rather than using
the shared, application-wide singletons, keeping tests fully isolated
from each other. The one exception is the monitoring-integration
tests, which necessarily exercise the shared
``monitoring.service.monitoring_service`` singleton -- those tests
clear its active provider before and after themselves, mirroring
``tests/test_automation.py``'s ``clean_monitoring`` fixture exactly.
"""

from __future__ import annotations

import os

import pytest

from configuration.environments import (
    APP_VERSION,
    DEFAULT_ENVIRONMENT_PROFILES,
    EnvironmentProfileRegistry,
)
from configuration.exceptions import (
    NoActiveProviderError,
    ProviderNotRegisteredError,
    UnknownEnvironmentError,
    UnknownFeatureFlagError,
)
from configuration.feature_flags import (
    DEFAULT_FEATURE_FLAGS,
    FeatureFlagRegistry,
    FeatureFlagService,
)
from configuration.models import Environment, EnvironmentProfile, FeatureFlagDefinition, LogLevel
from configuration.provider import EnvironmentVariableConfigurationProvider, InMemoryConfigurationProvider
from configuration.registry import ConfigurationProviderRegistry
from configuration.service import ConfigurationService
from monitoring.service import monitoring_service


# ==============================================================================
# Shared fixtures
# ==============================================================================


@pytest.fixture
def provider_registry() -> ConfigurationProviderRegistry:
    """A fresh, empty Configuration Provider Registry, isolated to a single test."""
    return ConfigurationProviderRegistry()


@pytest.fixture
def environment_registry() -> EnvironmentProfileRegistry:
    """A fresh Environment Profile Registry pre-populated with the three default profiles."""
    registry = EnvironmentProfileRegistry()
    registry.register_many(DEFAULT_ENVIRONMENT_PROFILES)
    return registry


@pytest.fixture
def in_memory_provider() -> InMemoryConfigurationProvider:
    """A fresh, empty in-memory configuration provider."""
    return InMemoryConfigurationProvider()


@pytest.fixture
def feature_flag_registry_fixture() -> FeatureFlagRegistry:
    """A fresh Feature Flag Registry pre-populated with the six default flags."""
    registry = FeatureFlagRegistry()
    registry.register_many(DEFAULT_FEATURE_FLAGS)
    return registry


@pytest.fixture
def clean_monitoring():
    """Clear the provider the shared ``monitoring_service`` actually writes to.

    Mirrors ``tests/test_integration.py``'s fixture of the same name
    exactly.
    """
    monitoring_service._provider.clear()
    yield
    monitoring_service._provider.clear()


# ==============================================================================
# 1. Models
# ==============================================================================


def test_environment_is_a_plain_string() -> None:
    assert Environment.DEVELOPMENT == "development"
    assert Environment.TESTING == "testing"
    assert Environment.PRODUCTION == "production"


def test_log_level_is_a_plain_string() -> None:
    assert LogLevel.DEBUG == "debug"
    assert LogLevel.INFO == "info"
    assert LogLevel.WARNING == "warning"
    assert LogLevel.ERROR == "error"


def test_environment_profile_is_frozen() -> None:
    profile = EnvironmentProfile(
        environment=Environment.DEVELOPMENT, logging_level=LogLevel.DEBUG,
        monitoring_enabled=True, api_rate_limit_requests_per_minute=100, require_https=False,
    )
    with pytest.raises(Exception):
        profile.require_https = True  # type: ignore[misc]


def test_feature_flag_definition_defaults() -> None:
    definition = FeatureFlagDefinition("my_flag", "A test flag.")
    assert definition.default_enabled is True


# ==============================================================================
# 2. Providers
# ==============================================================================


def test_in_memory_provider_get_and_set(in_memory_provider: InMemoryConfigurationProvider) -> None:
    assert in_memory_provider.get("APP_NAME") is None
    in_memory_provider.set("APP_NAME", "NovaMart")
    assert in_memory_provider.get("APP_NAME") == "NovaMart"


def test_in_memory_provider_set_many(in_memory_provider: InMemoryConfigurationProvider) -> None:
    in_memory_provider.set_many({"A": "1", "B": "2"})
    assert in_memory_provider.get("A") == "1"
    assert in_memory_provider.get("B") == "2"


def test_in_memory_provider_as_dict(in_memory_provider: InMemoryConfigurationProvider) -> None:
    in_memory_provider.set("A", "1")
    assert in_memory_provider.as_dict() == {"A": "1"}


def test_in_memory_provider_clear(in_memory_provider: InMemoryConfigurationProvider) -> None:
    in_memory_provider.set("A", "1")
    in_memory_provider.clear()
    assert in_memory_provider.as_dict() == {}


def test_in_memory_provider_constructed_with_initial_values() -> None:
    provider = InMemoryConfigurationProvider({"APP_NAME": "NovaMart"})
    assert provider.get("APP_NAME") == "NovaMart"


def test_environment_variable_provider_reads_os_environ() -> None:
    os.environ["NOVAMART_TEST_KEY_XYZ"] = "hello"
    try:
        provider = EnvironmentVariableConfigurationProvider(prefix="NOVAMART_")
        assert provider.get("TEST_KEY_XYZ") == "hello"
    finally:
        del os.environ["NOVAMART_TEST_KEY_XYZ"]


def test_environment_variable_provider_missing_key_returns_none() -> None:
    provider = EnvironmentVariableConfigurationProvider(prefix="NOVAMART_")
    assert provider.get("DEFINITELY_NOT_SET_XYZ") is None


def test_environment_variable_provider_as_dict_strips_prefix() -> None:
    os.environ["NOVAMART_ONE"] = "1"
    os.environ["UNRELATED_VAR"] = "ignored"
    try:
        provider = EnvironmentVariableConfigurationProvider(prefix="NOVAMART_")
        as_dict = provider.as_dict()
        assert as_dict.get("ONE") == "1"
        assert "UNRELATED_VAR" not in as_dict
        assert "NOVAMART_ONE" not in as_dict
    finally:
        del os.environ["NOVAMART_ONE"]
        del os.environ["UNRELATED_VAR"]


def test_provider_name_property() -> None:
    provider = InMemoryConfigurationProvider(name="custom")
    assert provider.name == "custom"


# ==============================================================================
# 3. Configuration Provider Registry (Provider Pattern + Registry Pattern)
# ==============================================================================


def test_registry_first_registered_provider_becomes_active(provider_registry: ConfigurationProviderRegistry) -> None:
    provider = InMemoryConfigurationProvider()
    provider_registry.register("memory", provider)
    assert provider_registry.active_name == "memory"
    assert provider_registry.get_active() is provider


def test_registry_no_active_provider_raises(provider_registry: ConfigurationProviderRegistry) -> None:
    with pytest.raises(NoActiveProviderError):
        provider_registry.get_active()


def test_registry_get_unregistered_provider_raises(provider_registry: ConfigurationProviderRegistry) -> None:
    with pytest.raises(ProviderNotRegisteredError):
        provider_registry.get("does-not-exist")


def test_registry_set_active_switches_provider(provider_registry: ConfigurationProviderRegistry) -> None:
    """Task 11: 'Provider Swapping' -- switching the active provider requires no code change elsewhere."""
    memory = InMemoryConfigurationProvider()
    env_provider = EnvironmentVariableConfigurationProvider(prefix="NOVAMART_")
    provider_registry.register("memory", memory, make_active=True)
    provider_registry.register("environment", env_provider)
    assert provider_registry.get_active() is memory

    provider_registry.set_active("environment")
    assert provider_registry.get_active() is env_provider
    assert provider_registry.active_name == "environment"


def test_registry_set_active_unregistered_name_raises(provider_registry: ConfigurationProviderRegistry) -> None:
    with pytest.raises(ProviderNotRegisteredError):
        provider_registry.set_active("nope")


def test_registry_registered_providers_sorted(provider_registry: ConfigurationProviderRegistry) -> None:
    provider_registry.register("zzz", InMemoryConfigurationProvider())
    provider_registry.register("aaa", InMemoryConfigurationProvider())
    assert provider_registry.registered_providers() == ("aaa", "zzz")


def test_registry_clear_resets_active(provider_registry: ConfigurationProviderRegistry) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    provider_registry.clear()
    assert provider_registry.active_name is None
    assert provider_registry.registered_providers() == ()


def test_module_level_registry_has_default_memory_provider() -> None:
    from configuration.registry import configuration_provider_registry as shared_registry

    assert "memory" in shared_registry.registered_providers()


# ==============================================================================
# 4. Environment Profiles (including environment switching)
# ==============================================================================


def test_environment_registry_has_all_three_default_profiles(environment_registry: EnvironmentProfileRegistry) -> None:
    for environment in (Environment.DEVELOPMENT, Environment.TESTING, Environment.PRODUCTION):
        assert environment_registry.exists(environment)


def test_environment_registry_get_by_string(environment_registry: EnvironmentProfileRegistry) -> None:
    profile = environment_registry.get("production")
    assert profile.environment == Environment.PRODUCTION


def test_environment_registry_unknown_environment_raises(environment_registry: EnvironmentProfileRegistry) -> None:
    with pytest.raises(UnknownEnvironmentError):
        environment_registry.get("not-a-real-environment")


def test_production_profile_is_stricter_than_development(environment_registry: EnvironmentProfileRegistry) -> None:
    dev = environment_registry.get(Environment.DEVELOPMENT)
    prod = environment_registry.get(Environment.PRODUCTION)
    assert prod.api_rate_limit_requests_per_minute < dev.api_rate_limit_requests_per_minute
    assert prod.require_https is True
    assert dev.require_https is False


def test_switching_environment_changes_the_resolved_profile(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    """Task 11: 'Environment Switching' -- the same ConfigurationService reflects whatever environment it's given."""
    dev_service = ConfigurationService(
        provider_registry=provider_registry, environment_registry=environment_registry, environment=Environment.DEVELOPMENT
    )
    prod_service = ConfigurationService(
        provider_registry=provider_registry, environment_registry=environment_registry, environment=Environment.PRODUCTION
    )
    assert dev_service.environment_profile.require_https is False
    assert prod_service.environment_profile.require_https is True


# ==============================================================================
# 5. Configuration Service
# ==============================================================================


def test_service_defaults_to_development_when_no_environment_configured(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.environment == Environment.DEVELOPMENT


def test_service_resolves_environment_from_active_provider(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider = InMemoryConfigurationProvider({"NOVAMART_ENVIRONMENT": "production"})
    provider_registry.register("memory", provider)
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.environment == Environment.PRODUCTION


def test_service_unknown_environment_value_falls_back_to_development(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider = InMemoryConfigurationProvider({"NOVAMART_ENVIRONMENT": "not-a-real-env"})
    provider_registry.register("memory", provider)
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.environment == Environment.DEVELOPMENT


def test_service_explicit_environment_overrides_provider(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider = InMemoryConfigurationProvider({"NOVAMART_ENVIRONMENT": "production"})
    provider_registry.register("memory", provider)
    service = ConfigurationService(
        provider_registry=provider_registry, environment_registry=environment_registry, environment=Environment.TESTING
    )
    assert service.environment == Environment.TESTING


def test_service_get_returns_value_when_present(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider({"APP_NAME": "NovaMart"}))
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.get("APP_NAME") == "NovaMart"


def test_service_get_returns_default_when_missing(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.get("MISSING", default="fallback") == "fallback"


def test_service_get_with_no_active_provider_never_raises(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    """The resilience guarantee: a missing provider resolves to the default, never an exception."""
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.get("ANYTHING", default="safe") == "safe"


def test_service_get_bool_parses_truthy_values(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider({"FLAG_A": "true", "FLAG_B": "0"}))
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.get_bool("FLAG_A") is True
    assert service.get_bool("FLAG_B") is False
    assert service.get_bool("MISSING", default=True) is True


def test_service_get_int_parses_or_falls_back(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider({"COUNT": "42", "BAD": "not-a-number"}))
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.get_int("COUNT") == 42
    assert service.get_int("BAD", default=7) == 7
    assert service.get_int("MISSING", default=3) == 3


def test_service_describe_reports_provenance(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider({"APP_NAME": "NovaMart"}, name="custom-memory"))
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    detail = service.describe("APP_NAME")
    assert detail.found is True
    assert detail.value == "NovaMart"
    assert detail.source == "custom-memory"


def test_service_describe_not_found(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    detail = service.describe("MISSING")
    assert detail.found is False
    assert detail.value is None


def test_service_active_provider_name(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    assert service.active_provider_name() == "memory"


def test_app_version_is_a_nonempty_string() -> None:
    assert isinstance(APP_VERSION, str)
    assert APP_VERSION


# ==============================================================================
# 6. Feature Flag Service
# ==============================================================================


def test_flag_service_default_enabled_state(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    assert flag_service.is_enabled("pdf_generation") is True


def test_flag_service_unknown_flag_raises(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    with pytest.raises(UnknownFeatureFlagError):
        flag_service.is_enabled("not_a_real_flag")


def test_flag_service_disable_then_enable_override(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)

    assert flag_service.is_enabled("pdf_generation") is True
    flag_service.disable("pdf_generation")
    assert flag_service.is_enabled("pdf_generation") is False
    flag_service.enable("pdf_generation")
    assert flag_service.is_enabled("pdf_generation") is True


def test_flag_service_reset_reverts_to_default(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)

    flag_service.disable("pdf_generation")
    assert flag_service.is_enabled("pdf_generation") is False
    flag_service.reset("pdf_generation")
    assert flag_service.is_enabled("pdf_generation") is True


def test_flag_service_enable_unknown_flag_raises(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    with pytest.raises(UnknownFeatureFlagError):
        flag_service.enable("not_a_real_flag")


def test_flag_service_configuration_override_takes_precedence_over_environment_default(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    """Resolution order: config value beats the environment profile's default."""
    provider_registry.register("memory", InMemoryConfigurationProvider({"FEATURE_PDF_GENERATION": "false"}))
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    assert flag_service.is_enabled("pdf_generation") is False


def test_flag_service_environment_default_used_when_flag_not_in_profile(
    provider_registry: ConfigurationProviderRegistry, feature_flag_registry_fixture: FeatureFlagRegistry
) -> None:
    """Falls through to the FeatureFlagDefinition's own default when the environment profile doesn't mention the flag."""
    from configuration.models import EnvironmentProfile as _EnvironmentProfile

    empty_env_registry = EnvironmentProfileRegistry()
    empty_env_registry.register(
        EnvironmentProfile(
            environment=Environment.DEVELOPMENT, logging_level=LogLevel.DEBUG,
            monitoring_enabled=True, api_rate_limit_requests_per_minute=100, require_https=False,
            feature_defaults={},  # deliberately empty
        )
    )
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=empty_env_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    assert flag_service.is_enabled("pdf_generation") is True  # definition's own default_enabled=True


def test_flag_service_all_flags_returns_every_registered_flag(
    provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    flags = dict(flag_service.all_flags())
    assert set(flags.keys()) == {definition.key for definition in DEFAULT_FEATURE_FLAGS}


def test_business_services_never_import_configuration_or_feature_flags() -> None:
    """Task 5: 'Business services should never contain hardcoded feature switches.'

    A concrete, checkable guarantee -- no business service imports the
    configuration package at all.
    """
    import ast
    import inspect

    import services.ai_recommendation_service
    import services.export_service
    import services.pdf_generator_service
    import services.reporting_service
    import utils.kpi_engine

    for module in (
        services.ai_recommendation_service, services.export_service, services.pdf_generator_service,
        services.reporting_service, utils.kpi_engine,
    ):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("configuration"), f"{module.__name__} imports configuration"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("configuration"), f"{module.__name__} imports configuration"


# ==============================================================================
# 7. Monitoring Integration (Task 9) -- shared monitoring_service, no second store
# ==============================================================================


def test_configuration_service_records_load_and_environment_events(
    clean_monitoring, provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    events = monitoring_service.get_events(service_name="ConfigurationService")
    ops = {event.operation for event in events}
    assert "load_configuration" in ops
    assert "select_environment" in ops


def test_feature_flag_service_records_evaluation_events(
    clean_monitoring, provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    flag_service.is_enabled("pdf_generation")
    events = monitoring_service.get_events(service_name="FeatureFlagService")
    assert any(event.operation == "evaluate_feature_flag" for event in events)


def test_feature_flag_service_records_override_events(
    clean_monitoring, provider_registry: ConfigurationProviderRegistry, environment_registry: EnvironmentProfileRegistry,
    feature_flag_registry_fixture: FeatureFlagRegistry,
) -> None:
    provider_registry.register("memory", InMemoryConfigurationProvider())
    config_service = ConfigurationService(provider_registry=provider_registry, environment_registry=environment_registry)
    flag_service = FeatureFlagService(configuration_service=config_service, registry=feature_flag_registry_fixture)
    flag_service.disable("pdf_generation")
    events = monitoring_service.get_events(service_name="FeatureFlagService")
    assert any(event.operation == "set_feature_flag_override" for event in events)
