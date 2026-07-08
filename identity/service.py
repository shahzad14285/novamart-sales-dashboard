"""Authentication Service for the NovaMart Identity & Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Tasks 3, 9.

The single entry point every UI call site uses to authenticate a user,
manage their session, and retrieve their identity. This module has
exactly one responsibility -- authentication -- and deliberately does
nothing else.

The Authentication Service does NOT:
    - Decide *how* identities/credentials are stored or checked
      (that's an :class:`~identity.provider.AuthenticationProvider`,
      injected in -- see "Dependency Injection" below).
    - Decide *what* an authenticated user is allowed to do (that's
      :class:`~authorization.service.AuthorizationService`, a
      completely separate package this service never imports from --
      see ``docs/IDENTITY_ARCHITECTURE.md``'s "Authentication vs
      Authorization" section for the full rationale). This module
      answers "who is this, and are they signed in" only; it never
      resolves a permission, a role, or a tenant-isolation check.
    - Contain any business logic. Every UI call site this framework
      protects calls this service *before* reaching
      :class:`~authorization.service.AuthorizationService` (see the
      Target Architecture in ``docs/IDENTITY_ARCHITECTURE.md``) --
      this service is called from the UI layer, never from inside
      ``services/*.py`` or ``utils/*.py``.
    - Ever let an observability failure become an authentication
      failure, or vice versa: monitoring events are recorded on a
      best-effort basis via the same resilient
      ``MonitoringService._store()`` guarantee Sprint 6.4 already
      established -- an outage in monitoring can never block or grant
      a sign-in.

Dependency Injection
----------------------
:class:`AuthenticationService` never hard-codes which provider or
session manager it uses. Its constructor accepts both as optional
arguments; when omitted, each defaults to the shared,
application-wide instance. This is what lets:

- Tests inject a fresh, isolated provider/session manager instead of
  sharing the application-wide ones.
- A future deployment swap from
  :class:`~identity.provider.InMemoryAuthenticationProvider` to a
  database-, LDAP-, or OAuth/OIDC/Entra ID/Google Identity/Okta/Auth0-backed
  provider by registering it and calling
  :meth:`~identity.registry.AuthenticationProviderRegistry.set_active`
  -- zero changes to this class or to any UI call site that uses it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from identity.exceptions import (
    InactiveIdentityError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    SessionExpiredError,
    SessionNotFoundError,
)
from identity.models import AuthenticationResult, LoginStatus, SessionInfo, UserIdentity
from identity.provider import AuthenticationProvider
from identity.registry import authentication_provider_registry
from identity.session import SessionManager
from identity.session import session_manager as default_session_manager
from monitoring.service import monitoring_service

logger = logging.getLogger("novamart.identity")

_SERVICE_NAME = "AuthenticationService"


class AuthenticationService:
    """Centralized authentication, session, and current-user resolution point.

    Example:
        >>> service = AuthenticationService()
        >>> result = service.sign_in("jane.doe", "demo123")
        >>> result.is_success
        True
        >>> service.get_current_user(result.session.session_id).display_name
        'Jane Doe'
        >>> service.sign_out(result.session.session_id)
    """

    def __init__(
        self,
        provider: AuthenticationProvider | None = None,
        session_manager: SessionManager | None = None,
    ) -> None:
        """Create an Authentication Service.

        Args:
            provider: The identity backend used to verify credentials
                and resolve identities. When omitted (the normal case
                for application code), the currently active provider
                from :data:`~identity.registry.authentication_provider_registry`
                is used. Tests and future callers can inject any other
                object satisfying
                :class:`~identity.provider.AuthenticationProvider`.
            session_manager: The session lifecycle manager to use.
                Defaults to the shared
                :data:`~identity.session.session_manager`. Tests inject
                a fresh, isolated :class:`~identity.session.SessionManager`
                instead.
        """
        self._provider: AuthenticationProvider = provider if provider is not None else authentication_provider_registry.get_active()
        self._session_manager: SessionManager = session_manager if session_manager is not None else default_session_manager

    # ------------------------------------------------------------------
    # Authentication -- Task 3 ("authenticate users", "sign in")
    # ------------------------------------------------------------------
    def authenticate(self, username: str, password: str) -> UserIdentity:
        """Verify a username/password pair, without creating a session.

        A pure identity-verification primitive, distinct from
        :meth:`sign_in`: useful anywhere credentials need to be
        checked without establishing (or replacing) a session -- e.g. a
        future "re-authenticate to confirm this sensitive action"
        prompt.

        Args:
            username: The submitted login name.
            password: The submitted password.

        Returns:
            The verified :class:`~identity.models.UserIdentity`.

        Raises:
            InvalidCredentialsError: If the username is unknown or the
                password does not match.
            InactiveIdentityError: If the credentials check out but the
                identity is not active.
        """
        identity = self._provider.verify_credentials(username, password)
        if identity is None:
            raise InvalidCredentialsError("invalid credentials")
        if not identity.is_active:
            raise InactiveIdentityError(identity.user_id)
        return identity

    def sign_in(self, username: str, password: str) -> AuthenticationResult:
        """Authenticate a user and create a new session for them.

        Every call -- granted or denied -- is recorded as a monitoring
        event (Task 9: "Login Successful" / "Login Failed").

        Args:
            username: The submitted login name.
            password: The submitted password.

        Returns:
            An :class:`~identity.models.AuthenticationResult` with
            ``status=LoginStatus.SUCCESS``, the resolved identity, and
            the newly created session.

        Raises:
            InvalidCredentialsError: If the username is unknown or the
                password does not match.
            InactiveIdentityError: If the credentials check out but the
                identity is not active.
        """
        try:
            identity = self.authenticate(username, password)
        except InvalidCredentialsError as exc:
            self._record(outcome="FAILED", operation="sign_in", user_id=None, reason=exc.reason)
            raise
        except InactiveIdentityError as exc:
            self._record(outcome="FAILED", operation="sign_in", user_id=exc.user_id, reason="inactive account")
            raise

        session = self._session_manager.create_session(identity.user_id)
        self._record(outcome="SUCCESS", operation="sign_in", user_id=identity.user_id, reason=None)
        return AuthenticationResult(
            status=LoginStatus.SUCCESS,
            identity=identity,
            session=session,
            message=f"Welcome back, {identity.display_name}.",
            timestamp=_utc_now(),
        )

    def sign_out(self, session_id: str | None) -> None:
        """Destroy a session, ending that sign-in.

        A no-op (not an error) if ``session_id`` is already invalid or
        unknown -- signing out twice should never raise. Recorded as a
        monitoring event (Task 9: "Logout") only when there was an
        actual session to end.

        Args:
            session_id: The session id to destroy.
        """
        session = self._session_manager.get_session(session_id)
        self._session_manager.destroy_session(session_id)
        if session is not None:
            self._record(outcome="SUCCESS", operation="sign_out", user_id=session.user_id, reason=None)

    # ------------------------------------------------------------------
    # Session validation -- Task 3 ("validate sessions", "refresh sessions")
    # ------------------------------------------------------------------
    def validate_session(self, session_id: str | None) -> SessionInfo:
        """Return ``session_id``'s session if it is currently valid.

        A read-only check -- does not update activity or extend
        expiration (see :meth:`refresh_session` for that). Recorded as
        a monitoring event only on genuine expiration (Task 9:
        "Session Expired") -- a session that was simply never
        established (:class:`~identity.exceptions.SessionNotFoundError`,
        the common case for an anonymous visitor on every page load
        before their first sign-in) is not recorded, to avoid flooding
        the audit trail with non-events; see
        ``docs/IDENTITY_ARCHITECTURE.md`` for the full rationale.

        Args:
            session_id: The session id to validate.

        Returns:
            The valid :class:`~identity.models.SessionInfo`.

        Raises:
            SessionNotFoundError: If no session matches ``session_id``.
            SessionExpiredError: If the session existed but has expired.
        """
        try:
            return self._session_manager.validate_session(session_id)
        except SessionExpiredError as exc:
            self._record(outcome="FAILED", operation="validate_session", user_id=exc.user_id, reason="session expired")
            raise

    def refresh_session(self, session_id: str | None) -> SessionInfo:
        """Validate a session and extend it based on this activity.

        Intended to be called once per authenticated page load (see
        ``components/auth.py::require_authentication``), implementing
        the "sliding expiration" behavior Task 5 describes. Recorded as
        a monitoring event on success (Task 9: "Session Refreshed") and
        on genuine expiration (Task 9: "Session Expired", via the same
        path :meth:`validate_session` uses).

        Args:
            session_id: The session id to refresh.

        Returns:
            The updated :class:`~identity.models.SessionInfo`.

        Raises:
            SessionNotFoundError: If no session matches ``session_id``.
            SessionExpiredError: If the session existed but has expired.
        """
        try:
            session = self._session_manager.record_activity(session_id)
        except SessionExpiredError as exc:
            self._record(outcome="FAILED", operation="validate_session", user_id=exc.user_id, reason="session expired")
            raise
        self._record(outcome="SUCCESS", operation="refresh_session", user_id=session.user_id, reason=None)
        return session

    # ------------------------------------------------------------------
    # Current user -- Task 3 ("retrieve current user")
    # ------------------------------------------------------------------
    def get_current_user(self, session_id: str | None) -> UserIdentity:
        """Return the identity behind a valid session, without touching activity.

        A cheap, non-recording, repeatable read -- safe to call many
        times per page render (e.g. once per navigation item being
        filtered) without flooding the monitoring log or resetting the
        sliding expiration window on every internal check. Use
        :meth:`refresh_session` for the once-per-page-load call that
        *should* extend the session and be recorded.

        Args:
            session_id: The session id to resolve.

        Returns:
            The :class:`~identity.models.UserIdentity` behind this
            session.

        Raises:
            SessionNotFoundError: If no session matches ``session_id``.
            SessionExpiredError: If the session existed but has expired.
            NotAuthenticatedError: If the session is valid but no
                identity can be resolved for it any longer (e.g. the
                identity was removed from the provider after the
                session was created).
        """
        session = self._session_manager.validate_session(session_id)
        identity = self._provider.get_identity(session.user_id)
        if identity is None:
            raise NotAuthenticatedError()
        return identity

    def is_authenticated(self, session_id: str | None) -> bool:
        """Return ``True`` if ``session_id`` currently resolves to a valid session.

        A non-raising check, intended for UI code that needs to decide
        whether to *show* something (e.g. whether to render the login
        screen at all) rather than treat an invalid session as an
        error.

        Args:
            session_id: The session id to check.

        Returns:
            ``True`` if the session is valid, ``False`` otherwise.
        """
        try:
            self._session_manager.validate_session(session_id)
            return True
        except (SessionNotFoundError, SessionExpiredError):
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _record(self, *, outcome: str, user_id: str | None, operation: str, reason: str | None) -> None:
        """Write the structured log line and monitoring event for one identity operation.

        Every "Login Successful" / "Login Failed" / "Logout" /
        "Session Expired" / "Session Refreshed" event (Task 9) is
        recorded here, exactly once, regardless of outcome -- an
        ``OPERATION_COMPLETED`` event for a success, an
        ``OPERATION_FAILED`` event for a failure. Both carry the
        affected identity's id (in ``metadata["user_id"]``, since
        ``monitoring.models.MonitoringEvent`` has no dedicated user
        field -- the same open-``metadata`` mechanism
        :class:`~authorization.service.AuthorizationService` already
        uses for the identical reason, see
        ``docs/OBSERVABILITY_ARCHITECTURE.md``) and a timestamp
        (assigned automatically by the Monitoring Service).

        Reusing the existing ``OPERATION_COMPLETED``/``OPERATION_FAILED``
        vocabulary (rather than adding new ``EventType`` members)
        requires zero changes to the monitoring package and means
        ``AuthenticationService`` shows up in the Monitoring
        dashboard's existing Service Statistics table for free -- the
        exact same deliberate choice
        :class:`~authorization.service.AuthorizationService` already
        made; see ``docs/IDENTITY_ARCHITECTURE.md``.

        Args:
            outcome: ``"SUCCESS"`` or ``"FAILED"``.
            user_id: The affected identity's id, or ``None`` if not
                yet known (e.g. an unknown username at sign-in).
            operation: One of ``"sign_in"``, ``"sign_out"``,
                ``"validate_session"``, ``"refresh_session"`` -- used
                as both the monitoring event's ``operation`` and part
                of the structured log line.
            reason: A short machine-readable reason for a failure, or
                ``None`` for a success.
        """
        timestamp = _utc_now().isoformat()
        message = f"user_id={user_id or '-'} operation={operation} timestamp={timestamp} outcome={outcome}"
        if outcome == "SUCCESS":
            logger.info(message)
        else:
            logger.warning(message)

        metadata: dict[str, object] = {"user_id": user_id}
        if reason is not None:
            metadata["reason"] = reason

        if outcome == "SUCCESS":
            monitoring_service.record_completed(
                service_name=_SERVICE_NAME,
                operation=operation,
                message=f"{operation} succeeded",
                metadata=metadata,
            )
        else:
            monitoring_service.record_failure(
                service_name=_SERVICE_NAME,
                operation=operation,
                error=f"{operation} failed ({reason})",
                metadata=metadata,
            )


def _utc_now() -> datetime:
    """Return the current UTC time.

    A tiny local helper, mirroring
    ``authorization.service._utc_now_isoformat``'s reasoning: keeps
    this module from taking on a dependency on any other package's
    internals beyond ``monitoring_service`` itself.
    """
    return datetime.now(timezone.utc)


# A shared, ready-to-use instance -- mirrors
# ``authorization.service.authorization_service`` and
# ``monitoring.service.monitoring_service``. Every UI call site imports
# this directly rather than constructing its own AuthenticationService,
# so every check is resolved against the same provider and session
# manager.
authentication_service = AuthenticationService()
