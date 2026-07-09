"""Health Check Service for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 6.

A centralized point that verifies every platform component -- Identity,
Authorization, Monitoring, Automation, Integration, and Business -- and
reports each as Healthy, Warning, or Unhealthy, plus an overall
platform status. Mirrors the Registry Pattern already used throughout
this codebase: *which* components are checked, and how, is declared
once via :meth:`HealthCheckRegistry.register` calls from a composition
root (this sprint: ``config/production_setup.py``), never hardcoded
inside :class:`HealthCheckService` itself -- adding a health check for
a future seventh platform component requires zero change to this
module.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from monitoring.service import monitoring_service
from operations.exceptions import DuplicateHealthCheckError, UnknownComponentError
from operations.models import ComponentHealth, HealthStatus, PlatformHealthReport

logger = logging.getLogger("novamart.operations.health")

_SERVICE_NAME = "HealthCheckService"

# A health check function takes no arguments and returns a (status, message)
# pair -- deliberately not a full ComponentHealth, so a check function
# never has to know its own component name or construct a timestamp;
# HealthCheckService fills those in uniformly.
HealthCheckFunction = Callable[[], "tuple[HealthStatus, str]"]

# Severity ranking used to compute an overall status from several
# component results -- the worst status among every checked component
# wins, exactly like a Kubernetes readiness/liveness aggregate.
_SEVERITY: dict[HealthStatus, int] = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.WARNING: 1,
    HealthStatus.UNHEALTHY: 2,
}


def aggregate_status(statuses: "tuple[HealthStatus, ...]") -> HealthStatus:
    """Return the worst (most severe) status among ``statuses``.

    Args:
        statuses: Zero or more component health statuses.

    Returns:
        The most severe status present, or :attr:`HealthStatus.HEALTHY`
        if ``statuses`` is empty (no components checked is not itself
        a failure -- it is a configuration gap the Readiness Service,
        not the Health Check Service, would flag).
    """
    if not statuses:
        return HealthStatus.HEALTHY
    return max(statuses, key=lambda status: _SEVERITY[status])


class HealthCheckRegistry:
    """A registry of every component health check known to the platform.

    Mirrors ``integration.registry.EndpointRegistry``'s split between
    plain data and a live callable: here there is no separate
    "definition" object (a component's identity *is* its name), but the
    same principle -- registration is data-driven, never a hardcoded
    branch -- applies identically.
    """

    def __init__(self) -> None:
        """Create an empty health check registry."""
        self._checks: dict[str, HealthCheckFunction] = {}

    def register(self, component: str, check: HealthCheckFunction) -> None:
        """Register a health check function for ``component``.

        Args:
            component: A short, human-readable component name (e.g.
                ``"Identity Platform"``).
            check: A zero-argument callable returning a
                ``(HealthStatus, message)`` pair.

        Raises:
            DuplicateHealthCheckError: If a check is already registered
                for ``component``.
        """
        if component in self._checks:
            raise DuplicateHealthCheckError(component)
        self._checks[component] = check

    def unregister(self, component: str) -> None:
        """Remove the health check registered for ``component``, if any."""
        self._checks.pop(component, None)

    def get(self, component: str) -> HealthCheckFunction | None:
        """Return the check function registered for ``component``, or ``None``."""
        return self._checks.get(component)

    def list_components(self) -> tuple[str, ...]:
        """Return every registered component name, sorted."""
        return tuple(sorted(self._checks.keys()))

    def clear(self) -> None:
        """Remove every registered health check.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._checks.clear()


# A shared, ready-to-use registry -- mirrors ``integration.registry.endpoint_registry``.
health_check_registry = HealthCheckRegistry()


class HealthCheckService:
    """Runs every registered component health check and reports overall platform health (Task 6).

    Example:
        >>> registry = HealthCheckRegistry()
        >>> registry.register("Identity Platform", lambda: (HealthStatus.HEALTHY, "OK"))
        >>> service = HealthCheckService(registry=registry)
        >>> service.check_all().overall_status
        <HealthStatus.HEALTHY: 'healthy'>
    """

    def __init__(self, *, registry: HealthCheckRegistry | None = None) -> None:
        """Create a Health Check Service.

        Args:
            registry: The health check catalogue to run. Defaults to
                the shared :data:`health_check_registry`.
        """
        self._registry = registry if registry is not None else health_check_registry
        self._lock = threading.Lock()

    def check_component(self, component: str) -> ComponentHealth:
        """Run the registered check for ``component`` and return its result.

        A check function's own exception is caught and reported as
        :attr:`~operations.models.HealthStatus.UNHEALTHY` rather than
        propagating -- mirrors every other resilience guarantee in this
        platform (a business service's failure never crashes the
        component checking it).

        Args:
            component: The component to check.

        Returns:
            A :class:`~operations.models.ComponentHealth` result.

        Raises:
            UnknownComponentError: If no health check is registered for
                ``component``.
        """
        check = self._registry.get(component)
        if check is None:
            raise UnknownComponentError(component, self._registry.list_components())

        try:
            status, message = check()
        except Exception as exc:  # noqa: BLE001 - a check's own failure must never crash health reporting
            logger.warning("Health check for '%s' raised: %s", component, exc)
            status, message = HealthStatus.UNHEALTHY, f"Health check raised an exception: {exc}"

        return ComponentHealth(component=component, status=status, message=message, checked_at=datetime.now(timezone.utc))

    def check_all(self) -> PlatformHealthReport:
        """Run every registered health check and return the aggregated platform report.

        Records a monitoring event (Task 9: "Record: ... Health
        checks") summarizing the overall outcome.

        Returns:
            A :class:`~operations.models.PlatformHealthReport`.
        """
        with self._lock:
            components = tuple(self.check_component(name) for name in self._registry.list_components())

        overall = aggregate_status(tuple(component.status for component in components))
        report = PlatformHealthReport(overall_status=overall, components=components, generated_at=datetime.now(timezone.utc))

        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="check_platform_health",
            message=f"Platform health: {overall.value} ({len(components)} component(s) checked).",
            metadata={
                "overall_status": overall.value,
                "components": {component.component: component.status.value for component in components},
            },
        )
        return report


# A shared, ready-to-use instance -- mirrors ``integration.gateway.api_gateway``.
health_check_service = HealthCheckService()
