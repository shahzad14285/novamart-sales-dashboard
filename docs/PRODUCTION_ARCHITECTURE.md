# NovaMart Production Readiness Platform

Sprint 6.9 -- Production Readiness Platform.

This document describes the centralized configuration and operational
readiness layer introduced in this sprint: a framework-agnostic
`configuration/` package (a Configuration Service, provider-based
value resolution, environment profiles, feature flags) and a
companion `operations/` package (Health Checks, Readiness Checks,
Deployment information) that together prepare NovaMart to run as a
multi-environment, enterprise-grade production deployment -- without
changing a single line of existing business logic.

It follows the structure and depth of `docs/INTEGRATION_ARCHITECTURE.md`,
`docs/AUTOMATION_ARCHITECTURE.md`, and `docs/AUTHORIZATION_ARCHITECTURE.md`.

---

## 1. Production Architecture

### 1.1 Why configuration and operations are their own platforms

The ticket's central constraint is architectural, not functional:

> "The platform must support these capabilities without changing
> business services."

Every platform NovaMart has accumulated sprint by sprint --
Identity, Authorization, Multi-Tenancy, Monitoring, Automation,
Integration, and the Business Intelligence services themselves -- was
built assuming its own operational settings (which backend is active,
what a "healthy" response looks like, whether a capability is turned
on) were either hardcoded or implicitly always-on. Bolting
"configuration" onto each platform individually would mean six
different places to check when diagnosing a bad deployment, six
different places a secret could leak into source control, and six
different, slightly-inconsistent ideas of what "healthy" means.

This sprint solves it with two new, independent packages plus one
narrow composition-root file, mirroring the exact pattern
`automation/` + `notification/` + `config/automation_setup.py`
established in Sprint 6.7 and `integration/` +
`config/integration_setup.py` established in Sprint 6.8:

```
configuration/         -- generic, reusable configuration resolution,
                           environment profiles, and feature flags.
                           Framework-agnostic. Never imports a specific
                           business service or platform component.

operations/             -- generic, reusable Health Checks, Readiness
                           Checks, and Deployment information.
                           Framework-agnostic. Depends only on
                           configuration/ and monitoring/ (the existing
                           shared observability channel).

config/production_setup.py
                      -- the ONLY file in the codebase allowed to import
                          configuration/ and operations/ together with
                          every other platform package (identity,
                          authorization, monitoring, automation,
                          integration) and the business services.
                          Mirrors config/integration_setup.py exactly.
```

A platform component's entire configuration footprint is reading from
one shared service:

```python
from configuration.service import configuration_service

rate_limit = configuration_service.environment_profile.api_rate_limit_requests_per_minute
```

No business service in `services/` or `utils/` imports `configuration/`
or `operations/` at all -- proven by
`tests/test_configuration.py::test_business_services_never_import_configuration_or_feature_flags`,
and by the full, unchanged pre-Sprint-6.9 test suite (616 tests)
continuing to pass without a single business-logic edit.

### 1.2 Target architecture, as built

```
                  Configuration Service
            (configuration/service.py)
                          │
      ┌───────────────┬───────────────┬───────────────┐
      ▼               ▼               ▼               ▼
 Identity        Authorization    Monitoring      Feature Flags
 (health check)  (health check)  (health check)  (feature_flags.py)
      │               │               │
      ▼               ▼               ▼
 Automation      Integration      Business Services
 (health check)  (health check)  (health check)
      │
      ▼
 Health Check Service
 (operations/health.py)
      │
      ▼
 Readiness Service
 (operations/readiness.py)
      │
      ▼
 Deployment Information
 (operations/deployment.py)
      │
      ▼
 Operations Dashboard (pages/10_Operations.py, administrator only)
```

Every arrow into "Identity / Authorization / Monitoring / Automation /
Integration / Business Services" in this diagram is a **read-only
health check**, registered from `config/production_setup.py` and run
by `operations.health.HealthCheckService` -- none of those six
platforms import `configuration/` or `operations/` themselves. The
dependency points *inward* (Operations checks the platforms) not
*outward* (platforms depending on Operations), which is what "The
platform must support these capabilities without changing business
services" means concretely.

### 1.3 Package layout

