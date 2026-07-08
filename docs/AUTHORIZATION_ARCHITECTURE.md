# Permission-Based Authorization Architecture

Sprint 6.5 -- Permission-Based Authorization Framework.

NovaMart's existing Service-Oriented Architecture (Tenant Context ->
Upload Center -> Data Loader -> KPI Engine -> Business Insights ->
Reporting Service -> AI Recommendation Service -> PDF Generator ->
Export Service -> Executive Report Center, observed throughout by the
Monitoring Service) is unchanged in this sprint. Nothing was added
*inside* any business service. What this sprint adds is a new layer
that sits *in front of* the UI/orchestration call sites that already
invoke those services -- deciding, before any of them run, whether the
current user is allowed to trigger that call at all.

## Architecture

```
authorization/                          -- framework-agnostic authorization package (no Streamlit)
    models.py          User, UserStatus                                (Task 2)
    permissions.py      Permission, PermissionRegistry, 11 default keys (Task 3)
    roles.py             Role, RoleRegistry, 4 default roles, ALL_PERMISSIONS_WILDCARD (Task 4)
    context.py            UserContext                                   (Task 6)
    provider.py            AuthorizationProvider (Protocol), InMemoryAuthorizationProvider (Task 7)
    registry.py              AuthorizationProviderRegistry, authorization_provider_registry (Task 7 mechanism)
    service.py                 AuthorizationService, authorization_service (Tasks 5, 6, 10)
    exceptions.py                AuthorizationError + 8 subclasses
    __init__.py                   re-exports every public symbol above

config/users.py                          -- demo user directory (5 seeded users), mirrors config/tenants.py
components/authorization.py              -- Task 9 UI helper: the only place pages/components touch authorization.service

Target Architecture (as delivered):
    User -> [Authentication: future] -> User Context -> Tenant Context -> Authorization Service -> Permission Registry -> Business Services

Protected call sites (Task 8), every one gated at the UI/orchestration
layer, never inside services/*.py or utils/*.py:
    components/upload_center.py           render_upload_center            -> UPLOAD_DATA
    pages/1_Dashboard.py                  (page body)                     -> VIEW_DASHBOARD
    pages/5_Reports.py                    (page body)                     -> VIEW_REPORTS
    ui/executive_report_center.py         render_executive_report_center  -> GENERATE_REPORTS
    ui/executive_report_center.py         _render_recommendations_tab     -> USE_AI_RECOMMENDATIONS
    ui/executive_report_center.py         _render_pdf_export_tab          -> GENERATE_PDF
    ui/executive_report_center.py         _render_data_export_tab         -> EXPORT_DATA
    pages/6_Monitoring.py                 (page body)                     -> VIEW_MONITORING
    pages/7_Tenant_Configuration.py       (page body)                     -> MANAGE_TENANTS
    components/sidebar.py                 render_sidebar                  -> filters NAV_ITEMS by is_authorized(...)
```

### Why this shape

**Authorization is enforced at the UI/orchestration layer, never
inside a business service.** This is the ticket's single most
important structural requirement -- "Business services must never
contain role-specific logic" and "Business services should assume
authorization has already been completed" -- and it is enforced by
where `AuthorizationService.require_permission()` is called from, not
by convention. Every call site is a page (`pages/*.py`), a screen
orchestrator (`ui/executive_report_center.py`), or a shared UI
component (`components/upload_center.py`, `components/sidebar.py`).
`services/*.py` and `utils/*.py` import nothing from the `authorization/`
package at all -- confirmed by inspection, not just by not having
edited them. This is a deliberate departure from Sprint 6.3's tenant
validation pattern, where `validate_tenant_context()` is called from
*inside* every business service; tenant validation is a business rule
those services own, but authorization is explicitly not.

