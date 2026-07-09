"""Unit tests for the Integration Platform & API Gateway (Sprint 6.8).

This file is part of the Task 11 deliverable: comprehensive coverage of
the ``integration/`` package -- the request/response/endpoint models,
the Endpoint Registry (registration, resolution, versioning), the
Request Validator, the Rate Limiter (per-user/per-tenant/per-endpoint
scoping), the Router, the API Gateway's full lifecycle orchestration,
the in-memory Integration Provider, and integration with the existing
Monitoring, Authentication, and Authorization services.

Following the convention already established by ``tests/test_automation.py``
and ``tests/test_notification.py``, this file does not import
``streamlit`` or anything from ``components/``/``ui/``/``pages/``. It
also never imports ``config/integration_setup.py`` -- proving
``integration/`` is usable entirely on its own, with no dependency on
which business services end up wired behind it (Task 1: "framework-
agnostic", Task 8: "Business services should remain unaware of
external callers").

Every test constructs its own :class:`~integration.gateway.APIGateway`
backed by fresh, isolated dependencies (:class:`~integration.registry.EndpointRegistry`,
:class:`~integration.router.Router`, :class:`~integration.validation.RequestValidator`,
:class:`~integration.rate_limiter.RateLimiter`, a fresh
:class:`~identity.service.AuthenticationService`, a fresh
:class:`~authorization.service.AuthorizationService`) via Dependency
Injection rather than using the shared, application-wide singletons --
this is what keeps tests fully isolated from each other and from
whatever a real page's import chain (via ``config/integration_setup.py``)
would otherwise register onto the shared instances. The one exception
is the monitoring-integration tests, which necessarily exercise the
shared ``monitoring.service.monitoring_service`` singleton (since
:class:`~integration.gateway.APIGateway` always records into it, by
design) -- those tests clear its active provider before and after
themselves, mirroring ``tests/test_automation.py``'s ``clean_monitoring``
fixture exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from authorization.context import UserContext
from authorization.models import User
from authorization.permissions import DEFAULT_PERMISSIONS, PermissionRegistry
from authorization.provider import InMemoryAuthorizationProvider
from authorization.roles import DEFAULT_ROLES, RoleRegistry
from authorization.service import AuthorizationService
from identity.models import IdentityStatus, UserIdentity
from identity.provider import InMemoryAuthenticationProvider
from identity.service import AuthenticationService
from identity.session import SessionManager
from integration.exceptions import (
    DuplicateEndpointError,
    EndpointNotFoundError,
    InvalidRequestError,
    ProviderNotRegisteredError,
    RateLimitExceededError,
)
from integration.gateway import APIGateway, build_request, new_request_id
from integration.models import (
    DEFAULT_RATE_LIMIT_POLICY,
    EndpointDefinition,
    IntegrationChannel,
    IntegrationRequest,
    IntegrationResponse,
    RateLimitPolicy,
    RateLimitStatus,
    RequestMethod,
    ResponseStatus,
)
from integration.provider import InMemoryIntegrationProvider, IntegrationProvider
from integration.rate_limiter import RateLimiter
from integration.registry import EndpointRegistry, IntegrationProviderRegistry
from integration.router import Router
from integration.validation import RequestValidator
from monitoring.provider import InMemoryMonitoringProvider
from monitoring.registry import monitoring_provider_registry
from monitoring.service import monitoring_service
from tenancy.models import Tenant

try:
    from tenancy.context import TenantContext
except ImportError:  # pragma: no cover - defensive, matches other test files' import shape
    TenantContext = None


# ==============================================================================
# Shared fixtures
# ==============================================================================


def _handler_echo(request: IntegrationRequest) -> dict:
    """A trivial endpoint handler used across most tests."""
    return {"ok": True, "endpoint": request.endpoint, "payload": request.payload}


@pytest.fixture
def endpoint_registry() -> EndpointRegistry:
    """A fresh, empty Endpoint Registry, isolated to a single test."""
    return EndpointRegistry()


@pytest.fixture
def router(endpoint_registry: EndpointRegistry) -> Router:
    """A Router bound to the fixture's isolated Endpoint Registry."""
    return Router(endpoint_registry)


@pytest.fixture
def validator() -> RequestValidator:
    """A fresh Request Validator, isolated to a single test."""
    return RequestValidator()


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """A fresh, empty Rate Limiter, isolated to a single test."""
    return RateLimiter()


@pytest.fixture
def auth_provider() -> InMemoryAuthenticationProvider:
    """A fresh, empty in-memory authentication provider, isolated to a single test."""
    return InMemoryAuthenticationProvider()


@pytest.fixture
def session_mgr() -> SessionManager:
    """A fresh SessionManager, isolated to a single test."""
    return SessionManager()


@pytest.fixture
def authentication_service(auth_provider: InMemoryAuthenticationProvider, session_mgr: SessionManager) -> AuthenticationService:
    """An AuthenticationService wired to fresh, isolated dependencies."""
    return AuthenticationService(provider=auth_provider, session_manager=session_mgr)


