"""Centralized User Context for the NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 6.

:class:`UserContext` is the single source of truth for "which user is
this unit of work being performed by, and what are they currently
allowed to do". It carries at most one
:class:`~authorization.models.User` plus that user's already-resolved
effective permissions; it does not know about Streamlit, sessions, or
any particular service -- exactly mirroring
``tenancy.context.TenantContext``'s shape and role.

This context is designed to **flow alongside** the existing
:class:`~tenancy.context.TenantContext`, not replace or embed it: a
unit of work is scoped by *both* "which organization" (``TenantContext``)
and "which user, with which permissions" (``UserContext``) at once, and
the two are resolved and passed together by callers, exactly as the
Target Architecture diagram in ``docs/AUTHORIZATION_ARCHITECTURE.md``
shows (``Tenant Context`` -> ``Authorization Service`` -> ``Permission
Registry`` -> ``Business Services``).

Why this is a plain class, not a global singleton
----------------------------------------------------
The same reasoning ``tenancy.context.TenantContext`` documents applies
here unchanged: a Streamlit server process serves multiple concurrent
browser sessions from the same Python process, so a module-level
"current user" would leak one session's identity and permissions into
another's request. ``UserContext`` is instantiated per unit of work
(per Streamlit session -- see ``components/authorization.py``, which
stores the selected user id in ``st.session_state``) and passed
explicitly into each call site that needs it.
"""

from __future__ import annotations

from authorization.models import User


class UserContext:
    """Holds the user (and their resolved permissions) a unit of work is scoped to.

    Immutable by convention (nothing here mutates its fields after
    construction) -- to change users, construct a new
    :class:`UserContext` rather than reassigning an existing one, so a
    reference held by one part of the app can never unexpectedly start
    pointing at a different user.

    Example:
        >>> context = UserContext(user=my_user, effective_permissions=frozenset({"view_dashboard"}))
        >>> context.has_user()
        True
        >>> context.has_permission("view_dashboard")
        True
        >>> context.has_permission("export_data")
        False

        >>> empty = UserContext.empty()
        >>> empty.has_user()
        False
    """

    def __init__(self, user: User | None = None, effective_permissions: frozenset[str] = frozenset()) -> None:
        """Create a user context, optionally already bound to a user.

        Args:
            user: The active user for this context, or ``None`` for an
                empty context (e.g. before a user has been resolved, or
                in an unauthenticated request).
            effective_permissions: The full set of permission keys this
                user currently holds -- the union of every permission
                their assigned roles grant plus any permissions granted
                to them directly. Always pre-resolved by
                :class:`~authorization.service.AuthorizationService`
                before a :class:`UserContext` is constructed; this
                class never computes it itself (Separation of Concerns).
        """
        self._user = user
        self._effective_permissions = frozenset(effective_permissions)

    @property
    def user(self) -> User | None:
        """The bound user, or ``None`` if this context is empty."""
        return self._user

    @property
    def effective_permissions(self) -> frozenset[str]:
        """The full set of permission keys currently available to this user."""
        return self._effective_permissions

    def has_user(self) -> bool:
        """Return ``True`` if a user is bound to this context (active or not)."""
        return self._user is not None

    def has_permission(self, permission: str) -> bool:
        """Return ``True`` if this context's effective permissions include ``permission``.

        Args:
            permission: The permission key to check.
        """
        return permission in self._effective_permissions

    @classmethod
    def for_user(cls, user: User, effective_permissions: frozenset[str]) -> "UserContext":
        """Build a context already bound to ``user`` with pre-resolved permissions."""
        return cls(user=user, effective_permissions=effective_permissions)

    @classmethod
    def empty(cls) -> "UserContext":
        """Build a context bound to no user (every permission check will fail)."""
        return cls(user=None, effective_permissions=frozenset())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        user_id = self._user.user_id if self._user else None
        return f"UserContext(user_id={user_id!r}, permissions={sorted(self._effective_permissions)!r})"
