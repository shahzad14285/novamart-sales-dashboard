# NovaMart Integration Platform & API Gateway

Sprint 6.8 -- Integration Platform & API Gateway.

This document describes the centralized integration layer introduced in
this sprint: a framework-agnostic `integration/` package (an API
Gateway, an Endpoint Registry, request validation, rate limiting, and a
provider abstraction) that becomes the single entry point every future
external system -- ERP, CRM, mobile app, web portal, partner system, BI
tool, external automation platform -- will reach NovaMart through.

It follows the structure and depth of `docs/AUTOMATION_ARCHITECTURE.md`,
`docs/AUTHORIZATION_ARCHITECTURE.md`, and `docs/IDENTITY_ARCHITECTURE.md`.

---

## 1. Integration Architecture

### 1.1 Why a gateway, not direct access to business services

The ticket's central constraint is architectural, not functional:

> "Business services must never be exposed directly to external
> systems. All external communication must pass through a centralized
> API Gateway."

NovaMart's business services (`KPIEngine`, `ReportingService`,
`PDFGeneratorService`, `ExportService`, `AIRecommendationService`, the
Upload/Data Loader pipeline) were each built, sprint by sprint, to do
exactly one thing and to be reachable only through the Streamlit UI
layer that already authenticates and authorizes every call. Letting a
future REST client, webhook, or connector call any of them directly
would mean re-implementing authentication, authorization, validation,
rate limiting, and monitoring once per integration channel -- and would
mean every future external-facing concern (a new auth scheme, a
tighter rate limit, a new API version) touches business logic that has
nothing to do with being called externally.

The Integration Platform solves this with one new, independent package
plus one narrow composition-root file:

```
integration/          -- generic, reusable API Gateway. Framework-
                          agnostic (no Streamlit import anywhere in it).
                          Never imports a specific business service.

config/integration_setup.py
                      -- the ONLY file in the codebase allowed to import
                          both integration/ and the business services it
                          fronts. Mirrors config/automation_setup.py
                          (Sprint 6.7) and config/credentials.py
                          (Sprint 6.6) exactly.
```

A business service's entire integration footprint is **zero lines**.
`utils/kpi_engine.py`, `services/reporting_service.py`,
`services/pdf_generator_service.py`, `services/export_service.py`, and
`services/ai_recommendation_service.py` are byte-for-byte unmodified by
this sprint -- proven by `tests/test_integration.py::test_existing_business_services_import_unmodified`
and by the full, unchanged pre-Sprint-6.8 test suite (538 tests)
continuing to pass without a single edit. "Business services should
remain unaware of external callers" is enforced structurally: none of
them import anything from `integration/`, and nothing in `integration/`
reaches into a business service except the thin, one-way adapter
functions in `config/integration_setup.py`.

### 1.2 Target architecture, as built

```
                        External Client
      (future REST client, webhook, ERP/CRM/BI connector, ...)
                              |
                              v
                 +-------------------------+
                 |   Integration Provider    |   <- integration/provider.py
                 |  (channel adapter; this   |      IntegrationProvider Protocol
                 |   sprint: in-memory sim)  |      InMemoryIntegrationProvider
                 +-------------------------+
                              |
                              | .submit(gateway, request)
                              v
                 +-------------------------+
                 |       API Gateway          |   <- integration/gateway.py
                 |  Receive -> Validate ->    |      APIGateway.handle_request()
                 |  Authenticate -> Authorize |
                 |  -> Rate Limit -> Route -> |
                 |  Monitor -> Respond        |
                 +-------------------------+
                    |     |      |      |
        +-----------+     |      |      +-----------+
        v                 v      v                  v
  RequestValidator   AuthN/AuthZ  RateLimiter   EndpointRegistry
  (validation.py)    (identity/,  (rate_limiter (registry.py) + Router
                      authorization/)   .py)         (router.py)
                                                        |
                                                        v
                                              +-------------------+
                                              |  Endpoint Handler   |  <- config/integration_setup.py
                                              |  (thin adapter)     |
                                              +-------------------+
                                                        |
                                                        v
                              Internal Platform (unmodified)
        KPIEngine | ReportingService | PDFGeneratorService |
        ExportService | AIRecommendationService | Automation | Notification
                                                        |
                                                        v
                                       monitoring.service.monitoring_service
                                (Task 9: every Gateway step recorded here,
                                 the same shared channel every other service uses)
```