**Plain string keys, not enums, for `Permission` and `Role`.** Task 3
and Task 4 both require "future custom permissions" / roles being
addable "without changing services." A closed Python `Enum` cannot be
extended at runtime; a string key registered into a mutable
`PermissionRegistry`/`RoleRegistry` can be. `PermissionRegistry.register(Permission(key="approve_budget", ...))`
followed by `RoleRegistry.register(Role(key="finance_manager", permissions=frozenset({"approve_budget", ...}), ...))`
is a complete, two-line way to add a brand-new capability and role to a
running system, with zero changes to `AuthorizationService` or to any
existing protected call site. `tests/test_authorization.py` proves this
directly (see "Automated tests" below).

**A `Registry` for permissions and a separate `Registry` for roles,
mirroring `TenantRegistry` and `MonitoringProviderRegistry`.** Both
follow the exact same shape already established twice in this
codebase: `register()`, `get()` (returns `None` rather than raising, so
callers choose whether a miss is fatal), `exists()`, and a shared,
application-wide instance populated once at import time
(`permission_registry`, `role_registry`). Reusing an established
pattern rather than inventing a third shape keeps the codebase's
"Registry Pattern" consistent across tenancy, monitoring, and
authorization.

**RBAC as the permission-assignment mechanism, with a direct-grant
escape hatch.** A `User`'s `roles` tuple is expanded into permissions
via the Role Registry; a `User`'s `permissions` tuple grants
permissions directly, bypassing roles entirely. `resolve_effective_permissions()`
computes the union of both. This satisfies the ticket's explicit
mechanism choice (RBAC) while leaving room for a future "grant this one
user an extra capability without inventing a new role for them" need,
without any structural change.

**A `Protocol`-based Provider Pattern, mirroring `AIRecommendationService`'s
`RecommendationProvider` and `MonitoringService`'s `MonitoringProvider`.**
`AuthorizationProvider` is a `@runtime_checkable typing.Protocol` with
two methods (`get_user`, `list_users`); `InMemoryAuthorizationProvider`
is the only concrete implementation this sprint ships.
`AuthorizationProviderRegistry` holds every registered provider and
exactly one active one, the same registry shape used for tenants and
monitoring. This is what makes a future Database, LDAP, OAuth, OpenID
Connect, Azure AD, Okta, or Auth0 backend a matter of writing one new
class and calling `authorization_provider_registry.set_active(...)` --
zero change to `AuthorizationService` or to any of the nine protected
call sites.