```
configuration/
    __init__.py       -- public re-exports only (Task 1)
    models.py          -- Environment, LogLevel, EnvironmentProfile,
                           ConfigurationValue, FeatureFlagDefinition,
                           DeploymentInfo (Task 4)
    exceptions.py       -- ConfigurationError and its six subclasses
    provider.py           -- ConfigurationProvider Protocol +
                             InMemoryConfigurationProvider +
                             EnvironmentVariableConfigurationProvider (Task 3)
    registry.py             -- ConfigurationProviderRegistry (Task 3)
    environments.py          -- EnvironmentProfileRegistry + the three
                                 default profiles (Task 4)
    service.py                 -- ConfigurationService (Task 2)
    feature_flags.py            -- FeatureFlagRegistry + FeatureFlagService (Task 5)

operations/
    __init__.py        -- public re-exports only
    models.py            -- HealthStatus, ComponentHealth,
                             PlatformHealthReport, ReadinessCheckResult,
                             ReadinessReport
    exceptions.py          -- OperationsError and its three subclasses
    health.py                -- HealthCheckRegistry + HealthCheckService
                                 + aggregate_status() (Task 6)
    readiness.py               -- ReadinessCheckRegistry + ReadinessService (Task 7)
    deployment.py                -- build_deployment_info() (Task 7, Task 10)
```

Every module in both packages is importable and independently
testable with zero Streamlit dependency -- `tests/test_configuration.py`
and `tests/test_operations.py` never import `streamlit`,
`components/`, `ui/`, or `pages/`.

---

## 2. Configuration Flow

`ConfigurationService` (Task 2) is the single centralized point every
platform component resolves configuration through. Its responsibilities,
in the order a typical lookup exercises them:

1. **Load environment settings** -- at construction time, the service
   resolves which `Environment` (Development, Testing, Production) is
   active by reading `NOVAMART_ENVIRONMENT` from whichever
   `ConfigurationProvider` is currently active (falling back to
   `Environment.DEVELOPMENT` if unset or unrecognized), and records two
   monitoring events (`load_configuration`, `select_environment` --
   Task 9).
2. **Resolve configuration values** -- `get()`/`get_bool()`/`get_int()`
   delegate to the active provider's `get()`. A missing provider or a
   missing key never raises; it resolves to the caller-supplied
   `default` (or `None`) -- the same resilience guarantee every other
   service in this platform makes for its own failure modes.
3. **Provide configuration** -- `environment_profile` exposes the
   active `EnvironmentProfile` (logging level, feature defaults,
   monitoring flag, API rate limit, HTTPS requirement) for any platform
   component that needs an environment-appropriate default rather than
   a literal value.
4. **Support feature flags** -- `FeatureFlagService` (Task 5) is built
   on top of `ConfigurationService`, not a replacement for it: a flag's
   resolved value can come from a `FEATURE_<KEY>` configuration key,
   letting a deployment toggle a capability via an environment variable
   with zero code change or redeploy.
5. **Supply configuration to platform components** -- every health
   check, every dashboard, and (via `config/production_setup.py`'s
   nav-level feature-flag gating) the sidebar itself reads through this
   one service, never through a component-owned setting.