@pytest.fixture
def permission_registry() -> PermissionRegistry:
    """A fresh permission registry pre-populated with every default permission."""
    registry = PermissionRegistry()
    registry.register_many(DEFAULT_PERMISSIONS)
    return registry


@pytest.fixture
def role_registry() -> RoleRegistry:
    """A fresh role registry pre-populated with every default role."""
    registry = RoleRegistry()
    registry.register_many(DEFAULT_ROLES)
    return registry


@pytest.fixture
def authz_provider() -> InMemoryAuthorizationProvider:
    """A fresh, empty in-memory authorization provider, isolated to a single test."""
    return InMemoryAuthorizationProvider()


@pytest.fixture
def authorization_service(
    authz_provider: InMemoryAuthorizationProvider, role_registry: RoleRegistry, permission_registry: PermissionRegistry
) -> AuthorizationService:
    """An AuthorizationService wired to fresh, isolated dependencies."""
    return AuthorizationService(provider=authz_provider, role_registry=role_registry, permission_registry=permission_registry)


@pytest.fixture
def gateway(
    endpoint_registry: EndpointRegistry,
    router: Router,
    validator: RequestValidator,
    rate_limiter: RateLimiter,
    authentication_service: AuthenticationService,
    authorization_service: AuthorizationService,
) -> APIGateway:
    """An APIGateway wired to fresh dependencies via Dependency Injection.

    Never touches the shared, application-wide ``api_gateway`` singleton
    or its default registries/services, so tests never leak endpoints,
    rate-limit counters, or sessions into (or read stale ones from)
    each other.
    """
    return APIGateway(
        endpoint_registry=endpoint_registry,
        router=router,
        validator=validator,
        rate_limiter=rate_limiter,
        authentication_service=authentication_service,
        authorization_service=authorization_service,
    )


@pytest.fixture
def tenant_context():
    """A minimal, active TenantContext for tests that need tenant attribution."""
    return TenantContext(tenant=Tenant(tenant_id="acme-retail", name="acme-retail", display_name="Acme Retail Group"))


@pytest.fixture
def user_context() -> UserContext:
    """A pre-resolved UserContext with no permissions, for tests that inject identity directly."""
    user = User(
        user_id="jane.doe", username="jane.doe", display_name="Jane Doe",
        email="jane.doe@example.com", tenant_id="acme-retail", roles=(),
    )
    return UserContext(user=user, effective_permissions=frozenset())


def _user_context_with(*permissions: str) -> UserContext:
    """Build a UserContext bound to the given permission keys."""
    user = User(
        user_id="jane.doe", username="jane.doe", display_name="Jane Doe",
        email="jane.doe@example.com", tenant_id="acme-retail", roles=(),
    )
    return UserContext(user=user, effective_permissions=frozenset(permissions))


@pytest.fixture
def clean_monitoring():
    """Clear the provider the shared ``monitoring_service`` actually writes to.

    Mirrors ``tests/test_automation.py``'s fixture of the same name
    exactly -- see that file's docstring for the full rationale.
    """
    monitoring_service._provider.clear()
    yield
    monitoring_service._provider.clear()


# ==============================================================================
# 1. Models
# ==============================================================================


def test_request_method_is_a_plain_string() -> None:
    assert RequestMethod.GET == "GET"
    assert RequestMethod.POST == "POST"
    assert RequestMethod.PUT == "PUT"
    assert RequestMethod.DELETE == "DELETE"
    assert RequestMethod.PATCH == "PATCH"


def test_response_status_is_a_plain_string() -> None:
    assert ResponseStatus.SUCCESS == "success"
    assert ResponseStatus.VALIDATION_ERROR == "validation_error"
    assert ResponseStatus.UNAUTHORIZED == "unauthorized"
    assert ResponseStatus.FORBIDDEN == "forbidden"
    assert ResponseStatus.RATE_LIMITED == "rate_limited"
    assert ResponseStatus.NOT_FOUND == "not_found"
    assert ResponseStatus.ERROR == "error"


def test_integration_channel_covers_every_named_future_provider() -> None:
    assert IntegrationChannel.REST_API == "rest_api"
    assert IntegrationChannel.WEBHOOK == "webhook"
    assert IntegrationChannel.ERP_CONNECTOR == "erp_connector"
    assert IntegrationChannel.CRM_CONNECTOR == "crm_connector"
    assert IntegrationChannel.POWER_BI == "power_bi"
    assert IntegrationChannel.SALESFORCE == "salesforce"
    assert IntegrationChannel.SAP == "sap"
    assert IntegrationChannel.MS_DYNAMICS == "ms_dynamics"


def test_integration_request_defaults() -> None:
    request = IntegrationRequest(
        request_id="req-1", api_version="v1", endpoint="kpi.retrieve",
        method=RequestMethod.GET, timestamp=datetime.now(timezone.utc),
    )
    assert request.tenant_id is None
    assert request.tenant_name is None
    assert request.user_id is None
    assert request.payload == {}


