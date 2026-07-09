"""Unit tests for the Automation Platform (Sprint 6.7).

This file is part of the Task 11 deliverable: comprehensive coverage of
the ``automation/`` package -- the event/job models, event construction
helpers, the in-memory event store and its registry, the Scheduler
(registration, due-job computation, manual execution, DI store), the
Automation Service (publish, handler registration/dispatch, event
querying, scheduled-job triggering), and integration with the existing
Monitoring Service.

Following the convention already established by every prior sprint's
test suite, this file does not import ``streamlit`` or anything from
``components/``/``ui/``/``pages/``. It also never imports
``notification/`` or ``config/automation_setup.py`` -- proving
``automation/`` is usable entirely on its own, with no dependency on
who ends up consuming its events (Task 1: "framework-agnostic",
Task 4: "Business services should never manage automation logic
directly").

Every test constructs its own :class:`~automation.service.AutomationService`
backed by a fresh :class:`~automation.provider.InMemoryAutomationEventStore`
and a fresh :class:`~automation.scheduler.Scheduler` (via Dependency
Injection) rather than using the shared, application-wide singletons --
this is what keeps tests fully isolated from each other and from
whatever a real page's import chain (via ``config/automation_setup.py``)
would otherwise register onto the shared instances. The one exception
is the monitoring-integration tests, which necessarily exercise the
shared ``monitoring.service.monitoring_service`` singleton (since
:class:`~automation.service.AutomationService` always records into it,
by design) -- those tests clear its active provider before and after
themselves, mirroring ``tests/test_identity.py``'s ``clean_monitoring``
fixture exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from automation.events import build_event, new_event_id, utc_now
from automation.exceptions import (
    JobAlreadyRegisteredError,
    NoActiveProviderError,
    ProviderNotRegisteredError,
    UnknownJobError,
)
from automation.models import (
    AutomationEvent,
    EventProcessingStatus,
    EventType,
    JobStatus,
    ScheduledJob,
    ScheduleFrequency,
)
from automation.provider import AutomationEventStore, InMemoryAutomationEventStore
from automation.registry import AutomationEventStoreRegistry
from automation.scheduler import Scheduler
from automation.service import ALL_EVENTS_WILDCARD, AutomationService
from monitoring.provider import InMemoryMonitoringProvider
from monitoring.registry import monitoring_provider_registry
from monitoring.service import monitoring_service
from tenancy.models import Tenant

try:
    from tenancy.context import TenantContext
except ImportError:  # pragma: no cover - defensive, matches other test files' import shape
    TenantContext = None


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def store() -> InMemoryAutomationEventStore:
    """A fresh, empty in-memory event store, isolated to a single test."""
    return InMemoryAutomationEventStore()


@pytest.fixture
def scheduler() -> Scheduler:
    """A fresh Scheduler with its own job store, isolated to a single test."""
    return Scheduler()


@pytest.fixture
def service(store: InMemoryAutomationEventStore, scheduler: Scheduler) -> AutomationService:
    """An AutomationService wired to fresh dependencies via Dependency Injection.

    Never touches the shared, application-wide ``automation_service``
    singleton or its scheduler, so tests never leak handlers/jobs into
    (or read stale ones from) each other.
    """
    return AutomationService(store=store, scheduler=scheduler)


@pytest.fixture
def tenant_context():
    """A minimal, active TenantContext for tests that need tenant attribution."""
    return TenantContext(tenant=Tenant(tenant_id="acme-retail", name="acme-retail", display_name="Acme Retail Group"))


@pytest.fixture
def clean_monitoring():
    """Clear the provider the shared ``monitoring_service`` actually writes to.

    Mirrors ``tests/test_identity.py``'s fixture of the same name exactly
    -- see that file's docstring for the full rationale.
    """
    monitoring_service._provider.clear()
    yield
    monitoring_service._provider.clear()


# ==============================================================================
# 1. Models
# ==============================================================================


def test_event_type_is_a_plain_string() -> None:
    assert EventType.DATA_UPLOADED == "data_uploaded"
    assert EventType.REPORT_GENERATED == "report_generated"
    assert EventType.PDF_GENERATED == "pdf_generated"
    assert EventType.EXPORT_COMPLETED == "export_completed"
    assert EventType.AI_ANALYSIS_COMPLETED == "ai_analysis_completed"
    assert EventType.KPI_THRESHOLD_REACHED == "kpi_threshold_reached"
    assert EventType.LOGIN_SUCCESS == "login_success"
    assert EventType.LOGIN_FAILED == "login_failed"


def test_event_processing_status_is_a_plain_string() -> None:
    assert EventProcessingStatus.PUBLISHED == "published"
    assert EventProcessingStatus.HANDLED == "handled"
    assert EventProcessingStatus.FAILED == "failed"


def test_automation_event_defaults() -> None:
    event = AutomationEvent(
        event_id="abc123",
        event_type=EventType.DATA_UPLOADED,
        source_service="DataLoader",
        timestamp=datetime.now(timezone.utc),
        status=EventProcessingStatus.PUBLISHED,
    )
    assert event.tenant_id is None
    assert event.tenant_name is None
    assert event.user_id is None
    assert event.payload == {}


def test_automation_event_is_frozen() -> None:
    event = AutomationEvent(
        event_id="abc123",
        event_type=EventType.DATA_UPLOADED,
        source_service="DataLoader",
        timestamp=datetime.now(timezone.utc),
        status=EventProcessingStatus.PUBLISHED,
    )
    with pytest.raises(Exception):
        event.status = EventProcessingStatus.HANDLED  # type: ignore[misc]


def test_schedule_frequency_is_a_plain_string() -> None:
    assert ScheduleFrequency.DAILY == "daily"
    assert ScheduleFrequency.WEEKLY == "weekly"
    assert ScheduleFrequency.MONTHLY == "monthly"
    assert ScheduleFrequency.MANUAL == "manual"


def test_scheduled_job_defaults() -> None:
    job = ScheduledJob(job_id="j1", name="Job One", frequency=ScheduleFrequency.DAILY)
    assert job.enabled is True
    assert job.last_run_at is None
    assert job.last_status == JobStatus.NEVER_RUN
    assert job.next_run_at is None


# ==============================================================================
# 2. Event construction helpers
# ==============================================================================


def test_new_event_id_is_unique() -> None:
    assert new_event_id() != new_event_id()


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is not None


def test_build_event_normalizes_known_string_to_enum_member() -> None:
    event = build_event(
        event_type="data_uploaded", source_service="DataLoader", status=EventProcessingStatus.PUBLISHED
    )
    assert event.event_type is EventType.DATA_UPLOADED


def test_build_event_preserves_a_novel_future_event_type_string() -> None:
    """Task 3: 'Design for future extensibility' -- an unrecognized event
    type string must survive build_event() unchanged, never rejected."""
    event = build_event(
        event_type="future_workflow_step_completed",
        source_service="FutureService",
        status=EventProcessingStatus.PUBLISHED,
    )
    assert event.event_type == "future_workflow_step_completed"


def test_build_event_assigns_unique_ids_and_timestamps() -> None:
    first = build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED)
    second = build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED)
    assert first.event_id != second.event_id


def test_build_event_payload_defaults_to_empty_dict_and_is_copied() -> None:
    payload = {"row_count": 10}
    event = build_event(
        event_type=EventType.DATA_UPLOADED, source_service="DataLoader",
        status=EventProcessingStatus.PUBLISHED, payload=payload,
    )
    payload["row_count"] = 999  # mutate the original after building
    assert event.payload["row_count"] == 10  # the event's copy is unaffected


def test_build_event_with_no_payload_returns_empty_dict() -> None:
    event = build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED)
    assert event.payload == {}


# ==============================================================================
# 3. Automation Event Store (Provider Pattern)
# ==============================================================================


def test_store_record_and_list_events(store: InMemoryAutomationEventStore) -> None:
    event = build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED)
    store.record(event)
    events = store.list_events()
    assert len(events) == 1
    assert events[0] == event


def test_store_list_events_newest_first(store: InMemoryAutomationEventStore) -> None:
    older = build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED)
    store.record(older)
    newer = build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED)
    store.record(newer)
    events = store.list_events()
    assert events[0].event_id == newer.event_id


def test_store_list_events_filters_by_every_field(store: InMemoryAutomationEventStore) -> None:
    match = build_event(
        event_type=EventType.REPORT_GENERATED, source_service="ReportingService",
        status=EventProcessingStatus.HANDLED, tenant_id="acme-retail",
    )
    other = build_event(
        event_type=EventType.PDF_GENERATED, source_service="PDFGeneratorService",
        status=EventProcessingStatus.PUBLISHED, tenant_id="other-tenant",
    )
    store.record(match)
    store.record(other)

    assert store.list_events(tenant_id="acme-retail") == (match,)
    assert store.list_events(event_type=EventType.REPORT_GENERATED) == (match,)
    assert store.list_events(status=EventProcessingStatus.HANDLED) == (match,)
    assert store.list_events(source_service="ReportingService") == (match,)


def test_store_list_events_respects_limit(store: InMemoryAutomationEventStore) -> None:
    for _ in range(5):
        store.record(build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED))
    assert len(store.list_events(limit=2)) == 2


def test_store_clear_removes_everything(store: InMemoryAutomationEventStore) -> None:
    store.record(build_event(event_type=EventType.DATA_UPLOADED, source_service="DataLoader", status=EventProcessingStatus.PUBLISHED))
    store.clear()
    assert store.list_events() == ()


def test_store_satisfies_automation_event_store_protocol(store: InMemoryAutomationEventStore) -> None:
    assert isinstance(store, AutomationEventStore)


class _ReadOnlyEventStore:
    """A from-scratch store with no shared base class, proving Provider Pattern swappability."""

    def __init__(self) -> None:
        self._events: list[AutomationEvent] = []

    def record(self, event: AutomationEvent) -> None:
        self._events.append(event)

    def list_events(self, **kwargs) -> tuple[AutomationEvent, ...]:
        return tuple(self._events)

    def clear(self) -> None:
        self._events.clear()


def test_automation_service_works_unmodified_against_a_brand_new_store_implementation() -> None:
    custom_store = _ReadOnlyEventStore()
    assert isinstance(custom_store, AutomationEventStore)

    custom_service = AutomationService(store=custom_store, scheduler=Scheduler())
    event = custom_service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    assert len(custom_store.list_events()) == 1
    assert custom_store.list_events()[0].event_id == event.event_id


# ==============================================================================
# 4. Automation Event Store Registry
# ==============================================================================


def test_registry_first_registered_store_becomes_active() -> None:
    registry = AutomationEventStoreRegistry()
    registry.register("memory", InMemoryAutomationEventStore())
    assert registry.active_name == "memory"


def test_registry_register_and_get() -> None:
    registry = AutomationEventStoreRegistry()
    store_instance = InMemoryAutomationEventStore()
    registry.register("memory", store_instance)
    assert registry.get("memory") is store_instance


def test_registry_get_unknown_raises() -> None:
    registry = AutomationEventStoreRegistry()
    with pytest.raises(ProviderNotRegisteredError):
        registry.get("does-not-exist")


def test_registry_get_active_with_no_stores_raises() -> None:
    registry = AutomationEventStoreRegistry()
    with pytest.raises(NoActiveProviderError):
        registry.get_active()


def test_registry_set_active_switches_store() -> None:
    registry = AutomationEventStoreRegistry()
    registry.register("memory", InMemoryAutomationEventStore())
    second = InMemoryAutomationEventStore()
    registry.register("second", second)
    assert registry.active_name == "memory"  # first registered wins by default

    registry.set_active("second")
    assert registry.active_name == "second"
    assert registry.get_active() is second


def test_registry_make_active_true_switches_immediately() -> None:
    registry = AutomationEventStoreRegistry()
    registry.register("memory", InMemoryAutomationEventStore())
    second = InMemoryAutomationEventStore()
    registry.register("second", second, make_active=True)
    assert registry.active_name == "second"


def test_registry_registered_providers_sorted() -> None:
    registry = AutomationEventStoreRegistry()
    registry.register("zeta", InMemoryAutomationEventStore())
    registry.register("alpha", InMemoryAutomationEventStore())
    assert registry.registered_providers() == ("alpha", "zeta")


def test_registry_clear_resets_active_selection() -> None:
    registry = AutomationEventStoreRegistry()
    registry.register("memory", InMemoryAutomationEventStore())
    registry.clear()
    assert registry.active_name is None
    assert registry.registered_providers() == ()


# ==============================================================================
# 5. Scheduler (Task 5)
# ==============================================================================


def test_scheduler_register_job_returns_it_with_computed_next_run_at(scheduler: Scheduler) -> None:
    job = scheduler.register_job("daily_job", "Daily Job", ScheduleFrequency.DAILY, callback=lambda: None)
    assert job.job_id == "daily_job"
    assert job.next_run_at is not None
    assert job.next_run_at > datetime.now(timezone.utc)


def test_scheduler_manual_job_has_no_next_run_at(scheduler: Scheduler) -> None:
    job = scheduler.register_job("manual_job", "Manual Job", ScheduleFrequency.MANUAL, callback=lambda: None)
    assert job.next_run_at is None


def test_scheduler_register_duplicate_job_id_raises(scheduler: Scheduler) -> None:
    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: None)
    with pytest.raises(JobAlreadyRegisteredError):
        scheduler.register_job("job1", "Job One Again", ScheduleFrequency.WEEKLY, callback=lambda: None)


def test_scheduler_unregister_job_removes_it(scheduler: Scheduler) -> None:
    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: None)
    scheduler.unregister_job("job1")
    with pytest.raises(UnknownJobError):
        scheduler.get_job("job1")


def test_scheduler_unregister_unknown_job_does_not_raise(scheduler: Scheduler) -> None:
    scheduler.unregister_job("never-existed")  # no error


def test_scheduler_get_job_unknown_raises(scheduler: Scheduler) -> None:
    with pytest.raises(UnknownJobError):
        scheduler.get_job("does-not-exist")


def test_scheduler_list_jobs_sorted_by_job_id(scheduler: Scheduler) -> None:
    scheduler.register_job("zeta_job", "Zeta", ScheduleFrequency.DAILY, callback=lambda: None)
    scheduler.register_job("alpha_job", "Alpha", ScheduleFrequency.DAILY, callback=lambda: None)
    job_ids = [job.job_id for job in scheduler.list_jobs()]
    assert job_ids == ["alpha_job", "zeta_job"]


def test_scheduler_due_jobs_returns_only_past_due_enabled_non_manual_jobs(scheduler: Scheduler) -> None:
    scheduler.register_job("daily_job", "Daily", ScheduleFrequency.DAILY, callback=lambda: None)
    scheduler.register_job("manual_job", "Manual", ScheduleFrequency.MANUAL, callback=lambda: None)

    # Nothing is due yet -- both jobs were just registered with a future next_run_at
    # (or no next_run_at at all, for the manual job).
    assert scheduler.due_jobs() == ()

    # A moment far enough in the future makes the daily job due, but never the manual one.
    far_future = datetime.now(timezone.utc) + timedelta(days=2)
    due = scheduler.due_jobs(as_of=far_future)
    assert [job.job_id for job in due] == ["daily_job"]


def test_scheduler_due_jobs_excludes_disabled_jobs(scheduler: Scheduler) -> None:
    scheduler.register_job("daily_job", "Daily", ScheduleFrequency.DAILY, callback=lambda: None, enabled=False)
    far_future = datetime.now(timezone.utc) + timedelta(days=2)
    assert scheduler.due_jobs(as_of=far_future) == ()


def test_scheduler_run_job_success_updates_status_and_timestamps(scheduler: Scheduler) -> None:
    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: "done")
    result = scheduler.run_job("job1")

    assert result.status == JobStatus.SUCCESS
    assert result.result == "done"
    assert result.error is None

    updated = scheduler.get_job("job1")
    assert updated.last_status == JobStatus.SUCCESS
    assert updated.last_run_at is not None


def test_scheduler_run_job_failure_is_captured_not_raised(scheduler: Scheduler) -> None:
    def _boom() -> None:
        raise RuntimeError("job blew up")

    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=_boom)
    result = scheduler.run_job("job1")  # must not raise

    assert result.status == JobStatus.FAILED
    assert "job blew up" in result.error
    assert scheduler.get_job("job1").last_status == JobStatus.FAILED


def test_scheduler_run_job_unknown_raises(scheduler: Scheduler) -> None:
    with pytest.raises(UnknownJobError):
        scheduler.run_job("does-not-exist")


def test_scheduler_run_job_advances_next_run_at_for_non_manual_jobs(scheduler: Scheduler) -> None:
    scheduler.register_job("weekly_job", "Weekly", ScheduleFrequency.WEEKLY, callback=lambda: None)
    before = scheduler.get_job("weekly_job").next_run_at
    scheduler.run_job("weekly_job")
    after = scheduler.get_job("weekly_job").next_run_at
    assert after > before


def test_scheduler_set_enabled_toggles_without_removing_job(scheduler: Scheduler) -> None:
    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: None)
    updated = scheduler.set_enabled("job1", False)
    assert updated.enabled is False
    assert scheduler.get_job("job1").enabled is False


def test_scheduler_clear_removes_every_job(scheduler: Scheduler) -> None:
    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: None)
    scheduler.register_job("job2", "Job Two", ScheduleFrequency.WEEKLY, callback=lambda: None)
    scheduler.clear()
    assert scheduler.list_jobs() == ()


def test_scheduler_accepts_an_injected_store() -> None:
    """A plain dict satisfies the MutableMapping store contract (Task 1's DI requirement)."""
    custom_store: dict[str, ScheduledJob] = {}
    mgr = Scheduler(store=custom_store)
    mgr.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: None)
    assert "job1" in custom_store


