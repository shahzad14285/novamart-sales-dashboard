"""Unit tests for the Production Platform's Operations package (Sprint 6.9).

This file is part of the Task 11 deliverable: comprehensive coverage of
the ``operations/`` package -- value objects, the Health Check Service
(registry, aggregation, resilience), the Readiness Service (including
the concrete Health-vs-Readiness distinction the ticket calls out by
name), Deployment information, and monitoring integration.

Following the convention already established by ``tests/test_integration.py``
and ``tests/test_configuration.py``, this file does not import
``streamlit`` or anything from ``components/``/``ui/``/``pages/``, and
never imports ``config/production_setup.py``. Every test constructs its
own :class:`~operations.health.HealthCheckService` and
:class:`~operations.readiness.ReadinessService` backed by fresh,
isolated registries via Dependency Injection. The one exception is the
monitoring-integration tests, which necessarily exercise the shared
``monitoring.service.monitoring_service`` singleton -- those tests
clear its active provider before and after themselves.
"""

from __future__ import annotations

import pytest

from configuration.environments import DEFAULT_ENVIRONMENT_PROFILES, EnvironmentProfileRegistry
from configuration.models import Environment
from configuration.provider import InMemoryConfigurationProvider
from configuration.registry import ConfigurationProviderRegistry
from configuration.service import ConfigurationService
from monitoring.service import monitoring_service
from operations.deployment import build_deployment_info
from operations.exceptions import DuplicateHealthCheckError, DuplicateReadinessCheckError, UnknownComponentError
from operations.health import HealthCheckRegistry, HealthCheckService, aggregate_status
from operations.models import ComponentHealth, HealthStatus, ReadinessCheckResult
from operations.readiness import ReadinessCheckRegistry, ReadinessService


# ==============================================================================
# Shared fixtures
# ==============================================================================


@pytest.fixture
def health_registry() -> HealthCheckRegistry:
    """A fresh, empty Health Check Registry, isolated to a single test."""
    return HealthCheckRegistry()


@pytest.fixture
def health_service(health_registry: HealthCheckRegistry) -> HealthCheckService:
    """A HealthCheckService wired to the fixture's isolated registry."""
    return HealthCheckService(registry=health_registry)


@pytest.fixture
def readiness_registry() -> ReadinessCheckRegistry:
    """A fresh, empty Readiness Check Registry, isolated to a single test."""
    return ReadinessCheckRegistry()


@pytest.fixture
def readiness_service_fixture(health_service: HealthCheckService, readiness_registry: ReadinessCheckRegistry) -> ReadinessService:
    """A ReadinessService wired to fresh, isolated dependencies."""
    return ReadinessService(health_service=health_service, readiness_registry=readiness_registry)


@pytest.fixture
def clean_monitoring():
    """Clear the provider the shared ``monitoring_service`` actually writes to."""
    monitoring_service._provider.clear()
    yield
    monitoring_service._provider.clear()


# ==============================================================================
# 1. Models
# ==============================================================================


def test_health_status_is_a_plain_string() -> None:
    assert HealthStatus.HEALTHY == "healthy"
    assert HealthStatus.WARNING == "warning"
    assert HealthStatus.UNHEALTHY == "unhealthy"


def test_component_health_defaults() -> None:
    health = ComponentHealth(component="Test", status=HealthStatus.HEALTHY)
    assert health.message == ""
    assert health.checked_at is None


def test_readiness_check_result_defaults() -> None:
    result = ReadinessCheckResult(check_name="test", passed=True)
    assert result.message == ""


# ==============================================================================
# 2. Health Check Registry
# ==============================================================================


def test_health_registry_register_and_get(health_registry: HealthCheckRegistry) -> None:
    check = lambda: (HealthStatus.HEALTHY, "ok")
    health_registry.register("Test Component", check)
    assert health_registry.get("Test Component") is check


def test_health_registry_duplicate_registration_raises(health_registry: HealthCheckRegistry) -> None:
    health_registry.register("Test Component", lambda: (HealthStatus.HEALTHY, "ok"))
    with pytest.raises(DuplicateHealthCheckError):
        health_registry.register("Test Component", lambda: (HealthStatus.HEALTHY, "ok"))


def test_health_registry_unregister(health_registry: HealthCheckRegistry) -> None:
    health_registry.register("Test Component", lambda: (HealthStatus.HEALTHY, "ok"))
    health_registry.unregister("Test Component")
    assert health_registry.get("Test Component") is None


def test_health_registry_list_components_sorted(health_registry: HealthCheckRegistry) -> None:
    health_registry.register("Zebra", lambda: (HealthStatus.HEALTHY, "ok"))
    health_registry.register("Alpha", lambda: (HealthStatus.HEALTHY, "ok"))
    assert health_registry.list_components() == ("Alpha", "Zebra")