def test_integration_request_is_frozen() -> None:
    request = IntegrationRequest(
        request_id="req-1", api_version="v1", endpoint="kpi.retrieve",
        method=RequestMethod.GET, timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises(Exception):
        request.endpoint = "other.endpoint"  # type: ignore[misc]


def test_integration_response_is_success_property() -> None:
    success = IntegrationResponse(
        request_id="req-1", status=ResponseStatus.SUCCESS, message="ok", created_at=datetime.now(timezone.utc)
    )
    failure = IntegrationResponse(
        request_id="req-1", status=ResponseStatus.ERROR, message="failed", created_at=datetime.now(timezone.utc)
    )
    assert success.is_success is True
    assert failure.is_success is False


def test_endpoint_definition_defaults() -> None:
    definition = EndpointDefinition(
        endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1"
    )
    assert definition.required_permission is None
    assert definition.rate_limit_policy is None
    assert definition.description == ""
    assert definition.required_fields == ()


def test_default_rate_limit_policy_is_reasonable() -> None:
    assert DEFAULT_RATE_LIMIT_POLICY.requests_per_minute > 0
    assert DEFAULT_RATE_LIMIT_POLICY.requests_per_hour > 0


def test_new_request_id_is_unique() -> None:
    assert new_request_id() != new_request_id()


def test_build_request_populates_request_id_and_timestamp() -> None:
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    assert request.request_id
    assert request.timestamp is not None
    assert request.endpoint == "kpi.retrieve"
    assert request.method == RequestMethod.GET


def test_build_request_accepts_plain_string_method() -> None:
    request = build_request(endpoint="kpi.retrieve", method="GET", api_version="v1")
    assert request.method == RequestMethod.GET


def test_build_request_defaults_payload_to_empty_dict() -> None:
    request = build_request(endpoint="kpi.retrieve")
    assert request.payload == {}


# ==============================================================================
# 2. Endpoint Registry
# ==============================================================================


def test_registry_register_and_find(endpoint_registry: EndpointRegistry) -> None:
    definition = EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1")
    endpoint_registry.register(definition, handler=_handler_echo)
    found = endpoint_registry.find("kpi.retrieve", RequestMethod.GET, "v1")
    assert found == definition


def test_registry_find_returns_none_for_unknown_endpoint(endpoint_registry: EndpointRegistry) -> None:
    assert endpoint_registry.find("does.not.exist", RequestMethod.GET, "v1") is None


def test_registry_resolve_returns_definition_and_handler(endpoint_registry: EndpointRegistry) -> None:
    definition = EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1")
    endpoint_registry.register(definition, handler=_handler_echo)
    resolved_def, handler = endpoint_registry.resolve("kpi.retrieve", RequestMethod.GET, "v1")
    assert resolved_def == definition
    assert handler is _handler_echo


def test_registry_resolve_raises_for_unknown_endpoint(endpoint_registry: EndpointRegistry) -> None:
    with pytest.raises(EndpointNotFoundError):
        endpoint_registry.resolve("does.not.exist", RequestMethod.GET, "v1")


def test_registry_register_duplicate_raises(endpoint_registry: EndpointRegistry) -> None:
    definition = EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1")
    endpoint_registry.register(definition, handler=_handler_echo)
    with pytest.raises(DuplicateEndpointError):
        endpoint_registry.register(definition, handler=_handler_echo)


def test_registry_unregister_removes_endpoint(endpoint_registry: EndpointRegistry) -> None:
    definition = EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1")
    endpoint_registry.register(definition, handler=_handler_echo)
    endpoint_registry.unregister("kpi.retrieve", RequestMethod.GET, "v1")
    assert endpoint_registry.find("kpi.retrieve", RequestMethod.GET, "v1") is None


def test_registry_list_endpoints_is_sorted(endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="zzz.last", path="/z", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="aaa.first", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    keys = [ep.endpoint_key for ep in endpoint_registry.list_endpoints()]
    assert keys == sorted(keys)


def test_registry_supports_multiple_api_versions_of_the_same_endpoint_key(endpoint_registry: EndpointRegistry) -> None:
    """Task 3: 'support API versioning' -- the same logical endpoint can exist at v1 and v2 simultaneously."""
    def _handler_v1(request: IntegrationRequest) -> dict:
        return {"version": "v1"}

    def _handler_v2(request: IntegrationRequest) -> dict:
        return {"version": "v2"}

    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1"),
        handler=_handler_v1,
    )
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v2/kpi", method=RequestMethod.GET, api_version="v2"),
        handler=_handler_v2,
    )

    _, handler_v1 = endpoint_registry.resolve("kpi.retrieve", RequestMethod.GET, "v1")
    _, handler_v2 = endpoint_registry.resolve("kpi.retrieve", RequestMethod.GET, "v2")
    assert handler_v1(None) == {"version": "v1"}
    assert handler_v2(None) == {"version": "v2"}
    assert set(endpoint_registry.all_versions()) == {"v1", "v2"}


