# Identity & Authentication Architecture

Sprint 6.6 -- Identity & Authentication Framework.

NovaMart's existing architecture (Tenant Context, Authorization
Service, Permission Registry, Monitoring Service, Executive Reporting,
AI Recommendation Service) is unchanged in this sprint. Nothing was
added *inside* the Authorization Framework, and nothing was added
*inside* any business service. What this sprint adds is a new layer
that sits *in front of* Authorization: before a user's permissions are
ever resolved, the platform now first establishes -- and continuously
re-verifies -- that a real, signed-in, non-expired session exists at
all.

## Architecture

```
identity/                                -- framework-agnostic identity package (no Streamlit)
    models.py          UserIdentity, IdentityStatus,                  (Task 2)
                        LoginStatus, SessionInfo, AuthenticationResult
    provider.py         AuthenticationProvider (Protocol), InMemoryAuthenticationProvider  (Task 4)
    session.py            SessionManager                                (Task 5)
    registry.py            AuthenticationProviderRegistry, authentication_provider_registry  (Task 6 mechanism)
    service.py                AuthenticationService, authentication_service  (Tasks 3, 9)
    exceptions.py                AuthenticationError + 7 subclasses
    __init__.py                    re-exports every public symbol above

config/credentials.py                     -- the ONE file allowed to know about both
                                              identity/ and authorization/ (projects
                                              config.users.USER_DEFINITIONS into
                                              identity.models.UserIdentity + a shared
                                              demo password)
components/auth.py                        -- Task 7/8/10 UI layer: login form, the
                                              authentication gate, the signed-in user panel

Target Architecture (as delivered):
    User -> Authentication Service -> Identity Provider -> Session Manager -> User Context -> Authorization Service -> Tenant Context -> Business Services

Every page's actual call order (Task 8):
    components.auth.require_authentication()          <- MUST succeed first
        |
    components.sidebar.render_sidebar()
        |-- components.tenant_selector.render_tenant_selector()
        |-- components.auth.render_user_panel()         <- displays the already-authenticated identity
        |-- (nav filtering via components.authorization.is_authorized)
        |
    components.authorization.require_permission_ui(...)  <- authorization, strictly after authentication
        |
    the protected business service call
```

### Why this shape

**Authentication is enforced at the UI/orchestration layer, exactly
where Sprint 6.5 enforced authorization -- never inside a business
service.** `identity.service.AuthenticationService` is called from
`components/auth.py`, which every page (`app.py`, `pages/*.py`) calls
via `require_authentication()` as its very first action after page
configuration -- before `render_sidebar()`, before any authorization
check, before any business service. No file under `services/` or
`utils/` imports anything from `identity/`.

**`identity/` never imports `authorization/`, and `authorization/`
was not modified at all.** This is the ticket's single most important
structural requirement -- "Authentication must remain completely
separated from Authorization" -- and it is enforced structurally, not
by convention: `tests/test_identity.py::test_authentication_and_authorization_are_independent_packages`
parses every module in `identity/` with `ast` and asserts none of them
import anything starting with `authorization`. The only file in the
entire codebase that imports from both packages is
`config/credentials.py`, a composition-root config file (the same role
`config/users.py` already plays for `authorization`+`tenancy`) --
never `identity/` or `authorization/` themselves. `authorization/service.py`,
`authorization/models.py`, and every other file in that package are
byte-for-byte unchanged from Sprint 6.5.

**The bridge between the two packages is exactly one plain string: a
`user_id`.** `components/authorization.py::get_active_user_context()`
now resolves `user_id` by asking `identity.service.authentication_service.get_current_user(session_id)`
instead of reading its own demo selectbox -- then hands that
`user_id` to `authorization_service.build_context(user_id, tenant_context)`,
completely unchanged from Sprint 6.5. Neither package's internals see
the other's types; `identity.models.UserIdentity` and
`authorization.models.User` are two independent value objects that
happen to describe the same person, kept in sync for the demo
directory by `config/credentials.py` alone.