def test_health_registry_clear(health_registry: HealthCheckRegistry) -> None:
    health_registry.register("Test Component", lambda: (HealthStatus.HEALTHY, "ok"))
    health_registry.clear()
    assert health_registry.list_components() == ()


# ==============================================================================
# 3. Aggregation logic
# ==============================================================================


def test_aggregate_status_empty_is_healthy() -> None:
    assert aggregate_status(()) == HealthStatus.HEALTHY


def test_aggregate_status_all_healthy() -> None:
    assert aggregate_status((HealthStatus.HEALTHY, HealthStatus.HEALTHY)) == HealthStatus.HEALTHY


def test_aggregate_status_one_warning_dominates_healthy() -> None:
    assert aggregate_status((HealthStatus.HEALTHY, HealthStatus.WARNING)) == HealthStatus.WARNING


def test_aggregate_status_one_unhealthy_dominates_everything() -> None:
    assert aggregate_status((HealthStatus.HEALTHY, HealthStatus.WARNING, HealthStatus.UNHEALTHY)) == HealthStatus.UNHEALTHY


# ==============================================================================
# 4. Health Check Service (Task 6)
# ==============================================================================


def test_service_check_component_healthy(health_service: HealthCheckService, health_registry: HealthCheckRegistry) -> None:
    health_registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    result = health_service.check_component("Identity Platform")
    assert result.status == HealthStatus.HEALTHY
    assert result.component == "Identity Platform"
    assert result.checked_at is not None


def test_service_check_component_unknown_raises(health_service: HealthCheckService) -> None:
    with pytest.raises(UnknownComponentError):
        health_service.check_component("Not A Real Component")


def test_service_check_component_catches_exceptions_as_unhealthy(
    health_service: HealthCheckService, health_registry: HealthCheckRegistry
) -> None:
    """A check function's own bug must never crash health reporting -- it becomes UNHEALTHY instead."""
    def _broken_check():
        raise RuntimeError("boom")

    health_registry.register("Broken Component", _broken_check)
    result = health_service.check_component("Broken Component")
    assert result.status == HealthStatus.UNHEALTHY
    assert "boom" in result.message