# ==============================================================================
# 6. Automation Service -- publish(), handlers (Task 4)
# ==============================================================================


def test_publish_with_no_handlers_returns_published_status(service: AutomationService) -> None:
    event = service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    assert event.status == EventProcessingStatus.PUBLISHED


def test_publish_with_succeeding_handler_returns_handled_status(service: AutomationService) -> None:
    received = []
    service.register_handler(EventType.DATA_UPLOADED, received.append)
    event = service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    assert event.status == EventProcessingStatus.HANDLED
    assert len(received) == 1
    assert received[0].event_id == event.event_id


def test_publish_with_failing_handler_returns_failed_status_and_never_raises(service: AutomationService) -> None:
    def _broken_handler(event) -> None:
        raise RuntimeError("handler exploded")

    service.register_handler(EventType.DATA_UPLOADED, _broken_handler)
    event = service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")  # must not raise
    assert event.status == EventProcessingStatus.FAILED


def test_publish_with_one_failing_and_one_succeeding_handler_still_runs_both(service: AutomationService) -> None:
    received = []

    def _broken_handler(event) -> None:
        raise RuntimeError("boom")

    service.register_handler(EventType.DATA_UPLOADED, _broken_handler)
    service.register_handler(EventType.DATA_UPLOADED, received.append)

    event = service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")

    assert len(received) == 1  # the good handler still ran
    assert event.status == EventProcessingStatus.FAILED  # but overall status reflects the failure


