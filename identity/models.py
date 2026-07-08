"""Identity models for the NovaMart Identity & Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Task 2.

Every type here is a plain, immutable value object -- no database
access, no credential checking, no session-storage logic -- matching
the value-object convention already established by
``authorization.models.User``, ``tenancy.models.Tenant``, and
``monitoring.models.MonitoringEvent``. Verifying a password and
deciding whether a session is still valid are the jobs of
:class:`~identity.service.AuthenticationService` and
:class:`~identity.session.SessionManager`, never these models.

Deliberately independent of ``authorization.models``
-------------------------------------------------------
:class:`UserIdentity` looks similar in shape to
``authorization.models.User`` (both carry a ``user_id``,
``display_name``, ``email``, ``tenant_id``...) but is its own type,
with its own :class:`IdentityStatus` distinct from
``authorization.models.UserStatus``. This is deliberate, not
duplication for its own sake: "Authentication must remain completely
separated from Authorization" (this sprint's explicit requirement)
means the *identity* layer must be able to answer "is this account
allowed to sign in at all" without importing anything from the
*authorization* package, whose job is the separate question of "what
is this already-signed-in user allowed to do." The two models are kept
in sync for the demo users by ``config/credentials.py``, the one
config-layer module allowed to know about both packages -- see its
docstring for the full rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping


class IdentityStatus(str, Enum):
    """Whether an identity is currently allowed to sign in.

    A plain ``str`` subclass (matching
    ``authorization.models.UserStatus``, ``tenancy.models.TenantStatus``,
    and ``monitoring.models.EventStatus``), so a member compares equal
    to, and can be constructed from, its underlying string value.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class UserIdentity:
    """A person's identity as known to the Identity & Authentication Framework.

    Attributes:
        user_id: Stable, unique identifier for this identity. Deliberately
            the same value space as ``authorization.models.User.user_id``
            for the demo users this sprint ships (see
            ``config/credentials.py``), which is what lets
            ``components/authorization.py`` resolve an
            :class:`~authorization.context.UserContext` from the
            ``user_id`` an authenticated session carries -- but the
            *type* here has no structural dependency on
            ``authorization.models.User`` at all.
        username: The login name presented at sign-in.
        display_name: Human-readable name shown in the UI.
        email: The identity's email address.
        tenant_id: The organization this identity's home tenant is. Carried
            here (not resolved from authorization) so the login screen and
            session panel can display "who, from where" without ever
            calling into the authorization package.
        status: Whether this identity is currently allowed to sign in.
        metadata: Optional, free-form extra data, mirroring the same
            "future extensibility" role every other value object's
            ``metadata`` mapping already plays in this codebase.

    Example:
        >>> identity = UserIdentity(
        ...     user_id="jane.doe", username="jane.doe", display_name="Jane Doe",
        ...     email="jane.doe@example.com", tenant_id="acme-retail",
        ... )
        >>> identity.is_active
        True
    """

    user_id: str
    username: str
    display_name: str
    email: str
    tenant_id: str
    status: IdentityStatus = IdentityStatus.ACTIVE
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Whether this identity is currently allowed to sign in."""
        return self.status == IdentityStatus.ACTIVE


class LoginStatus(str, Enum):
    """The outcome of a single sign-in attempt."""

    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class SessionInfo:
    """A single, active (or expired) authenticated session.

    Attributes:
        session_id: A unique, opaque identifier for this session (never
            the ``user_id`` itself, so a compromised or logged
            session id can't be trivially mapped back to an account).
        user_id: The identity this session belongs to.
        created_at: When the session was created (sign-in time).
        last_activity_at: When this session last had its activity
            recorded (see :class:`~identity.session.SessionManager`).
        expires_at: The instant after which this session is no longer
            valid. Recomputed on every activity update ("sliding"
            expiration), not fixed at creation time.

    Example:
        >>> from datetime import datetime, timedelta, timezone
        >>> now = datetime.now(timezone.utc)
        >>> session = SessionInfo(
        ...     session_id="abc123", user_id="jane.doe",
        ...     created_at=now, last_activity_at=now, expires_at=now + timedelta(minutes=30),
        ... )
        >>> session.is_expired
        False
    """

    session_id: str
    user_id: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        """Whether this session has passed its expiration instant."""
        return _utc_now() >= self.expires_at

    @property
    def remaining_seconds(self) -> float:
        """Seconds remaining before this session expires (never negative)."""
        return max(0.0, (self.expires_at - _utc_now()).total_seconds())


@dataclass(frozen=True)
class AuthenticationResult:
    """The outcome of a :meth:`~identity.service.AuthenticationService.sign_in` call.

    Bundles everything the UI layer needs from a single sign-in
    attempt -- the outcome, the resolved identity (on success), the
    newly created session (on success), and a business-friendly
    message -- so ``components/auth.py`` never has to make a second
    call just to learn "what session did signing in just create."

    Attributes:
        status: Whether this attempt succeeded.
        identity: The authenticated identity, or ``None`` on failure.
        session: The newly created session, or ``None`` on failure.
        message: A business-friendly, UI-ready message describing the
            outcome.
        timestamp: When this authentication attempt was resolved.
    """

    status: LoginStatus
    identity: UserIdentity | None
    session: SessionInfo | None
    message: str
    timestamp: datetime

    @property
    def is_success(self) -> bool:
        """Whether this authentication attempt succeeded."""
        return self.status == LoginStatus.SUCCESS


def _utc_now() -> datetime:
    """Return the current UTC time.

    A tiny local helper so ``identity/models.py`` has no dependency on
    any other package in this codebase, keeping it framework- and
    package-independent per Task 1.
    """
    return datetime.now(timezone.utc)