def test_service_check_all_aggregates_every_component(health_service: HealthCheckService, health_registry: HealthCheckRegistry) -> None:
    health_registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    health_registry.register("Authorization Platform", lambda: (HealthStatus.WARNING, "Degraded"))
    health_registry.register("Monitoring Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    report = health_service.check_all()
    assert report.overall_status == HealthStatus.WARNING
    assert len(report.components) == 3


def test_service_check_all_with_no_checks_registered_is_healthy(health_service: HealthCheckService) -> None:
    report = health_service.check_all()
    assert report.overall_status == HealthStatus.HEALTHY
    assert report.components == ()


def test_all_six_ticket_named_platform_components_can_be_registered(
    health_service: HealthCheckService, health_registry: HealthCheckRegistry
) -> None:
    """Task 6: 'Verify Identity, Authorization, Monitoring, Automation, Integration, Business Platform.'"""
    components = (
        "Identity Platform", "Authorization Platform", "Monitoring Platform",
        "Automation Platform", "Integration Platform", "Business Platform",
    )
    for component in components:
        health_registry.register(component, lambda: (HealthStatus.HEALTHY, "OK"))
    report = health_service.check_all()
    assert {c.component for c in report.components} == set(components)
    assert report.overall_status == HealthStatus.HEALTHY


# ==============================================================================
# 5. Readiness Check Registry
# ==============================================================================


def test_readiness_registry_register_and_run(readiness_registry: ReadinessCheckRegistry) -> None:
    readiness_registry.register("check_one", lambda: (True, "ok"))
    results = readiness_registry.run_all()
    assert len(results) == 1
    assert results[0].passed is True


def test_readiness_registry_duplicate_raises(readiness_registry: ReadinessCheckRegistry) -> None:
    readiness_registry.register("check_one", lambda: (True, "ok"))
    with pytest.raises(DuplicateReadinessCheckError):
        readiness_registry.register("check_one", lambda: (True, "ok"))


def test_readiness_registry_check_exception_becomes_failed(readiness_registry: ReadinessCheckRegistry) -> None:
    def _broken():
        raise RuntimeError("check exploded")

    readiness_registry.register("broken_check", _broken)
    results = readiness_registry.run_all()
    assert results[0].passed is False
    assert "check exploded" in results[0].message


# ==============================================================================
# 6. Readiness Service (Task 7) -- the Health vs Readiness distinction
# ==============================================================================


def test_readiness_service_ready_when_healthy_and_checks_pass(
    readiness_service_fixture: ReadinessService, health_registry: HealthCheckRegistry, readiness_registry: ReadinessCheckRegistry
) -> None:
    health_registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    readiness_registry.register("configuration_present", lambda: (True, "present"))
    report = readiness_service_fixture.evaluate()
    assert report.ready is True


def test_readiness_service_healthy_but_configuration_missing_is_not_ready(
    readiness_service_fixture: ReadinessService, health_registry: HealthCheckRegistry, readiness_registry: ReadinessCheckRegistry
) -> None:
    """The ticket's own worked example, verified directly:

        Healthy
        but
        Configuration missing
        -->
        Not Ready

    Every component reports HEALTHY, yet the platform is still Not
    Ready because a readiness check (not a health check) fails.
    """
    health_registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    health_registry.register("Authorization Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    readiness_registry.register("required_configuration_present", lambda: (False, "Missing required configuration key(s): API_KEY."))

    report = readiness_service_fixture.evaluate()

    assert report.health.overall_status == HealthStatus.HEALTHY  # every component healthy
    assert report.ready is False  # yet not ready
    assert any(not check.passed for check in report.checks)


def test_readiness_service_not_ready_when_unhealthy_even_if_checks_pass(
    readiness_service_fixture: ReadinessService, health_registry: HealthCheckRegistry, readiness_registry: ReadinessCheckRegistry
) -> None:
    health_registry.register("Identity Platform", lambda: (HealthStatus.UNHEALTHY, "down"))
    readiness_registry.register("configuration_present", lambda: (True, "present"))
    report = readiness_service_fixture.evaluate()
    assert report.ready is False


def test_readiness_service_ready_despite_warning_status(
    readiness_service_fixture: ReadinessService, health_registry: HealthCheckRegistry, readiness_registry: ReadinessCheckRegistry
) -> None:
    """A WARNING (not UNHEALTHY) component doesn't block readiness by itself -- only UNHEALTHY does."""
    health_registry.register("Automation Platform", lambda: (HealthStatus.WARNING, "no jobs registered"))
    readiness_registry.register("configuration_present", lambda: (True, "present"))
    report = readiness_service_fixture.evaluate()
    assert report.ready is True


def test_readiness_service_with_no_checks_registered_is_ready_if_healthy(readiness_service_fixture: ReadinessService) -> None:
    report = readiness_service_fixture.evaluate()
    assert report.ready is True


# ==============================================================================
# 7. Deployment information
# ==============================================================================


def test_build_deployment_info_reflects_environment() -> None:
    provider_registry = ConfigurationProviderRegistry()
    provider_registry.register("memory", InMemoryConfigurationProvider())
    environment_registry = EnvironmentProfileRegistry()
    environment_registry.register_many(DEFAULT_ENVIRONMENT_PROFILES)
    service = ConfigurationService(
        provider_registry=provider_registry, environment_registry=environment_registry, environment=Environment.PRODUCTION
    )
    info = build_deployment_info(service)
    assert info.environment == Environment.PRODUCTION
    assert info.version
    assert info.deployment_strategy
    assert info.generated_at is not None


def test_build_deployment_info_different_strategies_per_environment() -> None:
    provider_registry = ConfigurationProviderRegistry()
    provider_registry.register("memory", InMemoryConfigurationProvider())
    environment_registry = EnvironmentProfileRegistry()
    environment_registry.register_many(DEFAULT_ENVIRONMENT_PROFILES)

    dev_service = ConfigurationService(
        provider_registry=provider_registry, environment_registry=environment_registry, environment=Environment.DEVELOPMENT
    )
    prod_service = ConfigurationService(
        provider_registry=provider_registry, environment_registry=environment_registry, environment=Environment.PRODUCTION
    )
    dev_info = build_deployment_info(dev_service)
    prod_info = build_deployment_info(prod_service)
    assert dev_info.deployment_strategy != prod_info.deployment_strategy


# ==============================================================================
# 8. Monitoring Integration (Task 9) -- shared monitoring_service, no second store
# ==============================================================================


def test_health_check_service_records_check_event(
    clean_monitoring, health_service: HealthCheckService, health_registry: HealthCheckRegistry
) -> None:
    health_registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    health_service.check_all()
    events = monitoring_service.get_events(service_name="HealthCheckService")
    assert any(event.operation == "check_platform_health" for event in events)


def test_readiness_service_records_check_event(
    clean_monitoring, readiness_service_fixture: ReadinessService, health_registry: HealthCheckRegistry
) -> None:
    health_registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    readiness_service_fixture.evaluate()
    events = monitoring_service.get_events(service_name="ReadinessService")
    assert any(event.operation == "check_readiness" for event in events)


def test_operations_package_does_not_introduce_a_second_monitoring_mechanism(
    clean_monitoring, health_service: HealthCheckService, health_registry: HealthCheckRegistry
) -> None:
    """Task 9: every recordable fact about health/readiness is retrievable from the existing monitoring_service alone."""
    import operations.health as health_module
    import operations.readiness as readiness_module

    assert not hasattr(health_module, "HealthEventStore")
    assert not hasattr(readiness_module, "ReadinessEventStore")

    health_registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
    health_service.check_all()
    assert monitoring_service.get_events(service_name="HealthCheckService")