def test_publish_only_runs_handlers_for_the_matching_event_type(service: AutomationService) -> None:
    received = []
    service.register_handler(EventType.REPORT_GENERATED, received.append)
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    assert received == []


def test_publish_runs_wildcard_handlers_for_every_event_type(service: AutomationService) -> None:
    received = []
    service.register_handler(ALL_EVENTS_WILDCARD, received.append)
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    service.publish(EventType.REPORT_GENERATED, source_service="ReportingService")
    assert len(received) == 2


def test_publish_stores_the_event(service: AutomationService, store: InMemoryAutomationEventStore) -> None:
    event = service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    stored = store.list_events()
    assert len(stored) == 1
    assert stored[0].event_id == event.event_id


def test_publish_accepts_a_novel_future_event_type_without_any_service_change(service: AutomationService) -> None:
    """Task 11: 'New event types can be added without changing existing services.'"""
    event = service.publish("workflow_step_completed", source_service="FutureWorkflowService")
    assert event.event_type == "workflow_step_completed"
    assert event.status == EventProcessingStatus.PUBLISHED


def test_publish_attaches_tenant_and_user_information(service: AutomationService, tenant_context) -> None:
    event = service.publish(
        EventType.DATA_UPLOADED, source_service="DataLoader", tenant_context=tenant_context, user_id="jane.doe"
    )
    assert event.tenant_id == "acme-retail"
    assert event.tenant_name == "Acme Retail Group"
    assert event.user_id == "jane.doe"


