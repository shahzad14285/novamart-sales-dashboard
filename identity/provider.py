"""Authentication Provider abstraction for the NovaMart Identity &
Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Task 4.

:class:`~identity.service.AuthenticationService` never stores or
checks a credential itself -- it delegates every bit of identity
verification to a **provider** satisfying the
:class:`AuthenticationProvider` interface (a structural
``typing.Protocol``, mirroring
``authorization.provider.AuthorizationProvider`` and
``monitoring.provider.MonitoringProvider``). The service depends only
on that interface, never on a concrete identity store -- which is
exactly what lets business services (and the UI layer) stay
"provider-independent" (Task 4's explicit requirement).

This sprint ships :class:`InMemoryAuthenticationProvider`, a
process-local, dependency-free default seeded from the existing demo
users (via ``config/credentials.py``) and sufficient for demonstrating
the framework without a real identity backend. Future providers -- a
database, LDAP, OAuth, OpenID Connect, Microsoft Entra ID, Google
Identity, Okta, Auth0 -- are added by writing one new class that
satisfies :class:`AuthenticationProvider` and registering it via
:meth:`~identity.registry.AuthenticationProviderRegistry.register`.
Nothing in :class:`~identity.service.AuthenticationService`, or in any
business service or UI call site, needs to change.

No password hashing in this release, by design
---------------------------------------------------
Passwords are compared as plain strings. This is an explicit, called-out
scope decision (see the ticket's Task 7: "Do not implement password
encryption... The objective is architecture, not production security."),
not an oversight -- a future ``DatabaseAuthenticationProvider`` would
be the natural place to introduce salted password hashing, entirely
behind this same :class:`AuthenticationProvider` interface, with zero
change to :class:`~identity.service.AuthenticationService`.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from identity.models import UserIdentity


@runtime_checkable
class AuthenticationProvider(Protocol):
    """Interface every identity/credential backend must satisfy.

    A structural ``Protocol`` (Python's "duck typing with static-typing
    support"), so a class satisfies this interface simply by having
    compatible ``verify_credentials``/``get_identity`` methods -- no
    inheritance required. That's what lets a future
    ``DatabaseAuthenticationProvider``, ``LdapAuthenticationProvider``,
    or an OAuth/OIDC/Entra ID/Google Identity/Okta/Auth0-backed
    provider plug in without touching this module or subclassing
    anything defined here.
    """

    def verify_credentials(self, username: str, password: str) -> UserIdentity | None:
        """Check a username/password pair and return the matching identity.

        Args:
            username: The submitted login name.
            password: The submitted password, in plain text (see the
                module docstring for why this release compares
                passwords unhashed).

        Returns:
            The matching :class:`~identity.models.UserIdentity` if the
            credentials check out, or ``None`` if the username is
            unknown or the password does not match. Deliberately
            *not* distinguished by return type -- see
            ``identity.exceptions.InvalidCredentialsError``'s
            docstring for why.
        """
        ...

    def get_identity(self, user_id: str) -> UserIdentity | None:
        """Look up a single identity by id, independent of credentials.

        Used after a session has already been established (i.e. the
        password was already verified once, at sign-in) to re-resolve
        "who does this session belong to" on every subsequent request,
        without asking for a password again.

        Args:
            user_id: The identity id to resolve.

        Returns:
            The matching :class:`~identity.models.UserIdentity`, or
            ``None`` if no identity is known under that id.
        """
        ...


class InMemoryAuthenticationProvider:
    """Default authentication provider: holds identities and demo passwords in process memory.

    Sufficient for a single-process Streamlit deployment, for the demo
    identity directory this sprint seeds via ``config/credentials.py``,
    and for tests. Thread-safe (guarded by a simple lock) since a
    Streamlit server may serve multiple sessions concurrently on the
    same process -- the same reasoning already applied to
    ``authorization.provider.InMemoryAuthorizationProvider`` and
    ``monitoring.provider.InMemoryMonitoringProvider``.

    Not persisted across restarts and not shared across multiple server
    processes -- exactly the gap a future database-, LDAP-, or OAuth/
    OIDC-backed provider is meant to close, with zero change required
    to :class:`~identity.service.AuthenticationService` or any business
    service.

    Example:
        >>> provider = InMemoryAuthenticationProvider()
        >>> from identity.models import UserIdentity
        >>> provider.register_identity(
        ...     UserIdentity(
        ...         user_id="jane.doe", username="jane.doe", display_name="Jane Doe",
        ...         email="jane.doe@example.com", tenant_id="acme-retail",
        ...     ),
        ...     password="demo123",
        ... )
        >>> provider.verify_credentials("jane.doe", "demo123").display_name
        'Jane Doe'
        >>> provider.verify_credentials("jane.doe", "wrong-password") is None
        True
    """

    def __init__(self) -> None:
        """Create an empty in-memory authentication provider."""
        self._identities: dict[str, UserIdentity] = {}
        self._passwords: dict[str, str] = {}
        self._lock = threading.Lock()

    def register_identity(self, identity: UserIdentity, password: str) -> None:
        """Register (or replace) an identity and its demo password.

        Mirrors ``authorization.provider.InMemoryAuthorizationProvider.register_user``:
        calling this again with an already-registered ``user_id``
        replaces that identity's record and password, useful for
        updating a demo account without a separate "update" method.

        Args:
            identity: The identity to register.
            password: The plain-text demo password for this identity.
        """
        with self._lock:
            self._identities[identity.username] = identity
            self._passwords[identity.username] = password

    def register_many(self, entries: "tuple[tuple[UserIdentity, str], ...] | list[tuple[UserIdentity, str]]") -> None:
        """Register every ``(identity, password)`` pair in ``entries``.

        Args:
            entries: An iterable of ``(identity, password)`` pairs,
                typically the declarative list from
                ``config/credentials.py``.
        """
        for identity, password in entries:
            self.register_identity(identity, password)

    def verify_credentials(self, username: str, password: str) -> UserIdentity | None:
        """Check a username/password pair and return the matching identity.

        Args:
            username: The submitted login name.
            password: The submitted password.

        Returns:
            The matching identity if ``username`` is registered and
            ``password`` matches exactly, otherwise ``None``.
        """
        with self._lock:
            identity = self._identities.get(username)
            expected_password = self._passwords.get(username)
        if identity is None or expected_password is None:
            return None
        if password != expected_password:
            return None
        return identity

    def get_identity(self, user_id: str) -> UserIdentity | None:
        """Look up a single identity by id.

        Args:
            user_id: The identity id to resolve.

        Returns:
            The matching identity, or ``None`` if unknown.
        """
        with self._lock:
            for identity in self._identities.values():
                if identity.user_id == user_id:
                    return identity
        return None

    def clear(self) -> None:
        """Remove every registered identity and password.

        Primarily useful for tests that need a clean provider rather
        than one accumulating identities across an entire test run.
        """
        with self._lock:
            self._identities.clear()
            self._passwords.clear()
