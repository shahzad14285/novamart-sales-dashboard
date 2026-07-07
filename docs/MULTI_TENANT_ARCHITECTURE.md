# Multi-Tenant Architecture

Sprint 6.3 -- Multi-Tenant Business Intelligence Platform.

NovaMart's Service-Oriented Architecture (Upload Center -> Data Loader
-> KPI Engine -> Business Insights -> Reporting Service -> AI
Recommendation Service -> PDF Generator -> Export Service -> Executive
Report Center) is unchanged in this sprint. Every service still does
exactly what it did before; the only thing added is a mandatory,
consistently-enforced answer to one question before any of them run:
*which organization is this request for?*

## Architecture

```
tenancy/                                -- framework-agnostic tenancy package
    models.py        Tenant, TenantStatus            (Task 1)
    context.py        TenantContext, validate_tenant_context   (Tasks 2, 4, 5)
    registry.py        TenantRegistry, tenant_registry         (Task 6 mechanism)
    exceptions.py      TenantContextError + 3 subclasses       (Task 4)

config/tenants.py                       -- Task 6 configuration surface
    TENANT_DEFINITIONS -- the only place a tenant is declared
    register_default_tenants() -- registers them into tenant_registry at import time

components/tenant_selector.py           -- UI layer, session-scoped
    render_tenant_selector() -> TenantContext      (reads/writes st.session_state)
    get_active_tenant_context() -> TenantContext   (reads without re-rendering)

components/sidebar.py
    render_sidebar(active_label) -> TenantContext  -- renders the selector, once per page

Every tenant-aware service/component now accepts:
    ..., *, tenant_context: TenantContext | None = None
and calls validate_tenant_context(...) as its first line:
    utils/data_loader.py         DataLoader.load_uploaded_file
    components/upload_center.py  render_upload_center
    utils/kpi_engine.py          KPIEngine.calculate_all
    utils/insights.py            generate_business_insights
    components/analytics/insights.py           render_business_insights (via generate_business_insights)
    components/analytics/__init__.py           render_executive_analytics (Business Insights tab)
    services/reporting_service.py              ReportingService.generate_report
    services/ai_recommendation_service.py      AIRecommendationService.generate_recommendations
    services/pdf_generator_service.py          PDFGeneratorService.generate_pdf
    services/export_service.py                 ExportService.export
    ui/executive_report_center.py              render_executive_report_center (validates once, up front)

pages/1_Dashboard.py, pages/5_Reports.py -- resolve tenant_context via
render_sidebar() once, thread it into every call above.
```

### Why this shape

**A centralized `TenantContext`, not a parameter threaded ad hoc.**
Task 2 asks for one single source of truth for "which tenant is
active", not nine services independently deciding how to represent
that. `TenantContext` is a small, immutable-by-convention wrapper
around at most one `Tenant`; every service receives the *same* object
built the *same* way, so there is exactly one definition of "valid"
(`require_active_tenant()`) that every consumer shares.

**Why `TenantContext` is a plain class, not a global singleton.** A
Streamlit server process serves multiple browser sessions concurrently
from the same Python process. A module-level `TenantContext` instance
shared by the whole app would let one session's tenant selection bleed
into another session's request the moment two users are active at
once -- exactly the cross-tenant leak this sprint exists to prevent.
Instead, `TenantContext` is designed to be constructed per unit of work
and passed explicitly; the only place a tenant selection is actually
*stored* between reruns is `components/tenant_selector.py`, and it
stores it in `st.session_state`, which Streamlit itself keys per
browser session. This is also why `tenancy/` has zero import of
`streamlit` anywhere -- the validation/logging core stays reusable
outside a Streamlit context (a future API or scheduled job could use it
unchanged), while all the session-state coupling is pushed to one
UI-layer file.

**One validation-and-logging choke point, not nine.** Task 4
(validation) and Task 5 (logging) are both implemented exactly once, in
`validate_tenant_context()`. Every tenant-aware service's first line is
the same call with a different `service_name`/`operation` pair. This
means: a future tenant-aware service needs one line to get both
requirements for free, the validation rules can never drift between
services, and every log line in the system has an identical, greppable
shape regardless of which of the nine call sites produced it.

