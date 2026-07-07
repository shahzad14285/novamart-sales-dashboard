"""Observability & Monitoring Service for the NovaMart platform.

Sprint 6.4 -- Observability & Monitoring Service.

A small, framework-agnostic package (no Streamlit dependency anywhere
in it) that lets every business service in the existing pipeline
record what it did -- and lets an Administration / Monitoring page ask
"how is the platform doing" -- without either side knowing anything
about the other's implementation. See
``docs/OBSERVABILITY_ARCHITECTURE.md`` for the full design rationale.

Typical usage from a business service::

    from monitoring.service import monitoring_service

    def calculate_all(self, df, *, tenant_context=None):
        tenant = validate_tenant_context(tenant_context, service_name="KPIEngine", operation="calculate_all")
        with monitoring_service.time_operation(
            service_name="KPIEngine", operation="calculate_all", tenant_context=tenant_context
        ):
            ...  # existing business logic, unchanged

Typical usage from the Administration / Monitoring page::

    from monitoring.service import monitoring_service

    stats = monitoring_service.get_platform_stats()
    health = monitoring_service.get_all_service_health()
    activity = monitoring_service.get_tenant_activity()
    recent = monitoring_service.get_events(limit=50)
"""

from __future__ import annotations

from monitoring.events import OperationTimer, build_event
from monitoring.exceptions import (
    InvalidMonitoringEventError,
    MonitoringError,
    NoActiveProviderError,
    ProviderNotRegisteredError,
)
from monitoring.models import EventStatus, EventType, MonitoringEvent, PlatformStats, ServiceHealth, TenantActivity
from monitoring.provider import InMemoryMonitoringProvider, MonitoringProvider
from monitoring.registry import MonitoringProviderRegistry, monitoring_provider_registry
from monitoring.service import MonitoringService, monitoring_service

__all__ = [
    "EventStatus",
    "EventType",
    "InMemoryMonitoringProvider",
    "InvalidMonitoringEventError",
    "MonitoringError",
    "MonitoringEvent",
    "MonitoringProvider",
    "MonitoringProviderRegistry",
    "MonitoringService",
    "NoActiveProviderError",
    "OperationTimer",
    "PlatformStats",
    "ProviderNotRegisteredError",
    "ServiceHealth",
    "TenantActivity",
    "build_event",
    "monitoring_provider_registry",
    "monitoring_service",
]
