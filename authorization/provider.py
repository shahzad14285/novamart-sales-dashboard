"""Authorization Provider abstraction for the NovaMart Permission-Based
Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 7.

:class:`~authorization.service.AuthorizationService` never stores or
looks up a user itself -- it delegates every bit of user resolution to
a **provider** satisfying the :class:`AuthorizationProvider` interface
(a structural ``typing.Protocol``, mirroring
``monitoring.provider.MonitoringProvider`` and
``services.ai_recommendation_service.RecommendationProvider``). The
service depends only on that interface, never on a concrete identity
store -- which is exactly what lets business services stay
"provider-independent" (Task 7's explicit requirement).

This sprint ships :class:`InMemoryAuthorizationProvider`, a
process-local, dependency-free default sufficient for a single-process
Streamlit deployment and for demonstrating the framework without a real
identity backend. Future providers -- a database, LDAP, OAuth, OpenID
Connect, Azure AD, Okta, Auth0 -- are added by writing one new class
that satisfies :class:`AuthorizationProvider` and registering it via
:meth:`~authorization.registry.AuthorizationProviderRegistry.register`.
Nothing in :class:`~authorization.service.AuthorizationService`, or in
any business service or UI call site, needs to change.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from authorization.models import User


@runtime_checkable
class AuthorizationProvider(Protocol):
    """Interface every user/identity backend must satisfy.

    A structural ``Protocol`` (Python's "duck typing with static-typing
    support"), so a class satisfies this interface simply by having
    compatible ``get_user``/``list_users`` methods -- no inheritance
    required. That's what lets a future ``DatabaseAuthorizationProvider``,
    ``LdapAuthorizationProvider``, or an OAuth/OIDC/Azure AD/Okta/Auth0
    -backed provider plug in without touching this module or subclassing
    anything defined here.
    """

    def get_user(self, user_id: str) -> User | None:
        """Look up a single user by id.

        Args:
            user_id: The user id to resolve.

        Returns:
            The matching :class:`~authorization.models.User`, or
            ``None`` if no user is known under that id.
        """
        ...

    def list_users(self, *, tenant_id: str | None = None) -> tuple[User, ...]:
        """Return every known user, optionally filtered to one tenant.

        Args:
            tenant_id: If given, only users belonging to this tenant.

        Returns:
            A tuple of matching users.
        """
        ...


class InMemoryAuthorizationProvider:
    """Default authorization provider: holds users in process memory.

    Sufficient for a single-process Streamlit deployment, for the demo
    user directory this sprint seeds via ``config/users.py``, and for
    tests. Thread-safe (guarded by a simple lock) since a Streamlit
    server may serve multiple sessions concurrently on the same process
    -- the same reasoning already applied to
    ``monitoring.provider.InMemoryMonitoringProvider``.

    Not persisted across restarts and not shared across multiple server
    processes -- exactly the gap a future database-, LDAP-, or OAuth/
    OIDC-backed provider is meant to close, with zero change required
    to :class:`~authorization.service.AuthorizationService` or any
    business service.

    Example:
        >>> provider = InMemoryAuthorizationProvider()
        >>> from authorization.models import User
        >>> provider.register_user(User(
        ...     user_id="jane.doe", username="jane.doe", display_name="Jane Doe",
        ...     email="jane.doe@example.com", tenant_id="acme-retail", roles=("business_analyst",),
        ... ))
        >>> provider.get_user("jane.doe").display_name
        'Jane Doe'
    """

    def __init__(self) -> None:
        """Create an empty in-memory authorization provider."""
        self._users: dict[str, User] = {}
        self._lock = threading.Lock()

    def register_user(self, user: User) -> None:
        """Register (or replace) a user under their ``user_id``.

        Mirrors ``tenancy.registry.TenantRegistry.register``: calling
        this again with an already-registered ``user_id`` replaces that
        user's record, which is useful for updating a user's roles or
        status without a separate "update" method.

        Args:
            user: The user to register.
        """
        with self._lock:
            self._users[user.user_id] = user

    def register_many(self, users: "tuple[User, ...] | list[User]") -> None:
        """Register every user in ``users``.

        Args:
            users: An iterable of users to register, typically the
                declarative list from ``config/users.py``.
        """
        for user in users:
            self.register_user(user)

    def get_user(self, user_id: str) -> User | None:
        """Look up a single user by id.

        Args:
            user_id: The user id to resolve.

        Returns:
            The matching user, or ``None`` if unknown.
        """
        with self._lock:
            return self._users.get(user_id)

    def list_users(self, *, tenant_id: str | None = None) -> tuple[User, ...]:
        """Return every registered user, optionally filtered to one tenant.

        Args:
            tenant_id: If given, only users belonging to this tenant.

        Returns:
            A tuple of matching users.
        """
        with self._lock:
            users = tuple(self._users.values())
        if tenant_id is not None:
            users = tuple(user for user in users if user.tenant_id == tenant_id)
        return users

    def clear(self) -> None:
        """Remove every registered user.

        Primarily useful for tests that need a clean provider rather
        than one accumulating users across an entire test run.
        """
        with self._lock:
            self._users.clear()
