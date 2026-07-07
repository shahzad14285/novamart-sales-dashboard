# Observability & Monitoring Architecture

Sprint 6.4 -- Observability & Monitoring Service.

NovaMart's Service-Oriented Architecture (Tenant Selector -> Tenant
Context -> Upload Center -> Data Loader -> KPI Engine -> Business
Insights -> Reporting Service -> AI Recommendation Service -> PDF
Generator -> Export Service -> Executive Report Center) is unchanged
in this sprint. Every service still does exactly what it did before;
the only thing added is a second, independent line each one now also
does after (and around) its existing work: report what happened to a
centralized Monitoring Service, which knows nothing about sales,
tenants' business data, or reports -- only "a named operation started,
finished, took this long, and succeeded or failed."

## Architecture

```
monitoring/                             -- framework-agnostic monitoring package (no Streamlit)
    models.py         EventType, EventStatus, MonitoringEvent,        (Task 2)
                       ServiceHealth, PlatformStats, TenantActivity    (Task 7, 9 value objects)
    events.py          build_event(), OperationTimer                  (Tasks 2, 6)
    provider.py        MonitoringProvider (Protocol), InMemoryMonitoringProvider  (Task 4)
    registry.py        MonitoringProviderRegistry, monitoring_provider_registry  (Task 4 mechanism)
    service.py         MonitoringService, monitoring_service          (Tasks 3, 6, 7, 8)
    exceptions.py       MonitoringError + 3 subclasses
    __init__.py         re-exports every public symbol above

Every monitored service wraps its existing (unchanged) method body in:
    with monitoring_service.time_operation(
        service_name="<Service>", operation="<operation>", tenant_context=tenant_context
    ):
        ... existing business logic, unchanged ...

Instrumented call sites (Task 5):
    utils/data_loader.py         DataLoader.load_uploaded_file
    components/upload_center.py  _load_and_validate (wraps the loader call)
    utils/kpi_engine.py          KPIEngine.calculate_all
    utils/insights.py            generate_business_insights
    services/reporting_service.py         ReportingService.generate_report
    services/ai_recommendation_service.py AIRecommendationService.generate_recommendations
    services/pdf_generator_service.py     PDFGeneratorService.generate_pdf
    services/export_service.py            ExportService.export
    ui/executive_report_center.py         render_executive_report_center (screen-level, coarse-grained)

ui/monitoring_dashboard.py + pages/6_Monitoring.py   -- Task 9 Administration / Monitoring page
    reads exclusively through monitoring_service.get_platform_stats() / .get_all_service_health()
    / .get_tenant_activity() / .most_active_tenant() / .get_events(...) -- never writes an event.
```

### Why this shape

**A single context manager, not nine hand-written try/except/timer
blocks.** Task 6 explicitly forbids duplicating timing logic across
services. `MonitoringService.time_operation()` is the one place
`OperationTimer` is ever driven: it records `OPERATION_STARTED` on
entry, starts the timer, and on exit records exactly one of
`OPERATION_COMPLETED` (success, with duration) or `OPERATION_FAILED`
(the exception re-raised unchanged, with duration and the exception's
type name). Every one of the nine instrumented call sites is the
identical one-line pattern wrapping its existing body -- adding
monitoring to a tenth service later is copy-pasting that same line with
a new `service_name`/`operation`, never writing a new timer.

**Business services record events; they never decide how those events
are stored.** This is the ticket's central architectural requirement,
and it is enforced structurally, not by convention: `MonitoringService`
depends only on the `MonitoringProvider` `Protocol` (Task 4), and every
business service depends only on `MonitoringService`. Neither
`KPIEngine` nor `ExportService` nor any of the other seven imports
`monitoring.provider` at all -- they cannot reach into storage even by
accident, because nothing in their code has a reference to it.