This matches the ticket's Target Architecture exactly: `External Client
-> API Gateway (Authentication, Authorization, Request Validation, Rate
Limiting, Monitoring, API Versioning, Routing, Error Handling) ->
Internal Platform`.

### 1.3 Package layout

```
integration/
    __init__.py       -- public re-exports only (Task 1)
    models.py          -- IntegrationRequest, IntegrationResponse,
                           EndpointDefinition, RateLimitPolicy,
                           RateLimitStatus, RequestMethod, ResponseStatus,
                           IntegrationChannel (Task 4)
    exceptions.py       -- IntegrationError and its seven subclasses,
                            one per Gateway failure mode
    validation.py       -- RequestValidator (Task 5)
    registry.py          -- EndpointRegistry + IntegrationProviderRegistry
                            (Task 3, Task 7)
    provider.py           -- IntegrationProvider Protocol +
                             InMemoryIntegrationProvider (Task 7)
    router.py              -- Router: resolve + dispatch (Task 2 support)
    rate_limiter.py          -- RateLimiter (Task 6)
    gateway.py                -- APIGateway: the orchestrator (Task 2, Task 9)
```

Every module is importable and independently testable with zero
Streamlit dependency -- `tests/test_integration.py` never imports
`streamlit`, `components/`, `ui/`, or `pages/`, proving the package is
"framework independent" in the same sense `automation/` and
`notification/` already are.

---

## 2. API Gateway Flow

`APIGateway.handle_request()` runs every inbound request through a
fixed, eight-step lifecycle, in the exact order the ticket's Task 2
lists its responsibilities:

1. **Receive** -- the request (already built via `build_request()` by
   whatever `IntegrationProvider` accepted it) enters
   `handle_request()`. A `receive_request` event is recorded
   immediately, before any other processing, so even a request that
   fails every subsequent step still leaves a monitoring trail.
2. **Validate** -- `RequestValidator.validate()` confirms the endpoint
   exists, the request is well-formed, and every required field is
   present. This happens *before* authentication or authorization, so
   a caller gets a single, clear validation error rather than being
   told "unauthorized" for a request that was malformed in the first
   place (Task 5: "Validation should occur before routing").
3. **Authenticate** -- delegates to the exact same
   `identity.service.authentication_service` every Streamlit page
   already uses. If the caller already has a resolved `UserContext`
   (typical for an in-process provider), authentication is skipped;
   otherwise a `session_id` is resolved via
   `AuthenticationService.get_current_user()`.
4. **Authorize** -- if the resolved endpoint declares a
   `required_permission`, delegates to the exact same
   `authorization.service.authorization_service.require_permission()`
   every protected Streamlit action already uses. An endpoint with no
   `required_permission` (e.g. a future public health-check endpoint)
   skips this step entirely.
5. **Rate limit** -- `RateLimiter.evaluate()` checks both the caller's
   user- and tenant-scoped ceilings against the endpoint's
   `RateLimitPolicy` (or the Gateway's default policy if the endpoint
   declares none).
6. **Route** -- `Router.route()` resolves the validated request to its
   registered handler and invokes it. By this point the request has
   already passed validation, so an `EndpointNotFoundError` here would
   indicate a genuine platform bug, not a caller error.
7. **Monitor** -- every step above already recorded its own outcome
   into `monitoring.service.monitoring_service` as it happened; step 6
   (routing) additionally records `route_request` with the total
   `processing_time_ms` on success.
8. **Respond** -- a standardized `IntegrationResponse` is returned,
   carrying the original `request_id`, a `ResponseStatus`, a
   business-friendly `message`, optional `data`/`errors`, and
   `processing_time_ms`. This is true for both success and every
   failure mode -- `handle_request()` never raises an exception out to
   its caller (Task 2: "Return standardized responses"); see
   `tests/test_integration.py::test_gateway_never_raises_out_to_the_caller`.

Each failure mode maps to its own `ResponseStatus`:

| Step failed | ResponseStatus |
|---|---|
| Validation | `VALIDATION_ERROR` |
| Authentication | `UNAUTHORIZED` |
| Authorization | `FORBIDDEN` |
| Rate limit | `RATE_LIMITED` |
| Routing (defensive only) | `NOT_FOUND` |
| Handler exception | `ERROR` |
| (none -- success) | `SUCCESS` |

---

## 3. Routing Design

Routing is deliberately split across two collaborators with one
responsibility each:

- **`EndpointRegistry`** (`registry.py`) is the catalogue: it stores an
  immutable `EndpointDefinition` (endpoint key, path, method, API
  version, required permission, rate limit policy, required fields,
  description) alongside a parallel dict of handler callables, keyed by
  `(endpoint, method, api_version)`. This mirrors the
  `ScheduledJob`/`Scheduler` split from Sprint 6.7's Automation
  Platform exactly: the definition is plain, storable, inspectable data
  (what the Integration Dashboard's "Registered Endpoints" table reads
  directly); the handler is a live callable kept separately, so
  `EndpointDefinition` itself stays trivially serializable and
  comparison-friendly for tests.
- **`Router`** (`router.py`) is the dispatcher: given an
  already-validated request, it calls `EndpointRegistry.resolve()` and
  invokes the returned handler. It has no other responsibility -- no
  authentication, no rate limiting, no monitoring -- those all happen
  in the Gateway, before and around the call to `Router.route()`.

Routes are **configuration, not code** (Task 3: "Routes should be
configurable rather than hardcoded"). Nothing in `EndpointRegistry` or
`Router` branches on a specific endpoint key -- adding a new route is
one `endpoint_registry.register(EndpointDefinition(...), handler=...)`
call in a composition root (this sprint: `config/integration_setup.py`),
never a change to `integration/` itself.

**API versioning** falls directly out of this design: the same
`endpoint_key` (e.g. `"kpi.retrieve"`) can be registered multiple times
under different `api_version` values, each with its own path, handler,
and even its own required permission or rate limit policy, since the
registry's lookup key is the full `(endpoint, method, api_version)`
tuple. `EndpointRegistry.all_versions()` returns every version
currently in use, for the Integration Dashboard's "API Version Usage"
section. See
`tests/test_integration.py::test_registry_supports_multiple_api_versions_of_the_same_endpoint_key`
and `test_gateway_supports_multiple_api_versions_end_to_end`.

**Future endpoint discovery**: `EndpointRegistry.list_endpoints()`
already returns every registered endpoint, sorted, with its full
`EndpointDefinition` -- a future `GET /api/v1/endpoints` discovery
endpoint (or a future API documentation generator) needs zero new
plumbing; it registers itself as just another endpoint whose handler
calls `endpoint_registry.list_endpoints()`.

---

## 4. Request Lifecycle

An `IntegrationRequest` is immutable (a frozen dataclass) and carries
exactly the fields the ticket's Task 4 names: Request ID, API Version,
Endpoint, Method, Tenant (`tenant_id`/`tenant_name`), User (`user_id`),
Payload, and Timestamp. `build_request()` is the single place a
`request_id` (a UUID4 hex string) and `timestamp` are generated --
mirroring `automation.events.build_event()` exactly -- so every request
is uniquely and immutably identified the moment it's constructed, well
before it reaches the Gateway.

Because the request is frozen, the Gateway never mutates the caller's
original object in place. When authentication resolves a `user_id` (or
a `TenantContext` resolves a `tenant_id`/`tenant_name`) that the
original request didn't already carry, `_authenticate()` builds a
*new* request via `dataclasses.replace()` and threads that one through
the remaining lifecycle steps -- the original request object a test or
provider holds a reference to is never silently changed underneath it.

An `IntegrationResponse` is likewise immutable and carries exactly what
Task 4 asks for: Status, Message, Data, Errors, and Processing Time
(plus the originating `request_id`, so a caller can always correlate a
response back to its request). "Design for future extensibility" is
satisfied by both models being plain dataclasses with room to grow --
a future field (e.g. a `trace_id` for distributed tracing) is one new
field with a default value, never a breaking change to every existing
caller.

---

## 5. Validation Strategy

`RequestValidator.validate()` runs three checks, in order, but
**collects every failure reason before raising**, rather than stopping
at the first problem:

1. **Endpoint exists** -- looks the endpoint up via
   `EndpointRegistry.find()` (a non-raising lookup), not
   `EndpointRegistry.resolve()` (which raises) -- the validator decides
   what "not found" means for a caller (a `VALIDATION_ERROR`, with a
   business-friendly message), rather than reacting to an exception
   thrown from somewhere else.
2. **Request format** -- confirms `endpoint`/`api_version` are
   non-empty strings and `payload` is dict-shaped.
3. **Required fields** -- checks every key in the resolved
   `EndpointDefinition.required_fields` is present in the payload.

If any check fails, a single `InvalidRequestError` is raised, carrying
every collected reason as a tuple of business-friendly strings (e.g.
`"The 'format' field is required."`) -- so a caller fixing a request
with three problems sees all three at once, not one round trip per
problem. The Gateway catches this one exception type and returns
`ResponseStatus.VALIDATION_ERROR` with `errors` populated from those
reasons.

Validation is the *first* lifecycle step, run before authentication,
authorization, or rate limiting (Task 5: "Validation should occur
before routing") -- a malformed request never reaches, and never
consumes a rate-limit "credit" against, any of those later steps.

---

## 6. Rate Limiting

`RateLimiter` (`rate_limiter.py`) is a small, in-memory, sliding-window
limiter (Task 6: "Use an in-memory implementation. Persistent storage
is not required."), enforcing two independent ceilings per policy --
requests-per-minute and requests-per-hour -- either one being exceeded
blocks the request.

**Per-user and per-tenant limits** (Task 6) are both enforced by
`RateLimiter.evaluate()`: it checks the calling user's counter first
(the more specific, typically tighter-scoped limit), and only checks
the tenant's counter if the user-level check passed, so a single
request is never double-charged against both counters when it was
already going to be rejected.

**Per-endpoint scoping -- the key design decision.** Counters are keyed
as `f"user:{user_id}:{endpoint}"` / `f"tenant:{tenant_id}:{endpoint}"`,
*not* globally per caller. This was found and fixed during this
sprint's own smoke testing: an earlier, globally-scoped version let a
burst of calls against one generously-limited endpoint (e.g.
`kpi.retrieve` at 60/min) spuriously exhaust a *different*,
strictly-limited endpoint's ceiling (e.g. a hypothetical `1/min`
endpoint) for the very same caller, purely because both endpoints
shared one counter. Since every `EndpointDefinition` can carry its own
`RateLimitPolicy` (Task 3, Task 6), a shared global counter would make
each endpoint's individually-configured policy meaningless the moment
a caller touched more than one endpoint. Scoping the key per endpoint
keeps every endpoint's rate limit independently meaningful. See
`tests/test_integration.py::test_rate_limiter_scopes_counters_per_endpoint_not_globally`
and `test_gateway_rate_limit_on_one_endpoint_does_not_affect_a_different_endpoint`.

**Business services never know rate limits exist** (Task 6): only
`APIGateway.handle_request()` calls `RateLimiter.evaluate()`, after
authentication/authorization have already resolved who is calling and
before routing ever reaches a business-service adapter. No service in
`services/` or `utils/` imports `integration.rate_limiter` at all.

`RateLimiter.stats()` offers a read-only peek at a caller's current
usage without recording a new attempt, and `tracked_keys()` lists every
caller/endpoint combination with recorded activity -- both are what the
Integration Dashboard's "Rate Limit Statistics" section reads from,
without ever itself consuming one of the caller's allotted requests.

---

## 7. Provider Pattern

An **Integration Provider** is a channel adapter that sits in *front*
of the Gateway, translating one external channel's native call shape
into an `IntegrationRequest` and handing it to
`APIGateway.handle_request()`. This is the reverse dependency direction
from every other provider pattern in this codebase
(`notification.provider.NotificationProvider`,
`identity.provider.AuthenticationProvider`, which the *service* calls
out to): here, the provider calls *into* the Gateway.

This reversal is what makes Task 7's requirement --
"The API Gateway must remain provider-independent" -- a structural
guarantee rather than a convention: `integration/gateway.py` **never
imports `integration/provider.py`**, at all. This is directly
verified by
`tests/test_integration.py::test_gateway_module_never_imports_provider_module`,
which parses `gateway.py`'s own AST and asserts `integration.provider`
never appears among its imports. A provider is free to call
`handle_request()` however it likes; the Gateway has no idea the
provider exists.

`IntegrationProvider` is a `@runtime_checkable` `Protocol` (a `name`
property plus a `submit(gateway, request) -> IntegrationResponse`
method) -- structural typing, exactly like every other provider
interface in this platform. This sprint ships one concrete
implementation, `InMemoryIntegrationProvider`, which *simulates* an
external channel calling in: it forwards an already-built request
straight to the Gateway, in-process, with no real network hop ("Do NOT
implement a production HTTP server. The objective is architecture."),
and keeps a thread-safe log of every `(request, response)` pair it has
forwarded (mirroring `InMemoryNotificationProvider.sent_messages()`).

A single shared `InMemoryIntegrationProvider` instance is registered
under **every** `IntegrationChannel` this sprint defines --
`REST_API`, `WEBHOOK`, `ERP_CONNECTOR`, `CRM_CONNECTOR`, `POWER_BI`,
`SALESFORCE`, `SAP`, `MS_DYNAMICS` -- so every channel "works" today via
simulation, while each remains independently swappable later.
Registering a real `SalesforceConnectorProvider` under just the
`"salesforce"` key requires one `IntegrationProviderRegistry.register()`
call and zero change to `APIGateway`, `Router`, or any other provider's
registration -- proven by
`tests/test_integration.py::test_providers_are_interchangeable_behind_the_same_channel_key`.

---

## 8. Registry Pattern

Two registries mirror the pattern already established by
`tenancy.registry.TenantRegistry`,
`authorization.permissions.PermissionRegistry`, and
`automation.registry.AutomationEventStoreRegistry`:

- **`EndpointRegistry`** -- the endpoint catalogue (see Section 3).
- **`IntegrationProviderRegistry`** -- maps an `IntegrationChannel` key
  to the provider instance currently handling that channel.
  `register()`, `get()` (raises `ProviderNotRegisteredError` for an
  unknown channel -- a configuration error, not a silent no-op),
  `registered_channels()`, and `clear()` give it the exact same shape
  as every other registry in the codebase.

Both are plain, generic lookup tables with zero endpoint- or
channel-specific behavior baked in -- *which* endpoints and providers
exist is declared once, via `register()` calls from a composition root,
never a hardcoded `if endpoint == "...":` branch anywhere in
`integration/` itself.

---

## 9. Future REST APIs

This sprint intentionally ships no HTTP server ("Do NOT implement a
production HTTP server. The objective is architecture."). Adding real
REST support later requires exactly one new file: a `RESTIntegrationProvider`
(or similar) that satisfies `IntegrationProvider`, whose `submit()`
method is called from a real web framework's route handler (Flask,
FastAPI, or Streamlit's own experimental API surface). That handler's
entire job is to parse an inbound HTTP request into a `build_request()`
call and pass the result to `RESTIntegrationProvider.submit()`, which
hands it straight to `api_gateway.handle_request()` exactly as
`InMemoryIntegrationProvider` already does. No change is needed to
`APIGateway`, `Router`, `EndpointRegistry`, `RequestValidator`, or
`RateLimiter` -- every endpoint already registered against the shared
`endpoint_registry` (e.g. via `config/integration_setup.py`) becomes
reachable over real HTTP the moment such a provider is registered under
`IntegrationChannel.REST_API`.

---

## 10. Future Webhook Support

A future webhook receiver follows the identical pattern: a
`WebhookIntegrationProvider` satisfying `IntegrationProvider`, invoked
whenever an external system POSTs to NovaMart's webhook URL. Its
`submit()` method translates the webhook's payload into an
`IntegrationRequest` (typically targeting a narrower set of
webhook-specific endpoints, e.g. `"webhook.order_created"`, each
registered with its own `required_fields` describing the payload shape
that provider expects) and forwards it to the Gateway exactly like
every other provider. Delivery retries, signature verification, and
payload-shape validation are the webhook provider's own concern (or, for
signature/shape validation, could be layered into
`RequestValidator` via a future, endpoint-specific validation hook) --
none of it requires a second Gateway, a second Endpoint Registry, or a
second Rate Limiter. The entire point of this sprint's design is that
"a new integration channel" is additive: one new provider class, one
`IntegrationProviderRegistry.register()` call, and optionally a handful
of new endpoint registrations -- never a change to the Gateway itself.