`ConfigurationService.describe(key)` additionally returns a
`ConfigurationValue` carrying *provenance* -- which provider supplied
the value, or that none did -- which is what the Operations
Dashboard's "Configuration summary" section displays, so a
misconfigured deployment ("why isn't my environment variable taking
effect?") is diagnosable from the UI alone.

---

## 3. Provider Pattern

`ConfigurationProvider` (`configuration/provider.py`) is a
`@runtime_checkable` `Protocol` -- structural typing, exactly like
every other provider interface in this platform
(`identity.provider.AuthenticationProvider`,
`monitoring.provider.MonitoringProvider`,
`integration.provider.IntegrationProvider`). `ConfigurationService`
depends only on this interface, never on a concrete backend -- "The
Configuration Service must remain provider-independent" is satisfied
the same way Sprint 6.8 satisfied it for the API Gateway: nothing in
`configuration/service.py` imports a specific provider class.

This sprint ships two providers:

- **`InMemoryConfigurationProvider`** -- a plain, mutable, thread-safe
  dict of key/value pairs. Seeds the sensible defaults every deployment
  starts from (`config/production_setup.py`'s
  `_DEFAULT_CONFIGURATION_VALUES`).
- **`EnvironmentVariableConfigurationProvider`** -- reads from
  `os.environ`, optionally scoped to a prefix (`NOVAMART_`). The
  standard way a containerized or cloud deployment injects
  configuration and secrets at runtime without ever committing them to
  source control.

Both are registered into the shared `ConfigurationProviderRegistry`
by `config/production_setup.py`; the in-memory provider is active by
default, with the environment-variable provider registered alongside
it so an operator can switch (`configuration_provider_registry.set_active("environment")`)
with **zero code change**. `tests/test_configuration.py::test_registry_set_active_switches_provider`
proves this directly -- "Provider Swapping" (Task 11) as an automated,
regression-tested guarantee, not a manual claim.

**Future providers** -- Azure Key Vault, AWS Secrets Manager, Google
Secret Manager, HashiCorp Vault, or a database-backed configuration
store -- are added by writing one new class that satisfies
`ConfigurationProvider` (a `name` property, a `get(key)` method, an
`as_dict()` method) and registering it. Nothing in
`ConfigurationService`, `FeatureFlagService`, or any health check needs
to change.

---

## 4. Registry Pattern

Three registries in this sprint mirror the pattern already established
throughout the codebase (`tenancy.registry.TenantRegistry`,
`authorization.permissions.PermissionRegistry`,
`identity.registry.AuthenticationProviderRegistry`):

- **`ConfigurationProviderRegistry`** -- which configuration provider
  is active, mirroring `AuthenticationProviderRegistry`'s exact shape
  (`register`/`get`/`set_active`/`get_active`/`active_name`/
  `registered_providers`).
- **`EnvironmentProfileRegistry`** -- the environment catalogue (Task
  4), mirroring `TenantRegistry`.
- **`FeatureFlagRegistry`** -- the flag catalogue (Task 5), mirroring
  `PermissionRegistry`.

`operations/` adds two more, purpose-built for its own responsibilities:

- **`HealthCheckRegistry`** -- maps a platform component name to a
  zero-argument check callable.
- **`ReadinessCheckRegistry`** -- maps a readiness check name to a
  zero-argument check callable.

Every one of these is a generic lookup table with zero
component-specific behavior baked in -- *which* providers, profiles,
flags, or checks exist is declared once via `register()` calls from
`config/production_setup.py`, never a hardcoded
`if component == "...":` branch anywhere in `configuration/` or
`operations/`.

---

## 5. Environment Profiles

`EnvironmentProfile` (Task 4) bundles every operational setting one
environment needs: `logging_level`, `monitoring_enabled`,
`api_rate_limit_requests_per_minute`, `require_https`, and
`feature_defaults` (a per-environment default for every feature flag).
Three profiles are declared once, in `configuration/environments.py`,
and never duplicated elsewhere:

| Environment | Logging | Rate Limit | HTTPS Required |
|---|---|---|---|
| Development | DEBUG | 1000/min | No |
| Testing | INFO | 300/min | No |
| Production | WARNING | 60/min | Yes |

"Avoid hardcoded production values throughout the application" is
satisfied structurally: no file outside `configuration/environments.py`
contains a literal `if environment == "production":` check. A platform
component that needs an environment-appropriate value reads
`configuration_service.environment_profile.<field>` instead.

**Environment switching** is a first-class, tested operation --
`tests/test_configuration.py::test_switching_environment_changes_the_resolved_profile`
constructs two `ConfigurationService` instances against the same
registries, one pinned to `Environment.DEVELOPMENT` and one to
`Environment.PRODUCTION`, and confirms each resolves its own,
independent profile. In a real deployment, switching environments is
one environment variable (`NOVAMART_ENVIRONMENT=production`) --
`ConfigurationService` re-resolves it at construction time from
whichever provider is active.

---

## 6. Feature Flags

`FeatureFlagService` (Task 5) is the centralized enable/disable/check
point for the six capabilities this sprint's ticket names: AI
Recommendation, PDF Generation, Export Service, Automation, Monitoring
Dashboard, and Integration Dashboard. Resolution order for
`is_enabled(key)`, most specific first:

1. An explicit runtime override (`enable(key)`/`disable(key)` --
   e.g. an administrator toggling a flag from the Operations
   Dashboard).
2. A boolean configuration value at `FEATURE_<KEY_UPPERCASE>` on the
   active `ConfigurationProvider` (a deployment-level override with no
   code change).
3. The active `EnvironmentProfile`'s `feature_defaults` entry.
4. The flag's own `FeatureFlagDefinition.default_enabled`.

"Business services should never contain hardcoded feature switches" is
enforced structurally, not by convention:
`tests/test_configuration.py::test_business_services_never_import_configuration_or_feature_flags`
parses every business service module's AST and asserts none of them
import anything from `configuration`. Flag enforcement this sprint
happens at the **presentation layer** only -- `components/sidebar.py`
additionally hides the Monitoring / Automation / Integrations nav
entries when their corresponding flag (`monitoring_dashboard`,
`automation`, `integration_dashboard`) is disabled, purely additive on
top of the existing permission-based filtering (every flag defaults to
enabled, so this changes nothing for an unconfigured deployment). Every
flag evaluation is recorded to `monitoring_service` (Task 9), so an
administrator can audit exactly when and how often a flag was checked.

Deeper, in-service flag gating (e.g. hiding the "Generate PDF" button
inside the Reports page specifically, rather than the whole dashboard
page) is deliberately out of this sprint's scope -- see Section 10
("Assumptions") below; doing so would mean editing the pages that call
business logic, and the ticket's "Do not modify business logic"
boundary is interpreted conservatively here to mean the *pages*
orchestrating that logic too, not only the services themselves.

---

## 7. Health vs Readiness

This is the distinction the ticket asks to be explicitly documented,
and it is enforced as two separate services (`operations/health.py`,
`operations/readiness.py`), not one overloaded one:

- **Health** answers "is each platform component itself responding and
  functioning correctly, right now?" `HealthCheckService.check_all()`
  runs a check for each of the six named platforms (Identity,
  Authorization, Monitoring, Automation, Integration, Business) and
  aggregates the worst status among them (`HEALTHY` / `WARNING` /
  `UNHEALTHY`) into an overall `PlatformHealthReport`.
- **Readiness** answers "is the platform, as a whole, ready to serve
  external traffic, right now?" `ReadinessService.evaluate()` computes
  Health *and* runs a separate set of readiness checks (this sprint:
  "is every required configuration key present", "has an environment
  been resolved") -- `ready` is `True` only if the platform isn't
  `UNHEALTHY` **and** every readiness check passes.

The ticket's own worked example is implemented and directly tested,
not just described:

```
Healthy
but
Configuration missing
-->
Not Ready
```

`tests/test_operations.py::test_readiness_service_healthy_but_configuration_missing_is_not_ready`
registers every health check as `HEALTHY`, then registers one
readiness check that fails (a missing configuration key), and asserts
the resulting report shows `health.overall_status == HEALTHY` while
`ready == False` -- the exact scenario the ticket describes, proven,
not asserted in prose. `config/production_setup.py`'s own
`required_configuration_present` readiness check is this scenario's
real-world equivalent: if `APP_NAME` (or any other required key) were
removed from the default configuration and no environment variable
supplied it, every health check could still report Healthy while this
one readiness check would correctly fail, making the platform Not
Ready.

A `WARNING` health status, by contrast, does **not** by itself block
readiness -- only `UNHEALTHY` does
(`tests/test_operations.py::test_readiness_service_ready_despite_warning_status`).
A component reporting "no scheduled jobs registered" is a warning
worth investigating, not a reason to refuse traffic.

---

## 8. Deployment Strategy

NovaMart ships no production HTTP server this sprint or any prior one
-- every sprint's "the objective is architecture" boundary applies
here too. `operations/deployment.py::build_deployment_info()` produces
a read-only `DeploymentInfo` snapshot (environment, application
version, a short strategy description, build metadata) for the
Operations Dashboard; it never performs a deployment itself.

The three environments this platform supports map to three
increasingly formal deployment strategies:

| Environment | Strategy |
|---|---|
| Development | Single local process (`streamlit run app.py`); no build artifact, no HTTPS termination. |
| Testing | Single staging process behind a reverse proxy; deployed from a tagged build, no external traffic. |
| Production | Containerized process behind a load balancer with HTTPS termination; deployed from a released, versioned build. |

A real production rollout would additionally: build a container image
tagged with `configuration.environments.APP_VERSION`; inject
`NOVAMART_ENVIRONMENT=production` and every `NOVAMART_*` secret via the
orchestrator's own secrets mechanism (Kubernetes Secrets, ECS task
definition secrets, or a real secrets-manager-backed
`ConfigurationProvider` -- see Section 9); run the container behind a
load balancer terminating HTTPS (`EnvironmentProfile.require_https`
documents this requirement, it does not enforce it -- enforcement is
the load balancer/ingress's job); and gate traffic on the Readiness
Service (`ReadinessService.evaluate().ready`) via the orchestrator's
own readiness-probe mechanism, exactly the same shape as a Kubernetes
readiness probe.

---

## 9. Secrets Strategy

No secret is ever committed to source control in this sprint:
`config/production_setup.py`'s `_DEFAULT_CONFIGURATION_VALUES` dict
contains only non-sensitive defaults (`APP_NAME`, `DEPLOYMENT_REGION`,
`SUPPORT_CONTACT`) -- every value already safe to display on the
Operations Dashboard verbatim. A real secret (a database password, an
API key, a signing key) belongs in one of two places, neither of which
is this codebase:

1. **An environment variable**, read via
   `EnvironmentVariableConfigurationProvider` -- suitable for a
   single-process deployment where the orchestrator (Docker Compose,
   systemd, a PaaS) already injects environment variables securely.
2. **A dedicated secrets-manager provider** (Azure Key Vault, AWS
   Secrets Manager, Google Secret Manager, HashiCorp Vault) -- a future
   class satisfying `ConfigurationProvider`, registered alongside the
   two this sprint ships, for a deployment that needs rotation,
   audit-logged access, or fine-grained IAM policies a plain
   environment variable can't provide.

`ConfigurationProvider.as_dict()` -- used by the Operations Dashboard's
"Configuration summary" -- is the one place a future secrets-backed
provider must actively redact or omit sensitive values rather than
exposing them verbatim; this is called out explicitly in that method's
docstring so it isn't missed when such a provider is eventually
written.

---

## 10. Operational Readiness

Putting Sections 2-9 together, "operational readiness" for NovaMart
means:

1. **Configuration is centralized** -- one `ConfigurationService`,
   provider-backed, environment-aware (Sections 2-5).
2. **Every capability can be toggled without a redeploy** -- Feature
   Flags, resolvable from configuration (Section 6).
3. **Every platform component is independently health-checked** --
   Identity, Authorization, Monitoring, Automation, Integration,
   Business (Section 7).
4. **"Healthy" and "ready to serve traffic" are distinct, both
   computed, both visible** (Section 7).
5. **What's deployed, where, and how is inspectable at a glance** --
   the Operations Dashboard (`pages/10_Operations.py`, administrator
   access only via the existing `manage_platform` permission) surfaces
   every one of the above: current environment, active configuration
   provider, feature flags (with live toggle buttons), health status,
   readiness status, configuration summary, and deployment information
   -- exactly Task 10's list, nothing more.
6. **None of it required touching business logic** -- verified by the
   full, unmodified pre-Sprint-6.9 test suite (616 tests) continuing to
   pass, by an AST-level check that no business service imports
   `configuration/` or `operations/`, and by 82 new tests covering the
   two new packages end to end (698 tests total, 0 failures).

---

## Assumptions Made

- **UI-level feature-flag enforcement only.** Feature flags are wired
  into the sidebar's nav-item filtering (hiding the Monitoring,
  Automation, and Integrations pages when their flag is disabled) but
  not into individual buttons inside pages that already exist (e.g. a
  "Generate PDF" button inside Reports). Enforcing a flag at that
  granularity would mean editing the pages that orchestrate business
  logic calls, which this sprint treats as within the "Do not modify
  business logic" boundary, not outside it. `FeatureFlagService` is
  fully built, tested, and ready for a future sprint to wire in at that
  finer granularity.
- **Six platform-component health checks are lightweight liveness
  checks**, not deep functional tests: each confirms its platform's
  shared singleton/registry is reachable and non-empty (e.g. "is an
  authentication provider active", "does the permission registry have
  entries", "are report types defined") rather than exercising a full
  business workflow. This matches the ticket's "the objective is
  architecture" framing and avoids any risk of a health check itself
  mutating state or incurring the cost of a real business operation.
- **No production HTTP server, health/readiness endpoints, or actual
  secrets-manager integration are implemented** -- consistent with
  every prior sprint's identical constraint. `HealthCheckService` and
  `ReadinessService` are ready to be exposed over a future
  `integration/` Gateway endpoint (e.g. `GET /api/v1/health`) with zero
  change to either service.
- **`APP_VERSION` is a manually-maintained constant**
  (`configuration/environments.py`), not derived from git metadata or
  a build pipeline -- appropriate for this sprint's scope; a real CI/CD
  pipeline would inject it via `NOVAMART_VERSION` at build time instead.