**A structural `Protocol`, mirroring the pattern already used for AI
providers.** `MonitoringProvider` follows the exact shape of
`services.ai_recommendation_service.RecommendationProvider`: a
`@runtime_checkable typing.Protocol`, satisfied by having compatible
methods, not by inheritance. `InMemoryMonitoringProvider` is the only
implementation this sprint ships; `tests/test_monitoring.py` proves a
second, unrelated class with no shared base can be swapped in with zero
change to `MonitoringService` or to any business service.

**A registry for the active provider, mirroring `TenantRegistry`.**
`MonitoringProviderRegistry` holds every registered provider and
exactly one "active" one; `MonitoringService()` (no explicit provider)
asks the registry for whichever is active. This is what makes a future
migration -- SQLite, PostgreSQL, Prometheus, Grafana, Azure Monitor,
AWS CloudWatch -- a two-line change (`registry.register("sqlite",
SQLiteMonitoringProvider(...))` then `registry.set_active("sqlite")`),
never a code change to `MonitoringService` or to any of the nine
instrumented services. See "Future provider integration" below.

**A storage failure must never become a business failure.**
`MonitoringService._store()` wraps every call into the provider in a
broad `try/except`, logging a warning and swallowing the exception
rather than propagating it. This is the one guarantee every other
design decision in this package serves: an observability outage (a
full in-memory buffer, a future database being briefly unreachable)
can degrade monitoring, but it can never make a sale, a report, or an
export fail. `tests/test_monitoring.py::test_storage_failure_never_propagates_into_the_business_caller`
proves this directly with a provider whose `record()` always raises.

**Tenant fields are read defensively, never validated a second time.**
`monitoring.service._tenant_fields()` extracts `(tenant_id,
tenant_name)` from a `TenantContext` without raising -- unlike
`tenancy.context.validate_tenant_context`, whose job is exactly the
opposite. This is deliberate: tenant *validation* already happens once,
inside the same `with time_operation(...):` block, via each service's
existing `validate_tenant_context(...)` call. Monitoring's job is only
to *record* whatever tenant information was available, including "none
at all" -- which is itself useful operational data (see "A note on
monitoring rejected tenant validations" below).

**One factory function for every event, so identity is never
ad hoc.** `monitoring.events.build_event()` is the single place
`event_id` (a UUID4 hex string) and `timestamp` (UTC) are generated.
No call site -- not `MonitoringService`, not a future direct caller --
ever assigns those fields itself, which is what guarantees every event
in the system is uniquely and consistently identified regardless of
which of the nine instrumented services produced it.

**Aggregates are computed on demand, never kept as running totals.**
`ServiceHealth`, `PlatformStats`, and `TenantActivity` are plain, frozen
dataclasses recomputed from `provider.list_events(...)` every time
they're requested. This avoids an entire class of bugs (a counter that
drifts from the events it's supposed to summarize) at the cost of
O(n) aggregation per dashboard load -- an acceptable trade for this
sprint's default in-memory provider and typical event volumes; a future
higher-volume provider (Prometheus, a time-series database) would
likely maintain its own running aggregates and let
`get_platform_stats()`/`get_all_service_health()` simply forward to it,
which is exactly the kind of change the Provider Pattern isolates to
one new class.

## Event lifecycle

