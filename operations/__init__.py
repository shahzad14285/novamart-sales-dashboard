"""Operations Platform for the NovaMart Sales Intelligence Dashboard.

Sprint 6.9 -- Production Readiness Platform.

A small, framework-agnostic package (no Streamlit dependency anywhere
in it) providing Health Checks, Readiness Checks, and Deployment
information for every platform component. See
``docs/PRODUCTION_ARCHITECTURE.md`` for the full design rationale,
including the Health vs Readiness distinction this package exists to
enforce structurally (two separate services, not one overloaded one).
"""

from __future__ import annotations

from operations.deployment import build_deployment_info
from operations.exceptions import (
    DuplicateHealthCheckError,
    DuplicateReadinessCheckError,
    OperationsError,
    UnknownComponentError,
)
from operations.health import (
    HealthCheckRegistry,
    HealthCheckService,
    aggregate_status,
    health_check_registry,
    health_check_service,
)
from operations.models import ComponentHealth, HealthStatus, PlatformHealthReport, ReadinessCheckResult, ReadinessReport
from operations.readiness import ReadinessCheckRegistry, ReadinessService, readiness_check_registry, readiness_service

__all__ = [
    "ComponentHealth",
    "DuplicateHealthCheckError",
    "DuplicateReadinessCheckError",
    "HealthCheckRegistry",
    "HealthCheckService",
    "HealthStatus",
    "OperationsError",
    "PlatformHealthReport",
    "ReadinessCheckRegistry",
    "ReadinessCheckResult",
    "ReadinessReport",
    "ReadinessService",
    "UnknownComponentError",
    "aggregate_status",
    "build_deployment_info",
    "health_check_registry",
    "health_check_service",
    "readiness_check_registry",
    "readiness_service",
]
