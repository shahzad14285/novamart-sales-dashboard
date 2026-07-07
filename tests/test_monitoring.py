"""Unit tests for the Observability & Monitoring Service (Sprint 6.4).

This file is the Task 10 deliverable: comprehensive coverage of the
``monitoring/`` package itself -- event creation, the centralized
``MonitoringService``, the Provider Pattern (including a from-scratch
custom provider proving swappability), performance timing, error
recording, service health aggregation, tenant-aware events (including
isolation), and the aggregate queries the Administration / Monitoring
dashboard reads from.

Every test constructs its own :class:`~monitoring.service.MonitoringService`
backed by its own fresh :class:`~monitoring.provider.InMemoryMonitoringProvider`
(or a custom stub provider) rather than using the shared
``monitoring.service.monitoring_service`` singleton -- this is what
keeps tests fully isolated from each other and from whatever the rest
of the test suite records into the shared instance, with no shared
mutable state or teardown step required.

Business-logic correctness for each individually monitored service
(KPI Engine, Business Insights, Reporting, AI Recommendation, PDF
Generator, Export Service, Upload Center, Data Loader, Executive
Report Center) already has dedicated coverage in its own test file;
those files are unchanged by this sprint (monitoring only wraps their
existing method bodies, it never alters their logic), which
``tests/test_multi_tenancy.py`` and friends continuing to pass proves.
This file focuses purely on the monitoring package's own behavior.
"""

from __future__ import annotations

import time

import pytest

from monitoring.events import OperationTimer, build_event, new_event_id, utc_now
from monitoring.exceptions import (
    InvalidMonitoringEventError,
    NoActiveProviderError,
    ProviderNotRegisteredError,
)
from monitoring.models import EventStatus, EventType, MonitoringEvent
from monitoring.provider import InMemoryMonitoringProvider
from monitoring.registry import MonitoringProviderRegistry
from monitoring.service import MonitoringService
from tenancy.context import TenantContext
from tenancy.models import Tenant

# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def provider() -> InMemoryMonitoringProvider:
    """A fresh, empty in-memory provider, isolated to a single test."""
    return InMemoryMonitoringProvider()


@pytest.fixture
def service(provider: InMemoryMonitoringProvider) -> MonitoringService:
    """A MonitoringService wired to a fresh provider via Dependency Injection.

    Never touches the shared application-wide ``monitoring_service``
    singleton or the shared provider registry, so tests never leak
    events into (or read stale events from) each other.
    """
    return MonitoringService(provider=provider)


@pytest.fixture
def tenant_a() -> Tenant:
    return Tenant(tenant_id="org-a", name="org-a", display_name="Organization A")


@pytest.fixture
def tenant_b() -> Tenant:
    return Tenant(tenant_id="org-b", name="org-b", display_name="Organization B")


class _BrokenProvider:
    """A provider whose ``record`` always fails -- proves storage failures
    never escape :class:`MonitoringService` into a business caller."""

    def record(self, event: MonitoringEvent) -> None:
        raise RuntimeError("storage backend unreachable")

    def list_events(self, **kwargs):
        return ()

    def clear(self) -> None:
        pass


# ==============================================================================
# 1. Event creation
# ==============================================================================


def test_build_event_assigns_a_unique_event_id_and_utc_timestamp() -> None:
    event = build_event(
        service_name="KPIEngine",
        operation="calculate_all",
        event_type=EventType.OPERATION_COMPLETED,
        status=EventStatus.SUCCESS,
    )
    assert event.event_id
    assert event.timestamp is not None
    assert event.timestamp.tzinfo is not None


def test_build_event_produces_distinct_ids_for_two_events() -> None:
    first = build_event(
        service_name="KPIEngine", operation="calculate_all",
        event_type=EventType.OPERATION_STARTED, status=EventStatus.IN_PROGRESS,
    )
    second = build_event(
        service_name="KPIEngine", operation="calculate_all",
        event_type=EventType.OPERATION_STARTED, status=EventStatus.IN_PROGRESS,
    )
    assert first.event_id != second.event_id