```
1. A business service's method is called (e.g. KPIEngine.calculate_all(df, tenant_context=ctx))
       |
2. Its existing body is entered via:
       with monitoring_service.time_operation(service_name="KPIEngine", operation="calculate_all", tenant_context=ctx):
       |
3. On entry: monitoring_service.record_started(...) builds and stores an
   OPERATION_STARTED / IN_PROGRESS event (tenant id/name captured now, if available)
       |
4. An OperationTimer is started (time.perf_counter())
       |
5. The wrapped, UNCHANGED business logic runs:
       - validate_tenant_context(...) -- may raise MissingTenantContextError / InactiveTenantError
       - the service's real computation
       |
6a. SUCCESS PATH: the `with` block exits normally
       -> timer.stop() measures duration_ms
       -> record_completed(...) builds and stores an OPERATION_COMPLETED / SUCCESS event
       -> the service's return value is handed back to its original caller, unchanged
       |
6b. FAILURE PATH: any exception escapes the `with` block (including a tenant validation failure)
       -> timer.stop() measures duration_ms
       -> record_failure(..., error=exc, ...) builds and stores an OPERATION_FAILED / FAILURE event
          (exc's str() becomes the event's message; exc's type name is captured in metadata["error_type"])
       -> the ORIGINAL exception is re-raised unchanged -- the caller sees exactly the same error
          it always did; monitoring is purely an observer, never a gate
       |
7. Every event above (steps 3, 6a, 6b) is handed to MonitoringService._store(),
   which calls provider.record(event) and swallows (logs, never raises) any storage failure
       |
8. Later, independently, the Administration / Monitoring page (or any other reader) calls
   monitoring_service.get_events(...) / get_service_health(...) / get_platform_stats(...) /
   get_tenant_activity(...) / most_active_tenant() -- each one reads via provider.list_events(...)
   and aggregates on demand; nothing above this line is ever mutated by a read.
```

A `record_warning(...)` or `record_info(...)` call (used for a
non-fatal, non-timed note -- neither wired into a current call site,
but available to any future one) follows the same steps 3 and 7 only,
with `WARNING`/`INFO` in place of the started/completed/failed
sequence; it never measures a duration, since it isn't wrapping a timed
operation.

### A note on monitoring rejected tenant validations

Because `validate_tenant_context(...)` runs *inside* the
`time_operation` block (not before it), a missing or inactive tenant
produces **two** independent signals: the pre-existing structured log
line via `logging.getLogger("novamart.tenancy")` (Sprint 6.3,
unchanged), and a new `OPERATION_FAILED` monitoring event via
`novamart.monitoring`/the active provider. This is a deliberate design
choice, not an accident of where the `with` block happens to start: it
means a tenant-related failure is visible on the Monitoring dashboard
(as a failed operation for that service, and as activity attributable
to that tenant when the tenant *was* identifiable) exactly like any
other failure, directly serving the ticket's "Errors" and "Tenant
Activity" observability goals. The trade-off is that
`ServiceHealth.failed_executions` for a given service includes both
"real" business failures and rejected tenant validations; splitting
those into two counters was judged out of scope for this sprint (the
`event.message` and `event.metadata` already distinguish them for
anyone inspecting the Recent Events log) and is a natural, additive
enhancement for a future provider with richer querying.

## Provider Pattern

```
MonitoringProvider (typing.Protocol, @runtime_checkable)
    record(event: MonitoringEvent) -> None
    list_events(*, tenant_id=None, service_name=None, event_type=None, status=None, limit=None) -> tuple[MonitoringEvent, ...]
    clear() -> None
        |
        +-- InMemoryMonitoringProvider   (this sprint's default; thread-safe via threading.Lock)
        +-- <future> SQLiteMonitoringProvider
        +-- <future> PostgreSQLMonitoringProvider
        +-- <future> PrometheusMonitoringProvider
        +-- <future> GrafanaMonitoringProvider
        +-- <future> AzureMonitorProvider
        +-- <future> AWSCloudWatchProvider

MonitoringProviderRegistry
    register(name, provider, *, make_active=False)
    get(name) -> MonitoringProvider              (raises ProviderNotRegisteredError)
    set_active(name) -> None
    get_active() -> MonitoringProvider            (raises NoActiveProviderError)
    active_name -> str | None
    registered_providers() -> tuple[str, ...]

monitoring_provider_registry = MonitoringProviderRegistry()   # shared, application-wide
monitoring_provider_registry.register("memory", InMemoryMonitoringProvider(), make_active=True)

MonitoringService(provider: MonitoringProvider | None = None)
    -- provider omitted (every real call site) -> monitoring_provider_registry.get_active()
    -- provider supplied (every test) -> that exact instance, fully isolated
```