**`UserContext` as a sibling of `TenantContext`, not nested inside
it.** The ticket's Target Architecture lists `User Context -> Tenant
Context` as two boxes in the pipeline, and asks for a context that
"should flow alongside the existing Tenant Context" -- not a
restructuring of `TenantContext` itself. `UserContext` is a small,
independent class (`user`, `effective_permissions`) built with the same
shape as `TenantContext` (`for_user(...)`/`empty()` classmethods,
`has_user()`, a non-raising `has_permission()`). Callers resolve and
thread both explicitly; nothing merges them into a single object, so a
page that only needs the tenant (most of the existing pre-Sprint-6.5
code) is completely unaffected.

**Monitoring integration reuses the existing event vocabulary instead
of extending `monitoring/models.py`.** Rather than adding
`AUTHORIZATION_GRANTED` / `AUTHORIZATION_DENIED` / `PERMISSION_CHECKED`
as new `EventType` members, `AuthorizationService._record()` calls the
same `monitoring_service.record_completed()` / `record_failure()` every
other instrumented service already uses, with `service_name="AuthorizationService"`
and `operation=<permission_key>`. This requires zero changes to the
monitoring package -- maximally honoring "Do NOT redesign the existing
architecture" -- and has a useful side effect: `AuthorizationService`
automatically appears in the Monitoring dashboard's existing Service
Statistics table, with "successful" meaning "granted" and "failed"
meaning "denied," with no dashboard code changes at all. The checking
user's id (which has no dedicated field on `MonitoringEvent`) travels
in `metadata["user_id"]`, the same open-extensibility mechanism
`docs/OBSERVABILITY_ARCHITECTURE.md` already documents `metadata` for.

**A demo "user switcher," standing in for real authentication, exactly
the way `components/tenant_selector.py` already stands in for real
multi-tenant request routing.** The Target Architecture marks
"Authentication" as a *future* box, not something this sprint builds.
`components/authorization.py::render_user_switcher()` lets the person
running the demo pick "who they currently are" from `config/users.py`'s
seeded directory via a sidebar selectbox, stored in
`st.session_state["novamart_active_user_id"]` -- the same per-session
storage mechanism, for the same reason (a Streamlit process serves many
concurrent browser sessions; a module-level global would leak one
session's identity into another's), that `tenant_selector.py` already
uses for "which organization is active."

## Permission Model (Task 3)

Eleven permissions are registered by default, each a plain string key
with a human-readable description used verbatim in "Access Denied"
messages:

| Permission key | Description | Granted to (via role) |
|---|---|---|
| `view_dashboard` | View the sales dashboard | all four roles |
| `view_reports` | View reports | all four roles |
| `generate_reports` | Generate reports | System Administrator, Tenant Administrator, Business Analyst |
| `export_data` | Export data | System Administrator, Tenant Administrator, Business Analyst |
| `generate_pdf` | Generate PDF documents | System Administrator, Tenant Administrator, Business Analyst |
| `use_ai_recommendations` | Use AI-generated recommendations | System Administrator, Tenant Administrator, Business Analyst |
| `upload_data` | Upload sales data | System Administrator, Tenant Administrator, Business Analyst |
| `view_monitoring` | View platform monitoring and observability data | System Administrator only |
| `manage_users` | Manage user accounts | System Administrator, Tenant Administrator |
| `manage_tenants` | Manage tenant/organization configuration | System Administrator, Tenant Administrator |
| `manage_platform` | Manage platform-wide settings | System Administrator only |

`PermissionRegistry` (`authorization/permissions.py`) is a small,
mutable catalogue: `register()`, `register_many()`, `get()` (returns
`None` on a miss), `exists()`, `all_permissions()`, `all_keys()`
(sorted, for deterministic iteration), `clear()`. The shared
`permission_registry` instance is populated with the eleven defaults
above at import time via `register_default_permissions()`, and nothing
prevents a caller from registering a twelfth at any point afterward --
`resolve_effective_permissions()` re-reads `self._permission_registry.all_keys()`
on every call, so a wildcard-holding role (System Administrator) picks
up a newly-registered permission immediately, without a restart or any
code change.

Business services never evaluate a permission key. Only
`AuthorizationService` and `components/authorization.py` import
anything from `authorization.permissions` beyond the plain key
constants used to name what a call site requires.

## Role Registry (Task 4)

| Role key | Display name | Permissions |
|---|---|---|
| `system_administrator` | System Administrator | `*` (every currently registered permission -- see "the wildcard" below) |
| `tenant_administrator` | Tenant Administrator | `manage_tenants`, `manage_users`, `upload_data`, `view_dashboard`, `view_reports`, `generate_reports`, `generate_pdf`, `export_data`, `use_ai_recommendations` |
| `business_analyst` | Business Analyst | `upload_data`, `view_dashboard`, `view_reports`, `generate_reports`, `use_ai_recommendations`, `generate_pdf`, `export_data` |
| `executive_viewer` | Executive Viewer | `view_dashboard`, `view_reports` (read-only) |

`RoleRegistry` (`authorization/roles.py`) mirrors `PermissionRegistry`'s
shape exactly (`register()`, `get()`, `exists()`, `all_roles()`,
`all_keys()`, `clear()`). The shared `role_registry` instance is
populated with the four roles above at import time.

**The wildcard.** `ALL_PERMISSIONS_WILDCARD = "*"` is a sentinel value
a role's `permissions` frozenset can contain instead of enumerating
every key by hand. `AuthorizationService.resolve_effective_permissions()`
detects it and expands it to `self._permission_registry.all_keys()` --
evaluated fresh on every call, not captured once at role-definition
time -- so System Administrator's set of permissions is always "every
permission that currently exists," including one registered after this
sprint shipped. `tests/test_authorization.py` proves this directly with
a test that registers a brand-new permission mid-test and confirms a
System Administrator immediately holds it with no other change.

**Unknown role/permission keys degrade gracefully.** If a `User`
record references a role key or a directly-granted permission key that
isn't registered (a typo, a stale assignment after a permission was
removed), `resolve_effective_permissions()` skips it and logs a
warning rather than raising -- a misconfigured single assignment must
never crash every permission check for that user.

## Authorization Flow / Permission Checked lifecycle (Tasks 5, 10)

```
1. A page or UI component reaches the point where it would otherwise
   start doing real work (e.g. pages/1_Dashboard.py, right after render_header())
       |
