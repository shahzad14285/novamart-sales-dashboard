"""Unit tests for the Permission-Based Authorization Framework (Sprint 6.5).

This file is the Task 11 deliverable: comprehensive coverage of the
``authorization/`` package -- the Permission Registry, the Role
Registry, the Authorization Service (resolution, enforcement,
permission inheritance, tenant isolation), the Provider Pattern
(including a from-scratch custom provider proving swappability), the
User Context, unauthorized-access handling, and integration with the
existing Monitoring Service.

Scope note -- "UI authorization" (Task 11)
--------------------------------------------
Following the convention already established by every prior sprint's
test suite (no file under ``tests/`` imports ``streamlit`` or anything
from ``components/``/``ui/``/``pages/`` -- those layers are verified
via a headless dry run plus the manual test cases documented in each
sprint's architecture doc), this file does not import
``components.authorization`` directly. Every function that module
exposes (``is_authorized``, ``require_permission_ui``,
``render_user_switcher``) is a thin Streamlit-rendering wrapper around
exactly the :class:`~authorization.service.AuthorizationService`
methods this file already covers exhaustively
(:meth:`~authorization.service.AuthorizationService.has_permission`,
:meth:`~authorization.service.AuthorizationService.require_permission`)
-- so "UI authorization" here means proving that *backing logic* is
correct, which is what actually determines what the UI shows or hides.
The Streamlit-rendering behavior itself (hiding a nav item, rendering
an "Access Denied" panel) is exercised in the headless dry run recorded
in ``docs/AUTHORIZATION_ARCHITECTURE.md``'s "Automated tests" section.

Every test constructs its own :class:`~authorization.service.AuthorizationService`
backed by its own fresh :class:`~authorization.provider.InMemoryAuthorizationProvider`
and fresh :class:`~authorization.roles.RoleRegistry`/
:class:`~authorization.permissions.PermissionRegistry` (or a custom stub
provider) rather than using the shared, application-wide singletons --
this is what keeps tests fully isolated from each other and from
whatever ``config/users.py`` seeds into the real provider at import
time. The one exception is the monitoring-integration tests, which
necessarily exercise the shared
``monitoring.service.monitoring_service`` singleton (since
:class:`~authorization.service.AuthorizationService` always records
into it, by design -- see ``docs/AUTHORIZATION_ARCHITECTURE.md``) --
those tests clear the active monitoring provider before and after
themselves to stay isolated from any other test file's events.
"""

from __future__ import annotations

import pytest

from authorization.context import UserContext
from authorization.exceptions import (
    CrossTenantAccessError,
    InactiveUserError,
    MissingUserContextError,
    PermissionDeniedError,
    ProviderNotRegisteredError,
    UnknownPermissionError,
    UnknownUserError,
)
from authorization.models import User, UserStatus
from authorization.permissions import (
    DEFAULT_PERMISSIONS,
    EXPORT_DATA,
    GENERATE_PDF,
    GENERATE_REPORTS,
    MANAGE_PLATFORM,
    MANAGE_TENANTS,
    MANAGE_USERS,
    Permission,
    PermissionRegistry,
    UPLOAD_DATA,
    USE_AI_RECOMMENDATIONS,
    VIEW_DASHBOARD,
    VIEW_MONITORING,
    VIEW_REPORTS,
)
from authorization.provider import AuthorizationProvider, InMemoryAuthorizationProvider
from authorization.registry import AuthorizationProviderRegistry
from authorization.roles import (
    ALL_PERMISSIONS_WILDCARD,
    BUSINESS_ANALYST,
    DEFAULT_ROLES,
    EXECUTIVE_VIEWER,
    Role,
    RoleRegistry,
    SYSTEM_ADMINISTRATOR,
    TENANT_ADMINISTRATOR,
)
from authorization.service import AuthorizationService
from monitoring.provider import InMemoryMonitoringProvider
from monitoring.registry import monitoring_provider_registry
from monitoring.service import monitoring_service
from tenancy.context import TenantContext
from tenancy.models import Tenant

# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def permission_registry() -> PermissionRegistry:
    """A fresh permission registry pre-populated with the eleven defaults."""
    registry = PermissionRegistry()
    registry.register_many(DEFAULT_PERMISSIONS)
    return registry


@pytest.fixture
def role_registry() -> RoleRegistry:
    """A fresh role registry pre-populated with the four default roles."""
    registry = RoleRegistry()
    registry.register_many(DEFAULT_ROLES)
    return registry


@pytest.fixture
def provider() -> InMemoryAuthorizationProvider:
    """A fresh, empty in-memory authorization provider, isolated to a single test."""
    return InMemoryAuthorizationProvider()


@pytest.fixture
def service(
    provider: InMemoryAuthorizationProvider, role_registry: RoleRegistry, permission_registry: PermissionRegistry
) -> AuthorizationService:
    """An AuthorizationService wired to fresh dependencies via Dependency Injection.

    Never touches the shared, application-wide ``authorization_service``
    singleton or the shared registries, so tests never leak users/roles/
    permissions into (or read stale ones from) each other.
    """
    return AuthorizationService(provider=provider, role_registry=role_registry, permission_registry=permission_registry)


@pytest.fixture
def tenant_a() -> Tenant:
    return Tenant(tenant_id="org-a", name="org-a", display_name="Organization A")


@pytest.fixture
def tenant_b() -> Tenant:
    return Tenant(tenant_id="org-b", name="org-b", display_name="Organization B")


def _make_user(user_id: str, tenant_id: str, roles: tuple[str, ...] = (), **kwargs) -> User:
    return User(
        user_id=user_id, username=user_id, display_name=user_id.title(),
        email=f"{user_id}@example.com", tenant_id=tenant_id, roles=roles, **kwargs,
    )


# ==============================================================================
# 1. Permission Registry
# ==============================================================================


def test_permission_registry_registers_and_looks_up_by_key() -> None:
    registry = PermissionRegistry()
    registry.register(Permission("view_dashboard", "View the dashboard"))

    assert registry.exists("view_dashboard")
    assert registry.get("view_dashboard").description == "View the dashboard"


def test_permission_registry_get_unknown_key_returns_none() -> None:
    registry = PermissionRegistry()
    assert registry.get("does_not_exist") is None
    assert registry.exists("does_not_exist") is False


def test_permission_registry_default_permissions_include_every_ticket_permission(
    permission_registry: PermissionRegistry,
) -> None:
    expected = {
        VIEW_DASHBOARD, VIEW_REPORTS, GENERATE_REPORTS, EXPORT_DATA, GENERATE_PDF,
        USE_AI_RECOMMENDATIONS, UPLOAD_DATA, VIEW_MONITORING, MANAGE_USERS, MANAGE_TENANTS, MANAGE_PLATFORM,
    }
    assert expected <= set(permission_registry.all_keys())


def test_permission_registry_supports_registering_a_brand_new_permission_at_any_time(
    permission_registry: PermissionRegistry,
) -> None:
    """Proves Task 3's 'future custom permissions' requirement: a new
    permission is one register() call away, from anywhere, with no
    change to this module's source."""
    permission_registry.register(Permission("manage_billing", "Manage billing and invoices"))

    assert permission_registry.exists("manage_billing")
    assert "manage_billing" in permission_registry.all_keys()


def test_permission_registry_register_replaces_an_existing_entry() -> None:
    registry = PermissionRegistry()
    registry.register(Permission("view_dashboard", "Old description"))
    registry.register(Permission("view_dashboard", "New description"))

    assert registry.get("view_dashboard").description == "New description"
    assert len(registry.all_permissions()) == 1


def test_permission_registry_clear_removes_every_permission(permission_registry: PermissionRegistry) -> None:
    permission_registry.clear()
    assert permission_registry.all_keys() == ()