**Plain string provider names in a `Registry`, mirroring every prior
sprint.** `AuthenticationProviderRegistry` is structurally identical
to `AuthorizationProviderRegistry` and `MonitoringProviderRegistry`:
`register()`, `get()`, `set_active()`, `get_active()`, `active_name`,
`registered_providers()`. A future identity backend (Database, LDAP,
OAuth, OpenID Connect, Microsoft Entra ID, Google Identity, Okta,
Auth0) is one new class plus one `register()`/`set_active()` call --
zero changes to `AuthenticationService` or to `components/auth.py`.

**A `Protocol`-based Provider Pattern, mirroring `AuthorizationProvider`
and `MonitoringProvider`.** `AuthenticationProvider` is a
`@runtime_checkable typing.Protocol` with two methods
(`verify_credentials`, `get_identity`). `InMemoryAuthenticationProvider`
is the only implementation this sprint ships, seeded from
`config/credentials.py`. `tests/test_identity.py` proves swappability
directly with `_ReadOnlyProvider`, a from-scratch class sharing no
base class with `InMemoryAuthenticationProvider`.

**A framework-agnostic `SessionManager`, with Streamlit touched only
at the edge.** Task 5 asks for two things that read as being in
tension: "keep session logic inside the Identity layer" and "use the
existing Streamlit session state only as a storage mechanism."
`identity/session.py` resolves this by depending only on
`collections.abc.MutableMapping[str, SessionInfo]` -- satisfied by a
plain `dict` (the default, used by every test and by the shared
`session_manager` singleton) and equally satisfied by
`st.session_state` (which already implements the mapping protocol),
injectable via the constructor. `identity/session.py` itself never
imports Streamlit. What `st.session_state` *is* used for, in
`components/auth.py` alone, is remembering which single `session_id`
string belongs to this browser session -- the same "store a pointer,
not the record" pattern `components/tenant_selector.py` and
`components/authorization.py` already established for the active
tenant and (formerly) the active user selection. See "Session
Lifecycle" below for the full reasoning.

**Monitoring integration reuses the existing event vocabulary, exactly
as `AuthorizationService` already does.** `AuthenticationService._record()`
calls `monitoring_service.record_completed()` / `record_failure()`
with `service_name="AuthenticationService"`, requiring zero changes to
the monitoring package and making `AuthenticationService` appear in
the Monitoring dashboard's existing Service Statistics table for free.
See "Authentication vs Authorization" below for why this sprint
deliberately repeats a pattern instead of inventing a new one.

**A real login form, replacing Sprint 6.5's demo selectbox.**
`components/authorization.py::render_user_switcher()` -- the "pick who
you are" dropdown -- is gone. `components/auth.py::_render_login_form()`
is a real (if unencrypted, demo-password) username/password form; a
session, not a raw selection, is now what determines identity for the
rest of a browser session. This is a genuine UX upgrade this sprint's
ticket calls for (Task 7), not merely a refactor.

## Identity Model (Task 2)

| Type | Purpose | Key fields |
|---|---|---|
| `UserIdentity` | Who this person is | `user_id`, `username`, `display_name`, `email`, `tenant_id`, `status` (`IdentityStatus`), `metadata` |
| `SessionInfo` | One authenticated session | `session_id`, `user_id`, `created_at`, `last_activity_at`, `expires_at` (+ computed `is_expired`, `remaining_seconds`) |
| `AuthenticationResult` | The outcome of one sign-in attempt | `status` (`LoginStatus`), `identity`, `session`, `message`, `timestamp` (+ computed `is_success`) |
| `LoginStatus` | `SUCCESS` \| `FAILED` | -- |
| `IdentityStatus` | `ACTIVE` \| `INACTIVE` | -- |

`UserIdentity` deliberately does **not** reuse
`authorization.models.User`, even though the two look similar --
see "Authentication vs Authorization" below. All five types are
frozen/immutable value objects with no behavior beyond their own field
types, following this codebase's established convention
(`authorization.models.User`, `tenancy.models.Tenant`,
`monitoring.models.MonitoringEvent`).

## Authentication Flow (Tasks 3, 8, 9)

