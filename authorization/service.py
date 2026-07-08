"""Authorization Service for the NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Tasks 5, 6, 10.

The single entry point every UI/orchestration call site uses to
resolve a user's permissions and gate access to a capability. This
module has exactly one responsibility -- authorization -- and
deliberately does nothing else.

The Authorization Service does NOT:
    - Decide *how* users are stored or looked up (that's an
      :class:`~authorization.provider.AuthorizationProvider`, injected
      in -- see "Dependency Injection" below).
    - Validate or resolve tenants (that's ``tenancy.context``); it only
      cross-checks that a resolved user actually belongs to the tenant
      a request is scoped to (tenant isolation -- see
      :meth:`AuthorizationService.build_context`).
    - Contain any business logic. Every business service call site
      this framework protects assumes authorization has *already*
      happened before it runs (see the Target Architecture in
      ``docs/AUTHORIZATION_ARCHITECTURE.md``) -- this service is called
      from the UI/orchestration layer, never from inside
      ``services/*.py`` or ``utils/*.py``.
    - Ever let an observability failure become an authorization
      failure, or vice versa: monitoring events are recorded on a
      best-effort basis via the same resilient
      ``MonitoringService._store()`` guarantee Sprint 6.4 already
      established -- an outage in monitoring can never block or grant
      access.

Dependency Injection
----------------------
:class:`AuthorizationService` never hard-codes which provider, role
registry, or permission registry it uses. Its constructor accepts all
three as optional arguments; when omitted, each defaults to the
shared, application-wide instance. This is what lets:

- Tests inject a fresh, isolated provider/registries instead of
  sharing the application-wide ones.
- A future deployment swap from
  :class:`~authorization.provider.InMemoryAuthorizationProvider` to a
  database-, LDAP-, or OAuth/OIDC/Azure AD/Okta/Auth0-backed provider
  by registering it and calling
  :meth:`~authorization.registry.AuthorizationProviderRegistry.set_active`
  -- zero changes to this class or to any UI call site that uses it.
"""

from __future__ import annotations

import logging

from authorization.context import UserContext
from authorization.exceptions import (
    CrossTenantAccessError,
    InactiveUserError,
    MissingUserContextError,
    PermissionDeniedError,
    UnknownPermissionError,
    UnknownUserError,
)
from authorization.models import User, UserStatus
from authorization.permissions import permission_registry as default_permission_registry
from authorization.permissions import PermissionRegistry
from authorization.provider import AuthorizationProvider
from authorization.registry import authorization_provider_registry
from authorization.roles import ALL_PERMISSIONS_WILDCARD, role_registry as default_role_registry
from authorization.roles import RoleRegistry
from monitoring.service import monitoring_service
from tenancy.context import TenantContext

logger = logging.getLogger("novamart.authorization")

_SERVICE_NAME = "AuthorizationService"