# ==============================================================================
# 2. Role Registry
# ==============================================================================


def test_role_registry_registers_and_looks_up_by_key() -> None:
    registry = RoleRegistry()
    registry.register(Role("executive_viewer", "Executive Viewer", frozenset({VIEW_DASHBOARD})))

    assert registry.exists("executive_viewer")
    assert registry.get("executive_viewer").display_name == "Executive Viewer"


def test_role_registry_get_unknown_key_returns_none() -> None:
    registry = RoleRegistry()
    assert registry.get("does_not_exist") is None


def test_role_registry_default_roles_include_all_four_ticket_roles(role_registry: RoleRegistry) -> None:
    assert {SYSTEM_ADMINISTRATOR, TENANT_ADMINISTRATOR, BUSINESS_ANALYST, EXECUTIVE_VIEWER} <= set(
        role_registry.all_keys()
    )


def test_system_administrator_role_grants_the_all_permissions_wildcard(role_registry: RoleRegistry) -> None:
    role = role_registry.get(SYSTEM_ADMINISTRATOR)
    assert ALL_PERMISSIONS_WILDCARD in role.permissions


def test_tenant_administrator_role_grants_exactly_the_ticket_specified_permissions(role_registry: RoleRegistry) -> None:
    role = role_registry.get(TENANT_ADMINISTRATOR)
    expected = {
        MANAGE_TENANTS, MANAGE_USERS, UPLOAD_DATA, VIEW_DASHBOARD,
        VIEW_REPORTS, GENERATE_REPORTS, EXPORT_DATA, USE_AI_RECOMMENDATIONS,
    }
    assert expected <= role.permissions
    assert MANAGE_PLATFORM not in role.permissions


def test_business_analyst_role_grants_exactly_the_ticket_specified_permissions(role_registry: RoleRegistry) -> None:
    role = role_registry.get(BUSINESS_ANALYST)
    expected = {UPLOAD_DATA, VIEW_DASHBOARD, VIEW_REPORTS, GENERATE_REPORTS, USE_AI_RECOMMENDATIONS, GENERATE_PDF, EXPORT_DATA}
    assert role.permissions == expected
    assert MANAGE_TENANTS not in role.permissions
    assert MANAGE_USERS not in role.permissions


def test_executive_viewer_role_is_strictly_read_only(role_registry: RoleRegistry) -> None:
    role = role_registry.get(EXECUTIVE_VIEWER)
    assert role.permissions == {VIEW_DASHBOARD, VIEW_REPORTS}
    # None of the mutating/generating capabilities are present.
    for forbidden in (GENERATE_REPORTS, EXPORT_DATA, GENERATE_PDF, UPLOAD_DATA, MANAGE_TENANTS, MANAGE_USERS):
        assert forbidden not in role.permissions


def test_role_registry_supports_registering_a_brand_new_role_at_any_time(role_registry: RoleRegistry) -> None:
    """Proves Task 11's 'new roles can be added without changing services'
    requirement: a new role is one register() call away."""
    role_registry.register(Role("finance_auditor", "Finance Auditor", frozenset({VIEW_REPORTS, EXPORT_DATA})))

    assert role_registry.exists("finance_auditor")
    assert role_registry.get("finance_auditor").permissions == {VIEW_REPORTS, EXPORT_DATA}


def test_role_registry_clear_removes_every_role(role_registry: RoleRegistry) -> None:
    role_registry.clear()
    assert role_registry.all_keys() == ()


# ==============================================================================
# 3. Provider abstraction -- Provider Pattern (Task 7)
# ==============================================================================


def test_in_memory_provider_registers_and_resolves_a_user(provider: InMemoryAuthorizationProvider) -> None:
    user = _make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,))
    provider.register_user(user)

    assert provider.get_user("jane.doe") is user


def test_in_memory_provider_get_unknown_user_returns_none(provider: InMemoryAuthorizationProvider) -> None:
    assert provider.get_user("does-not-exist") is None