```
1. A page's script starts: st.set_page_config(...) / inject_header_styles()
       |
2. components.auth.require_authentication() is called -- BEFORE anything else, including render_sidebar()
       |
3. It reads the current browser session's session_id from st.session_state["novamart_session_id"]
       |
4a. No session_id, or session_id invalid/expired:
        -> the stale id (if any) is cleared from st.session_state
        -> the full login screen renders in this page's place
             (branding, a "session expired" notice if that's why, the login form, a demo-accounts hint)
        -> st.stop() -- nothing below this call runs for this visitor
       |
4b. session_id valid:
        -> authentication_service.refresh_session(session_id) -- validates AND extends the
           sliding expiration window AND records "Session Refreshed" (Task 9)
        -> authentication_service.get_current_user(session_id) -- cheap re-read for the UserIdentity
        -> require_authentication() returns that UserIdentity; the page continues normally
       |
5. components.sidebar.render_sidebar() runs next:
        -> render_tenant_selector()          (Sprint 6.3, unchanged)
        -> components.auth.render_user_panel(tenant_context)
               -> re-reads the current identity (cheap, no extra recording)
               -> resolves a UserContext via components.authorization.get_active_user_context(tenant_context)
                  (this is where AUTHORIZATION first runs -- strictly after authentication, Task 8's core requirement)
               -> displays name, role, active tenant, session status, and a Sign Out button
        -> filters NAV_ITEMS via components.authorization.is_authorized(...) (Sprint 6.5, unchanged)
       |
6. The page's own authorization gate runs (e.g. require_permission_ui(VIEW_DASHBOARD, ...)),
   exactly as it did in Sprint 6.5 -- authentication has already completed by this point
```