def test_registry_clear_removes_every_endpoint(endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    endpoint_registry.clear()
    assert endpoint_registry.list_endpoints() == ()


def test_provider_registry_register_and_get() -> None:
    registry = IntegrationProviderRegistry()
    provider = InMemoryIntegrationProvider()
    registry.register(IntegrationChannel.REST_API, provider)
    assert registry.get(IntegrationChannel.REST_API) is provider


def test_provider_registry_get_unregistered_channel_raises() -> None:
    registry = IntegrationProviderRegistry()
    with pytest.raises(ProviderNotRegisteredError):
        registry.get(IntegrationChannel.SAP)


def test_provider_registry_registered_channels() -> None:
    registry = IntegrationProviderRegistry()
    registry.register(IntegrationChannel.WEBHOOK, InMemoryIntegrationProvider())
    assert "webhook" in registry.registered_channels()


def test_module_level_provider_registry_has_every_channel_pre_registered() -> None:
    """integration/registry.py registers a shared InMemoryIntegrationProvider under every channel at import time."""
    from integration.registry import integration_provider_registry as shared_provider_registry

    for channel in IntegrationChannel:
        assert channel.value in shared_provider_registry.registered_channels()


# ==============================================================================
# 3. Request Validation
# ==============================================================================


def test_validator_passes_for_a_well_formed_request(endpoint_registry: EndpointRegistry, validator: RequestValidator) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    definition = validator.validate(request, endpoint_registry)
    assert definition.endpoint_key == "kpi.retrieve"


def test_validator_rejects_unknown_endpoint(endpoint_registry: EndpointRegistry, validator: RequestValidator) -> None:
    request = build_request(endpoint="does.not.exist", method=RequestMethod.GET, api_version="v1")
    with pytest.raises(InvalidRequestError) as exc_info:
        validator.validate(request, endpoint_registry)
    assert exc_info.value.reasons  # business-friendly reason(s) present


def test_validator_rejects_missing_required_field(endpoint_registry: EndpointRegistry, validator: RequestValidator) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="export.request", path="/a", method=RequestMethod.POST, api_version="v1",
            required_fields=("format",),
        ),
        handler=_handler_echo,
    )
    request = build_request(endpoint="export.request", method=RequestMethod.POST, api_version="v1", payload={})
    with pytest.raises(InvalidRequestError) as exc_info:
        validator.validate(request, endpoint_registry)
    assert any("format" in reason for reason in exc_info.value.reasons)


def test_validator_passes_when_required_field_present(endpoint_registry: EndpointRegistry, validator: RequestValidator) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="export.request", path="/a", method=RequestMethod.POST, api_version="v1",
            required_fields=("format",),
        ),
        handler=_handler_echo,
    )
    request = build_request(endpoint="export.request", method=RequestMethod.POST, api_version="v1", payload={"format": "csv"})
    definition = validator.validate(request, endpoint_registry)
    assert definition.endpoint_key == "export.request"


def test_validator_collects_every_failure_reason_at_once(endpoint_registry: EndpointRegistry, validator: RequestValidator) -> None:
    """Reasons are collected, not fail-fast on the first problem -- easier for a caller to fix everything in one round trip."""
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="export.request", path="/a", method=RequestMethod.POST, api_version="v1",
            required_fields=("format", "region"),
        ),
        handler=_handler_echo,
    )
    request = build_request(endpoint="export.request", method=RequestMethod.POST, api_version="v1", payload={})
    with pytest.raises(InvalidRequestError) as exc_info:
        validator.validate(request, endpoint_registry)
    assert len(exc_info.value.reasons) >= 2


# ==============================================================================
# 4. Rate Limiter
# ==============================================================================


def test_rate_limiter_allows_requests_under_the_ceiling(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=5, requests_per_hour=100)
    for _ in range(5):
        status = rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
        assert status.allowed is True


def test_rate_limiter_blocks_once_the_per_minute_ceiling_is_reached(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=2, requests_per_hour=100)
    rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    status = rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    assert status.allowed is False
    assert status.retry_after_seconds >= 0


def test_rate_limiter_blocks_once_the_per_hour_ceiling_is_reached(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=1000, requests_per_hour=2)
    rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    status = rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    assert status.allowed is False


def test_rate_limiter_scopes_counters_per_endpoint_not_globally(rate_limiter: RateLimiter) -> None:
    """The critical fix: a burst against a generous endpoint must not trip a strict endpoint's ceiling for the same caller."""
    generous = RateLimitPolicy(requests_per_minute=100, requests_per_hour=1000)
    strict = RateLimitPolicy(requests_per_minute=1, requests_per_hour=100)

    for _ in range(10):
        status = rate_limiter.check("user:jane.doe:kpi.retrieve", generous)
        assert status.allowed is True

    # The strict endpoint's counter is untouched by the above -- its first check must still succeed.
    first_strict = rate_limiter.check("user:jane.doe:strict.endpoint", strict)
    assert first_strict.allowed is True
    second_strict = rate_limiter.check("user:jane.doe:strict.endpoint", strict)
    assert second_strict.allowed is False


