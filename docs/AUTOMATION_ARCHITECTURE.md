# NovaMart Automation & Notification Platform

Sprint 6.7 -- Automation & Notification Platform.

This document describes the centralized automation and notification
layer introduced in this sprint: a framework-agnostic `automation/`
package (event publication, handler dispatch, scheduled jobs) and a
dedicated `notification/` package (templating, provider-based delivery,
delivery history) that together let business services *announce* that
something happened without ever knowing who reacts to it or how.

It follows the structure and depth of `docs/IDENTITY_ARCHITECTURE.md`
and `docs/AUTHORIZATION_ARCHITECTURE.md`.

---

## 1. Automation Architecture

### 1.1 Why a separate platform, not a feature bolted onto existing services

The ticket's central constraint is architectural, not functional:

> "Automation must remain completely separated from business services.
> Business services should never send emails, notifications, or
> schedule background work directly."

Every business service this sprint touches (`ReportingService`,
`PDFGeneratorService`, `ExportService`, `AIRecommendationService`,
`DataLoader`, `AuthenticationService`) already has exactly one
responsibility, established by prior sprints. Adding "and also decide
who to notify, on what channel, with what wording" to any of them would
violate the Single Responsibility Principle those services were
explicitly built to uphold, and would mean every future notification
requirement change touches business logic that has nothing to do with
notifications.

The Automation & Notification Platform solves this with two new,
independent packages plus one narrow composition-root file:

```
automation/          -- generic, reusable event bus + scheduler.
                         Framework-agnostic. Never imports notification/.

notification/        -- one consumer of automation events. Renders
                         templates, selects a provider, delivers.
                         Never imports automation/ except structurally,
                         as the type of the event it receives as a
                         parameter to handle_event().

config/automation_setup.py
                      -- the ONLY file in the codebase allowed to import
                         and wire automation/ and notification/
                         together. Mirrors config/credentials.py from
                         Sprint 6.6 (the identity <-> authorization
                         bridge) exactly.
```

A business service's entire automation footprint is one line:

```python
automation_service.publish(
    EventType.REPORT_GENERATED,
    source_service="ReportingService",
    payload={"report_type": key, "section_count": len(report.sections)},
    tenant_context=tenant_context,
)
```

It never imports `notification/`, never knows a Slack channel or email
address exists, and never learns whether the notification succeeded.
"Business services should simply announce that something happened.
Automation should decide what to do next" -- verbatim from the ticket
-- is enforced structurally: `notification/` has no public surface a
business service could call even by mistake, since its only entry point
(`NotificationService.handle_event`) is wired in as a *handler*, not
exposed as a service business code imports.

### 1.2 Target architecture, as built

```
Business Services (ReportingService, PDFGeneratorService,
ExportService, AIRecommendationService, DataLoader,
AuthenticationService, KPIThresholdWatcher)
        |
        | automation_service.publish(event_type, source_service=..., payload=..., tenant_context=...)
        v
AutomationService  (automation/service.py)
        |
        |-- stores the event via AutomationEventStore  (automation/provider.py)
        |-- runs every EventHandler registered for that event_type
        |         |
        |         v
        |   NotificationService.handle_event   (notification/service.py)
        |         |
        |         |-- selects a route (event_type -> channel, recipient)
        |         |-- selects + renders a NotificationTemplate  (notification/templates.py)
        |         |-- selects a NotificationProvider for that channel
        |         |         (notification/registry.py -> notification/provider.py)
        |         v
        |   Email / Slack / Teams / SMS / WhatsApp / Push / Webhook
        |         (all channel keys exist today; all route through the
        |          same InMemoryNotificationProvider, which simulates
        |          delivery -- see Section 5)
        |
        `-- Scheduler  (automation/scheduler.py)
                  |-- register_job / list_jobs / due_jobs / run_job
                  `-- trigger_scheduled_job() also records to Monitoring
```

Every arrow in this diagram is a real, tested call path in this
sprint's code -- there is no placeholder or "future work" box in the
part of the diagram that is actually implemented.