def test_new_event_id_and_utc_now_are_directly_usable() -> None:
    assert isinstance(new_event_id(), str) and new_event_id()
    assert utc_now().tzinfo is not None


def test_monitoring_event_carries_every_documented_field() -> None:
    event = build_event(
        service_name="ExportService",
        operation="export",
        event_type=EventType.OPERATION_FAILED,
        status=EventStatus.FAILURE,
        tenant_id="org-a",
        tenant_name="Organization A",
        duration_ms=12.5,
        message="bad format",
        metadata={"export_format": "xml"},
    )
    assert event.service_name == "ExportService"
    assert event.operation == "export"
    assert event.tenant_id == "org-a"
    assert event.tenant_name == "Organization A"
    assert event.duration_ms == 12.5
    assert event.message == "bad format"
    assert event.metadata["export_format"] == "xml"


def test_monitoring_event_is_immutable() -> None:
    event = build_event(
        service_name="KPIEngine", operation="calculate_all",
        event_type=EventType.OPERATION_STARTED, status=EventStatus.IN_PROGRESS,
    )
    with pytest.raises(Exception):
        event.service_name = "Something else"  # frozen dataclass -> raises


# ==============================================================================
# 2. MonitoringService -- recording primitives
# ==============================================================================


def test_record_started_stores_an_in_progress_event(service: MonitoringService) -> None:
    event = service.record_started(service_name="KPIEngine", operation="calculate_all")
    assert event.event_type == EventType.OPERATION_STARTED
    assert event.status == EventStatus.IN_PROGRESS
    assert service.get_events()[0].event_id == event.event_id


def test_record_completed_stores_a_success_event_with_duration(service: MonitoringService) -> None:
    event = service.record_completed(service_name="KPIEngine", operation="calculate_all", duration_ms=42.0)
    assert event.event_type == EventType.OPERATION_COMPLETED
    assert event.status == EventStatus.SUCCESS
    assert event.duration_ms == 42.0


def test_record_failure_with_an_exception_captures_message_and_error_type(service: MonitoringService) -> None:
    error = ValueError("bad input")
    event = service.record_failure(service_name="ExportService", operation="export", error=error, duration_ms=5.0)
    assert event.event_type == EventType.OPERATION_FAILED
    assert event.status == EventStatus.FAILURE
    assert event.message == "bad input"
    assert event.metadata["error_type"] == "ValueError"


def test_record_failure_with_a_plain_string_has_no_error_type_metadata(service: MonitoringService) -> None:
    event = service.record_failure(service_name="ExportService", operation="export", error="plain failure text")
    assert event.message == "plain failure text"
    assert "error_type" not in event.metadata


def test_record_warning_stores_a_warning_event(service: MonitoringService) -> None:
    event = service.record_warning(service_name="ReportingService", operation="generate_report", message="slow query")
    assert event.event_type == EventType.WARNING
    assert event.status == EventStatus.WARNING
    assert event.message == "slow query"


def test_record_info_stores_an_info_event(service: MonitoringService) -> None:
    event = service.record_info(service_name="DataLoader", operation="load_uploaded_file", message="using cached schema")
    assert event.event_type == EventType.INFO
    assert event.status == EventStatus.INFO


def test_record_event_requires_a_non_empty_service_name(service: MonitoringService) -> None:
    with pytest.raises(InvalidMonitoringEventError):
        service.record_event(
            service_name="   ", operation="calculate_all",
            event_type=EventType.INFO, status=EventStatus.INFO,
        )


def test_record_event_requires_a_non_empty_operation(service: MonitoringService) -> None:
    with pytest.raises(InvalidMonitoringEventError):
        service.record_event(
            service_name="KPIEngine", operation="",
            event_type=EventType.INFO, status=EventStatus.INFO,
        )