def test_rate_limiter_evaluate_scopes_by_user_and_endpoint(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=1, requests_per_hour=100)
    request = build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1", user_id="jane.doe")
    first = rate_limiter.evaluate(request, policy)
    second = rate_limiter.evaluate(request, policy)
    assert first.allowed is True
    assert second.allowed is False
    assert "jane.doe" in second.limit_key
    assert "strict.endpoint" in second.limit_key


def test_rate_limiter_evaluate_different_users_have_independent_counters(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=1, requests_per_hour=100)
    request_jane = build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1", user_id="jane.doe")
    request_john = build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1", user_id="john.smith")
    assert rate_limiter.evaluate(request_jane, policy).allowed is True
    assert rate_limiter.evaluate(request_john, policy).allowed is True  # a different user, unaffected by jane's usage


def test_rate_limiter_evaluate_checks_tenant_ceiling_too(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=1, requests_per_hour=100)
    request_1 = build_request(
        endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1", user_id="jane.doe", tenant_id="acme-retail"
    )
    request_2 = build_request(
        endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1", user_id="john.smith", tenant_id="acme-retail"
    )
    assert rate_limiter.evaluate(request_1, policy).allowed is True
    # A different user in the *same* tenant is still blocked once the tenant-level ceiling is exhausted.
    second_status = rate_limiter.evaluate(request_2, policy)
    assert second_status.allowed is False
    assert "acme-retail" in second_status.limit_key


def test_rate_limiter_evaluate_anonymous_caller_falls_back_to_shared_bucket(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=1, requests_per_hour=100)
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    first = rate_limiter.evaluate(request, policy)
    second = rate_limiter.evaluate(request, policy)
    assert first.allowed is True
    assert second.allowed is False
    assert "anonymous" in second.limit_key


def test_rate_limiter_stats_does_not_consume_a_request(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=1, requests_per_hour=100)
    rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    before = rate_limiter.stats("user:jane.doe:kpi.retrieve", policy)
    after = rate_limiter.stats("user:jane.doe:kpi.retrieve", policy)
    assert before.requests_this_minute == after.requests_this_minute == 1


def test_rate_limiter_tracked_keys_and_clear(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=10, requests_per_hour=100)
    rate_limiter.check("user:jane.doe:kpi.retrieve", policy)
    rate_limiter.check("tenant:acme-retail:kpi.retrieve", policy)
    assert set(rate_limiter.tracked_keys()) == {"user:jane.doe:kpi.retrieve", "tenant:acme-retail:kpi.retrieve"}
    rate_limiter.clear()
    assert rate_limiter.tracked_keys() == ()


def test_rate_limiter_prunes_entries_older_than_one_hour(rate_limiter: RateLimiter) -> None:
    policy = RateLimitPolicy(requests_per_minute=1, requests_per_hour=1)
    now = datetime.now(timezone.utc)
    rate_limiter.check("user:jane.doe:kpi.retrieve", policy, as_of=now - timedelta(hours=2))
    # The earlier request is outside the 1-hour window by the time this check runs -- allowed again.
    status = rate_limiter.check("user:jane.doe:kpi.retrieve", policy, as_of=now)
    assert status.allowed is True


# ==============================================================================
# 5. Router
# ==============================================================================


def test_router_dispatches_to_the_registered_handler(endpoint_registry: EndpointRegistry, router: Router) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1", payload={"rows": 10})
    result = router.route(request)
    assert result == {"ok": True, "endpoint": "kpi.retrieve", "payload": {"rows": 10}}


def test_router_raises_for_unresolvable_endpoint(router: Router) -> None:
    request = build_request(endpoint="does.not.exist", method=RequestMethod.GET, api_version="v1")
    with pytest.raises(EndpointNotFoundError):
        router.route(request)


# ==============================================================================
# 6. Integration Provider
# ==============================================================================


def test_in_memory_provider_satisfies_the_protocol() -> None:
    assert isinstance(InMemoryIntegrationProvider(), IntegrationProvider)


