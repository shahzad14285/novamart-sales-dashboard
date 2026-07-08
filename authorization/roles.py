"""Role Registry for the NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 4.

A :class:`Role` is a named, reusable bundle of permission keys -- the
Role-Based Access Control (RBAC) mechanism this framework uses to
*assign* permissions to users without listing every permission
individually on every :class:`~authorization.models.User` record.
Roles are, like permissions, plain string-keyed data registered into a
:class:`RoleRegistry` (mirroring ``tenancy.registry.TenantRegistry`` and
``authorization.permissions.PermissionRegistry``) rather than a closed
``Enum`` -- Task 11's "new roles can be added without changing
services" requirement is a structural guarantee here, not a promise:
a brand-new role is one :meth:`RoleRegistry.register` call away, from
any module, at any time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from authorization.permissions import (
    EXPORT_DATA,
    GENERATE_PDF,
    GENERATE_REPORTS,
    MANAGE_TENANTS,
    MANAGE_USERS,
    UPLOAD_DATA,
    USE_AI_RECOMMENDATIONS,
    VIEW_DASHBOARD,
    VIEW_REPORTS,
)

# --------------------------------------------------------------------------
# Well-known role keys.
# --------------------------------------------------------------------------
SYSTEM_ADMINISTRATOR = "system_administrator"
TENANT_ADMINISTRATOR = "tenant_administrator"
BUSINESS_ANALYST = "business_analyst"
EXECUTIVE_VIEWER = "executive_viewer"

# A sentinel permission key meaning "every permission currently
# registered in the PermissionRegistry", expanded dynamically by
# AuthorizationService.resolve_effective_permissions() at resolution
# time -- not a fixed list baked in here. This is what lets a brand-new
# permission (Task 3) automatically flow to System Administrators the
# moment it's registered, with zero change to this file.
ALL_PERMISSIONS_WILDCARD = "*"


@dataclass(frozen=True)
class Role:
    """A named, reusable bundle of permission keys (RBAC).

    Attributes:
        key: The stable identifier used everywhere a role needs to be
            assigned, looked up, or logged (e.g.
            ``"business_analyst"``).
        display_name: Human-readable name shown in the UI (e.g.
            ``"Business Analyst"``).
        permissions: The permission keys this role grants. May contain
            :data:`ALL_PERMISSIONS_WILDCARD` instead of an explicit
            list, meaning "every permission currently registered" --
            see :class:`~authorization.permissions.PermissionRegistry`.
        description: A short, human-readable explanation of who this
            role is for, suitable for an admin-facing role management
            screen.
    """

    key: str
    display_name: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    description: str = ""


class RoleRegistry:
    """A registry of every role known to the platform.

    Mirrors :class:`~authorization.permissions.PermissionRegistry` and
    ``tenancy.registry.TenantRegistry``: a generic lookup table with no
    role-specific behavior baked in. *Which* roles exist, and what each
    one grants, is declared once via :meth:`register` calls (see
    :func:`register_default_roles` below) -- never a hardcoded
    ``if role == "...":`` branch anywhere in the codebase.

    Example:
        >>> registry = RoleRegistry()
        >>> registry.register(Role("executive_viewer", "Executive Viewer", frozenset({"view_dashboard"})))
        >>> registry.get("executive_viewer").display_name
        'Executive Viewer'

        # Onboarding a brand-new role later, without touching this class
        # or any business service:
        >>> registry.register(Role("finance_auditor", "Finance Auditor", frozenset({"view_reports", "export_data"})))
    """

    def __init__(self) -> None:
        """Create an empty role registry."""
        self._roles: dict[str, Role] = {}

    def register(self, role: Role) -> None:
        """Register (or replace) a role under its ``key``.

        Calling this again with an already-registered key replaces
        that role's permission set -- useful for adjusting what an
        existing role grants without a separate "update" method.

        Args:
            role: The role to register.
        """
        self._roles[role.key] = role

    def register_many(self, roles: "tuple[Role, ...] | list[Role]") -> None:
        """Register every role in ``roles``.

        Args:
            roles: An iterable of roles to register, typically
                :data:`DEFAULT_ROLES`.
        """
        for role in roles:
            self.register(role)

    def get(self, key: str) -> Role | None:
        """Look up a role by key.

        Args:
            key: The role key to look up.

        Returns:
            The matching :class:`Role`, or ``None`` if no role is
            registered under that key.
        """
        return self._roles.get(key)

    def exists(self, key: str) -> bool:
        """Return ``True`` if ``key`` matches a registered role."""
        return key in self._roles

    def all_roles(self) -> tuple[Role, ...]:
        """Return every registered role, in registration order."""
        return tuple(self._roles.values())

    def all_keys(self) -> tuple[str, ...]:
        """Return every registered role key, sorted."""
        return tuple(sorted(self._roles.keys()))

    def clear(self) -> None:
        """Remove every registered role.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._roles.clear()


# The four default roles this sprint's ticket calls out by name (Task 4).
# Adding a fifth later is one new Role(...) entry here (or a
# `role_registry.register(...)` call from anywhere else, such as a future
# `config/roles.py`) -- never a change to any business service, which
# never references this tuple directly.
DEFAULT_ROLES: tuple[Role, ...] = (
    Role(
        key=SYSTEM_ADMINISTRATOR,
        display_name="System Administrator",
        permissions=frozenset({ALL_PERMISSIONS_WILDCARD}),
        description="Full platform access, across every tenant and every capability.",
    ),
    Role(
        key=TENANT_ADMINISTRATOR,
        display_name="Tenant Administrator",
        permissions=frozenset(
            {
                MANAGE_TENANTS,
                MANAGE_USERS,
                UPLOAD_DATA,
                VIEW_DASHBOARD,
                VIEW_REPORTS,
                GENERATE_REPORTS,
                GENERATE_PDF,
                EXPORT_DATA,
                USE_AI_RECOMMENDATIONS,
            }
        ),
        description="Manages their own organization's configuration, users, and reporting.",
    ),
    Role(
        key=BUSINESS_ANALYST,
        display_name="Business Analyst",
        permissions=frozenset(
            {
                UPLOAD_DATA,
                VIEW_DASHBOARD,
                VIEW_REPORTS,
                GENERATE_REPORTS,
                USE_AI_RECOMMENDATIONS,
                GENERATE_PDF,
                EXPORT_DATA,
            }
        ),
        description="Uploads data and works with dashboards, reports, and recommendations day to day.",
    ),
    Role(
        key=EXECUTIVE_VIEWER,
        display_name="Executive Viewer",
        permissions=frozenset({VIEW_DASHBOARD, VIEW_REPORTS}),
        description="Read-only access to dashboards and reports; cannot generate, export, or upload.",
    ),
)


def register_default_roles(registry: "RoleRegistry") -> None:
    """Register every role in :data:`DEFAULT_ROLES` into ``registry``.

    Called once, below, at import time against the shared
    :data:`role_registry` -- mirroring
    ``config.tenants.register_default_tenants()``. A test that needs a
    clean registry can call this against its own fresh
    :class:`RoleRegistry` instance instead.

    Args:
        registry: The registry to populate.
    """
    registry.register_many(DEFAULT_ROLES)


# A shared, ready-to-use registry -- mirrors
# ``authorization.permissions.permission_registry`` and
# ``tenancy.registry.tenant_registry``. Pre-populated with the four
# default roles this sprint's ticket requires, so the platform has a
# working role catalogue the moment this module is imported, with zero
# configuration required.
role_registry = RoleRegistry()
register_default_roles(role_registry)