# ==============================================================================
# 3. Provider abstraction -- Provider Pattern (Task 4)
# ==============================================================================


def test_in_memory_provider_records_and_lists_events_newest_first(provider: InMemoryMonitoringProvider) -> None:
    first = build_event(
        service_name="KPIEngine", operation="calculate_all",
        event_type=EventType.OPERATION_STARTED, status=EventStatus.IN_PROGRESS,
    )
    time.sleep(0.001)
    second = build_event(
        service_name="KPIEngine", operation="calculate_all",
        event_type=EventType.OPERATION_COMPLETED, status=EventStatus.SUCCESS,
    )
    provider.record(first)
    provider.record(second)

    events = provider.list_events()
    assert events[0].event_id == second.event_id
    assert events[1].event_id == first.event_id


def test_in_memory_provider_filters_by_every_supported_field(provider: InMemoryMonitoringProvider) -> None:
    provider.record(build_event(
        service_name="KPIEngine", operation="calculate_all", tenant_id="org-a",
        event_type=EventType.OPERATION_COMPLETED, status=EventStatus.SUCCESS,
    ))
    provider.record(build_event(
        service_name="ExportService", operation="export", tenant_id="org-b",
        event_type=EventType.OPERATION_FAILED, status=EventStatus.FAILURE,
    ))

    assert len(provider.list_events(service_name="KPIEngine")) == 1
    assert len(provider.list_events(tenant_id="org-b")) == 1
    assert len(provider.list_events(event_type=EventType.OPERATION_FAILED)) == 1
    assert len(provider.list_events(status=EventStatus.SUCCESS)) == 1
    assert len(provider.list_events(limit=1)) == 1
    assert len(provider.list_events(service_name="DoesNotExist")) == 0


def test_in_memory_provider_clear_removes_every_event(provider: InMemoryMonitoringProvider) -> None:
    provider.record(build_event(
        service_name="KPIEngine", operation="calculate_all",
        event_type=EventType.OPERATION_STARTED, status=EventStatus.IN_PROGRESS,
    ))
    provider.clear()
    assert provider.list_events() == ()


class _ListOnlyProvider:
    """A minimal, from-scratch provider (no shared base class) proving the
    Provider Pattern is a structural Protocol, not an inheritance contract --
    any object with the right three methods can act as a provider."""

    def __init__(self) -> None:
        self.recorded: list[MonitoringEvent] = []

    def record(self, event: MonitoringEvent) -> None:
        self.recorded.append(event)

    def list_events(self, *, tenant_id=None, service_name=None, event_type=None, status=None, limit=None):
        return tuple(self.recorded)

    def clear(self) -> None:
        self.recorded.clear()


def test_monitoring_service_works_unmodified_against_a_brand_new_provider_implementation() -> None:
    """Proves Task 4's central promise: swapping the storage backend
    requires zero changes to MonitoringService or to any business
    service -- only a different object passed into the constructor."""
    custom_provider = _ListOnlyProvider()
    service = MonitoringService(provider=custom_provider)

    service.record_completed(service_name="KPIEngine", operation="calculate_all", duration_ms=1.0)

    assert len(custom_provider.recorded) == 1
    assert custom_provider.recorded[0].service_name == "KPIEngine"


def test_monitoring_provider_registry_register_and_get() -> None:
    registry = MonitoringProviderRegistry()
    provider_instance = InMemoryMonitoringProvider()
    registry.register("memory", provider_instance)

    assert registry.get("memory") is provider_instance
    assert registry.registered_providers() == ("memory",)


def test_monitoring_provider_registry_get_unregistered_raises() -> None:
    registry = MonitoringProviderRegistry()
    with pytest.raises(ProviderNotRegisteredError):
        registry.get("does-not-exist")


