"""Permission Registry for the NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 3.

A :class:`Permission` is a plain, immutable value object -- a stable
string ``key`` plus a human-readable ``description``. Permissions are
declared as **plain string keys**, not a closed Python ``Enum``,
specifically so Task 3's "future custom permissions" requirement is a
structural guarantee rather than a promise: a brand-new permission is
one :meth:`PermissionRegistry.register` call away, at any time, from
any module -- never a change to this file's source and never a change
to an ``Enum``'s fixed member list.

Business services never hardcode a permission string inline (Task 3:
"Avoid hardcoded permission checks inside business services") -- they
never check permissions at all. Only
:class:`~authorization.service.AuthorizationService.require_permission`
(called from the UI/orchestration layer, see
``docs/AUTHORIZATION_ARCHITECTURE.md``) ever compares a permission key
against a user's effective permissions, and it always validates that
key is a *registered* one first via this registry, which is what turns
a typo'd permission key into an immediate, loud configuration error
instead of a silent, always-denied (or worse, always-granted) check.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Well-known permission keys.
#
# Plain string constants, not an Enum -- see the module docstring for why.
# Every business capability this sprint's ticket calls out gets one key
# here; a future capability is simply one more constant plus one more
# `permission_registry.register(...)` call in `register_default_permissions()`
# below, never a change to any service.
# --------------------------------------------------------------------------
VIEW_DASHBOARD = "view_dashboard"
VIEW_REPORTS = "view_reports"
GENERATE_REPORTS = "generate_reports"
EXPORT_DATA = "export_data"
GENERATE_PDF = "generate_pdf"
USE_AI_RECOMMENDATIONS = "use_ai_recommendations"
UPLOAD_DATA = "upload_data"
VIEW_MONITORING = "view_monitoring"
VIEW_AUTOMATION = "view_automation"
MANAGE_USERS = "manage_users"
MANAGE_TENANTS = "manage_tenants"
MANAGE_PLATFORM = "manage_platform"


@dataclass(frozen=True)
class Permission:
    """One capability a user can be granted, directly or via a role.

    Attributes:
        key: The stable identifier used everywhere a permission needs
            to be checked, logged, or assigned to a role/user (e.g.
            ``"export_data"``). Never shown to an end user directly.
        description: A short, human-readable explanation of what this
            permission allows, suitable for an admin-facing role/
            permission management screen.
    """

    key: str
    description: str


class PermissionRegistry:
    """A registry of every permission known to the platform.

    Mirrors the registry pattern already used throughout this codebase
    -- ``tenancy.registry.TenantRegistry``,
    ``monitoring.registry.MonitoringProviderRegistry`` -- so declaring a
    new permission is the same kind of operation as onboarding a new
    tenant or monitoring provider: one ``register()`` call with a plain
    data object, never a hardcoded ``if permission == "...":`` branch
    anywhere in the codebase.

    Example:
        >>> registry = PermissionRegistry()
        >>> registry.register(Permission("view_dashboard", "View the sales dashboard"))
        >>> registry.exists("view_dashboard")
        True

        # A brand-new, future permission is one call away, from anywhere:
        >>> registry.register(Permission("manage_billing", "Manage billing and invoices"))
    """

    def __init__(self) -> None:
        """Create an empty permission registry."""
        self._permissions: dict[str, Permission] = {}

    def register(self, permission: Permission) -> None:
        """Register (or replace) a permission under its ``key``.

        Calling this again with an already-registered key replaces
        that permission's description -- useful for correcting a
        description without needing a separate "update" method.

        Args:
            permission: The permission to register.
        """
        self._permissions[permission.key] = permission

    def register_many(self, permissions: "tuple[Permission, ...] | list[Permission]") -> None:
        """Register every permission in ``permissions``.

        Args:
            permissions: An iterable of permissions to register,
                typically :data:`DEFAULT_PERMISSIONS`.
        """
        for permission in permissions:
            self.register(permission)

    def get(self, key: str) -> Permission | None:
        """Look up a permission by key.

        Args:
            key: The permission key to look up.

        Returns:
            The matching :class:`Permission`, or ``None`` if no
            permission is registered under that key.
        """
        return self._permissions.get(key)

    def exists(self, key: str) -> bool:
        """Return ``True`` if ``key`` matches a registered permission."""
        return key in self._permissions

    def all_permissions(self) -> tuple[Permission, ...]:
        """Return every registered permission, in registration order."""
        return tuple(self._permissions.values())

    def all_keys(self) -> tuple[str, ...]:
        """Return every registered permission key, sorted.

        Used by :class:`~authorization.service.AuthorizationService` to
        expand a role's ``"*"`` (all permissions) wildcard -- see
        :mod:`authorization.roles`.
        """
        return tuple(sorted(self._permissions.keys()))

    def clear(self) -> None:
        """Remove every registered permission.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._permissions.clear()


# The eleven permissions this sprint's ticket calls out by name (Task 3).
# Adding a twelfth later is one new Permission(...) entry here (or a
# `permission_registry.register(...)` call from anywhere else, such as a
# future `config/permissions.py`) -- never a change to any business
# service, which never references this tuple directly.
DEFAULT_PERMISSIONS: tuple[Permission, ...] = (
    Permission(VIEW_DASHBOARD, "View the sales dashboard, KPIs, and executive analytics."),
    Permission(VIEW_REPORTS, "View an assembled executive report."),
    Permission(GENERATE_REPORTS, "Generate a new executive report from the current dataset."),
    Permission(EXPORT_DATA, "Export the underlying dataset as CSV, Excel, or JSON."),
    Permission(GENERATE_PDF, "Generate a PDF export of an assembled report."),
    Permission(USE_AI_RECOMMENDATIONS, "View AI-generated business recommendations."),
    Permission(UPLOAD_DATA, "Upload a new sales dataset."),
    Permission(VIEW_MONITORING, "View the platform's operational health and monitoring dashboard."),
    Permission(VIEW_AUTOMATION, "View the platform's automation events, scheduled jobs, and notification history."),
    Permission(MANAGE_USERS, "Create, update, or deactivate user accounts."),
    Permission(MANAGE_TENANTS, "View and manage tenant (organization) configuration."),
    Permission(MANAGE_PLATFORM, "Full platform administration, including all other permissions."),
)


def register_default_permissions(registry: "PermissionRegistry") -> None:
    """Register every permission in :data:`DEFAULT_PERMISSIONS` into ``registry``.

    Called once, below, at import time against the shared
    :data:`permission_registry` -- mirroring
    ``config.tenants.register_default_tenants()``. A test that needs a
    clean registry can call this against its own fresh
    :class:`PermissionRegistry` instance instead.

    Args:
        registry: The registry to populate.
    """
    registry.register_many(DEFAULT_PERMISSIONS)


# A shared, ready-to-use registry -- mirrors ``tenancy.registry.tenant_registry``.
# Pre-populated with every permission this sprint's ticket requires, so
# the platform has a working permission catalogue the moment this module
# is imported, with zero configuration required.
permission_registry = PermissionRegistry()
register_default_permissions(permission_registry)