### 1.3 What each package owns

**`automation/`** owns:
- The vocabulary of "something happened" (`EventType`, `AutomationEvent`).
- Publishing an event and dispatching it to zero or more handlers
  (`AutomationService.publish`).
- A pluggable, swappable place events are stored (`AutomationEventStore`
  Provider Pattern + `AutomationEventStoreRegistry`).
- A pluggable, swappable catalogue of schedulable jobs (`Scheduler`).

**`notification/`** owns:
- The vocabulary of "how to tell someone" (`NotificationChannel`,
  `NotificationMessage`, `NotificationTemplate`).
- Turning one automation event into zero or more notification attempts
  (`NotificationService.handle_event` / `.notify`).
- A pluggable, swappable place a channel's message actually gets sent
  (`NotificationProvider` Provider Pattern + `NotificationProviderRegistry`,
  a *per-channel routing table*, not a single active backend).
- A pluggable catalogue of subject/body wording (`TemplateRegistry`).

**`config/automation_setup.py`** owns:
- Registering `NotificationService.handle_event` as an
  `AutomationService` handler for every event type this sprint names.
- Registering this sprint's three demo scheduled jobs.
- Nothing else. It contains zero business logic and zero notification
  logic of its own -- it is pure wiring, imported once (for its side
  effect) from `components/sidebar.py`.

### 1.4 Coding standards applied

| Requirement | Where |
|---|---|
| Single Responsibility Principle | `AutomationService` publishes/dispatches; `NotificationService` templates/delivers; `Scheduler` schedules. None do more than one job. |
| Separation of Concerns | `automation/` never imports `notification/`; business services never import `notification/` at all. |
| Clean Architecture | Business services depend only on `automation.service.automation_service`, a single stable interface. Nothing in `automation/`/`notification/` depends on Streamlit. |
| Provider Pattern | `AutomationEventStore`, `NotificationProvider` -- both `typing.Protocol`s with an in-memory default implementation. |
| Registry Pattern | `AutomationEventStoreRegistry`, `NotificationProviderRegistry`, `TemplateRegistry`. |
| Dependency Injection | `AutomationService(store=..., scheduler=...)`, `NotificationService(provider_registry=..., template_registry=...)`, `Scheduler(store=...)` -- every dependency is constructor-injectable; every module-level singleton is just the zero-argument default. |
| Framework Independence | Neither `automation/` nor `notification/` imports `streamlit` anywhere. |
| Professional logging | `logging.getLogger("novamart.automation")` / `"novamart.automation.scheduler"` / `"novamart.notification")`, warning-level on every caught failure. |
| Modular design | Eight files in `automation/`, seven in `notification/`, each with one job (models, events, service, scheduler, registry, provider, exceptions). |

---

## 2. Event Flow

### 2.1 The event model (Task 3)

`automation.models.AutomationEvent` is a frozen dataclass with exactly
the fields the ticket requires:

| Field | Type | Notes |
|---|---|---|
| `event_id` | `str` | UUID4 hex, assigned once by `automation.events.build_event`. |
| `event_type` | `EventType \| str` | `EventType` is a `(str, Enum)` -- accepts a known member *or* any future string. |
| `source_service` | `str` | e.g. `"ReportingService"`. Matches the `service_name` values already used by `monitoring.service.monitoring_service`. |
| `tenant_id` / `tenant_name` | `str \| None` | Extracted from `TenantContext`, or `None` for platform-wide events (e.g. a scheduler job). |
| `user_id` | `str \| None` | The identity that triggered the event, if known. |
| `timestamp` | `datetime` | UTC, assigned once by `build_event`. |
| `payload` | `Mapping[str, object]` | Free-form, event-type-specific. Never inspected by `AutomationService` itself. |
| `status` | `EventProcessingStatus` | `PUBLISHED` (no handler ran), `HANDLED` (every handler succeeded), or `FAILED` (at least one handler raised). |