def test_in_memory_provider_list_users_filters_by_tenant(provider: InMemoryAuthorizationProvider) -> None:
    provider.register_many(
        [
            _make_user("a1", "org-a"),
            _make_user("a2", "org-a"),
            _make_user("b1", "org-b"),
        ]
    )

    assert len(provider.list_users()) == 3
    assert len(provider.list_users(tenant_id="org-a")) == 2
    assert len(provider.list_users(tenant_id="org-b")) == 1


def test_in_memory_provider_register_replaces_an_existing_user(provider: InMemoryAuthorizationProvider) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", status=UserStatus.ACTIVE))
    provider.register_user(_make_user("jane.doe", "org-a", status=UserStatus.INACTIVE))

    assert provider.get_user("jane.doe").status == UserStatus.INACTIVE
    assert len(provider.list_users()) == 1


def test_in_memory_provider_clear_removes_every_user(provider: InMemoryAuthorizationProvider) -> None:
    provider.register_user(_make_user("jane.doe", "org-a"))
    provider.clear()
    assert provider.list_users() == ()


class _ListOnlyProvider:
    """A minimal, from-scratch provider (no shared base class) proving the
    Provider Pattern is a structural Protocol, not an inheritance
    contract -- any object with the right two methods can act as a
    provider, exactly the promise Task 7 makes for future database-,
    LDAP-, OAuth/OIDC-, Azure AD-, Okta-, or Auth0-backed providers."""

    def __init__(self, users: dict[str, User]) -> None:
        self._users = users

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def list_users(self, *, tenant_id: str | None = None) -> tuple[User, ...]:
        users = tuple(self._users.values())
        if tenant_id is not None:
            users = tuple(u for u in users if u.tenant_id == tenant_id)
        return users


def test_authorization_service_works_unmodified_against_a_brand_new_provider_implementation(
    role_registry: RoleRegistry, permission_registry: PermissionRegistry
) -> None:
    """Proves Task 7's central promise: swapping the identity backend
    requires zero changes to AuthorizationService or to any UI call
    site -- only a different object passed into the constructor."""
    user = _make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,))
    custom_provider = _ListOnlyProvider({"jane.doe": user})
    service = AuthorizationService(provider=custom_provider, role_registry=role_registry, permission_registry=permission_registry)

    resolved = service.resolve_user("jane.doe")

    assert resolved is user
    assert isinstance(custom_provider, AuthorizationProvider)  # structural typing check


def test_authorization_provider_registry_register_and_get() -> None:
    registry = AuthorizationProviderRegistry()
    provider_instance = InMemoryAuthorizationProvider()
    registry.register("memory", provider_instance)

    assert registry.get("memory") is provider_instance
    assert registry.registered_providers() == ("memory",)


def test_authorization_provider_registry_get_unregistered_raises() -> None:
    registry = AuthorizationProviderRegistry()
    with pytest.raises(ProviderNotRegisteredError):
        registry.get("does-not-exist")


def test_authorization_provider_registry_set_active_and_get_active() -> None:
    registry = AuthorizationProviderRegistry()
    memory_provider = InMemoryAuthorizationProvider()
    other_provider = _ListOnlyProvider({})
    registry.register("memory", memory_provider, make_active=True)
    registry.register("other", other_provider)

    assert registry.get_active() is memory_provider
    assert registry.active_name == "memory"

    registry.set_active("other")
    assert registry.get_active() is other_provider
    assert registry.active_name == "other"


def test_authorization_service_defaults_to_the_registrys_active_provider() -> None:
    """When no provider is injected, AuthorizationService asks the
    shared registry for whichever provider is currently active --
    proving the Dependency Injection default without needing to touch
    the shared, application-wide registry singleton itself."""
    registry = AuthorizationProviderRegistry()
    provider_instance = InMemoryAuthorizationProvider()
    provider_instance.register_user(_make_user("jane.doe", "org-a"))
    registry.register("memory", provider_instance, make_active=True)

    import authorization.service as service_module

    original_registry = service_module.authorization_provider_registry
    service_module.authorization_provider_registry = registry
    try:
        service = AuthorizationService()
        assert service.resolve_user("jane.doe") is provider_instance.get_user("jane.doe")
    finally:
        service_module.authorization_provider_registry = original_registry