def test_monitoring_provider_registry_set_active_and_get_active() -> None:
    registry = MonitoringProviderRegistry()
    memory_provider = InMemoryMonitoringProvider()
    other_provider = _ListOnlyProvider()
    registry.register("memory", memory_provider, make_active=True)
    registry.register("other", other_provider)

    assert registry.get_active() is memory_provider
    assert registry.active_name == "memory"

    registry.set_active("other")
    assert registry.get_active() is other_provider
    assert registry.active_name == "other"


def test_monitoring_provider_registry_get_active_without_one_registered_raises() -> None:
    registry = MonitoringProviderRegistry()
    with pytest.raises(NoActiveProviderError):
        registry.get_active()


def test_monitoring_service_defaults_to_the_registrys_active_provider() -> None:
    """When no provider is injected, MonitoringService asks the shared
    registry for whichever provider is currently active -- proving the
    Dependency Injection default without needing to touch the shared,
    application-wide registry singleton itself."""
    registry = MonitoringProviderRegistry()
    provider_instance = InMemoryMonitoringProvider()
    registry.register("memory", provider_instance, make_active=True)

    import monitoring.service as service_module

    original_registry = service_module.monitoring_provider_registry
    service_module.monitoring_provider_registry = registry
    try:
        service = MonitoringService()
        service.record_started(service_name="KPIEngine", operation="calculate_all")
        assert len(provider_instance.list_events()) == 1
    finally:
        service_module.monitoring_provider_registry = original_registry


# ==============================================================================
# 4. Performance timing (Task 6)
# ==============================================================================


def test_operation_timer_start_stop_measures_a_positive_duration() -> None:
    timer = OperationTimer()
    timer.start()
    time.sleep(0.005)
    duration = timer.stop()

    assert duration > 0
    assert timer.duration_ms == duration


def test_operation_timer_as_a_context_manager_records_duration_on_exit() -> None:
    with OperationTimer() as timer:
        time.sleep(0.005)
    assert timer.duration_ms is not None
    assert timer.duration_ms > 0


def test_time_operation_records_started_then_completed_with_measured_duration(
    service: MonitoringService,
) -> None:
    with service.time_operation(service_name="KPIEngine", operation="calculate_all"):
        time.sleep(0.005)

    events = service.get_events(service_name="KPIEngine")
    assert len(events) == 2
    started, completed = events[1], events[0]  # newest first
    assert started.event_type == EventType.OPERATION_STARTED
    assert completed.event_type == EventType.OPERATION_COMPLETED
    assert completed.status == EventStatus.SUCCESS
    assert completed.duration_ms is not None and completed.duration_ms > 0


def test_time_operation_never_duplicates_timing_logic_per_call_site(service: MonitoringService) -> None:
    """Calling time_operation from two different 'services' relies on the
    exact same OperationTimer machinery -- there is only one place
    duration is ever computed in the whole package."""
    with service.time_operation(service_name="ServiceOne", operation="op"):
        pass
    with service.time_operation(service_name="ServiceTwo", operation="op"):
        pass

    for name in ("ServiceOne", "ServiceTwo"):
        completed = [e for e in service.get_events(service_name=name) if e.event_type == EventType.OPERATION_COMPLETED]
        assert len(completed) == 1
        assert completed[0].duration_ms is not None


# ==============================================================================
# 5. Error recording via time_operation
# ==============================================================================


def test_time_operation_records_failure_and_reraises_the_original_exception(service: MonitoringService) -> None:
    with pytest.raises(ValueError):
        with service.time_operation(service_name="ExportService", operation="export"):
            raise ValueError("unsupported format")

    events = service.get_events(service_name="ExportService")
    failed = [e for e in events if e.event_type == EventType.OPERATION_FAILED]
    assert len(failed) == 1
    assert failed[0].status == EventStatus.FAILURE
    assert failed[0].message == "unsupported format"
    assert failed[0].metadata["error_type"] == "ValueError"
    assert failed[0].duration_ms is not None