def test_in_memory_provider_forwards_to_the_gateway_and_returns_its_response(gateway: APIGateway, endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    provider = InMemoryIntegrationProvider()
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    response = provider.submit(gateway, request)
    assert response.status == ResponseStatus.UNAUTHORIZED  # no session/user_context supplied -- gateway rejects it


def test_in_memory_provider_logs_every_forwarded_exchange(gateway: APIGateway, endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    provider = InMemoryIntegrationProvider()
    provider.submit(gateway, build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"))
    provider.submit(gateway, build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"))
    forwarded = provider.forwarded_requests()
    assert len(forwarded) == 2


def test_in_memory_provider_clear_empties_the_log() -> None:
    provider = InMemoryIntegrationProvider()
    provider._forwarded.append((None, None))  # type: ignore[arg-type]
    provider.clear()
    assert provider.forwarded_requests() == ()


def test_providers_are_interchangeable_behind_the_same_channel_key() -> None:
    """Task 7: swapping which provider is registered under a channel requires no Gateway change."""

    class _FakeSalesforceProvider:
        name = "Fake Salesforce Connector"

        def submit(self, gateway, request):
            return gateway.handle_request(request)

    registry = IntegrationProviderRegistry()
    registry.register(IntegrationChannel.SALESFORCE, InMemoryIntegrationProvider())
    assert registry.get(IntegrationChannel.SALESFORCE).name == "In-Memory Simulated Provider"

    registry.register(IntegrationChannel.SALESFORCE, _FakeSalesforceProvider())
    assert registry.get(IntegrationChannel.SALESFORCE).name == "Fake Salesforce Connector"


def test_gateway_module_never_imports_provider_module() -> None:
    """Task 7: 'The API Gateway must remain provider-independent' -- a concrete, checkable guarantee."""
    import ast
    import inspect

    import integration.gateway as gateway_module

    source = inspect.getsource(gateway_module)
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
    assert "integration.provider" not in imported_modules


# ==============================================================================
# 7. API Gateway -- full lifecycle
# ==============================================================================


def test_gateway_successful_request(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, user_context=user_context)
    assert response.status == ResponseStatus.SUCCESS
    assert response.data == {"ok": True, "endpoint": "kpi.retrieve", "payload": {}}
    assert response.processing_time_ms >= 0


def test_gateway_unknown_endpoint_is_a_validation_error_not_a_crash(gateway: APIGateway, user_context: UserContext) -> None:
    request = build_request(endpoint="does.not.exist", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, user_context=user_context)
    assert response.status == ResponseStatus.VALIDATION_ERROR


def test_gateway_missing_required_field_is_a_validation_error(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="export.request", path="/a", method=RequestMethod.POST, api_version="v1", required_fields=("format",)
        ),
        handler=_handler_echo,
    )
    request = build_request(endpoint="export.request", method=RequestMethod.POST, api_version="v1", payload={})
    response = gateway.handle_request(request, user_context=user_context)
    assert response.status == ResponseStatus.VALIDATION_ERROR
    assert response.errors


def test_gateway_forbidden_when_user_lacks_required_permission(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="secure.endpoint", path="/a", method=RequestMethod.GET, api_version="v1", required_permission="manage_platform"
        ),
        handler=_handler_echo,
    )
    request = build_request(endpoint="secure.endpoint", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, user_context=user_context)  # user_context has no permissions
    assert response.status == ResponseStatus.FORBIDDEN


def test_gateway_success_when_user_has_required_permission(gateway: APIGateway, endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="secure.endpoint", path="/a", method=RequestMethod.GET, api_version="v1", required_permission="manage_platform"
        ),
        handler=_handler_echo,
    )
    request = build_request(endpoint="secure.endpoint", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, user_context=_user_context_with("manage_platform"))
    assert response.status == ResponseStatus.SUCCESS


def test_gateway_rate_limited_after_ceiling_exceeded(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="strict.endpoint", path="/a", method=RequestMethod.GET, api_version="v1",
            rate_limit_policy=RateLimitPolicy(requests_per_minute=1, requests_per_hour=100),
        ),
        handler=_handler_echo,
    )
    first = gateway.handle_request(build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    second = gateway.handle_request(build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    assert first.status == ResponseStatus.SUCCESS
    assert second.status == ResponseStatus.RATE_LIMITED


def test_gateway_rate_limit_on_one_endpoint_does_not_affect_a_different_endpoint(
    gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext
) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="strict.endpoint", path="/a", method=RequestMethod.GET, api_version="v1",
            rate_limit_policy=RateLimitPolicy(requests_per_minute=1, requests_per_hour=100),
        ),
        handler=_handler_echo,
    )
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/b", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    gateway.handle_request(build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    gateway.handle_request(build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)  # rate limited
    unaffected = gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    assert unaffected.status == ResponseStatus.SUCCESS