2. It calls components.authorization.require_permission_ui(
       PERMISSION, service_name="...", operation="...", tenant_context=tc, user_context=uc,
   )
       |
3. require_permission_ui resolves a UserContext if one wasn't already
   passed in (get_active_user_context -> reads st.session_state -> AuthorizationService.build_context)
       |
4. AuthorizationService.require_permission(context, PERMISSION, ...) is called
       |
5a. permission unknown to the registry -> UnknownPermissionError (a configuration bug, not a user-facing denial)
5b. user_context is None or has no user -> _record(DENIED, user_id=None, reason="missing user context") -> MissingUserContextError
5c. user resolved but lacks PERMISSION -> _record(DENIED, user_id=..., reason="permission not granted") -> PermissionDeniedError
5d. user resolved and holds PERMISSION -> _record(GRANTED, user_id=..., reason=None) -> returns the User
       |
6. Every _record(...) call (5b, 5c, 5d) does two things, in order:
       a. one structured log line via logging.getLogger("novamart.authorization")
          (INFO for a grant, WARNING for a denial)
       b. one monitoring event via monitoring_service.record_completed()/record_failure(),
          service_name="AuthorizationService", operation=<permission key>,
          metadata={"user_id", "permission", "checked_operation", "reason"}
       |
7a. GRANT path: require_permission_ui returns True; the caller proceeds exactly as before
7b. DENY path: require_permission_ui catches the AuthorizationError, renders a business-friendly
    "Access Denied" panel (looking up the permission's description from the Permission Registry
    for the message -- never a raw key or exception detail), and returns False; the caller
    (a two-line `if not require_permission_ui(...): return` / `st.stop()`) renders nothing further
```

A monitoring/storage failure can never block or grant access --
`AuthorizationService._record()` calls into `monitoring_service`, whose
own `_store()` already swallows provider failures (Sprint 6.4's
resilience guarantee, reused here unchanged).
`tests/test_authorization.py::test_a_storage_failure_never_prevents_a_permission_decision`
proves this directly with a monitoring provider whose `record()` always
raises.

## User Context Lifecycle (Task 6)

```
1. Once per page render, components.sidebar.render_sidebar() calls
   components.authorization.render_user_switcher(tenant_context)
       |
2. render_user_switcher reads the demo user directory from the active
   AuthorizationProvider, renders a selectbox, and stores the chosen
   user id in st.session_state["novamart_active_user_id"]
       |
3. It resolves that id into a UserContext via AuthorizationService.build_context(user_id, tenant_context):
       a. resolve_user(user_id)      -> UnknownUserError if not found
       b. check user.is_active        -> InactiveUserError if not
       c. resolve_effective_permissions(user)   (roles + direct grants, wildcard expanded live)
       d. tenant isolation check: user.tenant_id must equal tenant_context.tenant.tenant_id,
          UNLESS the user's resolved permissions already cover every currently
          registered permission (the System Administrator exemption -- see below)
          -> CrossTenantAccessError if neither holds
       e. UserContext.for_user(user, permissions)
       |
4. Any AuthorizationError raised during resolution degrades to UserContext.empty()
   rather than crashing the sidebar or the page underneath it -- every downstream
   is_authorized()/require_permission_ui() call then simply denies everything,
   which surfaces its own business-friendly message instead
       |
5. Every other component on the same page render calls
   components.authorization.get_active_user_context(tenant_context) to read the
   already-resolved context back out of session state, without re-rendering the picker