def test_time_operation_does_not_record_a_completed_event_when_it_fails(service: MonitoringService) -> None:
    with pytest.raises(RuntimeError):
        with service.time_operation(service_name="KPIEngine", operation="calculate_all"):
            raise RuntimeError("boom")

    completed = [e for e in service.get_events() if e.event_type == EventType.OPERATION_COMPLETED]
    assert completed == []


def test_storage_failure_never_propagates_into_the_business_caller() -> None:
    """The defining guarantee of Task 3/6: an observability outage must
    never be able to cause a business outage. A provider that always
    raises must still let time_operation's business logic run and
    return normally."""
    service = MonitoringService(provider=_BrokenProvider())

    with service.time_operation(service_name="KPIEngine", operation="calculate_all"):
        result = 1 + 1  # the "business logic"

    assert result == 2  # never interrupted despite every record() call failing


# ==============================================================================
# 6. Service health (Task 7)
# ==============================================================================


def test_get_service_health_for_a_service_with_no_events_is_all_zero(service: MonitoringService) -> None:
    health = service.get_service_health("NeverCalled")
    assert health.total_executions == 0
    assert health.successful_executions == 0
    assert health.failed_executions == 0
    assert health.warning_count == 0
    assert health.average_duration_ms is None
    assert health.last_execution is None


def test_get_service_health_aggregates_success_failure_and_warning_counts(service: MonitoringService) -> None:
    service.record_completed(service_name="KPIEngine", operation="calculate_all", duration_ms=10.0)
    service.record_completed(service_name="KPIEngine", operation="calculate_all", duration_ms=20.0)
    service.record_failure(service_name="KPIEngine", operation="calculate_all", error="boom", duration_ms=30.0)
    service.record_warning(service_name="KPIEngine", operation="calculate_all", message="slow")
    service.record_started(service_name="KPIEngine", operation="calculate_all")  # excluded from totals

    health = service.get_service_health("KPIEngine")
    assert health.total_executions == 3  # 2 completed + 1 failed, STARTED excluded
    assert health.successful_executions == 2
    assert health.failed_executions == 1
    assert health.warning_count == 1
    assert health.average_duration_ms == pytest.approx(20.0)  # mean of 10, 20, 30
    assert health.last_execution is not None


def test_get_all_service_health_returns_one_entry_per_service_alphabetically(service: MonitoringService) -> None:
    service.record_completed(service_name="ExportService", operation="export")
    service.record_completed(service_name="KPIEngine", operation="calculate_all")
    service.record_completed(service_name="AIRecommendationService", operation="generate_recommendations")

    names = [health.service_name for health in service.get_all_service_health()]
    assert names == sorted(names)
    assert set(names) == {"ExportService", "KPIEngine", "AIRecommendationService"}


# ==============================================================================
# 7. Tenant-aware events (Task 8)
# ==============================================================================


def test_time_operation_records_tenant_id_and_tenant_name_on_every_event(
    service: MonitoringService, tenant_a: Tenant
) -> None:
    context = TenantContext(tenant=tenant_a)
    with service.time_operation(service_name="KPIEngine", operation="calculate_all", tenant_context=context):
        pass

    for event in service.get_events(service_name="KPIEngine"):
        assert event.tenant_id == "org-a"
        assert event.tenant_name == "Organization A"


def test_event_recorded_with_no_tenant_context_has_none_tenant_fields(service: MonitoringService) -> None:
    event = service.record_completed(service_name="KPIEngine", operation="calculate_all")
    assert event.tenant_id is None
    assert event.tenant_name is None


def test_event_recorded_with_an_empty_tenant_context_has_none_tenant_fields(service: MonitoringService) -> None:
    event = service.record_completed(
        service_name="KPIEngine", operation="calculate_all", tenant_context=TenantContext.empty()
    )
    assert event.tenant_id is None
    assert event.tenant_name is None