Because `MonitoringProvider` is a structural `Protocol` rather than an
abstract base class, a future provider needs no import from this
package's inheritance hierarchy at all -- it only needs to expose the
three matching methods. This is proven directly in
`tests/test_monitoring.py::test_monitoring_service_works_unmodified_against_a_brand_new_provider_implementation`,
which builds a minimal provider from scratch (no shared base class)
and shows `MonitoringService` records into it correctly with zero
changes to `MonitoringService` itself.

## Health metrics (Task 7)

`ServiceHealth` is computed by `MonitoringService.get_service_health(service_name)`
/ `get_all_service_health()` from that service's recorded events, live,
every time it's requested:

| Field | Computed as |
|---|---|
| `total_executions` | count of `OPERATION_COMPLETED` + `OPERATION_FAILED` events (excludes `OPERATION_STARTED`, `WARNING`, `INFO`) |
| `successful_executions` | count of `OPERATION_COMPLETED` events |
| `failed_executions` | count of `OPERATION_FAILED` events |
| `warning_count` | count of `WARNING` events |
| `average_duration_ms` | mean `duration_ms` across every `OPERATION_COMPLETED`/`OPERATION_FAILED` event that recorded one; `None` if none has |
| `last_execution` | the latest timestamp across **every** event of any type for that service; `None` if it has never recorded one |

`total_executions` deliberately excludes `OPERATION_STARTED` markers:
counting both the start and the matching completion/failure of the same
operation would double-count every single request. `last_execution`
deliberately includes every event type (including `STARTED`): it
answers "when did this service last do *anything*", the broadest useful
signal, distinct from "how many operations has it *finished*".

## Performance metrics (Task 6)

`OperationTimer` (`monitoring/events.py`) is the single implementation
of "measure elapsed time" in the whole platform -- `time_operation()`
is built directly on it, and no service anywhere writes its own
`time.perf_counter()` pair. It uses `time.perf_counter()` specifically
(a monotonic clock unaffected by system clock adjustments), which is
appropriate for measuring a *duration* as opposed to
`monitoring.events.utc_now()`, which stamps *when* something happened.

`PlatformStats.average_duration_ms` and each `ServiceHealth.average_duration_ms`
use the same rule: the mean over every `OPERATION_COMPLETED`/`OPERATION_FAILED`
event that has a `duration_ms`. A future provider backed by a
time-series store could additionally expose percentiles (p50/p95/p99)
without any change to how `time_operation()` records the raw duration
on each event -- the raw per-event `duration_ms` this sprint already
stores is exactly the input such an enhancement would aggregate over.

## Tenant-aware monitoring (Task 8)

Every event recorded through `time_operation()` (or any `record_*`
method) captures `tenant_id` and `tenant_name` from whatever
`TenantContext` was passed in, via `_tenant_fields()`. `tenant_name` is
captured redundantly at record time (not looked up later by
`tenant_id`) so a historical event still reads correctly even after a
tenant is renamed -- mirroring the same reasoning already applied to
`tenancy.models.Tenant.metadata`.

`get_tenant_activity()` aggregates `operation_count` (completed +
failed events, same rule as `ServiceHealth.total_executions`) and
`last_activity` (latest timestamp of any type) per distinct
`tenant_id`, across every service at once -- this is what lets the
Monitoring dashboard show "which organization is generating the most
load" without any per-service special-casing. Events with no
`tenant_id` (a call made with a missing tenant context) are excluded
from this view, since there's no tenant to attribute them to; they are
still visible in the platform-wide `get_platform_stats()` and in the
Recent Events log. `most_active_tenant()` is `get_tenant_activity()`
plus one `max(...)` call, breaking ties by most recent activity.