def test_publish_payload_is_carried_through_unchanged(service: AutomationService) -> None:
    event = service.publish(EventType.DATA_UPLOADED, source_service="DataLoader", payload={"row_count": 42})
    assert event.payload == {"row_count": 42}


def test_register_handler_accepts_string_event_types(service: AutomationService) -> None:
    received = []
    service.register_handler("data_uploaded", received.append)
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    assert len(received) == 1


def test_registered_event_types_excludes_wildcard(service: AutomationService) -> None:
    service.register_handler(EventType.DATA_UPLOADED, lambda event: None)
    service.register_handler(ALL_EVENTS_WILDCARD, lambda event: None)
    assert service.registered_event_types() == ("data_uploaded",)


# ==============================================================================
# 7. Automation Service -- get_events() (Task 10 support)
# ==============================================================================


def test_get_events_returns_published_events(service: AutomationService) -> None:
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    service.publish(EventType.REPORT_GENERATED, source_service="ReportingService")
    assert len(service.get_events()) == 2


def test_get_events_filters_by_event_type(service: AutomationService) -> None:
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    service.publish(EventType.REPORT_GENERATED, source_service="ReportingService")
    matching = service.get_events(event_type=EventType.REPORT_GENERATED)
    assert len(matching) == 1
    assert matching[0].event_type == EventType.REPORT_GENERATED


