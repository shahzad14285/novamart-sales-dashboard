"""NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework.

A framework-agnostic package (no Streamlit dependency) implementing
centralized, permission-based authorization with Role-Based Access
Control (RBAC) as the permission-assignment mechanism. See
``docs/AUTHORIZATION_ARCHITECTURE.md`` for the full design.

Re-exports every public symbol so callers can write, e.g.::

    from authorization import authorization_service, PermissionDeniedError
    from authorization.permissions import VIEW_DASHBOARD

instead of reaching into individual submodules.
"""

from __future__ import annotations

from authorization.context import UserContext
from authorization.exceptions import (
    AuthorizationError,
    CrossTenantAccessError,
    InactiveUserError,
    MissingUserContextError,
    NoActiveProviderError,
    PermissionDeniedError,
    ProviderNotRegisteredError,
    UnknownPermissionError,
    UnknownRoleError,
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
    permission_registry,
)
from authorization.provider import AuthorizationProvider, InMemoryAuthorizationProvider
from authorization.registry import AuthorizationProviderRegistry, authorization_provider_registry
from authorization.roles import (
    ALL_PERMISSIONS_WILDCARD,
    BUSINESS_ANALYST,
    DEFAULT_ROLES,
    EXECUTIVE_VIEWER,
    Role,
    RoleRegistry,
    SYSTEM_ADMINISTRATOR,
    TENANT_ADMINISTRATOR,
    role_registry,
)
from authorization.service import AuthorizationService, authorization_service

__all__ = [
    "ALL_PERMISSIONS_WILDCARD",
    "AuthorizationError",
    "AuthorizationProvider",
    "AuthorizationProviderRegistry",
    "AuthorizationService",
    "BUSINESS_ANALYST",
    "CrossTenantAccessError",
    "DEFAULT_PERMISSIONS",
    "DEFAULT_ROLES",
    "EXECUTIVE_VIEWER",
    "EXPORT_DATA",
    "GENERATE_PDF",
    "GENERATE_REPORTS",
    "InMemoryAuthorizationProvider",
    "InactiveUserError",
    "MANAGE_PLATFORM",
    "MANAGE_TENANTS",
    "MANAGE_USERS",
    "MissingUserContextError",
    "NoActiveProviderError",
    "Permission",
    "PermissionDeniedError",
    "PermissionRegistry",
    "ProviderNotRegisteredError",
    "Role",
    "RoleRegistry",
    "SYSTEM_ADMINISTRATOR",
    "TENANT_ADMINISTRATOR",
    "UPLOAD_DATA",
    "USE_AI_RECOMMENDATIONS",
    "UnknownPermissionError",
    "UnknownRoleError",
    "UnknownUserError",
    "User",
    "UserContext",
    "UserStatus",
    "VIEW_DASHBOARD",
    "VIEW_MONITORING",
    "VIEW_REPORTS",
    "authorization_provider_registry",
    "authorization_service",
    "permission_registry",
    "role_registry",
]