`tests/test_monitoring.py` proves isolation directly: two tenants'
operations recorded into the same `MonitoringService` never mix --
tenant A's `operation_count` is unaffected by tenant B's events, and
`get_tenant_activity()` never attributes one tenant's event to another.

## Future provider integration

Adding a new backend later means:

1. Write one new class satisfying `MonitoringProvider` (three methods:
   `record`, `list_events`, `clear`) -- e.g. `SQLiteMonitoringProvider`,
   `PrometheusMonitoringProvider`.
2. Register it: `monitoring_provider_registry.register("sqlite", SQLiteMonitoringProvider("monitoring.db"))`.
3. Activate it: `monitoring_provider_registry.set_active("sqlite")`.

Nothing else changes:

- `MonitoringService` never imports a concrete provider class -- it
  only calls the three `MonitoringProvider` methods, so any conforming
  object works.
- None of the nine instrumented business services import
  `monitoring.provider` or `monitoring.registry` at all -- they only
  ever call `monitoring_service.time_operation(...)`, so a provider
  swap requires editing zero business-service files.
- `ui/monitoring_dashboard.py` only calls `monitoring_service`'s query
  methods (`get_platform_stats()`, etc.) -- it is unaware a provider
  swap ever happened, and continues to render correctly against
  whatever the new provider returns.
- A provider that can't answer part of `list_events()`'s filter set
  efficiently (e.g. an early Prometheus integration exposing only
  aggregate counters, not raw per-event history) can still satisfy the
  `Protocol` by returning an empty tuple or a best-effort subset from
  `list_events()` while implementing `record()` fully -- the aggregate
  query methods (`get_service_health`, `get_platform_stats`,
  `get_tenant_activity`) would simply reflect whatever `list_events()`
  is able to return, with no change required to `MonitoringService`.

## Confirmation against the agreed architecture

- [x] Existing SOA pipeline (Tenant Selector -> Tenant Context ->
      Upload Center -> Data Loader -> KPI Engine -> Business Insights
      -> Reporting Service -> AI Recommendation Service -> PDF
      Generator -> Export Service -> Executive Report Center) preserved
      exactly; only monitoring instrumentation was added.
- [x] Business logic in every instrumented service is unchanged --
      confirmed by inspection: the only addition to each is wrapping
      its existing method body in one `with monitoring_service.time_operation(...):`
      block, with zero re-indentation of logic beyond that single level.
- [x] Dedicated, centralized Monitoring Service (`monitoring/service.py`)
      -- business services record events; they never know how or where
      those events are stored.
- [x] Framework-agnostic `monitoring/` package with no Streamlit
      dependency (`__init__.py`, `models.py`, `events.py`, `service.py`,
      `provider.py`, `registry.py`, `exceptions.py`).
- [x] Reusable Monitoring Event Model (`MonitoringEvent`) with Event
      ID, Timestamp, Tenant ID, Service Name, Operation Name, Event
      Type, Status, Duration, Message, and Metadata, designed for
      future extensibility (a plain, frozen dataclass with an open
      `metadata` mapping).
- [x] Centralized Monitoring Service: record events, record errors,
      record execution duration, record warnings, record informational
      events, retrieve monitoring statistics, retrieve service health
      information -- all as a single entry point (`MonitoringService`).
- [x] Provider Pattern: `MonitoringProvider` abstraction, default
      in-memory provider, future providers (SQLite, PostgreSQL,
      Prometheus, Grafana, Azure Monitor, AWS CloudWatch) pluggable
      with zero change to `MonitoringService` or to any business
      service.
- [x] Monitoring integrated into all nine listed services: Upload
      Center, Data Loader, KPI Engine, Business Insights, Reporting
      Service, AI Recommendation Service, PDF Generator, Export
      Service, Executive Report Center.
- [x] Performance measurement: start time, end time, and duration
      captured automatically via one reusable abstraction
      (`OperationTimer` / `time_operation()`) -- never duplicated per
      service.