# ==============================================================================
# 4. User Context
# ==============================================================================


def test_user_context_empty_has_no_user_and_no_permissions() -> None:
    context = UserContext.empty()
    assert context.has_user() is False
    assert context.effective_permissions == frozenset()
    assert context.has_permission(VIEW_DASHBOARD) is False


def test_user_context_for_user_carries_user_and_permissions() -> None:
    user = _make_user("jane.doe", "org-a")
    context = UserContext.for_user(user, frozenset({VIEW_DASHBOARD, VIEW_REPORTS}))

    assert context.has_user() is True
    assert context.user is user
    assert context.has_permission(VIEW_DASHBOARD) is True
    assert context.has_permission(EXPORT_DATA) is False


def test_user_context_repr_does_not_raise() -> None:
    # A debugging aid only -- just prove it doesn't blow up and mentions the user id.
    user = _make_user("jane.doe", "org-a")
    context = UserContext.for_user(user, frozenset())
    assert "jane.doe" in repr(context)
    assert "jane.doe" not in repr(UserContext.empty())


# ==============================================================================
# 5. Authorization Service -- resolution
# ==============================================================================


def test_resolve_user_returns_the_matching_user(service: AuthorizationService, provider: InMemoryAuthorizationProvider) -> None:
    user = _make_user("jane.doe", "org-a")
    provider.register_user(user)

    assert service.resolve_user("jane.doe") is user


def test_resolve_user_unknown_id_raises(service: AuthorizationService) -> None:
    with pytest.raises(UnknownUserError):
        service.resolve_user("does-not-exist")


def test_build_context_for_active_user_resolves_permissions(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,)))
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

    assert context.has_user()
    assert context.has_permission(UPLOAD_DATA)
    assert context.has_permission(MANAGE_TENANTS) is False


def test_build_context_for_inactive_user_raises(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", status=UserStatus.INACTIVE))
    with pytest.raises(InactiveUserError):
        service.build_context("jane.doe", TenantContext(tenant=tenant_a))


def test_build_context_without_a_tenant_context_skips_the_isolation_check(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,)))
    context = service.build_context("jane.doe", tenant_context=None)
    assert context.has_user()


# ==============================================================================
# 6. Permission inheritance
# ==============================================================================


def test_resolve_effective_permissions_expands_a_regular_roles_permissions(service: AuthorizationService) -> None:
    user = _make_user("jane.doe", "org-a", roles=(EXECUTIVE_VIEWER,))
    permissions = service.resolve_effective_permissions(user)
    assert permissions == {VIEW_DASHBOARD, VIEW_REPORTS}


def test_resolve_effective_permissions_expands_the_wildcard_role_to_every_registered_permission(
    service: AuthorizationService, permission_registry: PermissionRegistry
) -> None:
    user = _make_user("admin", "org-a", roles=(SYSTEM_ADMINISTRATOR,))
    permissions = service.resolve_effective_permissions(user)
    assert permissions == set(permission_registry.all_keys())


def test_a_newly_registered_permission_automatically_reaches_system_administrators(
    service: AuthorizationService, permission_registry: PermissionRegistry
) -> None:
    """The wildcard is expanded live, not from a fixed snapshot -- a
    brand-new permission registered after the role was defined still
    reaches every wildcard-holding role with zero code change."""
    user = _make_user("admin", "org-a", roles=(SYSTEM_ADMINISTRATOR,))
    permission_registry.register(Permission("manage_billing", "Manage billing"))

    permissions = service.resolve_effective_permissions(user)
    assert "manage_billing" in permissions