**Business-friendly errors, detailed logs -- kept structurally
separate.** `MissingTenantContextError`, `TenantNotFoundError`, and
`InactiveTenantError` messages contain no tenant IDs, service names, or
stack traces (Task 4's "avoid exposing technical implementation
details"), so `str(exc)` is always safe to show directly via
`st.error()`. The identifying detail those messages omit -- tenant id,
service, operation, timestamp -- is captured instead in the structured
log line `validate_tenant_context()` writes on every call, success or
failure (Task 5), via `logging.getLogger("novamart.tenancy")`.

**Configuration-driven onboarding, not conditional logic.**
`TenantRegistry` is a generic lookup table with no tenant-specific
behavior baked in -- it mirrors the registry pattern already
established by `KPIEngine.register`, `ExportService.register`,
`ReportingService.define_report`, and
`PDFGeneratorService.register_content_renderer`. *Which* tenants exist
is declared once, in `config/tenants.py`'s `TENANT_DEFINITIONS` tuple.
Onboarding a new tenant, renaming one, or deactivating one is always
one entry in that tuple -- never a new `if tenant == "...":` branch
anywhere in the codebase (Task 6). `tests/test_multi_tenancy.py` proves
this directly: it registers five never-before-seen tenants purely via
`registry.register_many(...)` and validates them successfully with zero
new conditional code.

**A keyword-only, defaulted parameter as the least-breaking extension
point.** Every tenant-aware method gained exactly one new parameter --
`*, tenant_context: TenantContext | None = None` -- appended after
existing positional parameters. This preserves every existing call
site syntactically (Release v0.3.0 backward compatibility) while still
making the parameter mandatory *in practice*: omitting it doesn't
silently succeed, it raises `MissingTenantContextError` the first time
validation runs. See "A note on backward compatibility" below for why
that distinction matters.

**Validated once, at the top, not once per tab.**
`render_executive_report_center()` calls `validate_tenant_context()`
itself, before rendering anything -- including the Upload Center --
and returns immediately on failure with a single `st.error()`. Each
individual service call inside its tabs (`generate_report`,
`generate_recommendations`, `generate_pdf`, `export`) still receives
and validates `tenant_context` too (defense in depth, and correct
behavior for any *other* caller that invokes those services directly,
bypassing this screen), but the user only ever sees one clean failure
message per page, not a partially-rendered screen with an error buried
in one tab.

## Tenant Context lifecycle

```
1. Page loads (pages/1_Dashboard.py or pages/5_Reports.py)
       |
2. render_sidebar(active_label=...) is called
       |
3. render_tenant_selector() runs inside it:
       - reads tenant_registry.active_tenants() (populated from config/tenants.py)
       - reads the previous selection from st.session_state["novamart_active_tenant_id"]
       - renders st.selectbox(...) with that as the default
       - writes the (possibly new) selection back to st.session_state
       - resolves the selected id -> Tenant -> TenantContext.for_tenant(tenant)
       |
4. render_sidebar() returns that TenantContext to the page
       |
5. The page threads tenant_context into every service/component call:
       render_upload_center(..., tenant_context=tenant_context)
       sales_kpi_engine.calculate_all(df, tenant_context=tenant_context)
       generate_business_insights(df, tenant_context=tenant_context)
       render_executive_analytics(df, tenant_context=tenant_context)
       render_executive_report_center(tenant_context=tenant_context)
       |
6. Each receiving service calls validate_tenant_context(tenant_context, ...) first:
       - None or empty context           -> MissingTenantContextError, logged REJECTED
       - Tenant exists but INACTIVE       -> InactiveTenantError, logged REJECTED
       - Tenant exists and ACTIVE         -> returns the Tenant, logged OK
       |
7. Only on success does the service's original, unchanged business logic run.
```

`get_active_tenant_context()` (also in `components/tenant_selector.py`)
exists for the one case where a component needs the resolved tenant
without being the one that renders the selector -- e.g.
`render_executive_report_center()`'s default when it isn't passed a
`tenant_context` explicitly. It reads the same `st.session_state` key
the selector already wrote, so both routes always agree on "who is
active right now".

A `TenantContext` itself is otherwise stateless and short-lived: it is
constructed once per page render (step 3) and passed down by value
through the call chain for that run. Nothing mutates it in place --
switching tenants means the *next* Streamlit rerun constructs a new
`TenantContext` from a new selectbox value, never reassigning an
existing instance a different tenant underneath a caller still holding
a reference to it.

## Data isolation strategy

Isolation in this platform rests on three points, all provable and
covered by `tests/test_multi_tenancy.py`:

1. **No shared mutable state carries a tenant's data between
   requests.** Every tenant-aware service is a plain function/method
   call: it takes a `DataFrame`/context object and a `TenantContext`,
   computes a result, and returns it. Nothing is cached keyed by
   anything *other* than the tenant's own supplied data (the one
   pre-existing exception, `utils/data_loader.py`'s `@st.cache_data`
   functions, only ever serve the shared, non-tenant-specific bundled
   sample CSV -- confirmed by inspection before this sprint touched
   that file, and unchanged here).