- [x] Service Health: successful executions, failed executions,
      warning count, average execution time, last execution, and total
      executions, retrievable through the Monitoring Service
      (`get_service_health` / `get_all_service_health`).
- [x] Tenant awareness: every monitoring event includes Tenant ID and
      Tenant Name from the existing `TenantContext`, enabling
      tenant-level operational reporting (`get_tenant_activity`,
      `most_active_tenant`).
- [x] Administration / Monitoring dashboard (`pages/6_Monitoring.py` +
      `ui/monitoring_dashboard.py`) displaying Platform Overview,
      Service Statistics, Tenant Activity, and a Recent Events log.
- [x] Comprehensive tests covering event creation, the Monitoring
      Service, provider abstraction (including a from-scratch custom
      provider), performance timing, error recording, service health,
      tenant-aware events (including isolation), and dashboard
      statistics (`tests/test_monitoring.py`).
- [x] Existing services continue working: the full pre-existing test
      suite (12 files, 238 tests before this sprint) passes unchanged
      alongside the 43 new monitoring tests, with zero modification to
      any pre-existing test file.
- [x] Follows Single Responsibility Principle, Separation of Concerns,
      Service-Oriented Architecture, Provider Pattern, Registry Pattern,
      Dependency Injection (`MonitoringService(provider=...)`), and
      Clean Architecture (framework-agnostic `monitoring/` core,
      Streamlit coupling isolated to `ui/monitoring_dashboard.py` and
      `pages/6_Monitoring.py`).
- [x] Type hints, docstrings, and professional logging throughout; no
      monitoring code duplicated across services (one `time_operation`
      choke point), no hardcoded provider, no tight coupling, no new
      global mutable state beyond the same kind of shared,
      module-level singleton pattern (`monitoring_service`,
      `monitoring_provider_registry`) already used by every other
      service in this codebase (`sales_kpi_engine`, `tenant_registry`,
      etc.), and no changes to existing business logic.

## Automated tests

`tests/test_monitoring.py` (new, 43 tests) covers the `monitoring/`
package end to end: event creation and immutability (`build_event`,
uniqueness of `event_id`); every `MonitoringService` recording
primitive (`record_started`/`record_completed`/`record_failure`/
`record_warning`/`record_info`, including validation errors for a
missing `service_name`/`operation`); the Provider Pattern (the default
`InMemoryMonitoringProvider`'s filtering/ordering/`clear()` behavior,
`MonitoringProviderRegistry`'s register/get/set_active/get_active
semantics including its two dedicated exceptions, and a from-scratch
custom provider proving `MonitoringService` needs zero changes to work
against a brand-new storage backend); `OperationTimer` and
`time_operation()` (duration measurement, the started-then-completed
sequence on success, the started-then-failed-with-reraise sequence on
an exception, and the storage-failure-resilience guarantee via a
provider whose `record()` always raises); `ServiceHealth` aggregation
(zero-event baseline, and a mixed success/failure/warning/started
scenario with a hand-checked average duration); tenant-aware events
(tenant id/name capture, `None`/empty-context handling, and -- the
isolation check -- two tenants' operations recorded into the same
service never mixing in `get_tenant_activity()` or
`most_active_tenant()`); and the dashboard's data source
(`get_platform_stats()`, `get_events()`'s filtering and `limit`
behavior).

Every pre-existing test file was left completely unmodified this
sprint (`tests/test_kpi_engine.py`, `tests/test_insights.py`,
`tests/test_export_service.py`, `tests/test_reporting_service.py`,
`tests/test_ai_recommendation_service.py`,
`tests/test_pdf_generator_service.py`, `tests/test_multi_tenancy.py`,
`tests/test_analytics.py`, `tests/test_calculations.py`,
`tests/test_filters.py`, `tests/test_formatting.py`,
`tests/test_helpers.py`) -- monitoring only wraps each instrumented
method's existing body, it never alters a signature, a return value, or
a business rule, so no existing assertion needed to change.