def test_get_events_respects_limit(service: AutomationService) -> None:
    for _ in range(3):
        service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    assert len(service.get_events(limit=1)) == 1


# ==============================================================================
# 8. Automation Service -- trigger_scheduled_job() (Task 4, Task 9)
# ==============================================================================


def test_trigger_scheduled_job_delegates_to_scheduler(service: AutomationService, scheduler: Scheduler) -> None:
    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: "ran")
    result = service.trigger_scheduled_job("job1")
    assert result.status == JobStatus.SUCCESS
    assert result.result == "ran"


def test_trigger_scheduled_job_unknown_raises(service: AutomationService) -> None:
    with pytest.raises(UnknownJobError):
        service.trigger_scheduled_job("does-not-exist")


# ==============================================================================
# 9. Monitoring integration (Task 9)
# ==============================================================================


def _events_for(operation: str) -> tuple:
    """Return every recorded AutomationService event for one operation."""
    return tuple(
        event
        for event in monitoring_service.get_events(service_name="AutomationService")
        if event.operation == operation
    )


def test_publish_event_is_recorded_as_a_completed_monitoring_event(
    service: AutomationService, clean_monitoring
) -> None:
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    events = _events_for("publish_event")
    assert len(events) == 1
    assert events[0].status.value == "success"