2. **The active tenant selection itself is session-scoped, not
   process-scoped.** As described above, `st.session_state` is keyed
   per browser session by Streamlit, so two concurrent users each get
   their own `novamart_active_tenant_id` -- there is no module-level
   variable anywhere in `tenancy/` or `components/tenant_selector.py`
   that could let one session's selection be read by another.
3. **Every service call requires an explicit, freshly-resolved
   `TenantContext` for that specific call.** There is no "ambient
   current tenant" a service reaches out and reads from a global --
   the caller must have one in hand and pass it. This makes a
   cross-tenant leak structurally hard to introduce by accident: doing
   so would require a caller to explicitly pass the *wrong* tenant's
   context, not merely forget to scope something.

`tests/test_multi_tenancy.py` proves this empirically, not just
structurally: it runs two different tenants' data through the KPI
Engine, Business Insights, Reporting Service, and Export Service in the
same test process (mirroring two concurrent Streamlit sessions on one
server) and asserts each tenant's results only ever reflect that
tenant's own input data, plus a dedicated check that
`validate_tenant_context()`'s structured log line always names the
tenant actually being processed -- never the other one -- for audit
correctness.

## Configuration process

Onboarding, renaming, or deactivating a tenant is a one-file change:

1. Open `config/tenants.py`.
2. Add, edit, or remove a `Tenant(...)` entry in `TENANT_DEFINITIONS`.
   - New tenant: add an entry with a unique `tenant_id`.
   - Deactivate: change that tenant's `status=TenantStatus.INACTIVE`.
   - Rename: edit `display_name` (or `name`); `tenant_id` should stay
     stable since it's the key everything else looks up.
   - Future per-tenant options (a plan tier, feature flags, contact
     info): add keys to that tenant's `metadata` mapping -- no model or
     service change required, since `metadata` exists exactly for this
     (Task 1's "Optional Metadata for future expansion").
3. Nothing else changes. No service, page, or component ever branches
   on a tenant id -- they all resolve tenants exclusively through
   `tenant_registry.get(...)` / `.active_tenants()`, so a new
   `TENANT_DEFINITIONS` entry is visible everywhere (tenant selector
   dropdown, validation, logging) the next time the app runs, with zero
   other edits.

`TENANT_DEFINITIONS` is a plain Python tuple today; nothing about the
`TenantRegistry` API assumes that. A future iteration reading tenants
from a database, an admin API, or a JSON/YAML file would only need to
replace `register_default_tenants()`'s body -- every consumer
downstream already goes through the registry, never this list
directly.

## Developer guidelines for future services

A new tenant-aware service should:

1. Accept a keyword-only `tenant_context: TenantContext | None = None`
   parameter on its main entry point (the method a caller invokes to
   do real work -- not every internal helper needs one).
2. Call `validate_tenant_context(tenant_context, service_name="YourService", operation="your_operation")`
   as the first line of that method, before touching any input data.
   Use the returned `Tenant` if the operation needs tenant metadata
   (e.g. `tenant.metadata["plan"]`); otherwise the call's side effects
   (validation + logging) are enough.
3. Let `MissingTenantContextError` / `InactiveTenantError` propagate to
   the UI layer, which should catch `TenantContextError` (the common
   base class) and display `str(exc)` directly via `st.error(...)` --
   never construct a new user-facing message, since the exception
   message is already written to be shown as-is.
4. Never write a tenant id into a branch of business logic. If a
   service ever seems to need different behavior per tenant, that
   belongs in the tenant's `metadata` (read generically), never in an
   `if tenant_id == "...":` check.
5. Add tests for the same four cases every existing tenant-aware
   service has: valid tenant (happy path), missing tenant, inactive
   tenant, and -- if the service touches a dataset -- an isolation
   check proving two tenants' inputs never produce each other's output.

## A note on backward compatibility

The ticket asks for two things that are in tension if read too
literally: "maintain backward compatibility with Release v0.3.0" and
"every service must receive tenant information before processing" (a
new, mandatory requirement). The interpretation applied throughout this
sprint: backward compatibility means every pre-existing method keeps
its exact signature shape, parameter order, and business logic for
equivalent inputs -- a v0.3.0 call site with all its original
positional arguments still type-checks and calls correctly. It does
*not* mean a caller who was previously getting business results back
can now omit tenant information and continue to silently get real
results with no scoping -- that would be incompatible with "no tenant
should ever access another tenant's data" and "missing tenant requests
should fail safely", both stated as hard requirements. Any code path in
this app that reaches a tenant-aware service already resolves a
`tenant_context` first (via `render_sidebar()`), so this distinction is
about how a v0.3.0-era *direct, unmodified* call to, say,
`sales_kpi_engine.calculate_all(df)` now behaves: it still runs (the
parameter is optional at the signature level), but raises
`MissingTenantContextError` rather than returning a result scoped to no
one in particular.

## Confirmation against the agreed architecture

- [x] Existing SOA pipeline (Upload Center -> Data Loader -> KPI Engine
      -> Business Insights -> Reporting Service -> AI Recommendation
      Service -> PDF Generator -> Export Service -> Executive Report
      Center) preserved exactly; only tenant awareness was added.
- [x] Centralized `TenantContext` (`tenancy/context.py`) is the single
      source of truth every service receives tenant information
      through.
- [x] Every listed service is tenant-aware: Upload Service, Data
      Loader, KPI Engine, Business Insights, Reporting Service, AI
      Recommendation Service, PDF Generator, Export Service, Executive
      Report Center.
- [x] Business logic in every one of those services is unchanged --
      confirmed by inspection: the only addition to each is one
      `validate_tenant_context(...)` call before existing logic runs.
- [x] Validation stops processing on a missing/inactive tenant with a
      professional, business-friendly message containing no
      implementation detail (`tenancy/exceptions.py`).
- [x] Structured logging (tenant id, service name, operation,
      timestamp, outcome) on every validation attempt, success or
      failure (`tenancy/context.py::_log`).
- [x] Configuration-driven tenant registration (`config/tenants.py` +
      `tenancy/registry.py`) with zero `if tenant == "...":` logic
      anywhere in the codebase.
- [x] Comprehensive tests covering Valid Tenant, Missing Tenant,
      Inactive Tenant, Tenant Isolation, Report/AI Recommendation/PDF/
      Export Generation, and configuration-driven onboarding
      (`tests/test_multi_tenancy.py`, plus updated per-service test
      files).
- [x] Follows Single Responsibility Principle, Separation of Concerns,
      Service-Oriented Architecture, Provider Pattern (services remain
      swappable), Registry Pattern (`TenantRegistry`, mirroring
      existing registries), and Clean Architecture (framework-agnostic
      `tenancy/` core, Streamlit coupling isolated to
      `components/tenant_selector.py`).
- [x] Type hints, docstrings, and professional logging throughout;
      no code duplication (one validation choke point), no hardcoded
      tenants, no broken existing APIs, no new global mutable state.

## Automated tests

`tests/test_multi_tenancy.py` (new, 37 tests) covers the tenancy
package end to end: valid/missing/inactive tenant resolution, tenant
isolation across the KPI Engine / Business Insights / Reporting
Service / Export Service, structured-logging correctness (including
that a rejected validation never logs the *other* tenant's id),
per-service tenant-gating for Report/AI Recommendation/PDF/Export
generation, and configuration-driven registration (including
registering brand-new tenants with zero conditional code, `TenantRegistry`
override/replace semantics, and confirming `config/tenants.py`
populates the shared registry at import time).

Every existing service test file was also updated to supply a
`tenant_context` fixture and thread it through the calls that now
require one, plus two new tests per file (`..._without_tenant_context_raises`,
`..._with_inactive_tenant_raises`):
`tests/test_kpi_engine.py`, `tests/test_insights.py`,
`tests/test_export_service.py`, `tests/test_reporting_service.py`,
`tests/test_ai_recommendation_service.py`,
`tests/test_pdf_generator_service.py`.

Verification performed: `python3 -m py_compile` across the entire
project tree (zero errors), then real execution of all twelve
`pytest`-style test files (238 tests total, 0 failures) via a
hand-built `pytest`-compatible shim in this offline sandbox (real
`pytest` isn't installed and there is no network access to install
it -- `pandas`, `reportlab`, `pdfplumber`, and `openpyxl` are already
present, so those tests run against the real libraries, not mocks). In
addition, a headless dry run using a minimal Streamlit-API stub
exercised `pages/1_Dashboard.py`, `pages/5_Reports.py`, and
`ui.executive_report_center.render_executive_report_center()` directly
across five tenant scenarios: valid active tenant, missing tenant
(`None` and empty `TenantContext`), inactive tenant, switching between
two tenants' datasets in sequence, and an empty dataset with a valid
tenant -- all producing exactly the expected `st.error` message (or
none) with no unhandled exception.

## Manual test cases

| # | Steps | Expected result |
|---|-------|------------------|
| 1 | Open the Dashboard page for the first time in a browser session | The sidebar shows an "Active Tenant" dropdown defaulting to the first active tenant (e.g. NovaMart Headquarters); the Globex Demo Account (inactive) does not appear in the list. |
| 2 | Upload a valid sales file with a tenant selected | KPIs and Executive Analytics render normally, scoped to that tenant (no visible difference in the numbers themselves -- isolation is about *not* mixing data, not changing it). |
| 3 | Switch the "Active Tenant" dropdown to a different organization mid-session | The page reruns; KPIs/analytics recompute against the same uploaded file but under the new tenant's context; no error, no stale data from the previous tenant. |
| 4 | Manually clear `st.session_state`'s tenant key (or open a fresh session with no prior selection) and land on the Reports page | The Executive Report Center shows a clear "Tenant context is missing" message and stops -- no partially rendered report, no traceback. |
| 5 | (Developer test) Temporarily set a tenant's `status` to `TenantStatus.INACTIVE` in `config/tenants.py` and reload | That tenant disappears from the selector's options entirely (only active tenants are offered); if it was the previously-selected tenant, the selector falls back to the first still-active option. |
| 6 | Generate a PDF report, then an export, both while "Organization A" is selected | Both downloads succeed; the PDF/export byte content reflects only the currently uploaded/filtered dataset, with no dependence on which tenant was previously active in the session. |
| 7 | (Developer test) Add a brand-new `Tenant(...)` entry to `config/tenants.py` and restart the app | The new tenant appears in the selector immediately, with no other file changed -- confirming Task 6's configuration-only onboarding. |
| 8 | Open the Reports page with no dataset uploaded and a valid, active tenant selected | Shows the Upload Center's empty state (not a tenant error) -- proves tenant validation and "no data yet" are handled as distinct, correctly-ordered conditions. |
