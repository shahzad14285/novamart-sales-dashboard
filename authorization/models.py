"""User model for the NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 2.

A :class:`User` is a plain, immutable value object describing one
person authorized to use the platform. It carries no behavior beyond
its own field types -- no database access, no permission resolution
logic -- matching the value-object convention already established by
``tenancy.models.Tenant``, ``monitoring.models.MonitoringEvent``, and
every other value object in this codebase. Resolving a user's
*effective* permissions (combining role-granted and directly-assigned
permissions) is the job of :class:`~authorization.service.AuthorizationService`,
never this model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class UserStatus(str, Enum):
    """Whether a user is currently allowed to use the platform.

    A plain ``str`` subclass (matching ``tenancy.models.TenantStatus``
    and ``monitoring.models.EventStatus``), so a member compares equal
    to, and can be constructed from, its underlying string value.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class User:
    """A person authorized to use the NovaMart platform.

    Attributes:
        user_id: Stable, unique identifier for the user (e.g.
            ``"jane.doe"``). Used as the key everywhere a user needs to
            be looked up or logged -- never the display name, which may
            change.
        username: Short, machine-friendly login name. Distinct from
            ``user_id`` only in that a future implementation could
            rotate ``user_id`` (a database key or external identity
            provider subject id) while keeping ``username`` stable, or
            vice versa; today they are typically the same value.
        display_name: Human-readable name shown in the UI (e.g.
            ``"Jane Doe"``).
        email: The user's email address.
        tenant_id: The single organization this user belongs to. A user
            is always scoped to exactly one tenant in this release --
            see ``docs/AUTHORIZATION_ARCHITECTURE.md`` for how this
            enforces tenant isolation alongside
            ``tenancy.context.TenantContext``.
        roles: Role keys assigned to this user (must match keys
            registered in :class:`~authorization.roles.RoleRegistry`).
            Each role expands to a set of permissions at resolution
            time -- see :meth:`~authorization.service.AuthorizationService.resolve_effective_permissions`.
        permissions: Permission keys granted to this user directly, on
            top of whatever their roles already grant (must match keys
            registered in :class:`~authorization.permissions.PermissionRegistry`).
            Lets a single user be given one extra capability without
            requiring a brand-new role to be defined for them.
        status: Whether the user is currently active. Defaults to
            :attr:`UserStatus.ACTIVE`.
        metadata: Optional, free-form extra data (e.g. a job title, a
            department, a preferred locale) that lets future
            requirements attach new information to a user *without*
            requiring a change to this model or to any service that
            already depends on it -- the same "future expansion" role
            ``tenancy.models.Tenant.metadata`` already plays.

    Example:
        >>> user = User(
        ...     user_id="jane.doe",
        ...     username="jane.doe",
        ...     display_name="Jane Doe",
        ...     email="jane.doe@example.com",
        ...     tenant_id="acme-retail",
        ...     roles=("business_analyst",),
        ... )
        >>> user.is_active
        True
    """

    user_id: str
    username: str
    display_name: str
    email: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    status: UserStatus = UserStatus.ACTIVE
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Whether this user is currently allowed to use the platform."""
        return self.status == UserStatus.ACTIVE