**The login form itself** (Task 7): username, password, a "Sign In"
button, and business-friendly validation -- a blank field is caught
before ever calling the Authentication Service ("Please enter both a
username and a password"); a bad username or password produces the
same generic "The username or password you entered is incorrect"
message either way (no username enumeration -- see
`identity/exceptions.py`); an inactive account produces "This account
is currently inactive. Please contact your administrator." On success,
the new session id is stored and `st.rerun()` immediately re-renders
the page as the now-authenticated user.

**Sign-in success/failure and sign-out are recorded via the exact same
`OPERATION_COMPLETED`/`OPERATION_FAILED` vocabulary** every other
instrumented service uses, with `service_name="AuthenticationService"`
and the affected identity's id in `metadata["user_id"]` -- zero
changes to `monitoring/models.py` or `monitoring/service.py` (Task 9).

## Session Lifecycle (Task 5)

```
1. AuthenticationService.sign_in(username, password) succeeds
       -> SessionManager.create_session(user_id) builds a SessionInfo:
              session_id = uuid4().hex (never the user_id itself)
              created_at = last_activity_at = now
              expires_at = now + 30 minutes (DEFAULT_SESSION_TIMEOUT_MINUTES)
       -> stored in the SessionManager's own store (a plain dict by default)
       -> the session_id (a single string) is handed back to the UI layer,
          which stores ONLY that string in st.session_state["novamart_session_id"]
       |
2. On every subsequent page load, require_authentication() calls refresh_session(session_id):
       -> SessionManager.validate_session(session_id):
              not found  -> SessionNotFoundError (not recorded -- see below)
              found, expired -> the session is evicted from the store, SessionExpiredError raised
                                 (recorded as "Session Expired", Task 9)
              found, valid   -> returned as-is
       -> if valid: SessionManager.record_activity(session_id) replaces the stored SessionInfo
          with last_activity_at=now, expires_at=now+30min ("sliding" expiration --
          a session that keeps being used never expires; one left idle for 30
          minutes does) -- recorded as "Session Refreshed" (Task 9)
       |
3. AuthenticationService.sign_out(session_id):
       -> SessionManager.destroy_session(session_id) removes it from the store
       -> recorded as "Logout" (Task 9) only if a session actually existed --
          signing out twice, or an already-expired session, is never an error
          and never produces a duplicate/spurious event
```

**Why "Session Not Found" is never recorded, but "Session Expired"
always is.** `SessionNotFoundError` is the ordinary state for every
anonymous visitor on every single page load before their first sign-in
-- recording an event for it would flood the audit trail with
non-events. `SessionExpiredError` means a session *did* exist and
transitioned to invalid, which is exactly the kind of state change an
audit trail exists to capture. This distinction is verified directly:
`tests/test_identity.py::test_session_not_found_is_not_recorded` and
`::test_session_expired_is_recorded`.

**Why validation and "touching" activity are two separate `SessionManager`
methods.** `validate_session()` is a read-only check (used internally
by `is_authenticated()` for cheap, repeated, non-mutating checks);
`record_activity()` validates *and* extends the session in one step.
`AuthenticationService.get_current_user()` calls the cheap read-only
path (safe to call many times per page render, e.g. once per nav item
being filtered) while `refresh_session()` -- called exactly once per
page load, by `require_authentication()` -- is the only place a
session's expiration is actually extended and a "Session Refreshed"
event recorded. Calling the expensive, recording path on every
internal check would both reset the sliding window unpredictably and
flood the Monitoring dashboard.

## Identity Provider Pattern (Task 4)

```
AuthenticationProvider (typing.Protocol, @runtime_checkable)
    verify_credentials(username: str, password: str) -> UserIdentity | None
    get_identity(user_id: str) -> UserIdentity | None
        |
        +-- InMemoryAuthenticationProvider   (this sprint's default; thread-safe via threading.Lock)
        +-- <future> DatabaseAuthenticationProvider
        +-- <future> LdapAuthenticationProvider
        +-- <future> OAuthAuthenticationProvider
        +-- <future> OpenIDConnectAuthenticationProvider
        +-- <future> MicrosoftEntraIDAuthenticationProvider
        +-- <future> GoogleIdentityAuthenticationProvider
        +-- <future> OktaAuthenticationProvider
        +-- <future> Auth0AuthenticationProvider

AuthenticationProviderRegistry
    register(name, provider, *, make_active=False)
    get(name) -> AuthenticationProvider                (raises ProviderNotRegisteredError)
    set_active(name) -> None
    get_active() -> AuthenticationProvider               (raises NoActiveProviderError)
    active_name -> str | None
    registered_providers() -> tuple[str, ...]

authentication_provider_registry = AuthenticationProviderRegistry()   # shared, application-wide
authentication_provider_registry.register("memory", InMemoryAuthenticationProvider(), make_active=True)

AuthenticationService(provider=None, session_manager=None)
    -- both omitted (every real call site) -> the two shared, application-wide instances
    -- either supplied (every test) -> that exact instance, fully isolated
```

Because `AuthenticationProvider` is a structural `Protocol` rather than
an abstract base class, a future provider needs no import from this
package's inheritance hierarchy -- it only needs to expose
`verify_credentials` and `get_identity` with matching signatures.
`tests/test_identity.py::test_authentication_service_works_unmodified_against_a_brand_new_provider_implementation`
proves this directly with a minimal, from-scratch provider class that
`AuthenticationService` authenticates through with zero code changes.

**No password hashing in this release, by explicit design.** Task 7
states plainly: "Do not implement password encryption... The objective
is architecture, not production security." `InMemoryAuthenticationProvider`
compares passwords as plain strings; `config/credentials.py` seeds
every demo identity with the same password (`novamart123`, shown
openly on the login screen's "Demo accounts" hint, since there is no
other way to discover it). A future `DatabaseAuthenticationProvider`
is exactly where salted password hashing belongs -- entirely behind
the same `AuthenticationProvider` interface, with zero change to
`AuthenticationService`.

## Authentication vs Authorization

This is the ticket's central question, and the answer is structural,
not just documentation:

| | Authentication (`identity/`) | Authorization (`authorization/`) |
|---|---|---|
| Answers | "Who is this, and are they signed in?" | "What is this already-signed-in user allowed to do?" |
| Entry point | `identity.service.authentication_service` | `authorization.service.authorization_service` |
| Runs | First, always (Task 8) | Second, only after authentication succeeds |
| Depends on | Nothing from `authorization/` (verified by `ast`-based test) | Nothing from `identity/` |
| Failure mode | `SessionNotFoundError`/`SessionExpiredError`/`InvalidCredentialsError` -> the login screen | `PermissionDeniedError` -> an "Access Denied" panel *within* an already-authenticated page |
| UI glue | `components/auth.py` | `components/authorization.py` |
| Shared with the other layer | Exactly one plain string: a `user_id` | Exactly one plain string: a `user_id` |
| Monitoring | `service_name="AuthenticationService"`, reusing `OPERATION_COMPLETED`/`OPERATION_FAILED` | `service_name="AuthorizationService"`, the identical reused vocabulary |

The two packages independently arrived at the same architectural
pattern (Provider + Registry + a `_record()` helper reusing the
monitoring vocabulary) because they are solving the same *shape* of
problem -- "verify something about a request, record what happened,
stay swappable" -- for two different questions. Repeating a
proven pattern rather than inventing a new one for `identity/` is
deliberate consistency, not an accident of copy-paste: anyone who
already understands `authorization/`'s architecture from
`docs/AUTHORIZATION_ARCHITECTURE.md` can read `identity/`'s source with
zero new concepts to learn.

## Future SSO Integration

Task 1 explicitly asks the framework to "support future Single Sign-On."
The seam is exactly `AuthenticationProvider`: an OAuth 2.0/OpenID
Connect/SAML-backed provider (Microsoft Entra ID, Google Identity,
Okta, Auth0 are all named explicitly in the ticket) would implement
`verify_credentials`/`get_identity` by redirecting to the identity
provider's hosted login page and exchanging the resulting token for a
`UserIdentity`, rather than checking a password locally. Nothing about
`AuthenticationService`, `SessionManager`, or `components/auth.py`'s
gate contract changes -- `require_authentication()` still just needs
*a* valid session to exist. The one piece of UI that *would* change is
`_render_login_form()` itself (an SSO flow redirects to an external
page rather than collecting a password locally) -- everything
downstream of a successful sign-in (session creation, the sliding
expiration window, monitoring events, the identity->authorization
bridge) is already provider-agnostic today.

## Future MFA Support

Task 1 also asks the framework to "support future Multi-Factor
Authentication." Two extension points already exist without any
redesign:

1. **`AuthenticationResult`** already models a first-class outcome of
   an authentication attempt distinct from "success" and "failure" in
   spirit -- adding a `LoginStatus.MFA_REQUIRED` member and an
   `AuthenticationService.verify_mfa_code(pending_token, code)` method
   that completes a sign-in already begun by `sign_in()` is additive:
   no existing method's signature needs to change, since callers
   already branch on `result.status`.
2. **`SessionManager`** already separates "a session was created" from
   "a session is fully trusted" only implicitly (every session is
   immediately fully trusted today) -- a `SessionInfo.mfa_verified: bool`
   field (defaulting to `True` for providers that don't require MFA)
   would let `AuthenticationService.get_current_user()` optionally
   enforce a second factor before returning an identity, again with no
   change to any of the dozens of call sites that already call
   `get_current_user()`/`refresh_session()`.

Neither extension is implemented this sprint -- both are structural
observations about where they would attach, consistent with this
codebase's established practice of documenting a concrete "next
iteration" seam rather than speculatively building unrequested scope.

## Confirmation against the agreed architecture

- [x] Existing architecture (Multi-Tenant Architecture, Tenant Context,
      Monitoring Platform, Permission-Based Authorization Framework,
      User Context, Executive Reporting, AI Recommendation Service)
      preserved exactly; `authorization/` was not modified at all,
      `services/*.py` and `utils/*.py` are untouched.
- [x] Centralized, framework-agnostic `identity/` package (no
      Streamlit dependency) with `models.py`, `provider.py`,
      `session.py`, `registry.py`, `service.py`, `exceptions.py`,
      `__init__.py`.
- [x] Reusable identity models: User Identity, Authentication Result,
      Session Information, Login Status, Authentication Timestamp
      (`AuthenticationResult.timestamp`), Last Activity
      (`SessionInfo.last_activity_at`), Session Expiration
      (`SessionInfo.expires_at`) -- all designed for future
      extensibility via open `metadata` mappings and additive fields.
- [x] Centralized Authentication Service: authenticate users, sign in,
      sign out, validate sessions, refresh sessions, retrieve current
      user, business-friendly authentication errors -- business
      services never authenticate users directly (verified: zero
      imports of `identity` from `services/`/`utils/`).
- [x] Authentication Provider abstraction, in-memory provider using
      the existing demo users (via `config/credentials.py`), future
      providers (Database, LDAP, OAuth, OpenID Connect, Microsoft
      Entra ID, Google Identity, Okta, Auth0) pluggable with zero
      change to `AuthenticationService`.
- [x] Reusable Session Manager: create, destroy, validate, update last
      activity, handle expiration -- framework-independent, with
      Streamlit touched only at the UI edge (`components/auth.py`
      storing one `session_id` string in `st.session_state`).
- [x] Identity Registry managing available providers, the active
      provider, and future provider switching, without any change to
      authentication logic.
- [x] Professional login experience: username, password, Sign In
      button, business-friendly validation messages, logged-in user
      display, logout -- no password encryption, demo users only
      (Task 7's explicit scope).
- [x] Authentication executes before authorization on every protected
      page: `require_authentication()` is the first call after page
      configuration on `app.py` and all seven `pages/*.py` files,
      strictly before `render_sidebar()` (which is itself where
      authorization first runs).
- [x] Monitoring records Login Successful, Login Failed, Logout,
      Session Expired, and Session Refreshed -- reusing the existing
      `OPERATION_COMPLETED`/`OPERATION_FAILED` vocabulary, zero changes
      to `monitoring/models.py` or `monitoring/service.py`.
- [x] UI: unauthenticated users see the login screen in place of any
      protected page (functionally a redirect); the sidebar displays
      the current user's name and role, the active tenant, and session
      status; authentication errors are business-friendly throughout.
- [x] Comprehensive tests (`tests/test_identity.py`, 68 tests) covering
      the Authentication Service, Identity Provider (including a
      from-scratch custom provider), Session Manager, login, logout,
      session expiration, invalid login, the Provider Registry,
      monitoring integration, and authorization integration (including
      a structural, `ast`-based proof of package independence).
- [x] Existing functionality continues working: the full pre-existing
      test suite (14 files, 332 tests before this sprint) passes
      unchanged alongside the 68 new identity tests, 400 total, 0
      failures.
- [x] Providers are interchangeable -- proven directly by the
      from-scratch `_ReadOnlyProvider` test.
- [x] Sessions behave correctly -- creation, sliding-window renewal,
      expiration-with-eviction, and idempotent destruction are each
      covered by a dedicated test and by the headless dry-run below.
- [x] Follows Single Responsibility Principle, Separation of Concerns,
      Clean Architecture, Provider Pattern (`AuthenticationProvider`),
      Registry Pattern (`AuthenticationProviderRegistry`), Dependency
      Injection (`AuthenticationService`'s constructor), and Framework
      Independence (no Streamlit import anywhere under `identity/`).

## Automated tests

`tests/test_identity.py` -- 68 tests across twelve sections:

1. **Models** -- `UserIdentity.is_active`, `SessionInfo.is_expired`/`remaining_seconds`,
   `AuthenticationResult.is_success`, `LoginStatus`/`IdentityStatus` as
   plain strings.
2. **Authentication Provider** -- registration, credential verification
   (correct, wrong password, unknown username), identity lookup by id,
   bulk registration, replacement, clearing, `Protocol` conformance.
3. **Session Manager** -- creation, lookup, validation (unknown,
   expired-and-evicted), sliding-activity extension, idempotent
   destruction, clearing, and an injected-store test proving the
   `MutableMapping` contract (a plain `dict` works, satisfying Task
   5's DI requirement without needing Streamlit installed).
4. **Authentication Service -- `authenticate()`** -- success, unknown
   username, wrong password, inactive identity, and the deliberately
   identical error message for the first two (no username
   enumeration).
5. **Login -- `sign_in()`** -- full result shape (status, identity,
   session, message), a retrievable session, no session created on
   failure or inactivity.
6. **Logout -- `sign_out()`** -- destroys the session, idempotent on a
   second call, safe against an unknown/`None` session id.
7. **Session expiration** -- `validate_session()`/`get_current_user()`/
   `is_authenticated()` all correctly reject an expired session.
8. **Invalid login** -- unknown username, wrong password, no session
   at all, and an identity that vanishes from the provider mid-session
   (`NotAuthenticatedError`).
9. **Registry** -- register/get/set_active/get_active, first-registered-becomes-active,
   `make_active=True`, sorted `registered_providers()`, and the
   from-scratch `_ReadOnlyProvider` swappability proof.
10. **Monitoring integration** -- sign-in success/failure, sign-out
    (and that an unknown session's sign-out is *not* recorded), session
    expiration (and that "never signed in" is *not* recorded), session
    refresh, `AuthenticationService` appearing correctly in
    `get_service_health()`, and resilience against a broken monitoring
    provider.
11. **Authorization integration** -- a structural, `ast`-based proof
    that `identity/` never imports `authorization/`; a full
    identity-to-authorization handoff test using independently
    constructed provider/registries on both sides; proof that neither
    an unauthenticated nor an expired-session request ever reaches
    authorization.
12. **Regression** -- fresh service instances never share session
    state; the zero-argument constructor path every real call site
    uses; the full `AuthenticationError` subclass hierarchy.

**Full-suite regression run:** all 15 test files (14 pre-existing + the
new `test_identity.py`), 400 tests total, 0 failures, run together in
a single sandbox process.

## Manual test cases (headless dry-run)

Exercised via a headless dry-run driving the real
`components.auth`/`components.authorization` functions
(`require_authentication`, `is_authenticated`, `render_user_panel`,
`get_active_user_context`, `is_authorized`) against every seeded demo
persona, using the project's existing Streamlit-stub harness (extended
this sprint with `st.form`/`st.form_submit_button`/`st.rerun`) so real
application code runs end to end with no UI framework installed:

| Check | Result |
|---|---|
| Unauthenticated visit halts at the login screen (`st.stop()` fires) | Pass |
| A signed-in session passes the gate and returns the correct identity | Pass |
| `is_authenticated()` reflects the active session | Pass |
| Authorization resolves the exact user id authentication just verified | Pass |
| `business.analyst` holds `VIEW_DASHBOARD`, not `VIEW_MONITORING`/`MANAGE_TENANTS` | Pass |
| The sidebar user panel returns a correctly-resolved `UserContext` | Pass |
| The gate halts again immediately after sign-out | Pass |
| An expired session is detected, shows a "session expired" notice, clears the stale id, and halts | Pass |
| System Administrator / Tenant Administrator / Business Analyst / Executive Viewer each sign in and resolve correctly end to end | Pass (all 4) |
| The inactive demo account is blocked at sign-in and never reaches authorization | Pass |

All 17 checks passed with zero unhandled exceptions.

## Assumptions made

- **Login "redirect" is implemented as an in-place login screen, not a
  separate page.** Every protected page already gates itself behind
  `require_authentication()`; rendering the login screen in that exact
  page's place and calling `st.stop()` is functionally identical to a
  redirect (the visitor sees only the login screen) without
  introducing a literal `pages/0_Login.py` and `st.switch_page` calls
  on every page. Documented explicitly in `components/auth.py`'s
  module docstring.
- **The demo user switcher from Sprint 6.5 is retired, not kept as a
  fallback.** Task 7 asks for a real login interface, and Task 10 asks
  for unauthenticated users to be redirected -- keeping the old "pick
  who you are" selectbox alongside real login would mean two
  contradictory ways to become "signed in" as different people in the
  same session. `render_user_switcher()` no longer exists;
  `components/authorization.py::get_active_user_context()` now sources
  its `user_id` from the identity session exclusively.
- **A single shared demo password (`novamart123`) for every seeded
  account**, shown openly on the login screen, per Task 7's explicit
  "no password encryption... demo users only" scope. A per-user
  password was considered and rejected as adding friction without
  adding any real security in a demo release.
- **Session timeout is 30 minutes, sliding.** Not specified by the
  ticket; chosen as a reasonable default for an interactive business
  dashboard and exposed as a constructor parameter
  (`SessionManager(timeout_minutes=...)`) rather than hard-coded, so a
  future deployment can tune it without a code change.
- **"Session Not Found" (never signed in) is not recorded as a
  monitoring event; "Session Expired" (a session that existed and
  lapsed) always is.** Recording every anonymous page view before a
  first sign-in would flood the audit trail with a non-event; a
  genuine expiration is a meaningful state transition. Documented and
  tested explicitly (see "Session Lifecycle" above).
- **`identity.models.UserIdentity` intentionally duplicates a few
  fields already present on `authorization.models.User`** (display
  name, email, tenant id) rather than reusing that type, to keep the
  two packages structurally independent per this sprint's central
  requirement. `config/credentials.py` is the one place that keeps
  them in sync for the demo directory; a real deployment backed by an
  external identity provider would populate `UserIdentity` from that
  provider's claims directly, with no dependency on `authorization/`
  either way.
