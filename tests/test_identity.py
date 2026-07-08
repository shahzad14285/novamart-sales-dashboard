"""Unit tests for the Identity & Authentication Framework (Sprint 6.6).

This file is the Task 11 deliverable: comprehensive coverage of the
``identity/`` package -- the identity/session models, the Authentication
Provider (including a from-scratch custom provider proving
swappability), the Session Manager (creation, validation, sliding
activity, expiration, destruction), the Authentication Service
(authenticate, sign in, sign out, validate/refresh session, retrieve
current user), the Provider Registry, integration with the existing
Monitoring Service, and integration with the existing Authorization
Framework (proving authentication precedes authorization).

Scope note -- "Login"/"UI" (Task 11)
----------------------------------------
Following the convention already established by every prior sprint's
test suite (no file under ``tests/`` imports ``streamlit`` or anything
from ``components/``/``ui/``/``pages/`` -- those layers are verified
via a headless dry run plus the manual test cases documented in each
sprint's architecture doc), this file does not import
``components.auth`` or ``components.authorization`` directly. Every
function those modules expose is a thin Streamlit-rendering wrapper
around exactly the :class:`~identity.service.AuthenticationService`
methods this file already covers exhaustively -- so "Login" and
"Logout" here mean proving that *backing logic* is correct, which is
what actually determines what the login screen shows. The
Streamlit-rendering behavior itself (the login form, the "Session
expired" notice, the user panel) is exercised in the headless dry run
recorded in ``docs/IDENTITY_ARCHITECTURE.md``'s "Automated tests"
section.

Every test constructs its own :class:`~identity.service.AuthenticationService`
backed by its own fresh :class:`~identity.provider.InMemoryAuthenticationProvider`
and fresh :class:`~identity.session.SessionManager` (or a custom stub
provider) rather than using the shared, application-wide singletons --
this is what keeps tests fully isolated from each other and from
whatever ``config/credentials.py`` seeds into the real provider at
import time. The one exception is the monitoring-integration tests,
which necessarily exercise the shared
``monitoring.service.monitoring_service`` singleton (since
:class:`~identity.service.AuthenticationService` always records into
it, by design -- see ``docs/IDENTITY_ARCHITECTURE.md``) -- those tests
clear the active monitoring provider before and after themselves to
stay isolated from any other test file's events.
"""

from __future__ import annotations

import time

import pytest

from authorization.models import User as AuthorizationUser
from authorization.permissions import DEFAULT_PERMISSIONS, PermissionRegistry, VIEW_DASHBOARD
from authorization.provider import InMemoryAuthorizationProvider
from authorization.roles import BUSINESS_ANALYST, DEFAULT_ROLES, RoleRegistry
from authorization.service import AuthorizationService
from identity.exceptions import (
    AuthenticationError,
    InactiveIdentityError,
    InvalidCredentialsError,
    NoActiveProviderError,
    NotAuthenticatedError,
    ProviderNotRegisteredError,
    SessionExpiredError,
    SessionNotFoundError,
)
from identity.models import AuthenticationResult, IdentityStatus, LoginStatus, SessionInfo, UserIdentity
from identity.provider import AuthenticationProvider, InMemoryAuthenticationProvider
from identity.registry import AuthenticationProviderRegistry
from identity.service import AuthenticationService
from identity.session import SessionManager
from monitoring.provider import InMemoryMonitoringProvider
from monitoring.registry import monitoring_provider_registry
from monitoring.service import monitoring_service

# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


def _make_identity(user_id: str = "jane.doe", *, status: IdentityStatus = IdentityStatus.ACTIVE) -> UserIdentity:
    """Build a minimal, valid UserIdentity for tests."""
    return UserIdentity(
        user_id=user_id,
        username=user_id,
        display_name="Jane Doe",
        email=f"{user_id}@example.com",
        tenant_id="acme-retail",
        status=status,
    )