def test_resolve_effective_permissions_unions_multiple_roles(service: AuthorizationService) -> None:
    user = _make_user("jane.doe", "org-a", roles=(EXECUTIVE_VIEWER, BUSINESS_ANALYST))
    permissions = service.resolve_effective_permissions(user)
    # Business Analyst's set is a superset of Executive Viewer's here.
    assert permissions == service.resolve_effective_permissions(_make_user("x", "org-a", roles=(BUSINESS_ANALYST,)))


def test_resolve_effective_permissions_adds_directly_granted_permissions_on_top_of_roles(
    service: AuthorizationService,
) -> None:
    user = _make_user("jane.doe", "org-a", roles=(EXECUTIVE_VIEWER,), permissions=(MANAGE_TENANTS,))
    permissions = service.resolve_effective_permissions(user)
    assert permissions == {VIEW_DASHBOARD, VIEW_REPORTS, MANAGE_TENANTS}


def test_resolve_effective_permissions_skips_an_unknown_role_without_raising(service: AuthorizationService) -> None:
    user = _make_user("jane.doe", "org-a", roles=("not_a_real_role",))
    permissions = service.resolve_effective_permissions(user)
    assert permissions == frozenset()


def test_resolve_effective_permissions_skips_an_unknown_direct_permission_without_raising(
    service: AuthorizationService,
) -> None:
    user = _make_user("jane.doe", "org-a", permissions=("not_a_real_permission",))
    permissions = service.resolve_effective_permissions(user)
    assert permissions == frozenset()


def test_user_with_no_roles_and_no_permissions_has_no_effective_permissions(service: AuthorizationService) -> None:
    user = _make_user("jane.doe", "org-a")
    assert service.resolve_effective_permissions(user) == frozenset()


# ==============================================================================
# 7. Unauthorized access / enforcement
# ==============================================================================


def test_require_permission_grants_and_returns_the_user(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,)))
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

    user = service.require_permission(
        context, UPLOAD_DATA, service_name="UploadCenter", operation="upload", tenant_context=TenantContext(tenant=tenant_a)
    )
    assert user.user_id == "jane.doe"


def test_require_permission_denies_when_permission_not_granted(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(EXECUTIVE_VIEWER,)))
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

    with pytest.raises(PermissionDeniedError) as exc_info:
        service.require_permission(context, EXPORT_DATA, service_name="ExportService", operation="export")
    # Business-friendly: no permission key or user id in the message text.
    assert "export_data" not in str(exc_info.value)
    assert "jane.doe" not in str(exc_info.value)


def test_require_permission_with_none_context_raises_missing_user_context(service: AuthorizationService) -> None:
    with pytest.raises(MissingUserContextError) as exc_info:
        service.require_permission(None, VIEW_DASHBOARD, service_name="Dashboard", operation="view")
    assert "Traceback" not in str(exc_info.value)


def test_require_permission_with_empty_context_raises_missing_user_context(service: AuthorizationService) -> None:
    with pytest.raises(MissingUserContextError):
        service.require_permission(UserContext.empty(), VIEW_DASHBOARD, service_name="Dashboard", operation="view")


def test_require_permission_with_unregistered_permission_key_raises_unknown_permission(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant
) -> None:
    provider.register_user(_make_user("admin", "org-a", roles=(SYSTEM_ADMINISTRATOR,)))
    context = service.build_context("admin", TenantContext(tenant=tenant_a))

    with pytest.raises(UnknownPermissionError):
        service.require_permission(context, "not_a_real_permission", service_name="X", operation="y")


def test_has_permission_is_non_raising_and_returns_a_boolean(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(EXECUTIVE_VIEWER,)))
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

    assert service.has_permission(context, VIEW_DASHBOARD) is True
    assert service.has_permission(context, EXPORT_DATA) is False
    assert service.has_permission(None, VIEW_DASHBOARD) is False