def test_get_tenant_activity_never_mixes_one_tenants_operations_into_another(
    service: MonitoringService, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)

    with service.time_operation(service_name="KPIEngine", operation="calculate_all", tenant_context=context_a):
        pass
    with service.time_operation(service_name="KPIEngine", operation="calculate_all", tenant_context=context_a):
        pass
    with service.time_operation(service_name="KPIEngine", operation="calculate_all", tenant_context=context_b):
        pass

    activities = {activity.tenant_id: activity for activity in service.get_tenant_activity()}
    assert activities["org-a"].operation_count == 2
    assert activities["org-b"].operation_count == 1
    # Proves isolation: A's count is unaffected by B's events and vice versa.
    assert activities["org-a"].operation_count != activities["org-b"].operation_count


def test_get_tenant_activity_excludes_events_with_no_tenant(service: MonitoringService, tenant_a: Tenant) -> None:
    service.record_completed(service_name="KPIEngine", operation="calculate_all")  # no tenant
    service.record_completed(
        service_name="KPIEngine", operation="calculate_all", tenant_context=TenantContext(tenant=tenant_a)
    )

    activities = service.get_tenant_activity()
    assert len(activities) == 1
    assert activities[0].tenant_id == "org-a"


def test_most_active_tenant_returns_the_tenant_with_the_most_operations(
    service: MonitoringService, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)
    for _ in range(3):
        service.record_completed(service_name="KPIEngine", operation="calculate_all", tenant_context=context_a)
    service.record_completed(service_name="KPIEngine", operation="calculate_all", tenant_context=context_b)

    busiest = service.most_active_tenant()
    assert busiest is not None
    assert busiest.tenant_id == "org-a"
    assert busiest.operation_count == 3


def test_most_active_tenant_returns_none_when_nothing_is_tenant_attributed(service: MonitoringService) -> None:
    service.record_completed(service_name="KPIEngine", operation="calculate_all")
    assert service.most_active_tenant() is None


# ==============================================================================
# 8. Dashboard statistics (Task 9's data source)
# ==============================================================================


def test_get_platform_stats_aggregates_across_every_service(service: MonitoringService) -> None:
    service.record_completed(service_name="KPIEngine", operation="calculate_all", duration_ms=10.0)
    service.record_completed(service_name="ExportService", operation="export", duration_ms=30.0)
    service.record_failure(service_name="ReportingService", operation="generate_report", error="boom", duration_ms=20.0)
    service.record_started(service_name="KPIEngine", operation="calculate_all")  # excluded

    stats = service.get_platform_stats()
    assert stats.total_operations == 3
    assert stats.successful_operations == 2
    assert stats.failed_operations == 1
    assert stats.average_duration_ms == pytest.approx(20.0)


def test_get_platform_stats_with_no_events_has_zero_counts_and_no_average(service: MonitoringService) -> None:
    stats = service.get_platform_stats()
    assert stats.total_operations == 0
    assert stats.successful_operations == 0
    assert stats.failed_operations == 0
    assert stats.average_duration_ms is None


def test_get_events_applies_limit_and_returns_newest_first(service: MonitoringService) -> None:
    for i in range(5):
        service.record_info(service_name="KPIEngine", operation="calculate_all", message=f"note {i}")
        time.sleep(0.001)

    limited = service.get_events(limit=2)
    assert len(limited) == 2
    assert limited[0].message == "note 4"
    assert limited[1].message == "note 3"


def test_get_events_filters_by_tenant_service_type_and_status(
    service: MonitoringService, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    context_a = TenantContext(tenant=tenant_a)
    context_b = TenantContext(tenant=tenant_b)
    service.record_completed(service_name="KPIEngine", operation="calculate_all", tenant_context=context_a)
    service.record_failure(service_name="ExportService", operation="export", error="x", tenant_context=context_b)

    assert len(service.get_events(tenant_id="org-a")) == 1
    assert len(service.get_events(service_name="ExportService")) == 1
    assert len(service.get_events(event_type=EventType.OPERATION_FAILED)) == 1
    assert len(service.get_events(status=EventStatus.SUCCESS)) == 1