@pytest.fixture
def provider() -> InMemoryAuthenticationProvider:
    """A fresh, empty in-memory authentication provider, isolated to a single test."""
    return InMemoryAuthenticationProvider()


@pytest.fixture
def session_mgr() -> SessionManager:
    """A fresh SessionManager with the default 30-minute timeout, isolated to a single test."""
    return SessionManager()


@pytest.fixture
def service(provider: InMemoryAuthenticationProvider, session_mgr: SessionManager) -> AuthenticationService:
    """An AuthenticationService wired to fresh dependencies via Dependency Injection.

    Never touches the shared, application-wide ``authentication_service``
    singleton or its session manager, so tests never leak sessions into
    (or read stale ones from) each other.
    """
    return AuthenticationService(provider=provider, session_manager=session_mgr)


@pytest.fixture
def clean_monitoring():
    """Clear the provider the shared ``monitoring_service`` actually writes to.

    AuthenticationService always records into the shared,
    application-wide ``monitoring_service`` singleton by design (see
    docs/IDENTITY_ARCHITECTURE.md) -- unlike every other fixture in
    this file, there is no dependency-injected alternative to swap in.

    Deliberately clears ``monitoring_service``'s own provider reference
    rather than ``monitoring_provider_registry.get_active()``: since
    ``MonitoringService`` resolves its provider once via Dependency
    Injection at construction time (see ``monitoring/service.py``), a
    test elsewhere that registers a *new* provider instance under the
    same active name (e.g. an isolation test that temporarily swaps in
    a broken provider and restores a fresh one afterward) leaves the
    shared singleton pointing at an instance the registry no longer
    considers "active." Going through the singleton's own reference
    guarantees this fixture clears whatever
    ``AuthenticationService`` -- or any other instrumented service
    sharing this singleton -- is actually recording into, regardless
    of what the registry's bookkeeping currently says.
    """
    monitoring_service._provider.clear()
    yield
    monitoring_service._provider.clear()


# ==============================================================================
# 1. Models
# ==============================================================================


def test_identity_is_active_reflects_status() -> None:
    active = _make_identity(status=IdentityStatus.ACTIVE)
    inactive = _make_identity(status=IdentityStatus.INACTIVE)
    assert active.is_active is True
    assert inactive.is_active is False


def test_session_info_is_expired_and_remaining_seconds() -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fresh = SessionInfo(
        session_id="s1", user_id="jane.doe", created_at=now, last_activity_at=now, expires_at=now + timedelta(minutes=30)
    )
    assert fresh.is_expired is False
    assert fresh.remaining_seconds > 0

    stale = SessionInfo(
        session_id="s2", user_id="jane.doe", created_at=now, last_activity_at=now, expires_at=now - timedelta(seconds=1)
    )
    assert stale.is_expired is True
    assert stale.remaining_seconds == 0.0


def test_authentication_result_is_success() -> None:
    from datetime import datetime, timezone

    identity = _make_identity()
    success = AuthenticationResult(
        status=LoginStatus.SUCCESS, identity=identity, session=None, message="ok", timestamp=datetime.now(timezone.utc)
    )
    failure = AuthenticationResult(
        status=LoginStatus.FAILED, identity=None, session=None, message="no", timestamp=datetime.now(timezone.utc)
    )
    assert success.is_success is True
    assert failure.is_success is False


def test_login_status_and_identity_status_are_plain_strings() -> None:
    assert LoginStatus.SUCCESS == "success"
    assert LoginStatus.FAILED == "failed"
    assert IdentityStatus.ACTIVE == "active"
    assert IdentityStatus.INACTIVE == "inactive"


# ==============================================================================
# 2. Authentication Provider
# ==============================================================================


def test_provider_register_and_verify_credentials(provider: InMemoryAuthenticationProvider) -> None:
    identity = _make_identity("jane.doe")
    provider.register_identity(identity, "secret123")

    resolved = provider.verify_credentials("jane.doe", "secret123")
    assert resolved == identity