`EventType` currently has nine members: `DATA_UPLOADED`,
`REPORT_GENERATED`, `PDF_GENERATED`, `EXPORT_COMPLETED`,
`AI_ANALYSIS_COMPLETED`, `KPI_THRESHOLD_REACHED`, `LOGIN_SUCCESS`,
`LOGIN_FAILED`, and `USER_LOGOUT` (added beyond the ticket's explicit
list, per Task 8's "User logout" suggestion). This is deliberately not
a closed set a business service must be hard-coded against --
`AutomationService.publish()` accepts any string, and
`automation.events.build_event()` normalizes a *known* string to the
real enum member while leaving a genuinely novel string untouched (see
Section 7, "New event types without changing existing services").

### 2.2 Step by step: what happens when a business service calls `publish()`

1. A business service (already inside its existing, unmodified
   business-logic method) calls:
   ```python
   automation_service.publish(
       EventType.REPORT_GENERATED, source_service="ReportingService",
       payload={...}, tenant_context=tenant_context,
   )
   ```
2. `AutomationService.publish()` records an `OPERATION_COMPLETED`
   monitoring event (`"publish_event"`) -- this always succeeds,
   regardless of what happens next.
3. It looks up every registered `EventHandler` for that `event_type`,
   plus every handler registered under the `ALL_EVENTS_WILDCARD`.
4. It builds the immutable `AutomationEvent` via `build_event()`
   (assigning `event_id` and `timestamp`).
5. If there are handlers, it runs each one, catching any exception
   individually (`_run_handler`) -- one bad handler can never break
   another handler, and a handler's own monitoring event
   (`"handle_event"`, completed or failed) is recorded per handler.
6. It resolves the event's final `status`:
   - `PUBLISHED` if no handler was registered at all.
   - `HANDLED` if every handler ran without raising.
   - `FAILED` if at least one handler raised.
7. It stores the event exactly once, via the configured
   `AutomationEventStore`, itself wrapped in a try/except so a storage
   failure can never propagate.
8. It returns the finished `AutomationEvent` to the business service.

**The business service's call never raises**, regardless of what
happens in steps 3-7. This is the resilience guarantee that let this
sprint add `automation_service.publish(...)` calls to six existing
services without risking any of the ~415 pre-existing tests.

### 2.3 Where events are stored, and for how long

`AutomationEventStore` (Provider Pattern -- see Section 5) is a
structural `Protocol` with `record`, `list_events`, and `clear`. This
sprint ships `InMemoryAutomationEventStore`: a thread-safe, in-process
list, sufficient for a single-process Streamlit deployment and for
tests. Events persist for the lifetime of the process; there is no
eviction policy in this release (a future SQLite/Kafka/Redis-backed
store would add one without changing `AutomationService`).

### 2.4 Event integration points (Task 8)

| Business service | Event published | Where |
|---|---|---|
| `ReportingService.generate_report()` | `REPORT_GENERATED` | after the `Report` object is built, before returning |
| `PDFGeneratorService.generate_pdf()` | `PDF_GENERATED` | after the `PDFResult` is built, before returning |
| `ExportService.export()` | `EXPORT_COMPLETED` | after the exporter runs, before returning |
| `AIRecommendationService.generate_recommendations()` | `AI_ANALYSIS_COMPLETED` | after the `RecommendationBatch` is built, before returning |
| `DataLoader.load_uploaded_file()` | `DATA_UPLOADED` | after cleaning/validation finishes, before returning |
| `AuthenticationService.sign_in()` | `LOGIN_SUCCESS` / `LOGIN_FAILED` | on success, and on `InvalidCredentialsError`/`InactiveIdentityError` |
| `AuthenticationService.sign_out()` | `USER_LOGOUT` | only when a session actually existed |
| `KPIThresholdWatcher.check_kpi_thresholds()` (new, additive) | `KPI_THRESHOLD_REACHED` | one event per breached KPI, called from `ui/executive_report_center.py` right after KPIs are computed |

Every one of these is a single, additive call appended at the end of
an already-working method -- **no existing return value, exception
type, or observable behavior of any of these methods changed.** This
is verified explicitly: all pre-existing tests for these six services
(``test_reporting_service.py``, ``test_pdf_generator_service.py``,
``test_export_service.py``, ``test_ai_recommendation_service.py``, the
data-loader tests inside ``test_analytics.py``/``test_filters.py``/etc.,
and ``test_identity.py``) still pass unmodified.

`KPIThresholdWatcher` deserves a special note: the ticket says "Do not
modify business logic," and `utils/kpi_engine.py` is exactly that --
business logic. So threshold-checking was **not** added there. Instead,
`services/kpi_threshold_watcher.py` is a brand-new, purely additive
module that only *reads* already-computed `KPIResult` values (never
recalculates anything) and publishes `KPI_THRESHOLD_REACHED` for any
KPI below its configured minimum. It's called once, from
`ui/executive_report_center.py`, immediately after the existing
`sales_kpi_engine.calculate_all(...)` call -- one new line, zero
changes to the KPI engine itself.

---

## 3. Notification Flow

### 3.1 How `NotificationService` gets called at all

`NotificationService.handle_event` is registered as an
`automation.service.EventHandler` by `config/automation_setup.py`:

```python
for event_type in _HANDLED_EVENT_TYPES:
    automation_service.register_handler(event_type, notification_service.handle_event)
```

No business service calls `notification_service` -- most business
services don't even import `notification/`. This is the structural
enforcement of Task 6's "Business services should never send
notifications directly."

### 3.2 Step by step: `handle_event()` -> a delivered notification

1. `AutomationService.publish()` (Section 2.2, step 5) calls
   `notification_service.handle_event(event)` as one of the event's
   registered handlers.
2. `handle_event()` looks up a **route** for `event.event_type` in its
   internal routing table (`event_type -> (channel, recipient_resolver)`).
   If there's no route, it returns `()` immediately -- not every event
   needs a notification, and that's not an error.
3. If a route exists, the recipient resolver runs (either a static
   string, e.g. `"executives@novamart.demo"`, or a callable that
   inspects the event -- e.g. a future "look up this tenant's
   configured contact").
4. `notify()` selects a template: `event.<event_type>` if one is
   registered, else the `event.generic` fallback -- never raises for a
   missing template.
5. `notify()` renders the template's subject/body against a context
   built from the event (`event_type`, `source_service`, `tenant_name`,
   `user_id`, plus every key in `event.payload`). A template
   referencing a context key that isn't present renders the literal
   `{key}` text (via `SafeFormatDict`) instead of raising.
6. `notify()` selects a `NotificationProvider` for the route's channel
   from `NotificationProviderRegistry`.
7. `notify()` calls `provider.send(pending_message)`.
8. On success: the delivered (`SENT`) message is appended to history
   and a monitoring `"send_notification"` completed event is recorded.
   On **any** failure at steps 4-7 (unknown template that also isn't
   the fallback, unregistered channel, or the provider itself raising):
   `_record_failure()` builds a `FAILED` `NotificationMessage`, appends
   it to history, logs a warning, and records a monitoring
   `"send_notification"` failure event -- **`notify()` never raises.**

### 3.3 Default routing table (Task 8's suggested events)

| Event type | Channel | Recipient |
|---|---|---|
| `data_uploaded` | Email | `operations@novamart.demo` |
| `report_generated` | Email | `executives@novamart.demo` |
| `pdf_generated` | Email | `executives@novamart.demo` |
| `export_completed` | Email | `operations@novamart.demo` |
| `ai_analysis_completed` | Slack | `#novamart-insights` |
| `kpi_threshold_reached` | Slack | `#novamart-executives` |
| `login_failed` | Email | `security@novamart.demo` |

This is intentionally a small, illustrative demo table -- a real
deployment would populate it from tenant-specific notification
preferences via the same `register_route()` method, with zero change
to `NotificationService`.

### 3.4 The `EventType` `str()` vs `.value` bug, and why it matters here

`EventType` is a `(str, Enum)` subclass. On this project's Python
version, `str(EventType.REPORT_GENERATED)` returns
`"EventType.REPORT_GENERATED"`, **not** `"report_generated"` -- a
common Python gotcha for `str`-subclassed enums. Because the routing
table and template registry are keyed by plain string values (e.g.
`"report_generated"`), a naive `str(event.event_type)` would silently
break every lookup.

`notification.service._event_type_key()` is the one place this is
normalized: `event_type.value if isinstance(event_type, EventType) else str(event_type)`,
applied consistently in `register_route()`, `handle_event()`, and
`notify()` (including the rendered `{event_type}` placeholder and
monitoring metadata). `AutomationService.publish()`/`register_handler()`
apply the identical normalization independently, so the two packages
never disagree about what a given event type's string key is, even
though they never import each other.

---

## 4. Scheduler Design (Task 5)

### 4.1 Scope, per the ticket

> "Actual background execution is not required. The objective is
> architectural design."

`automation.scheduler.Scheduler` therefore does **not** run a
background thread, a cron loop, or an `asyncio` task. What it provides,
fully working today, is everything a future real scheduler would need
to drive:

- A stable catalogue of named jobs (`register_job`, `list_jobs`,
  `unregister_job`, `get_job`).
- `ScheduleFrequency`: `DAILY`, `WEEKLY`, `MONTHLY`, `MANUAL`.
- Computed `next_run_at` for every non-manual job, recalculated after
  every run (`_next_run_at`, using fixed deltas: 1 day / 1 week / 30
  days).
- `due_jobs(as_of=None)`: every enabled, non-manual job whose
  `next_run_at` has passed -- the exact question a real scheduler's
  poll loop would ask on every tick. Nothing in this sprint calls this
  on a timer; it exists so that loop is a drop-in addition later, not
  a redesign.
- `run_job(job_id)` -- **manual execution**, the one path this sprint
  actually exercises. Both a future automatic trigger and the
  Automation Dashboard's "Run Now" button call exactly this method.
  Updates `last_run_at`, `last_status`, and `next_run_at` regardless of
  whether the callback succeeded or raised; a raising callback is
  captured into `JobExecutionResult.error`, never re-raised.
- `set_enabled(job_id, enabled)` -- toggle without removing.

### 4.2 Why an injectable store (mirrors `identity.session.SessionManager`)

```python
Scheduler(store: MutableMapping[str, ScheduledJob] | None = None)
```

`Scheduler` depends only on a plain `MutableMapping[str, ScheduledJob]`
for its state (defaulting to a `dict`) -- exactly the same DI pattern
`identity.session.SessionManager` already uses for
`MutableMapping[str, SessionInfo]`. This keeps the class framework-
independent while remaining trivially usable from Streamlit (never
imported here) or a future persistent store, and lets every test
inject a fresh store instead of sharing the application-wide
`automation.scheduler.scheduler` singleton.

### 4.3 This sprint's demo jobs

`config/automation_setup.py` registers three demo jobs against the
shared `scheduler` singleton (guarded by `if not scheduler.list_jobs():`
to avoid double-registration across reruns):

| Job id | Frequency | Callback |
|---|---|---|
| `daily_platform_summary` | Daily | Publishes `REPORT_GENERATED` with `payload={"job": "daily_platform_summary", ...}` |
| `weekly_executive_report` | Weekly | Publishes `REPORT_GENERATED` with `payload={"job": "weekly_executive_report", ...}` |
| `monthly_platform_report` | Monthly | Publishes `REPORT_GENERATED` with `payload={"job": "monthly_platform_report", ...}` |

Each callback is deliberately trivial -- it just calls
`automation_service.publish(EventType.REPORT_GENERATED, source_service="Scheduler", ...)`.
This proves the full round trip (Scheduler -> AutomationService ->
NotificationService) works without needing real report data, exactly
matching Task 5's "architectural design" objective and the Business
Goal's "Generate weekly reports" / "Email scheduled reports" bullets.

---

## 5. Provider Pattern

The Provider Pattern is applied **twice, in two different shapes**,
because the two problems it solves are genuinely different:

### 5.1 `AutomationEventStore` -- single active backend

Mirrors `monitoring.provider.MonitoringProvider` exactly: there is
conceptually *one* place events are stored at a time. `AutomationService`
depends on the `AutomationEventStore` `Protocol` (`record`,
`list_events`, `clear`) and resolves its store either via constructor
injection or via `AutomationEventStoreRegistry.get_active()`. Swapping
to a future SQLite/Kafka/Redis-backed store is one `register()` call
plus `set_active()` -- zero changes to `AutomationService`.

### 5.2 `NotificationProvider` -- per-channel routing table, not "one active backend"

This is the more interesting design decision. Unlike monitoring or
automation storage, notification delivery genuinely needs *different
transports simultaneously* -- email and Slack are never
interchangeable "the current backend." So `NotificationProviderRegistry`
is a **routing table**: `NotificationChannel -> NotificationProvider`,
with no "active" concept at all. `NotificationService` looks up
`self._providers.get(channel)` for whatever channel a route selected.

This sprint pre-populates *every* `NotificationChannel` (`EMAIL`,
`SLACK`, `TEAMS`, `SMS`, `WHATSAPP`, `PUSH`, `WEBHOOK`) with **the same**
`InMemoryNotificationProvider` instance (Task 7: "Implement an
in-memory provider that simulates delivery"). It never makes a network
call and always succeeds, keeping every "sent" message in memory
(`sent_messages()`) for introspection and tests.

Replacing just one channel with a real provider later --
`registry.register(NotificationChannel.EMAIL, SendGridEmailProvider(api_key=...))`
-- leaves every other channel on simulation, with zero change to
`NotificationService` or to any other channel's provider. This is
exactly what Task 11's "Providers are interchangeable" verifies (see
`tests/test_notification.py::test_registry_channels_are_independently_swappable`).

### 5.3 Both providers are structural `Protocol`s, not base classes

`AutomationEventStore` and `NotificationProvider` are both
`@runtime_checkable Protocol`s (matching
`identity.provider.AuthenticationProvider` and
`authorization.provider.AuthorizationProvider`). A class satisfies
either interface purely by having compatible method signatures -- no
inheritance required. Both test suites include a from-scratch provider
class with no shared base class (`_ReadOnlyEventStore`,
`_WebhookStubProvider`) proving this swappability concretely, not just
by type-checking.

---

## 6. Registry Pattern

| Registry | Shape | Mirrors |
|---|---|---|
| `AutomationEventStoreRegistry` | Single active backend (`register` / `get` / `set_active` / `get_active`) | `monitoring.registry.MonitoringProviderRegistry` |
| `NotificationProviderRegistry` | Per-channel routing table, no "active" concept | New pattern, purpose-built for multi-channel delivery (Section 5.2) |
| `TemplateRegistry` | Key -> value catalogue (`register` / `get` / `exists` / `render` / `all_keys`) | `authorization.permissions.PermissionRegistry` / `authorization.roles.RoleRegistry` |

Every registry follows the same rules already established across this
codebase: registration is a plain dict-backed operation, a
"first-registered-wins" or explicit `set_active`/`make_active` decides
what's active (where "active" is a meaningful concept at all), and
`clear()` exists purely for test isolation, never called by application
code. This uniformity is what makes onboarding a new provider or
template "the same kind of operation" no matter which registry it's
for -- exactly the consistency Task 11 verifies with "New event types
can be added without changing existing services."

---

## 7. Testing Summary (Task 11)

`tests/test_automation.py` (71 tests) and `tests/test_notification.py`
(52 tests) were added this sprint, for **123 new tests**, covering:

- **Models**: every enum's string values, dataclass defaults, frozen/immutable.
- **Event construction**: `build_event`'s enum-normalization and
  novel-string-preservation, unique ids, defensive payload copying.
- **Automation Event Store**: record/list/filter (by tenant, type,
  status, source service)/limit/clear, Protocol conformance, a
  from-scratch custom store working unmodified against
  `AutomationService`.
- **Automation Event Store Registry**: register/get/set_active/
  get_active, first-registered-becomes-active, `make_active=True`,
  `ProviderNotRegisteredError`, `NoActiveProviderError`, sorted listing,
  clear.
- **Scheduler**: registration (including duplicate-id rejection),
  unregistration, unknown-job lookup, sorted listing, `due_jobs`
  (respecting `enabled` and `next_run_at`), `run_job` success and
  failure (never raising), `next_run_at` advancing after a run,
  `set_enabled`, `clear`, DI store injection.
- **Automation Service**: `publish()` with no handler (`PUBLISHED`),
  one succeeding handler (`HANDLED`), one failing handler (`FAILED`,
  never raised), a mix of failing/succeeding handlers (both still run),
  event-type-scoped vs. wildcard handler dispatch, novel/future event
  types, tenant/user attribution, `get_events()` filtering, and
  `trigger_scheduled_job()` (success and failure, unknown job raises).
- **Notification models, provider, registry, templates**: the
  equivalent coverage for `notification/`, plus the routing-table
  swappability test and the `SafeFormatDict` missing-key behavior.
- **Notification Service**: `handle_event()` routing (matched,
  unmatched, dynamic recipient resolver, an `EventType` member used
  directly as a route key), `notify()`'s template selection (including
  fallback), provider selection failure, provider-raises failure (never
  raised to the caller), history recording (success and failure),
  filtering/limiting `get_history()`.
- **Monitoring integration** (Task 9): every one of "event published",
  "event handled" (success and failure), "notification sent",
  "notification failed", and "scheduled job executed" is asserted
  directly against `monitoring_service.get_events(service_name=...)`,
  plus two dedicated "a broken monitoring provider never blocks the
  underlying operation" tests (mirroring the identical guarantee
  `AuthenticationService`'s test suite already proves).
- **Regression / isolation**: fresh service instances never share
  handlers or history; the zero-argument constructor path every real
  call site uses still works; `notification/` never imports
  `automation.service` (structural `ast`-based proof, mirroring
  `test_identity.py`'s identity/authorization independence proof).

**Existing functionality unchanged**: all pre-existing tests continue
to pass unmodified, with one intentional, documented update --
`tests/test_authorization.py`'s hardcoded `len(DEFAULT_PERMISSIONS) == 11`
assertion was updated to `12`, since this sprint added a twelfth
permission (`VIEW_AUTOMATION`) for the new Automation Dashboard, the
same way `VIEW_MONITORING` was added in a prior sprint.

**Full regression result**: **538 / 538 tests passing** -- the
pre-existing 415 tests plus this sprint's 123 new tests, with 0
failures. A separate headless dry run (using the project's existing
Streamlit-stub harness) additionally confirmed: `config/automation_setup.py`
registers its handlers and demo jobs correctly at import time; a
scheduled job can be triggered end-to-end through the real composition
root; publishing a `REPORT_GENERATED` event through the *shared*
`automation_service` singleton automatically triggers the wired
notification handler, producing a `SENT` email notification in
`notification_service`'s history; and both `ui/automation_dashboard.py`
and `pages/8_Automation.py` import and render without error against an
authenticated demo session.

---

## 8. Future Workflow Automation

This platform's design leaves clear, additive extension points for
genuine workflow automation (multi-step, conditional, or long-running
processes) without requiring a redesign:

- **Chained handlers**: since `AutomationService.publish()` already
  supports multiple handlers per event type, a workflow step is simply
  another `register_handler()` call. A handler that itself calls
  `automation_service.publish()` for a follow-up event type (e.g. a
  future `REPORT_GENERATED` handler that, once a condition is met,
  publishes `WORKFLOW_STEP_2_READY`) creates a chain with zero changes
  to `AutomationService` itself.
- **Conditional dispatch**: `NotificationService`'s routing table
  already demonstrates the pattern -- a future `WorkflowEngine` could
  read the same kind of `event_type -> action` table, but with actions
  richer than "send a notification" (e.g. "wait for approval," "call
  an external API," "branch based on payload").
- **Novel event types need no registry change**: as proven by
  `test_publish_accepts_a_novel_future_event_type_without_any_service_change`,
  a brand-new event type is one `automation_service.publish("new_type", ...)`
  call away, from any future service, with no change to `EventType`,
  `AutomationService`, or any existing handler.
- **The `payload` field is intentionally opaque**: `AutomationEvent.payload`
  is never inspected by `AutomationService`, only by whichever
  handler/template chooses to read specific keys -- so a future
  workflow's richer payload shape (e.g. `{"approval_required": True,
  "approver_role": "tenant_administrator"}`) requires no model change.

## 9. Future Background Processing

Per Task 5, this sprint deliberately does not run anything in the
background -- but every piece a real background execution layer would
need already exists:

- **`Scheduler.due_jobs(as_of=None)`** is the exact query a poll loop
  (a `while True: time.sleep(60); for job in scheduler.due_jobs(): ...`
  loop, a Celery Beat schedule, an APScheduler `BackgroundScheduler`,
  or a cloud function on a timer trigger) would call on every tick.
  Nothing currently calls it automatically; wiring it up is additive,
  not a redesign.
- **`Scheduler.run_job(job_id)`** already has the exact semantics a
  background worker needs: it never raises (a callback's exception is
  captured into `JobExecutionResult.error`), and it returns timing
  information (`duration_ms`) suitable for logging/alerting.
- **The event store and notification history are already
  process-shared, in-memory data structures** -- a background worker
  running in the same process (a Streamlit background thread, for
  instance) would read/write the exact same `automation_service` and
  `notification_service` singletons a request-handling code path uses,
  with no additional plumbing.
- **A future persistent event store or job store** (Section 5.1, 6)
  would be required before running real background execution across
  multiple processes/machines, since `InMemoryAutomationEventStore` and
  `Scheduler`'s default `dict` store are both process-local by design
  -- but swapping either one in is, again, one registration call, not
  a rewrite of `AutomationService` or `Scheduler`.

---

## 10. Assumptions Made

1. **"Actual background execution is not required"** was taken
   literally: `Scheduler` computes correct due-dates and supports
   manual execution, but nothing polls it automatically. The Automation
   Dashboard's "Run Now" button is the only execution trigger in this
   release, matching Task 5 and Task 10 exactly.
2. **Demo routing table and demo scheduled jobs are illustrative, not
   configurable per tenant in this release.** A real deployment would
   read routes and job definitions from tenant-specific settings; the
   `register_route()` / `register_job()` APIs already support this,
   but no settings UI was built this sprint (out of scope per the
   ticket).
3. **`InMemoryNotificationProvider` "sends" every channel identically**
   (it never actually contacts Slack, email, Teams, etc.) -- Task 7
   explicitly asks for a provider that "simulates delivery," so this is
   as designed, not a shortcut.
4. **KPI thresholds are a small, hardcoded demo set**
   (`services/kpi_threshold_watcher.py`'s `DEFAULT_KPI_THRESHOLDS`),
   since no ticket task specifies a threshold-configuration UI. The
   watcher accepts an injectable `thresholds` mapping, so wiring this
   to a future per-tenant settings screen is additive.
5. **`USER_LOGOUT` was added as a ninth `EventType` member** beyond the
   ticket's explicit eight, since Task 8's suggested-events list
   explicitly names "User logout" as an event to integrate.
6. **The composition-root wiring import lives in `components/sidebar.py`**
   (not `components/auth.py`), because `sidebar.py` is imported by
   every page's top-level imports before any page's business logic can
   execute -- guaranteeing handler/job registration happens before
   first use. This mirrors exactly how `components/auth.py` already
   imports `config.credentials` for the identical reason.
7. **No new user-facing permission beyond `VIEW_AUTOMATION`** was
   introduced; the Automation Dashboard is treated as a platform
   administration screen (per Task 10: "This dashboard is for platform
   administration"), gated the same way the existing Monitoring
   dashboard is gated by `VIEW_MONITORING`.