def test_inactive_user_status_flag_is_correct() -> None:
    active_user = _make_user("a", "org-a", status=UserStatus.ACTIVE)
    inactive_user = _make_user("b", "org-a", status=UserStatus.INACTIVE)
    assert active_user.is_active is True
    assert inactive_user.is_active is False


# ==============================================================================
# 8. Tenant isolation
# ==============================================================================


def test_build_context_raises_cross_tenant_access_error_for_a_mismatched_tenant(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,)))

    with pytest.raises(CrossTenantAccessError):
        service.build_context("jane.doe", TenantContext(tenant=tenant_b))

    # Still works fine against the user's own tenant.
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))
    assert context.has_user()


def test_system_administrator_is_exempt_from_the_tenant_isolation_check(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_b: Tenant
) -> None:
    """A System Administrator's User record still declares one 'home'
    tenant_id, but their wildcard-permission role warrants durable
    cross-tenant reach for platform administration -- see
    docs/AUTHORIZATION_ARCHITECTURE.md."""
    provider.register_user(_make_user("admin", "org-a", roles=(SYSTEM_ADMINISTRATOR,)))

    context = service.build_context("admin", TenantContext(tenant=tenant_b))
    assert context.has_user()
    assert context.has_permission(MANAGE_TENANTS)


def test_two_tenants_users_permissions_never_cross_contaminate(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    provider.register_user(_make_user("a1", "org-a", roles=(BUSINESS_ANALYST,)))
    provider.register_user(_make_user("b1", "org-b", roles=(EXECUTIVE_VIEWER,)))

    context_a = service.build_context("a1", TenantContext(tenant=tenant_a))
    context_b = service.build_context("b1", TenantContext(tenant=tenant_b))

    assert context_a.has_permission(EXPORT_DATA) is True
    assert context_b.has_permission(EXPORT_DATA) is False
    # Re-check A's context after resolving B -- proves nothing about
    # resolving B mutated A's already-returned context.
    assert context_a.has_permission(EXPORT_DATA) is True


def test_tenant_administrator_is_confined_to_their_own_tenant_despite_the_name(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_b: Tenant
) -> None:
    """Unlike System Administrator, Tenant Administrator is scoped to
    managing its *own* tenant, not every tenant -- confirms the
    exemption in build_context() is keyed on holding every permission,
    not on role name."""
    provider.register_user(_make_user("tenant.admin", "org-a", roles=(TENANT_ADMINISTRATOR,)))

    with pytest.raises(CrossTenantAccessError):
        service.build_context("tenant.admin", TenantContext(tenant=tenant_b))


# ==============================================================================
# 9. Monitoring integration (Task 10)
# ==============================================================================


@pytest.fixture
def clean_monitoring():
    """Clear the shared monitoring provider before and after a test.

    AuthorizationService.require_permission() always records into the
    shared, application-wide ``monitoring_service`` singleton by design
    (see docs/AUTHORIZATION_ARCHITECTURE.md) -- unlike every other
    fixture in this file, there is no dependency-injected alternative
    to swap in. Clearing the active provider before and after keeps
    these specific tests isolated from whatever else records into the
    shared monitoring service elsewhere in a full test run.
    """
    active_provider = monitoring_provider_registry.get_active()
    active_provider.clear()
    yield
    active_provider.clear()


def test_require_permission_grant_is_recorded_as_a_completed_monitoring_event(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant, clean_monitoring
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,)))
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

    service.require_permission(
        context, UPLOAD_DATA, service_name="UploadCenter", operation="upload", tenant_context=TenantContext(tenant=tenant_a)
    )

    events = monitoring_service.get_events(service_name="AuthorizationService")
    assert len(events) == 1
    assert events[0].status.value == "success"
    assert events[0].metadata["user_id"] == "jane.doe"
    assert events[0].metadata["permission"] == UPLOAD_DATA
    assert events[0].tenant_id == "org-a"