def test_handle_event_success_is_recorded(service: AutomationService, clean_monitoring) -> None:
    service.register_handler(EventType.DATA_UPLOADED, lambda event: None)
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    events = _events_for("handle_event")
    assert len(events) == 1
    assert events[0].status.value == "success"


def test_handle_event_failure_is_recorded(service: AutomationService, clean_monitoring) -> None:
    def _broken(event) -> None:
        raise RuntimeError("boom")

    service.register_handler(EventType.DATA_UPLOADED, _broken)
    service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
    events = _events_for("handle_event")
    assert len(events) == 1
    assert events[0].status.value == "failure"


def test_run_scheduled_job_success_is_recorded(
    service: AutomationService, scheduler: Scheduler, clean_monitoring
) -> None:
    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=lambda: None)
    service.trigger_scheduled_job("job1")
    events = _events_for("run_scheduled_job")
    assert len(events) == 1
    assert events[0].status.value == "success"


def test_run_scheduled_job_failure_is_recorded(
    service: AutomationService, scheduler: Scheduler, clean_monitoring
) -> None:
    def _boom() -> None:
        raise RuntimeError("job blew up")

    scheduler.register_job("job1", "Job One", ScheduleFrequency.DAILY, callback=_boom)
    service.trigger_scheduled_job("job1")
    events = _events_for("run_scheduled_job")
    assert len(events) == 1
    assert events[0].status.value == "failure"