class AuthorizationService:
    """Centralized resolution and enforcement point for user permissions.

    Example:
        >>> service = AuthorizationService()
        >>> user_context = service.build_context("jane.doe", tenant_context)
        >>> service.require_permission(
        ...     user_context, "export_data", service_name="ExportService", operation="export",
        ...     tenant_context=tenant_context,
        ... )
        User(user_id='jane.doe', ...)
    """

    def __init__(
        self,
        provider: AuthorizationProvider | None = None,
        role_registry: RoleRegistry | None = None,
        permission_registry: PermissionRegistry | None = None,
    ) -> None:
        """Create an Authorization Service.

        Args:
            provider: The identity backend used to resolve users. When
                omitted (the normal case for application code), the
                currently active provider from
                :data:`~authorization.registry.authorization_provider_registry`
                is used. Tests and future callers can inject any other
                object satisfying
                :class:`~authorization.provider.AuthorizationProvider`.
            role_registry: The role catalogue used to expand a user's
                roles into permissions. Defaults to the shared
                :data:`~authorization.roles.role_registry`.
            permission_registry: The permission catalogue used to
                validate permission keys and expand the "all
                permissions" wildcard. Defaults to the shared
                :data:`~authorization.permissions.permission_registry`.
        """
        self._provider: AuthorizationProvider = provider if provider is not None else authorization_provider_registry.get_active()
        self._role_registry: RoleRegistry = role_registry if role_registry is not None else default_role_registry
        self._permission_registry: PermissionRegistry = (
            permission_registry if permission_registry is not None else default_permission_registry
        )

    # ------------------------------------------------------------------
    # Resolution -- Task 5 ("resolve user permissions", "resolve role mappings")
    # ------------------------------------------------------------------
    def resolve_user(self, user_id: str) -> User:
        """Look up a user by id via the configured provider.

        Args:
            user_id: The user id to resolve.

        Returns:
            The matching :class:`~authorization.models.User`.

        Raises:
            UnknownUserError: If no user is known under ``user_id``.
        """
        user = self._provider.get_user(user_id)
        if user is None:
            raise UnknownUserError(user_id)
        return user

    def resolve_effective_permissions(self, user: User) -> frozenset[str]:
        """Compute the full set of permissions ``user`` currently holds.

        The union of every permission granted by each of ``user.roles``
        (expanded via the role registry -- a role listing
        :data:`~authorization.roles.ALL_PERMISSIONS_WILDCARD` expands to
        *every currently registered* permission, not a fixed snapshot,
        so a brand-new permission automatically reaches System
        Administrators the moment it's registered) plus any permissions
        granted to the user directly via ``user.permissions``.

        Args:
            user: The user to resolve permissions for.

        Returns:
            The frozen set of every permission key this user currently
            holds, directly or via a role. Unknown role/permission keys
            on the user record are skipped rather than raised (a stale
            or misconfigured assignment must never crash a permission
            check; see ``docs/AUTHORIZATION_ARCHITECTURE.md`` for the
            rationale), but are logged as a warning for visibility.
        """
        resolved: set[str] = set()

        for role_key in user.roles:
            role = self._role_registry.get(role_key)
            if role is None:
                logger.warning("User %s references unknown role '%s' -- skipped.", user.user_id, role_key)
                continue
            if ALL_PERMISSIONS_WILDCARD in role.permissions:
                resolved.update(self._permission_registry.all_keys())
            else:
                resolved.update(role.permissions)

        for permission_key in user.permissions:
            if not self._permission_registry.exists(permission_key):
                logger.warning(
                    "User %s is directly granted unknown permission '%s' -- skipped.", user.user_id, permission_key
                )
                continue
            resolved.add(permission_key)

        return frozenset(resolved)

    def build_context(self, user_id: str, tenant_context: TenantContext | None = None) -> UserContext:
        """Resolve a user and their effective permissions into a :class:`UserContext`.

        This is the single place a :class:`~authorization.context.UserContext`
        is ever constructed from a user id -- every UI call site that
        needs "the current user" should go through this method (or the
        session-scoped ``components.authorization`` helper built on top
        of it), never build a ``UserContext`` by hand.

        Args:
            user_id: The user id to resolve (in this release, selected
                via the demo user switcher -- see
                ``components/authorization.py``; a future
                authentication integration would supply this from a
                verified session/token instead, with no change to this
                method's contract).
            tenant_context: The active tenant this request is scoped
                to, if any. When both a user and a tenant are resolved,
                the user's own ``tenant_id`` must match the tenant
                context's tenant -- enforcing tenant isolation (Task
                11) at the authorization layer, independent of and in
                addition to whatever tenant checks the business
                services themselves perform. The one exception is a
                user holding a role granted every currently registered
                permission (a System Administrator, by default) -- see
                "Why System Administrators are exempt" below.

        Returns:
            A fully-resolved :class:`~authorization.context.UserContext`.

        Raises:
            UnknownUserError: If no user is known under ``user_id``.
            InactiveUserError: If the resolved user is not active.
            CrossTenantAccessError: If a tenant is given, the resolved
                user does not belong to it, and the user does not hold
                platform-wide access.

        Why System Administrators are exempt
        --------------------------------------
        Task 2 requires exactly one ``tenant_id`` field on
        :class:`~authorization.models.User` -- a person still needs a
        "home" organization on their record even if their role is
        platform-wide. But a role granting *every* permission (System
        Administrator, by default, via
        :data:`~authorization.roles.ALL_PERMISSIONS_WILDCARD`) is
        meaningless if that same person is then blocked from acting
        against any tenant other than their own -- "manage the whole
        platform" and "confined to one organization" are contradictory
        requirements for the same role. Effective permissions are
        therefore resolved *before* the tenant check, and a user whose
        resolved permissions already cover every currently registered
        permission is exempt from it. Every other role -- including
        Tenant Administrator, which despite its name is still scoped to
        managing its *own* tenant, not every tenant -- remains strictly
        confined to its ``tenant_id``.
        """
        user = self.resolve_user(user_id)
        if not user.is_active:
            raise InactiveUserError(user.user_id)

        permissions = self.resolve_effective_permissions(user)

        if tenant_context is not None and tenant_context.tenant is not None:
            has_platform_wide_access = set(self._permission_registry.all_keys()) <= permissions
            if user.tenant_id != tenant_context.tenant.tenant_id and not has_platform_wide_access:
                raise CrossTenantAccessError(user.user_id)

        return UserContext.for_user(user, permissions)

    # ------------------------------------------------------------------
    # Enforcement -- Task 5 ("validate permissions", "deny unauthorized
    # access", "produce business-friendly authorization errors")
    # ------------------------------------------------------------------
    def has_permission(self, user_context: UserContext | None, permission: str) -> bool:
        """Return ``True`` if ``user_context`` currently holds ``permission``.

        A non-raising check, intended for UI code that needs to decide
        whether to *show* something (a menu item, a button) rather than
        block an action outright -- see
        :func:`components.authorization.is_authorized`. For gating an
        actual operation, prefer :meth:`require_permission`, which also
        produces the audit trail Task 10 requires.

        Args:
            user_context: The context to check, or ``None``.
            permission: The permission key to check for.

        Returns:
            ``True`` if a user is present and holds the permission,
            ``False`` otherwise (including when ``user_context`` is
            ``None``).
        """
        return user_context is not None and user_context.has_permission(permission)

    def require_permission(
        self,
        user_context: UserContext | None,
        permission: str,
        *,
        service_name: str,
        operation: str,
        tenant_context: TenantContext | None = None,
    ) -> User:
        """Validate that ``user_context`` holds ``permission``, or raise.

        This is the single validation-and-logging-and-monitoring choke
        point every protected call site uses (Task 5, Task 10) --
        mirroring ``tenancy.context.validate_tenant_context``'s shape
        exactly, for the same reasons: one implementation instead of
        one per call site, an identical structured log line regardless
        of which of the eight protected capabilities produced it, and a
        permanent audit trail via the Monitoring Service every business
        service already reports into.

        Every call -- granted or denied -- is recorded as a monitoring
        event via :data:`~monitoring.service.monitoring_service`, using
        the *same* ``OPERATION_COMPLETED``/``OPERATION_FAILED``
        vocabulary every other instrumented service already uses (a
        deliberate choice -- see ``docs/AUTHORIZATION_ARCHITECTURE.md``
        -- that requires zero changes to the monitoring package itself
        and makes ``AuthorizationService`` show up in the Monitoring
        dashboard's existing Service Statistics table for free, with
        "successful" meaning "granted" and "failed" meaning "denied").
        A monitoring/storage failure can never block or grant access --
        see ``MonitoringService._store()``'s resilience guarantee.

        Args:
            user_context: The context of the user attempting the
                action, or ``None`` if no user has been resolved at
                all.
            permission: The permission key required for this action.
                Must be a key registered in the permission registry
                this service was constructed with.
            service_name: The name of the calling service/component,
                for logging and monitoring (e.g. ``"ExportService"``).
            operation: The name of the operation being performed, for
                logging and monitoring (e.g. ``"export"``).
            tenant_context: The active tenant this request is scoped
                to, if any -- threaded through to the recorded
                monitoring event so authorization activity is
                attributable to a tenant exactly like every other
                monitored operation.

        Returns:
            The authorized :class:`~authorization.models.User`.

        Raises:
            UnknownPermissionError: If ``permission`` isn't a key this
                service's permission registry knows about -- a
                configuration/programming error, not an end-user
                authorization failure.
            MissingUserContextError: If ``user_context`` is ``None`` or
                has no user bound to it.
            PermissionDeniedError: If the user is resolved but does not
                hold ``permission``.
        """
        if not self._permission_registry.exists(permission):
            raise UnknownPermissionError(permission, self._permission_registry.all_keys())

        if user_context is None or user_context.user is None:
            self._record(
                outcome="DENIED", user_id=None, permission=permission,
                service_name=service_name, operation=operation, tenant_context=tenant_context,
                reason="missing user context",
            )
            raise MissingUserContextError()

        user = user_context.user
        if not user_context.has_permission(permission):
            self._record(
                outcome="DENIED", user_id=user.user_id, permission=permission,
                service_name=service_name, operation=operation, tenant_context=tenant_context,
                reason="permission not granted",
            )
            raise PermissionDeniedError(permission)

        self._record(
            outcome="GRANTED", user_id=user.user_id, permission=permission,
            service_name=service_name, operation=operation, tenant_context=tenant_context,
            reason=None,
        )
        return user

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _record(
        self,
        *,
        outcome: str,
        user_id: str | None,
        permission: str,
        service_name: str,
        operation: str,
        tenant_context: TenantContext | None,
        reason: str | None,
    ) -> None:
        """Write the structured log line and monitoring event for one permission check.

        Every "Permission Checked" event (Task 10) is recorded here,
        exactly once, regardless of outcome -- an ``OPERATION_COMPLETED``
        event for a grant ("Authorization Granted"), an
        ``OPERATION_FAILED`` event for a denial ("Authorization
        Denied"). Both carry the checking user's id (in
        ``metadata["user_id"]``, since
        ``monitoring.models.MonitoringEvent`` has no dedicated user
        field -- its open ``metadata`` mapping exists exactly for this
        kind of extension, see ``docs/OBSERVABILITY_ARCHITECTURE.md``),
        the tenant id (via ``tenant_context``, the same as every other
        instrumented service), and a timestamp (assigned automatically
        by the Monitoring Service, the same as every other event).

        Args:
            outcome: ``"GRANTED"`` or ``"DENIED"``.
            user_id: The user id being checked, or ``None`` if no user
                context was available at all.
            permission: The permission key that was checked.
            service_name: The service/component the check was made on
                behalf of.
            operation: The operation the check was made on behalf of.
            tenant_context: The active tenant, if any.
            reason: A short machine-readable reason for a denial, or
                ``None`` for a grant.
        """
        timestamp = _utc_now_isoformat()
        message = (
            f"user_id={user_id or '-'} permission={permission} service={service_name} "
            f"operation={operation} timestamp={timestamp} outcome={outcome}"
        )
        if outcome == "GRANTED":
            logger.info(message)
        else:
            logger.warning(message)

        metadata = {"user_id": user_id, "permission": permission, "checked_operation": f"{service_name}.{operation}"}
        if reason is not None:
            metadata["reason"] = reason

        if outcome == "GRANTED":
            monitoring_service.record_completed(
                service_name=_SERVICE_NAME,
                operation=permission,
                tenant_context=tenant_context,
                message=f"Authorization granted for {service_name}.{operation}",
                metadata=metadata,
            )
        else:
            monitoring_service.record_failure(
                service_name=_SERVICE_NAME,
                operation=permission,
                error=f"Authorization denied for {service_name}.{operation} ({reason})",
                tenant_context=tenant_context,
                metadata=metadata,
            )


def _utc_now_isoformat() -> str:
    """Return the current UTC time as an ISO-8601 string.

    A tiny, local helper (rather than importing ``monitoring.events.utc_now``)
    so ``authorization/service.py`` doesn't take on a dependency on
    monitoring's internals beyond ``monitoring_service`` itself.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# A shared, ready-to-use instance -- mirrors
# ``monitoring.service.monitoring_service`` and
# ``tenancy.registry.tenant_registry``. Every UI call site imports this
# directly rather than constructing its own AuthorizationService, so
# every check is resolved against the same provider and registries.
authorization_service = AuthorizationService()