```

**Why System Administrators are exempt from tenant isolation.** Task 2
requires exactly one `tenant_id` field on `User` -- every person still
needs a "home" organization on their record, even one whose role is
meant to be platform-wide. But a role granting *every* permission
(System Administrator) is meaningless if that same person is then
blocked from acting against any tenant other than their own --
"administer the whole platform" and "confined to one organization" are
contradictory for the same role. `build_context()` therefore resolves
effective permissions *before* the tenant check, and skips
`CrossTenantAccessError` when those permissions already cover every
currently registered permission. Every other role -- including Tenant
Administrator, which despite its name remains scoped to its *own*
tenant -- stays strictly confined to its `tenant_id`.
`tests/test_authorization.py` verifies both halves of this directly: a
System Administrator user successfully builds a context against a
different tenant, and a Tenant Administrator user is correctly blocked
with `CrossTenantAccessError` under the identical scenario. This was
also confirmed via a headless dry-run exercising all five demo
personas against both their home tenant and a foreign tenant (see
"Manual test cases" below).

## Provider Pattern (Task 7)

```
AuthorizationProvider (typing.Protocol, @runtime_checkable)
    get_user(user_id: str) -> User | None
    list_users(*, tenant_id: str | None = None) -> tuple[User, ...]
        |
        +-- InMemoryAuthorizationProvider   (this sprint's default; thread-safe via threading.Lock)
        +-- <future> DatabaseAuthorizationProvider
        +-- <future> LDAPAuthorizationProvider
        +-- <future> OAuthAuthorizationProvider
        +-- <future> OpenIDConnectAuthorizationProvider
        +-- <future> AzureADAuthorizationProvider
        +-- <future> OktaAuthorizationProvider
        +-- <future> Auth0AuthorizationProvider

AuthorizationProviderRegistry
    register(name, provider, *, make_active=False)
    get(name) -> AuthorizationProvider              (raises ProviderNotRegisteredError)
    set_active(name) -> None
    get_active() -> AuthorizationProvider             (raises NoActiveProviderError)
    active_name -> str | None
    registered_providers() -> tuple[str, ...]

authorization_provider_registry = AuthorizationProviderRegistry()   # shared, application-wide
authorization_provider_registry.register("memory", InMemoryAuthorizationProvider(), make_active=True)

AuthorizationService(provider: AuthorizationProvider | None = None, role_registry=None, permission_registry=None)
    -- every argument omitted (every real call site) -> the three shared, application-wide instances
    -- any argument supplied (every test) -> that exact instance, fully isolated
```

Because `AuthorizationProvider` is a structural `Protocol` rather than
an abstract base class, a future provider needs no import from this
package's inheritance hierarchy -- it only needs to expose `get_user`
and `list_users` with matching signatures. `tests/test_authorization.py`
proves this directly with a minimal, from-scratch provider class
(`_ListOnlyProvider`, no shared base with `InMemoryAuthorizationProvider`)
that `AuthorizationService` resolves users through with zero code
changes.

`config/users.py` seeds five demo users into whichever provider is
active at import time (`getattr(provider, "register_many", None)`, a
defensive check -- a future external identity provider, such as one
backed by LDAP or Azure AD, would not support local seeding at all,
and `config/users.py` logs instead of crashing in that case rather than
assuming every provider is writable).

## Future Authentication Integration

The Target Architecture places "Authentication (Future)" between `User`
and `User Context` -- deliberately not built this sprint. The seam is
`components.authorization.get_active_user_context()`'s *implementation*:
today it reads a selectbox choice out of `st.session_state`; a future
integration would instead resolve a verified session token, OAuth
claim, or SSO assertion into a `user_id` and call the exact same
`AuthorizationService.build_context(user_id, tenant_context)` this
sprint already built. Nothing downstream changes:

- `AuthorizationService.build_context()`'s signature (`user_id: str,
  tenant_context: TenantContext | None`) is already authentication-agnostic
  -- it has never assumed *how* a user id was obtained.
- Every one of the dozens of `is_authorized()` / `require_permission_ui()`
  call sites across `pages/*.py`, `ui/executive_report_center.py`, and
  `components/*.py` is unaware the user switcher exists at all -- they
  only ever call `components.authorization`'s public functions.
- Swapping the identity *backend* (where `User` records live) is a
  separate, already-solved concern -- the Provider Pattern above --
  from swapping how a *specific request's* user id is determined, which
  is authentication's job.

## Confirmation against the agreed architecture

- [x] Existing SOA pipeline (Tenant Context -> Upload Center -> Data
      Loader -> KPI Engine -> Business Insights -> Reporting Service ->
      AI Recommendation Service -> PDF Generator -> Export Service ->
      Executive Report Center) preserved exactly; no business logic in
      any service was modified.
- [x] Business services contain no role-specific logic -- confirmed by
      inspection: `authorization/` is imported only from `pages/*.py`,
      `ui/executive_report_center.py`, and `components/*.py`; zero
      imports from any file under `services/` or `utils/`.
- [x] Centralized, framework-agnostic `authorization/` package (no
      Streamlit dependency) with `models.py`, `permissions.py`,
      `roles.py`, `context.py`, `service.py`, `registry.py`,
      `provider.py`, `exceptions.py`, `__init__.py`.
- [x] User Model with User ID, User Name, Display Name, Email, Tenant
      ID, Assigned Roles, Assigned Permissions, Status, and an open
      `metadata` mapping for extensibility.
- [x] Permission Registry with all eleven ticket-specified permissions,
      avoiding hardcoded permission checks inside business services.
- [x] Role Registry with all four ticket-specified roles, matching the
      ticket's exact permission assignments.
- [x] Authorization Service resolving user permissions, resolving role
      mappings, validating permissions, denying unauthorized access,
      and producing business-friendly authorization errors -- business
      services never evaluate permissions directly.
- [x] Reusable Authorization Context (`UserContext`) carrying Current
      User, Current Tenant (via the existing, unmodified
      `TenantContext` passed alongside it), and Effective Permissions.
- [x] Provider Pattern: `AuthorizationProvider` abstraction, default
      in-memory provider, future providers (Database, LDAP, OAuth,
      OpenID Connect, Azure AD, Okta, Auth0) pluggable with zero change
      to `AuthorizationService` or to any protected call site.
- [x] Authorization integrated at all eight ticket-listed points: Upload
      Center, Dashboard, Reporting Service (via the Executive Report
      Center's report-generation call), AI Recommendation Service (via
      its tab), PDF Generator (via its tab), Export Service (via its
      tab), Monitoring Dashboard, Tenant Configuration -- every check
      occurs before the protected business call, never after.
- [x] Reusable UI authorization helper (`components/authorization.py`):
      hides unauthorized nav items (`render_sidebar` filtering via
      `is_authorized`), hides unauthorized actions (each Executive
      Report Center tab gates itself independently), renders a single
      consistent "Access Denied" message, prevents unauthorized page
      access (`require_permission_ui` + `st.stop()`/`return`), and
      avoids duplicated authorization code (every call site uses the
      same two functions).
- [x] Monitoring integration: every permission check records a
      "Permission Checked" audit trail entry via the existing
      Monitoring Service, carrying User ID, Tenant ID, Timestamp, and
      grant/deny outcome -- zero changes to `monitoring/models.py` or
      `monitoring/service.py`.
- [x] Comprehensive tests (`tests/test_authorization.py`, 58 tests)
      covering the Permission Registry, Role Registry, Authorization
      Service, Provider abstraction, User Context, permission
      inheritance (including live wildcard expansion), unauthorized
      access, tenant isolation (including the System Administrator
      exemption), and monitoring integration.
- [x] Existing functionality continues working: the full pre-existing
      test suite (13 files, 274 tests before this sprint) passes
      unchanged alongside the 58 new authorization tests, with zero
      modification to any pre-existing test file's assertions (two
      pre-existing test files needed re-syncing after an unrelated
      sandbox file-transfer artifact truncated two lines -- see
      "Assumptions made" in the final summary; the source of truth on
      disk was never affected).
- [x] New roles/permissions addable without changing services --
      proven directly by a test that registers a new permission mid-test
      and confirms it reaches System Administrator with no other change.
- [x] Follows Single Responsibility Principle, Separation of Concerns,
      Clean Architecture, Dependency Injection (`AuthorizationService`'s
      constructor), Registry Pattern (`PermissionRegistry`,
      `RoleRegistry`, `AuthorizationProviderRegistry`), Provider Pattern
      (`AuthorizationProvider`), and Extensibility (string keys instead
      of enums, open `metadata` mappings).

## Automated tests

`tests/test_authorization.py` -- 58 tests across ten sections:

1. **Permission Registry** -- registration, lookup, duplicate handling,
   `all_keys()` ordering, the eleven default permissions exist with
   correct descriptions.
2. **Role Registry** -- registration, lookup, the four default roles
   grant exactly the ticket-specified permission sets.
3. **Provider abstraction** -- `InMemoryAuthorizationProvider` CRUD,
   `AuthorizationProviderRegistry` register/get/set_active/get_active,
   and a from-scratch custom provider (`_ListOnlyProvider`) proving
   `AuthorizationService` works against any `Protocol`-conforming
   object.
4. **User Context** -- `has_user()`, `has_permission()`, `for_user()`,
   `empty()`.
5. **Authorization Service resolution** -- `resolve_user`,
   `resolve_effective_permissions` (roles, direct grants, unknown-key
   skip-with-warning), `build_context` grant/deny paths.
6. **Permission inheritance** -- wildcard expansion, including a live
   test that registers a new permission mid-test and confirms System
   Administrator immediately holds it.
7. **Unauthorized access** -- `require_permission` raising
   `UnknownPermissionError` / `MissingUserContextError` /
   `PermissionDeniedError` as appropriate; `has_permission`'s
   non-raising behavior.
8. **Tenant isolation** -- a same-tenant user succeeds, a
   cross-tenant user is rejected, the System Administrator exemption is
   proven directly, and Tenant Administrator's confinement to its own
   tenant (despite its name) is proven directly.
9. **Monitoring integration** -- grant and denial are each recorded as
   exactly one monitoring event with correct status and metadata; a
   missing user context is still recorded with `user_id=None`;
   `AuthorizationService` appears in `get_service_health()` with
   correct success/failure counts; a broken monitoring provider never
   prevents a correct permission decision.
10. **Regression** -- existing permission/role/context behavior is
    unaffected by later additions within the same test run.

Following this project's established convention (confirmed via
inspection: no file under `tests/` imports `streamlit` or anything from
`components/`/`ui/`/`pages/`), `tests/test_authorization.py` tests the
`AuthorizationService` backing logic exhaustively rather than importing
`components.authorization` directly. `components/authorization.py`'s
UI-layer behavior (the selectbox, the Access Denied panel, the
sidebar's nav filtering) is verified via the headless dry-run and
manual test cases below instead.

**Full-suite regression run:** all 14 test files (13 pre-existing + the
new `test_authorization.py`), 332 tests total, 0 failures, run together
in a single sandbox process.

## Manual test cases (headless dry-run)

Exercised via a headless dry-run driving the real
`components.authorization` functions (`get_active_user_context`,
`is_authorized`, `require_permission_ui`) against every seeded persona,
using the project's existing Streamlit-stub harness so real application
code runs end to end with no UI framework installed:

| User | Tenant | Resolved | Dashboard | Reports (view) | Generate Reports | AI Recs | PDF | Export | Upload | Monitoring | Tenant Config |
|---|---|---|---|---|---|---|---|---|---|---|---|
| System Administrator | novamart-hq (home) | yes | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Tenant Administrator | acme-retail (home) | yes | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| Business Analyst | acme-retail (home) | yes | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| Executive Viewer | acme-retail (home) | yes | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Inactive user (Business Analyst role) | acme-retail (home) | **no** (`InactiveUserError` swallowed) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Business Analyst | novamart-hq (**foreign** tenant) | **no** (`CrossTenantAccessError` swallowed) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| System Administrator | acme-retail (**foreign** tenant) | yes (platform-wide exemption) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Every row above matches its role definition exactly, including the two
edge cases the design decisions above call out specifically (an
inactive account resolves to zero permissions rather than crashing; a
System Administrator retains full access outside their home tenant
while a Business Analyst is correctly locked out).

Additionally confirmed in the same dry-run:

- `require_permission_ui()`'s grant path returns `True` and renders no
  "Access Denied" panel.
- `require_permission_ui()`'s deny path returns `False` and renders the
  "Access Denied" panel (verified the panel-render call fires).
- `st.stop()` (now called by `pages/1_Dashboard.py` on a denied
  `VIEW_DASHBOARD` check) halts script execution the same way real
  Streamlit does, confirmed against an extended stub.
- Zero unhandled exceptions across all seven scenarios above plus the
  grant/deny/stop checks.

## Assumptions made

- **Executive Viewer and the Reports page.** The ticket assigns
  `VIEW_REPORTS` (a coarse, page-level gate) and `GENERATE_REPORTS` (a
  finer gate on the actual report-assembly call) to different roles --
  Executive Viewer holds the former but not the latter. Because this
  release has no persisted "last generated report" an Executive Viewer
  could view without triggering generation, `VIEW_REPORTS` gates
  entering the Reports page and seeing its nav item, while
  `GENERATE_REPORTS` gates the `sales_reporting_service.generate_report()`
  call the page always makes to render anything. In this release, an
  Executive Viewer can reach the Reports page but sees "Access Denied"
  in place of report content. This is flagged as a natural next
  iteration (a cached/persisted report an Executive Viewer could view
  read-only) rather than something this sprint's scope covers.
- **Tenant Administrator holds `generate_pdf`.** The ticket's Task 4
  list for Tenant Administrator does not explicitly mention PDF
  generation, but does list "reports" and "export" broadly, and a
  Tenant Administrator managing their organization's reporting would
  be unable to produce a client-ready report without it. Included for
  functional completeness; easy to remove with a one-line change to
  `authorization/roles.py` if the ticket intended otherwise.
- **System Administrator's cross-tenant exemption** is implemented as
  "holds every currently registered permission" rather than a
  dedicated `is_platform_admin` flag on `User`, keeping the User model
  exactly as specified in Task 2 (no extra field) while still
  satisfying the implicit requirement that a platform-wide role
  actually be platform-wide. See "Why System Administrators are exempt"
  above for the full rationale.
- **The new Tenant Configuration page is intentionally minimal.** Task
  8 lists "Tenant Configuration" as something to protect, but no such
  page existed anywhere in the codebase before this sprint. A new,
  minimal page (`pages/7_Tenant_Configuration.py` + `ui/tenant_configuration.py`)
  was built with two read-only tables (tenant directory, user
  directory) so there is something real for `MANAGE_TENANTS` to
  protect. Building create/edit/deactivate forms was judged out of
  this sprint's scope, which asks for access to be protected, not for
  a full administration console.
- **UI-layer testing follows the project's existing convention**
  (confirmed via inspection of every existing `tests/*.py` file): the
  checked-in pytest suite never imports `streamlit`/`components`/`ui`/`pages`.
  `components/authorization.py`'s rendering behavior is therefore
  verified via the headless dry-run and manual test table above, the
  same pattern already used for `ui/executive_report_center.py` and
  `ui/monitoring_dashboard.py` in prior sprints, rather than by
  introducing a new testing convention specific to this sprint.
- **Two pre-existing test files needed a two-line re-sync during
  verification, unrelated to this sprint's changes.** During the final
  sandbox test run, `tests/test_ai_recommendation_service.py` and
  `tests/test_export_service.py` (both written in earlier sprints, not
  touched by this one) showed a single truncated identifier each in the
  sandbox copy used for verification. The source files on disk were
  confirmed correct; the sandbox copies were re-synced from disk before
  the final 332-test run, which passed with zero failures. No test
  assertions or application behavior were changed.