def test_a_monitoring_storage_failure_never_prevents_publish(
    store: InMemoryAutomationEventStore, scheduler: Scheduler, clean_monitoring
) -> None:
    """Mirrors AuthenticationService's own resilience guarantee: even if the
    monitoring provider is broken, AutomationService.publish() must still
    correctly publish -- an observability outage can never become an
    automation outage."""

    class _BrokenMonitoringProvider(InMemoryMonitoringProvider):
        def record(self, event) -> None:  # noqa: ANN001 - test double
            raise RuntimeError("storage backend unreachable")

    monitoring_provider_registry.register("broken", _BrokenMonitoringProvider(), make_active=True)
    try:
        broken_service = AutomationService(store=store, scheduler=scheduler)
        event = broken_service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")
        assert event.status == EventProcessingStatus.PUBLISHED  # publish still succeeded
    finally:
        monitoring_provider_registry.register("memory", InMemoryMonitoringProvider(), make_active=True)


def test_a_storage_failure_never_prevents_publish(scheduler: Scheduler) -> None:
    """A broken event store must not stop publish() from running handlers
    and returning a resolved event -- mirrors MonitoringService._store()'s
    resilience guarantee exactly."""

    class _BrokenStore:
        def record(self, event) -> None:
            raise RuntimeError("disk full")

        def list_events(self, **kwargs) -> tuple:
            return ()

        def clear(self) -> None:
            pass

    received = []
    broken_service = AutomationService(store=_BrokenStore(), scheduler=scheduler)
    broken_service.register_handler(EventType.DATA_UPLOADED, received.append)
    event = broken_service.publish(EventType.DATA_UPLOADED, source_service="DataLoader")  # must not raise
    assert event.status == EventProcessingStatus.HANDLED
    assert len(received) == 1


# ==============================================================================
# 10. Regression -- isolation and defaults
# ==============================================================================


def test_fresh_service_instances_do_not_share_handlers(store: InMemoryAutomationEventStore) -> None:
    service_a = AutomationService(store=store, scheduler=Scheduler())
    service_b = AutomationService(store=InMemoryAutomationEventStore(), scheduler=Scheduler())

    received = []
    service_a.register_handler(EventType.DATA_UPLOADED, received.append)
    service_b.publish(EventType.DATA_UPLOADED, source_service="DataLoader")

    assert received == []  # service_b's publish never touched service_a's handler


def test_default_automation_service_constructs_without_arguments() -> None:
    """The zero-argument constructor path every real business service uses."""
    default_service = AutomationService()
    assert isinstance(default_service, AutomationService)


def test_default_scheduler_constructs_without_arguments() -> None:
    default_scheduler = Scheduler()
    assert isinstance(default_scheduler, Scheduler)