Verification performed: `python3 -m py_compile` across the entire
project tree (zero errors), then real execution of all thirteen
`pytest`-style test files (281 tests total: 238 pre-existing + 43 new,
0 failures) via a hand-built `pytest`-compatible shim in this offline
sandbox (real `pytest` isn't installed and there is no network access
to install it -- `pandas`, `reportlab`, `pdfplumber`, and `openpyxl`
are already present, so those tests run against the real libraries, not
mocks). In addition, a headless dry run using a minimal Streamlit-API
stub exercised `ui.executive_report_center.render_executive_report_center()`
and `ui.monitoring_dashboard.render_monitoring_dashboard()` together
end to end against real business data and a real, freshly-cleared
`MonitoringService`: simulating traffic across four services and two
tenants (including one recorded failure and one recorded warning),
confirming the dashboard renders every section (Platform Overview,
Service Statistics, Tenant Activity, Recent Events) with zero
unhandled exceptions and correctly aggregated numbers, then separately
confirming the dashboard's empty-state guidance renders correctly
against a freshly cleared provider with no events at all.

## Manual test cases

| # | Steps | Expected result |
|---|-------|------------------|
| 1 | Open the new "Monitoring" page from the sidebar navigation before uploading any data anywhere in the app | Platform Overview, Service Statistics, and Tenant Activity each show a calm "no operations recorded yet" empty state rather than zeros presented as if they were real measurements. |
| 2 | Upload a valid sales file on the Dashboard page, then open the Monitoring page | Platform Overview's Total/Successful Operations increase; Service Statistics shows a row for `KPIEngine` and `BusinessInsights` with a 100% success rate and a measured average duration. |
| 3 | Generate an Executive Report, its AI Recommendations, a PDF, and a CSV export on the Reports page, then reload the Monitoring page | Service Statistics now also lists `ReportingService`, `AIRecommendationService`, `PDFGeneratorService`, `ExportService`, and `ExecutiveReportCenter`, each with plausible request counts and durations; Recent Events shows each operation's `OPERATION_COMPLETED` entry near the top, newest first. |
| 4 | On the Export tab of the Reports page, request an export format that later becomes unsupported (e.g. temporarily rename `"csv"` to `"cvs"` in a test, or otherwise force an `UnsupportedExportFormatError`) | The Reports page still shows its existing, unchanged `st.error(...)` message; the Monitoring page's Service Statistics shows `ExportService`'s failed-execution count increase, and the failure appears in Recent Events with the error message. |
| 5 | Switch the "Active Tenant" dropdown to a second organization, upload a dataset for it, and generate a report | Tenant Activity on the Monitoring page now lists both organizations with independent operation counts; "Most Active Tenant" reflects whichever organization has generated more completed/failed operations so far. |
| 6 | On the Monitoring page's Recent Events section, filter by a specific service and then by a specific status | The event table narrows to only matching rows in both cases; switching either filter back to "All" restores the full (limited) list. |
| 7 | (Developer test) Temporarily set a tenant to `TenantStatus.INACTIVE` in `config/tenants.py`, restart the app, and attempt to use it via the sidebar before it's filtered out (or call a service directly with an inactive tenant's context) | The existing tenant-rejection message/behavior from Sprint 6.3 is unchanged; the Monitoring page's Recent Events log additionally shows an `OPERATION_FAILED` entry for that attempt, giving an administrator visibility into the rejected access attempt. |
| 8 | (Developer test) Register and activate a second, in-memory-backed custom `MonitoringProvider` via `monitoring_provider_registry` at app startup, then repeat test case 2 | The app behaves identically from the user's perspective; the Monitoring page continues to render correctly, now backed by the newly active provider -- confirming the provider swap required no change to any page, service, or dashboard code. |
