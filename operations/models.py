"""Health and Readiness value objects for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 6, Task 7.

Every type here is a plain, immutable value object -- no behavior, no
storage, no Streamlit dependency -- matching the convention already
established by ``monitoring.models.MonitoringEvent`` and
``integration.models.IntegrationResponse``.
:class:`~operations.health.HealthCheckService` and
:class:`~operations.readiness.ReadinessService` are the only things in
this package that hold behavior; everything below is data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class HealthStatus(str, Enum):
    """The outcome of one component's health check (Task 6).

    A plain ``str`` subclass, matching every other enum in this
    platform. Ordered worst-to-best is *not* the declaration order
    here -- :func:`~operations.health.aggregate_status` defines the
    actual severity ranking used to compute an overall platform status
    from several component statuses.
    """

    HEALTHY = "healthy"
    WARNING = "warning"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class ComponentHealth:
    """One platform component's health check result (Task 6).

    Attributes:
        component: The platform component this result describes (e.g.
            ``"Identity Platform"``, ``"Business Platform"``).
        status: The outcome -- healthy, warning, or unhealthy.
        message: A short, human-readable explanation, especially useful
            when ``status`` isn't healthy.
        checked_at: When this check was performed.
    """

    component: str
    status: HealthStatus
    message: str = ""
    checked_at: datetime | None = None


@dataclass(frozen=True)
class PlatformHealthReport:
    """The aggregated health of every checked platform component (Task 6).

    Attributes:
        overall_status: The platform-wide status -- the worst status
            among every :class:`ComponentHealth` in ``components`` (see
            :func:`~operations.health.aggregate_status`).
        components: Every individual component's health result.
        generated_at: When this report was produced.
    """

    overall_status: HealthStatus
    components: tuple[ComponentHealth, ...] = field(default_factory=tuple)
    generated_at: datetime | None = None


@dataclass(frozen=True)
class ReadinessCheckResult:
    """One readiness check's outcome (Task 7).

    Distinct from :class:`ComponentHealth`: a readiness check asks "is
    this platform *ready to serve traffic right now*" (e.g. "is
    required configuration present"), not "is this component itself
    functioning" -- see ``docs/PRODUCTION_ARCHITECTURE.md``'s Health vs
    Readiness section for the full distinction, with the ticket's own
    example: a platform can be Healthy (every component responding)
    while still Not Ready (a required configuration key is missing).

    Attributes:
        check_name: A short, stable name for this check (e.g.
            ``"required_configuration_present"``).
        passed: Whether this check passed.
        message: A short, human-readable explanation, especially useful
            when ``passed`` is ``False``.
    """

    check_name: str
    passed: bool
    message: str = ""


@dataclass(frozen=True)
class ReadinessReport:
    """Whether the platform is ready to serve traffic right now (Task 7).

    Attributes:
        ready: ``True`` only if the platform is healthy (see
            :attr:`health`) *and* every readiness check passed.
        health: The underlying :class:`PlatformHealthReport` this
            readiness evaluation was based on.
        checks: Every individual readiness check's result.
        generated_at: When this report was produced.
    """

    ready: bool
    health: PlatformHealthReport
    checks: tuple[ReadinessCheckResult, ...] = field(default_factory=tuple)
    generated_at: datetime | None = None
