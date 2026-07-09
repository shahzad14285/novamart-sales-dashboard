"""Readiness Check Service for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 7.

Health and Readiness answer two different questions, and this module
exists specifically to keep them from being conflated:

- **Health** (``operations/health.py``) asks "is each platform
  component itself responding and functioning correctly, right now?"
- **Readiness** (this module) asks "is the platform, as a whole, ready
  to serve external traffic, right now?"

A platform can be entirely Healthy -- every component responding,
nothing crashing -- while still Not Ready, because Readiness also
depends on things Health checks don't look at: is required
configuration actually present, has an environment been resolved, are
mandatory endpoints registered. The ticket's own example makes this
concrete::

    Healthy
    but
    Configuration missing
    -->
    Not Ready

A newly-deployed instance with a missing required secret is a textbook
case: every component starts up fine (Healthy), but the platform still
shouldn't receive traffic until that secret is present (Not Ready).
Readiness is therefore always computed as Health *plus* a set of
additional, independent checks -- never a re-implementation of Health
logic (Task 7 doesn't ask for a second way to detect a crashed
component, only an additional gate on top of a working one).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from monitoring.service import monitoring_service
from operations.exceptions import DuplicateReadinessCheckError
from operations.health import HealthCheckService, health_check_service as default_health_check_service
from operations.models import ReadinessCheckResult, ReadinessReport

logger = logging.getLogger("novamart.operations.readiness")

_SERVICE_NAME = "ReadinessService"

# A readiness check function takes no arguments and returns a
# (passed, message) pair -- the check itself decides what "ready" means
# for whatever it inspects (a required configuration key, a populated
# endpoint registry, ...).
ReadinessCheckFunction = Callable[[], "tuple[bool, str]"]


class ReadinessCheckRegistry:
    """A registry of every readiness check known to the platform.

    Mirrors :class:`~operations.health.HealthCheckRegistry`'s shape
    exactly -- registration is data-driven, from a composition root,
    never a hardcoded branch inside :class:`ReadinessService`.
    """

    def __init__(self) -> None:
        """Create an empty readiness check registry."""
        self._checks: dict[str, ReadinessCheckFunction] = {}

    def register(self, check_name: str, check: ReadinessCheckFunction) -> None:
        """Register a readiness check function under ``check_name``.

        Args:
            check_name: A short, stable name for this check (e.g.
                ``"required_configuration_present"``).
            check: A zero-argument callable returning a
                ``(passed, message)`` pair.

        Raises:
            DuplicateReadinessCheckError: If a check is already
                registered under ``check_name``.
        """
        if check_name in self._checks:
            raise DuplicateReadinessCheckError(check_name)
        self._checks[check_name] = check

    def unregister(self, check_name: str) -> None:
        """Remove the readiness check registered under ``check_name``, if any."""
        self._checks.pop(check_name, None)

    def list_checks(self) -> tuple[str, ...]:
        """Return every registered check name, sorted."""
        return tuple(sorted(self._checks.keys()))

    def clear(self) -> None:
        """Remove every registered readiness check.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._checks.clear()

    def run_all(self) -> tuple[ReadinessCheckResult, ...]:
        """Run every registered readiness check, never letting one check's failure break the rest."""
        results = []
        for name in self.list_checks():
            check = self._checks[name]
            try:
                passed, message = check()
            except Exception as exc:  # noqa: BLE001 - a check's own failure must never crash readiness reporting
                logger.warning("Readiness check '%s' raised: %s", name, exc)
                passed, message = False, f"Readiness check raised an exception: {exc}"
            results.append(ReadinessCheckResult(check_name=name, passed=passed, message=message))
        return tuple(results)


# A shared, ready-to-use registry -- mirrors ``operations.health.health_check_registry``.
readiness_check_registry = ReadinessCheckRegistry()


class ReadinessService:
    """Computes whether the platform is ready to serve traffic (Task 7).

    ``ready`` is ``True`` only when the platform's aggregated
    :class:`~operations.models.HealthStatus` is not
    :attr:`~operations.models.HealthStatus.UNHEALTHY` **and** every
    registered readiness check passes -- both conditions, always, so a
    platform can never report "ready" while a component is actively
    broken, and can never report "ready" while a required piece of
    configuration is simply absent.

    Example:
        >>> service = ReadinessService()
        >>> report = service.evaluate()
        >>> report.ready
        True
    """

    def __init__(
        self,
        *,
        health_service: HealthCheckService | None = None,
        readiness_registry: ReadinessCheckRegistry | None = None,
    ) -> None:
        """Create a Readiness Service.

        Args:
            health_service: The Health Check Service to base readiness
                on. Defaults to the shared
                :data:`~operations.health.health_check_service`.
            readiness_registry: The readiness check catalogue to run.
                Defaults to the shared :data:`readiness_check_registry`.
        """
        self._health_service = health_service if health_service is not None else default_health_check_service
        self._readiness_registry = readiness_registry if readiness_registry is not None else readiness_check_registry
        self._lock = threading.Lock()

    def evaluate(self) -> ReadinessReport:
        """Compute the current :class:`~operations.models.ReadinessReport`.

        Records a monitoring event (Task 9: "Record: ... Readiness
        checks") summarizing the outcome.

        Returns:
            A :class:`~operations.models.ReadinessReport`.
        """
        from operations.models import HealthStatus

        with self._lock:
            health = self._health_service.check_all()
            checks = self._readiness_registry.run_all()

        ready = health.overall_status != HealthStatus.UNHEALTHY and all(check.passed for check in checks)
        report = ReadinessReport(ready=ready, health=health, checks=checks, generated_at=datetime.now(timezone.utc))

        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="check_readiness",
            message=f"Platform readiness: {'ready' if ready else 'not ready'}.",
            metadata={
                "ready": ready,
                "health_status": health.overall_status.value,
                "checks": {check.check_name: check.passed for check in checks},
            },
        )
        return report


# A shared, ready-to-use instance -- mirrors ``operations.health.health_check_service``.
readiness_service = ReadinessService()