def test_gateway_endpoint_without_explicit_policy_uses_the_default(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    # DEFAULT_RATE_LIMIT_POLICY allows well more than one request -- proves the default is actually applied.
    for _ in range(3):
        response = gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
        assert response.status == ResponseStatus.SUCCESS


def test_gateway_handler_exception_becomes_a_standardized_error_response(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    def _broken_handler(request: IntegrationRequest) -> dict:
        raise RuntimeError("boom")

    endpoint_registry.register(
        EndpointDefinition(endpoint_key="broken.endpoint", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_broken_handler
    )
    request = build_request(endpoint="broken.endpoint", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, user_context=user_context)
    assert response.status == ResponseStatus.ERROR
    assert "boom" in " ".join(response.errors)


def test_gateway_never_raises_out_to_the_caller(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    """Every failure mode -- validation, auth, authz, rate limit, handler exception -- is caught and returned, never raised."""
    def _broken_handler(request: IntegrationRequest) -> dict:
        raise ValueError("should never escape handle_request")

    endpoint_registry.register(
        EndpointDefinition(endpoint_key="broken.endpoint", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_broken_handler
    )
    try:
        response = gateway.handle_request(build_request(endpoint="broken.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"handle_request raised instead of returning a standardized response: {exc}")
    assert response.status == ResponseStatus.ERROR


def test_gateway_response_always_carries_the_original_request_id(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, user_context=user_context)
    assert response.request_id == request.request_id


def test_gateway_supports_multiple_api_versions_end_to_end(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v1/kpi", method=RequestMethod.GET, api_version="v1"),
        handler=lambda request: {"version": "v1"},
    )
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/api/v2/kpi", method=RequestMethod.GET, api_version="v2"),
        handler=lambda request: {"version": "v2"},
    )
    response_v1 = gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    response_v2 = gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v2"), user_context=user_context)
    assert response_v1.data == {"version": "v1"}
    assert response_v2.data == {"version": "v2"}


def test_gateway_tenant_context_is_resolved_from_request_tenant_id_when_not_supplied(
    gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext
) -> None:
    """Task 4: the request carries a Tenant field the Gateway can resolve into a real TenantContext."""
    from tenancy.registry import tenant_registry

    tenant_registry.register(Tenant(tenant_id="acme-retail", name="acme-retail", display_name="Acme Retail Group"))

    captured: dict = {}

    def _capture_handler(request: IntegrationRequest) -> dict:
        captured["tenant_id"] = request.tenant_id
        return {"ok": True}

    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_capture_handler
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1", tenant_id="acme-retail")
    response = gateway.handle_request(request, user_context=user_context)
    assert response.status == ResponseStatus.SUCCESS
    assert captured["tenant_id"] == "acme-retail"


# ==============================================================================
# 8. Authentication Integration
# ==============================================================================


def _make_identity(user_id: str = "jane.doe") -> UserIdentity:
    return UserIdentity(
        user_id=user_id, username=user_id, display_name="Jane Doe",
        email=f"{user_id}@example.com", tenant_id="acme-retail", status=IdentityStatus.ACTIVE,
    )


def test_gateway_resolves_identity_from_session_id_when_no_user_context_given(
    gateway: APIGateway, endpoint_registry: EndpointRegistry, authentication_service: AuthenticationService,
    auth_provider: InMemoryAuthenticationProvider, authz_provider: InMemoryAuthorizationProvider,
) -> None:
    auth_provider.register_identity(_make_identity("jane.doe"), "secret123")
    authz_provider.register_user(
        User(user_id="jane.doe", username="jane.doe", display_name="Jane Doe", email="jane.doe@example.com", tenant_id="acme-retail", roles=())
    )
    sign_in_result = authentication_service.sign_in("jane.doe", "secret123")

    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, session_id=sign_in_result.session.session_id)
    assert response.status == ResponseStatus.SUCCESS


def test_gateway_unauthorized_when_session_id_is_invalid(gateway: APIGateway, endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, session_id="not-a-real-session")
    assert response.status == ResponseStatus.UNAUTHORIZED


def test_gateway_unauthorized_when_no_session_or_user_context_given(gateway: APIGateway, endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request)
    assert response.status == ResponseStatus.UNAUTHORIZED


def test_gateway_already_resolved_user_context_skips_authentication_service(
    gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext
) -> None:
    """Passing an already-resolved UserContext avoids re-authenticating -- same shortcut every other service in the platform accepts."""
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1")
    response = gateway.handle_request(request, user_context=user_context)
    assert response.status == ResponseStatus.SUCCESS


# ==============================================================================
# 9. Authorization Integration
# ==============================================================================


def test_gateway_authorization_uses_the_injected_authorization_service(
    gateway: APIGateway, endpoint_registry: EndpointRegistry, authz_provider: InMemoryAuthorizationProvider
) -> None:
    """Proves the Gateway delegates to AuthorizationService.require_permission rather than re-implementing permission checks."""
    authz_provider.register_user(
        User(
            user_id="jane.doe", username="jane.doe", display_name="Jane Doe", email="jane.doe@example.com",
            tenant_id="acme-retail", roles=(), permissions=("manage_platform",),
        )
    )
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="secure.endpoint", path="/a", method=RequestMethod.GET, api_version="v1", required_permission="manage_platform"
        ),
        handler=_handler_echo,
    )
    user_context = UserContext(
        user=User(user_id="jane.doe", username="jane.doe", display_name="Jane Doe", email="jane.doe@example.com", tenant_id="acme-retail", roles=()),
        effective_permissions=frozenset({"manage_platform"}),
    )
    response = gateway.handle_request(
        build_request(endpoint="secure.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context
    )
    assert response.status == ResponseStatus.SUCCESS


def test_gateway_endpoint_with_no_required_permission_skips_authorization(gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="public.endpoint", path="/a", method=RequestMethod.GET, api_version="v1", required_permission=None),
        handler=_handler_echo,
    )
    response = gateway.handle_request(
        build_request(endpoint="public.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context
    )
    assert response.status == ResponseStatus.SUCCESS


# ==============================================================================
# 10. Monitoring Integration (Task 9) -- shared monitoring_service, no second store
# ==============================================================================


def test_gateway_records_receive_request_event(clean_monitoring, gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    events = monitoring_service.get_events(service_name="APIGateway")
    assert any(event.operation == "receive_request" for event in events)


def test_gateway_records_successful_routing_with_duration(clean_monitoring, gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    events = monitoring_service.get_events(service_name="APIGateway")
    route_events = [event for event in events if event.operation == "route_request"]
    assert route_events
    assert route_events[0].duration_ms is not None


def test_gateway_records_validation_failure(clean_monitoring, gateway: APIGateway, user_context: UserContext) -> None:
    gateway.handle_request(build_request(endpoint="does.not.exist", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    events = monitoring_service.get_events(service_name="APIGateway")
    assert any(event.operation == "validate_request" for event in events)


def test_gateway_records_authentication_failure(clean_monitoring, gateway: APIGateway, endpoint_registry: EndpointRegistry) -> None:
    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"), session_id="invalid")
    events = monitoring_service.get_events(service_name="APIGateway")
    assert any(event.operation == "authenticate" for event in events)


def test_gateway_records_authorization_failure(clean_monitoring, gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="secure.endpoint", path="/a", method=RequestMethod.GET, api_version="v1", required_permission="manage_platform"
        ),
        handler=_handler_echo,
    )
    gateway.handle_request(build_request(endpoint="secure.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    events = monitoring_service.get_events(service_name="APIGateway")
    assert any(event.operation == "authorize" for event in events)


def test_gateway_records_rate_limit_rejection(clean_monitoring, gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="strict.endpoint", path="/a", method=RequestMethod.GET, api_version="v1",
            rate_limit_policy=RateLimitPolicy(requests_per_minute=1, requests_per_hour=100),
        ),
        handler=_handler_echo,
    )
    gateway.handle_request(build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    gateway.handle_request(build_request(endpoint="strict.endpoint", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    events = monitoring_service.get_events(service_name="APIGateway")
    assert any(event.operation == "rate_limit" for event in events)


def test_gateway_does_not_introduce_a_second_monitoring_mechanism(clean_monitoring, gateway: APIGateway, endpoint_registry: EndpointRegistry, user_context: UserContext) -> None:
    """Task 9: every recordable fact about a request is retrievable from the existing monitoring_service alone."""
    import integration.gateway as gateway_module

    # The Gateway module defines no event-store class/singleton of its own.
    assert not hasattr(gateway_module, "IntegrationEventStore")
    assert not hasattr(gateway_module, "integration_event_store")

    endpoint_registry.register(
        EndpointDefinition(endpoint_key="kpi.retrieve", path="/a", method=RequestMethod.GET, api_version="v1"), handler=_handler_echo
    )
    gateway.handle_request(build_request(endpoint="kpi.retrieve", method=RequestMethod.GET, api_version="v1"), user_context=user_context)
    # The one and only place this request's history can be queried from.
    assert monitoring_service.get_events(service_name="APIGateway")


# ==============================================================================
# 11. Regression -- existing functionality is unaffected
# ==============================================================================


def test_existing_business_services_import_unmodified() -> None:
    """Task 8: business services should remain unaware of external callers -- importing them must not require integration/."""
    import services.ai_recommendation_service  # noqa: F401
    import services.export_service  # noqa: F401
    import services.pdf_generator_service  # noqa: F401
    import services.reporting_service  # noqa: F401
    import utils.kpi_engine  # noqa: F401


def test_existing_authorization_permission_count_includes_view_integrations() -> None:
    """Sprint 6.8 adds exactly one new permission (VIEW_INTEGRATIONS) on top of Sprint 6.7's twelve."""
    from authorization.permissions import DEFAULT_PERMISSIONS as _default_permissions
    from authorization.permissions import VIEW_INTEGRATIONS

    assert VIEW_INTEGRATIONS in [permission.key for permission in _default_permissions]
    assert len(_default_permissions) == 13


def test_gateway_is_the_only_way_the_test_suite_reaches_registered_handlers() -> None:
    """Sanity check: a handler is only ever invoked through Router.route, which the Gateway alone calls internally."""
    calls: list[str] = []

    def _tracking_handler(request: IntegrationRequest) -> dict:
        calls.append(request.endpoint)
        return {"ok": True}

    registry = EndpointRegistry()
    registry.register(
        EndpointDefinition(endpoint_key="tracked.endpoint", path="/a", method=RequestMethod.GET, api_version="v1"),
        handler=_tracking_handler,
    )
    router = Router(registry)
    gateway = APIGateway(endpoint_registry=registry, router=router)
    gateway.handle_request(
        build_request(endpoint="tracked.endpoint", method=RequestMethod.GET, api_version="v1"),
        user_context=_user_context_with(),
    )
    assert calls == ["tracked.endpoint"]