def test_provider_verify_credentials_wrong_password(provider: InMemoryAuthenticationProvider) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    assert provider.verify_credentials("jane.doe", "wrong-password") is None


def test_provider_verify_credentials_unknown_username(provider: InMemoryAuthenticationProvider) -> None:
    assert provider.verify_credentials("nobody", "anything") is None


def test_provider_get_identity_by_user_id(provider: InMemoryAuthenticationProvider) -> None:
    identity = _make_identity("jane.doe")
    provider.register_identity(identity, "secret123")
    assert provider.get_identity("jane.doe") == identity
    assert provider.get_identity("unknown") is None


def test_provider_register_many(provider: InMemoryAuthenticationProvider) -> None:
    entries = ((_make_identity("a"), "pw-a"), (_make_identity("b"), "pw-b"))
    provider.register_many(entries)
    assert provider.verify_credentials("a", "pw-a") is not None
    assert provider.verify_credentials("b", "pw-b") is not None


def test_provider_register_identity_replaces_existing(provider: InMemoryAuthenticationProvider) -> None:
    provider.register_identity(_make_identity("jane.doe"), "old-password")
    provider.register_identity(_make_identity("jane.doe"), "new-password")
    assert provider.verify_credentials("jane.doe", "old-password") is None
    assert provider.verify_credentials("jane.doe", "new-password") is not None


def test_provider_clear_removes_everything(provider: InMemoryAuthenticationProvider) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    provider.clear()
    assert provider.get_identity("jane.doe") is None
    assert provider.verify_credentials("jane.doe", "secret123") is None


def test_provider_satisfies_authentication_provider_protocol(provider: InMemoryAuthenticationProvider) -> None:
    assert isinstance(provider, AuthenticationProvider)


# ==============================================================================
# 3. Session Manager
# ==============================================================================