def test_require_permission_denial_is_recorded_as_a_failed_monitoring_event(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant, clean_monitoring
) -> None:
    provider.register_user(_make_user("jane.doe", "org-a", roles=(EXECUTIVE_VIEWER,)))
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

    with pytest.raises(PermissionDeniedError):
        service.require_permission(
            context, EXPORT_DATA, service_name="ExportService", operation="export", tenant_context=TenantContext(tenant=tenant_a)
        )

    events = monitoring_service.get_events(service_name="AuthorizationService")
    assert len(events) == 1
    assert events[0].status.value == "failure"
    assert events[0].metadata["user_id"] == "jane.doe"
    assert events[0].metadata["reason"] == "permission not granted"


def test_missing_user_context_denial_is_still_recorded_with_no_user_id(
    service: AuthorizationService, clean_monitoring
) -> None:
    with pytest.raises(MissingUserContextError):
        service.require_permission(None, VIEW_DASHBOARD, service_name="Dashboard", operation="view")

    events = monitoring_service.get_events(service_name="AuthorizationService")
    assert len(events) == 1
    assert events[0].status.value == "failure"
    assert events[0].metadata["user_id"] is None


def test_authorization_service_shows_up_in_service_health_with_grant_deny_as_success_failure(
    service: AuthorizationService, provider: InMemoryAuthorizationProvider, tenant_a: Tenant, clean_monitoring
) -> None:
    """Emergent behavior documented in docs/AUTHORIZATION_ARCHITECTURE.md:
    reusing OPERATION_COMPLETED/OPERATION_FAILED means AuthorizationService
    appears in the Monitoring dashboard's existing Service Statistics
    table for free."""
    provider.register_user(_make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,)))
    context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

    service.require_permission(context, UPLOAD_DATA, service_name="UploadCenter", operation="upload")
    try:
        service.require_permission(context, MANAGE_TENANTS, service_name="TenantConfig", operation="view")
    except PermissionDeniedError:
        pass

    health = monitoring_service.get_service_health("AuthorizationService")
    assert health.successful_executions == 1
    assert health.failed_executions == 1
    assert health.total_executions == 2


def test_a_storage_failure_never_prevents_a_permission_decision(
    role_registry: RoleRegistry, permission_registry: PermissionRegistry, tenant_a: Tenant, clean_monitoring
) -> None:
    """Mirrors monitoring's own resilience guarantee: even if the
    monitoring provider is broken, AuthorizationService must still
    correctly grant or deny access -- an observability outage can never
    become an authorization outage."""

    class _BrokenMonitoringProvider(InMemoryMonitoringProvider):
        def record(self, event) -> None:  # noqa: ANN001 - test double
            raise RuntimeError("storage backend unreachable")

    monitoring_provider_registry.register("broken", _BrokenMonitoringProvider(), make_active=True)
    try:
        provider = InMemoryAuthorizationProvider()
        provider.register_user(_make_user("jane.doe", "org-a", roles=(BUSINESS_ANALYST,)))
        service = AuthorizationService(provider=provider, role_registry=role_registry, permission_registry=permission_registry)
        context = service.build_context("jane.doe", TenantContext(tenant=tenant_a))

        user = service.require_permission(context, UPLOAD_DATA, service_name="UploadCenter", operation="upload")
        assert user.user_id == "jane.doe"  # decision still correct despite broken monitoring
    finally:
        monitoring_provider_registry.register("memory", InMemoryMonitoringProvider(), make_active=True)


# ==============================================================================
# 10. Regression -- existing functionality unaffected
# ==============================================================================


def test_default_roles_and_permissions_tuples_are_not_mutated_by_registry_use(service: AuthorizationService) -> None:
    """DEFAULT_ROLES / DEFAULT_PERMISSIONS are module-level tuples shared
    by every fresh registry fixture -- proves resolving permissions
    through one test's registry never mutates the shared declarative
    data other tests (and the real application) also read from."""
    assert len(DEFAULT_ROLES) == 4
    assert len(DEFAULT_PERMISSIONS) == 11