def test_session_manager_create_and_get_session(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session("jane.doe")
    assert session.user_id == "jane.doe"
    assert session_mgr.get_session(session.session_id) == session


def test_session_manager_get_session_unknown_returns_none(session_mgr: SessionManager) -> None:
    assert session_mgr.get_session("does-not-exist") is None
    assert session_mgr.get_session(None) is None


def test_session_manager_validate_session_unknown_raises(session_mgr: SessionManager) -> None:
    with pytest.raises(SessionNotFoundError):
        session_mgr.validate_session("does-not-exist")
    with pytest.raises(SessionNotFoundError):
        session_mgr.validate_session(None)


def test_session_manager_validate_session_valid_returns_session(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session("jane.doe")
    validated = session_mgr.validate_session(session.session_id)
    assert validated == session


def test_session_manager_record_activity_extends_expiration(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session("jane.doe")
    time.sleep(0.01)
    updated = session_mgr.record_activity(session.session_id)
    assert updated.last_activity_at > session.last_activity_at
    assert updated.expires_at > session.expires_at


def test_session_manager_destroy_session_removes_it(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session("jane.doe")
    session_mgr.destroy_session(session.session_id)
    assert session_mgr.get_session(session.session_id) is None


def test_session_manager_destroy_session_twice_does_not_raise(session_mgr: SessionManager) -> None:
    session = session_mgr.create_session("jane.doe")
    session_mgr.destroy_session(session.session_id)
    session_mgr.destroy_session(session.session_id)  # no error
    session_mgr.destroy_session(None)  # no error
    session_mgr.destroy_session("never-existed")  # no error


def test_session_manager_expired_session_raises_and_is_removed() -> None:
    expiring_mgr = SessionManager(timeout_minutes=-1)  # already expired the instant it's created
    session = expiring_mgr.create_session("jane.doe")

    with pytest.raises(SessionExpiredError):
        expiring_mgr.validate_session(session.session_id)

    # The expired session was evicted as a side effect -- a second
    # lookup now reports "not found", not "expired" again.
    with pytest.raises(SessionNotFoundError):
        expiring_mgr.validate_session(session.session_id)


def test_session_manager_record_activity_on_expired_session_raises() -> None:
    expiring_mgr = SessionManager(timeout_minutes=-1)
    session = expiring_mgr.create_session("jane.doe")
    with pytest.raises(SessionExpiredError):
        expiring_mgr.record_activity(session.session_id)


def test_session_manager_clear_removes_every_session(session_mgr: SessionManager) -> None:
    s1 = session_mgr.create_session("a")
    s2 = session_mgr.create_session("b")
    session_mgr.clear()
    assert session_mgr.get_session(s1.session_id) is None
    assert session_mgr.get_session(s2.session_id) is None


def test_session_manager_accepts_an_injected_store() -> None:
    """A plain dict satisfies the MutableMapping store contract (Task 5's DI requirement)."""
    custom_store: dict[str, SessionInfo] = {}
    mgr = SessionManager(store=custom_store)
    session = mgr.create_session("jane.doe")
    assert session.session_id in custom_store
    assert custom_store[session.session_id] == session


# ==============================================================================
# 4. Authentication Service -- authenticate()
# ==============================================================================


def test_authenticate_success(service: AuthenticationService, provider: InMemoryAuthenticationProvider) -> None:
    identity = _make_identity("jane.doe")
    provider.register_identity(identity, "secret123")
    resolved = service.authenticate("jane.doe", "secret123")
    assert resolved == identity


def test_authenticate_unknown_username_raises_invalid_credentials(service: AuthenticationService) -> None:
    with pytest.raises(InvalidCredentialsError):
        service.authenticate("nobody", "anything")


def test_authenticate_wrong_password_raises_invalid_credentials(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    with pytest.raises(InvalidCredentialsError):
        service.authenticate("jane.doe", "wrong-password")


def test_authenticate_inactive_identity_raises(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe", status=IdentityStatus.INACTIVE), "secret123")
    with pytest.raises(InactiveIdentityError):
        service.authenticate("jane.doe", "secret123")


def test_invalid_credentials_message_is_identical_for_unknown_user_and_wrong_password(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    """Deliberate: no username enumeration -- see identity/exceptions.py."""
    provider.register_identity(_make_identity("jane.doe"), "secret123")

    with pytest.raises(InvalidCredentialsError) as unknown_exc:
        service.authenticate("nobody", "anything")
    with pytest.raises(InvalidCredentialsError) as wrong_pw_exc:
        service.authenticate("jane.doe", "wrong-password")

    assert str(unknown_exc.value) == str(wrong_pw_exc.value)


# ==============================================================================
# 5. Login -- sign_in()
# ==============================================================================


def test_sign_in_success_returns_full_result(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    identity = _make_identity("jane.doe")
    provider.register_identity(identity, "secret123")

    result = service.sign_in("jane.doe", "secret123")

    assert result.is_success is True
    assert result.status == LoginStatus.SUCCESS
    assert result.identity == identity
    assert result.session is not None
    assert result.session.user_id == "jane.doe"
    assert "Jane Doe" in result.message


def test_sign_in_creates_a_retrievable_session(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")
    assert service.get_current_user(result.session.session_id).user_id == "jane.doe"


def test_sign_in_wrong_password_does_not_create_a_session(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider, session_mgr: SessionManager
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    with pytest.raises(InvalidCredentialsError):
        service.sign_in("jane.doe", "wrong-password")
    # No session was created for this failed attempt.
    assert service.is_authenticated(None) is False


def test_sign_in_inactive_identity_raises_and_creates_no_session(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe", status=IdentityStatus.INACTIVE), "secret123")
    with pytest.raises(InactiveIdentityError):
        service.sign_in("jane.doe", "secret123")


# ==============================================================================
# 6. Logout -- sign_out()
# ==============================================================================


def test_sign_out_destroys_the_session(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")

    service.sign_out(result.session.session_id)

    with pytest.raises(SessionNotFoundError):
        service.get_current_user(result.session.session_id)


def test_sign_out_twice_does_not_raise(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")
    service.sign_out(result.session.session_id)
    service.sign_out(result.session.session_id)  # no error


def test_sign_out_unknown_session_does_not_raise(service: AuthenticationService) -> None:
    service.sign_out("never-existed")  # no error
    service.sign_out(None)  # no error


# ==============================================================================
# 7. Session expiration
# ==============================================================================


def test_validate_session_on_expired_session_raises(
    provider: InMemoryAuthenticationProvider,
) -> None:
    expiring_service = AuthenticationService(provider=provider, session_manager=SessionManager(timeout_minutes=-1))
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = expiring_service.sign_in("jane.doe", "secret123")

    with pytest.raises(SessionExpiredError):
        expiring_service.validate_session(result.session.session_id)


def test_get_current_user_on_expired_session_raises(
    provider: InMemoryAuthenticationProvider,
) -> None:
    expiring_service = AuthenticationService(provider=provider, session_manager=SessionManager(timeout_minutes=-1))
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = expiring_service.sign_in("jane.doe", "secret123")

    with pytest.raises(SessionExpiredError):
        expiring_service.get_current_user(result.session.session_id)


def test_is_authenticated_false_for_expired_session(
    provider: InMemoryAuthenticationProvider,
) -> None:
    expiring_service = AuthenticationService(provider=provider, session_manager=SessionManager(timeout_minutes=-1))
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = expiring_service.sign_in("jane.doe", "secret123")
    assert expiring_service.is_authenticated(result.session.session_id) is False


def test_is_authenticated_false_for_no_session(service: AuthenticationService) -> None:
    assert service.is_authenticated(None) is False
    assert service.is_authenticated("never-existed") is False


def test_is_authenticated_true_for_valid_session(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")
    assert service.is_authenticated(result.session.session_id) is True


# ==============================================================================
# 8. Invalid login
# ==============================================================================


def test_sign_in_unknown_username_raises(service: AuthenticationService) -> None:
    with pytest.raises(InvalidCredentialsError):
        service.sign_in("nobody", "anything")


def test_sign_in_wrong_password_raises(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    with pytest.raises(InvalidCredentialsError):
        service.sign_in("jane.doe", "not-the-password")


def test_get_current_user_without_any_session_raises_session_not_found(service: AuthenticationService) -> None:
    with pytest.raises(SessionNotFoundError):
        service.get_current_user(None)


def test_get_current_user_returns_not_authenticated_if_identity_vanishes(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    """A session can outlive the identity it points to (e.g. removed mid-session)."""
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")
    provider.clear()  # simulate the identity being removed from the provider

    with pytest.raises(NotAuthenticatedError):
        service.get_current_user(result.session.session_id)


# ==============================================================================
# 9. Registry
# ==============================================================================


def test_registry_first_registered_provider_becomes_active() -> None:
    registry = AuthenticationProviderRegistry()
    registry.register("memory", InMemoryAuthenticationProvider())
    assert registry.active_name == "memory"


def test_registry_register_and_get() -> None:
    registry = AuthenticationProviderRegistry()
    provider_instance = InMemoryAuthenticationProvider()
    registry.register("memory", provider_instance)
    assert registry.get("memory") is provider_instance


def test_registry_get_unknown_raises() -> None:
    registry = AuthenticationProviderRegistry()
    with pytest.raises(ProviderNotRegisteredError):
        registry.get("does-not-exist")


def test_registry_get_active_with_no_providers_raises() -> None:
    registry = AuthenticationProviderRegistry()
    with pytest.raises(NoActiveProviderError):
        registry.get_active()


def test_registry_set_active_switches_provider() -> None:
    registry = AuthenticationProviderRegistry()
    registry.register("memory", InMemoryAuthenticationProvider())
    second = InMemoryAuthenticationProvider()
    registry.register("second", second)
    assert registry.active_name == "memory"  # first registered wins by default

    registry.set_active("second")
    assert registry.active_name == "second"
    assert registry.get_active() is second


def test_registry_make_active_true_switches_immediately() -> None:
    registry = AuthenticationProviderRegistry()
    registry.register("memory", InMemoryAuthenticationProvider())
    second = InMemoryAuthenticationProvider()
    registry.register("second", second, make_active=True)
    assert registry.active_name == "second"


def test_registry_registered_providers_sorted() -> None:
    registry = AuthenticationProviderRegistry()
    registry.register("zeta", InMemoryAuthenticationProvider())
    registry.register("alpha", InMemoryAuthenticationProvider())
    assert registry.registered_providers() == ("alpha", "zeta")


class _ReadOnlyProvider:
    """A from-scratch provider with no shared base class, proving Provider Pattern swappability.

    Satisfies :class:`~identity.provider.AuthenticationProvider`
    purely structurally (a ``typing.Protocol``) -- this class never
    imports or subclasses ``InMemoryAuthenticationProvider``.
    """

    def __init__(self, identities: dict[str, tuple[UserIdentity, str]]) -> None:
        self._identities = identities

    def verify_credentials(self, username: str, password: str) -> UserIdentity | None:
        entry = self._identities.get(username)
        if entry is None:
            return None
        identity, expected_password = entry
        return identity if password == expected_password else None

    def get_identity(self, user_id: str) -> UserIdentity | None:
        for identity, _password in self._identities.values():
            if identity.user_id == user_id:
                return identity
        return None


def test_authentication_service_works_unmodified_against_a_brand_new_provider_implementation(
    session_mgr: SessionManager,
) -> None:
    custom_provider = _ReadOnlyProvider({"jane.doe": (_make_identity("jane.doe"), "secret123")})
    assert isinstance(custom_provider, AuthenticationProvider)

    custom_service = AuthenticationService(provider=custom_provider, session_manager=session_mgr)
    result = custom_service.sign_in("jane.doe", "secret123")
    assert result.is_success is True
    assert custom_service.get_current_user(result.session.session_id).user_id == "jane.doe"

    with pytest.raises(InvalidCredentialsError):
        custom_service.sign_in("jane.doe", "wrong-password")


# ==============================================================================
# 10. Monitoring integration
# ==============================================================================


def _events_for(operation: str) -> tuple:
    """Return every recorded AuthenticationService event for one operation.

    ``MonitoringService.get_events()`` filters by ``service_name``,
    ``tenant_id``, ``event_type``, and ``status`` -- it has no
    ``operation`` filter, since ``operation`` is a free-form string set
    by each instrumented service (see ``monitoring/service.py``). This
    helper does the narrowing client-side, exactly as a real caller
    (e.g. a future "Authentication Events" filter on the Monitoring
    dashboard) would.
    """
    return tuple(
        event
        for event in monitoring_service.get_events(service_name="AuthenticationService")
        if event.operation == operation
    )


def test_sign_in_success_is_recorded_as_a_completed_monitoring_event(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider, clean_monitoring
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    service.sign_in("jane.doe", "secret123")

    events = _events_for("sign_in")
    assert len(events) == 1
    assert events[0].status.value == "success"
    assert events[0].metadata["user_id"] == "jane.doe"


def test_sign_in_failure_is_recorded_as_a_failed_monitoring_event(
    service: AuthenticationService, clean_monitoring
) -> None:
    with pytest.raises(InvalidCredentialsError):
        service.sign_in("nobody", "anything")

    events = _events_for("sign_in")
    assert len(events) == 1
    assert events[0].status.value == "failure"
    assert events[0].metadata["user_id"] is None


def test_sign_out_is_recorded(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider, clean_monitoring
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")
    service.sign_out(result.session.session_id)

    events = _events_for("sign_out")
    assert len(events) == 1
    assert events[0].status.value == "success"
    assert events[0].metadata["user_id"] == "jane.doe"


def test_sign_out_of_unknown_session_is_not_recorded(service: AuthenticationService, clean_monitoring) -> None:
    service.sign_out("never-existed")
    assert len(_events_for("sign_out")) == 0


def test_session_expired_is_recorded(provider: InMemoryAuthenticationProvider, clean_monitoring) -> None:
    expiring_service = AuthenticationService(provider=provider, session_manager=SessionManager(timeout_minutes=-1))
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = expiring_service.sign_in("jane.doe", "secret123")

    with pytest.raises(SessionExpiredError):
        expiring_service.validate_session(result.session.session_id)

    events = _events_for("validate_session")
    assert len(events) == 1
    assert events[0].status.value == "failure"
    assert events[0].metadata["user_id"] == "jane.doe"
    assert events[0].metadata["reason"] == "session expired"


def test_session_not_found_is_not_recorded(service: AuthenticationService, clean_monitoring) -> None:
    """The common "never signed in" case should not flood the audit trail -- see docs."""
    with pytest.raises(SessionNotFoundError):
        service.validate_session(None)
    assert len(_events_for("validate_session")) == 0


def test_session_refreshed_is_recorded(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider, clean_monitoring
) -> None:
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")
    service.refresh_session(result.session.session_id)

    events = _events_for("refresh_session")
    assert len(events) == 1
    assert events[0].status.value == "success"
    assert events[0].metadata["user_id"] == "jane.doe"


def test_authentication_service_shows_up_in_service_health_with_success_failure_counts(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider, clean_monitoring
) -> None:
    """Emergent behavior documented in docs/IDENTITY_ARCHITECTURE.md: reusing
    OPERATION_COMPLETED/OPERATION_FAILED means AuthenticationService appears
    in the Monitoring dashboard's existing Service Statistics table for free."""
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    service.sign_in("jane.doe", "secret123")
    try:
        service.sign_in("jane.doe", "wrong-password")
    except InvalidCredentialsError:
        pass

    health = monitoring_service.get_service_health("AuthenticationService")
    assert health.successful_executions == 1
    assert health.failed_executions == 1
    assert health.total_executions == 2


def test_a_monitoring_storage_failure_never_prevents_a_sign_in(
    provider: InMemoryAuthenticationProvider, session_mgr: SessionManager, clean_monitoring
) -> None:
    """Mirrors AuthorizationService's own resilience guarantee: even if the
    monitoring provider is broken, AuthenticationService must still
    correctly authenticate -- an observability outage can never become an
    authentication outage."""

    class _BrokenMonitoringProvider(InMemoryMonitoringProvider):
        def record(self, event) -> None:  # noqa: ANN001 - test double
            raise RuntimeError("storage backend unreachable")

    monitoring_provider_registry.register("broken", _BrokenMonitoringProvider(), make_active=True)
    try:
        provider.register_identity(_make_identity("jane.doe"), "secret123")
        broken_service = AuthenticationService(provider=provider, session_manager=session_mgr)
        result = broken_service.sign_in("jane.doe", "secret123")
        assert result.is_success is True  # decision still correct despite broken monitoring
    finally:
        monitoring_provider_registry.register("memory", InMemoryMonitoringProvider(), make_active=True)


# ==============================================================================
# 11. Authorization integration -- authentication precedes authorization
# ==============================================================================


def test_authentication_and_authorization_are_independent_packages() -> None:
    """identity/ never imports authorization/, and vice versa -- structural proof."""
    import ast
    import inspect

    import identity.exceptions
    import identity.models
    import identity.provider
    import identity.registry
    import identity.service
    import identity.session

    for module in (
        identity.exceptions,
        identity.models,
        identity.provider,
        identity.registry,
        identity.service,
        identity.session,
    ):
        source = inspect.getsource(module)
        tree = ast.parse(source)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)
        assert not any(name.startswith("authorization") for name in imported_names), (
            f"{module.__name__} unexpectedly imports from authorization/: {imported_names}"
        )


def test_a_valid_authenticated_user_id_flows_into_authorization(
    service: AuthenticationService, provider: InMemoryAuthenticationProvider
) -> None:
    """Simulates the real integration seam (components/authorization.py):
    identity resolves *who*, authorization resolves *what they can do*,
    and the only thing passed between them is a plain user_id string."""
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = service.sign_in("jane.doe", "secret123")
    authenticated_identity = service.get_current_user(result.session.session_id)

    # A matching authorization-side User, built independently (exactly as
    # config/credentials.py keeps the two directories in sync for real).
    permission_registry = PermissionRegistry()
    permission_registry.register_many(DEFAULT_PERMISSIONS)
    role_registry = RoleRegistry()
    role_registry.register_many(DEFAULT_ROLES)
    authz_provider = InMemoryAuthorizationProvider()
    authz_provider.register_user(
        AuthorizationUser(
            user_id=authenticated_identity.user_id,
            username=authenticated_identity.username,
            display_name=authenticated_identity.display_name,
            email=authenticated_identity.email,
            tenant_id=authenticated_identity.tenant_id,
            roles=(BUSINESS_ANALYST,),
        )
    )
    authorization_service = AuthorizationService(
        provider=authz_provider, role_registry=role_registry, permission_registry=permission_registry
    )

    user_context = authorization_service.build_context(authenticated_identity.user_id)
    assert authorization_service.has_permission(user_context, VIEW_DASHBOARD) is True


def test_an_unauthenticated_request_never_reaches_authorization(service: AuthenticationService) -> None:
    """No session at all must fail at the authentication step -- authorization is never consulted."""
    with pytest.raises(SessionNotFoundError):
        service.get_current_user(None)
    # If authentication had (incorrectly) let this through, a caller
    # would have gone on to call authorization_service.build_context(None)
    # or similar -- this test proves the identity layer stops it first.


def test_an_expired_session_never_reaches_authorization(
    provider: InMemoryAuthenticationProvider,
) -> None:
    """An expired session must fail at the authentication step, not silently degrade to "no user"."""
    expiring_service = AuthenticationService(provider=provider, session_manager=SessionManager(timeout_minutes=-1))
    provider.register_identity(_make_identity("jane.doe"), "secret123")
    result = expiring_service.sign_in("jane.doe", "secret123")

    with pytest.raises(SessionExpiredError):
        expiring_service.get_current_user(result.session.session_id)


# ==============================================================================
# 12. Regression -- no shared mutable state leaks between tests
# ==============================================================================


def test_fresh_service_instances_do_not_share_state(provider: InMemoryAuthenticationProvider) -> None:
    """Two independently constructed services over the same provider still
    keep their sessions separate, since each gets its own SessionManager."""
    service_a = AuthenticationService(provider=provider, session_manager=SessionManager())
    service_b = AuthenticationService(provider=provider, session_manager=SessionManager())
    provider.register_identity(_make_identity("jane.doe"), "secret123")

    result_a = service_a.sign_in("jane.doe", "secret123")
    assert service_b.is_authenticated(result_a.session.session_id) is False


def test_default_authentication_service_constructs_without_arguments() -> None:
    """The zero-argument constructor path every real UI call site uses."""
    default_service = AuthenticationService()
    assert isinstance(default_service, AuthenticationService)


def test_authentication_error_hierarchy() -> None:
    """Every specific exception is catchable via the shared base class."""
    assert issubclass(InvalidCredentialsError, AuthenticationError)
    assert issubclass(InactiveIdentityError, AuthenticationError)
    assert issubclass(SessionNotFoundError, AuthenticationError)
    assert issubclass(SessionExpiredError, AuthenticationError)
    assert issubclass(NotAuthenticatedError, AuthenticationError)
    assert issubclass(ProviderNotRegisteredError, AuthenticationError)
    assert issubclass(NoActiveProviderError, AuthenticationError)
