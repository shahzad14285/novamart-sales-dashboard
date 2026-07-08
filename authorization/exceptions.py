"""Authorization-related exceptions for the NovaMart Permission-Based
Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 5.

Every message on these exceptions is written to be shown directly to
an end user (e.g. via ``st.error``) -- professional and
business-friendly, with no user IDs, permission keys, service names,
stack traces, or other implementation detail included in the message
text itself. That detail is still captured, but only in the structured
log line :func:`~authorization.service.AuthorizationService.require_permission`
writes and in the monitoring event it records -- never in text that
reaches the screen.

Mirrors the ``<Package>Error`` base-class convention already used by
``tenancy.exceptions.TenantContextError`` and
``monitoring.exceptions.MonitoringError``: catch
:class:`AuthorizationError` in calling code to handle any authorization
failure with a single ``except`` clause.
"""

from __future__ import annotations


class AuthorizationError(Exception):
    """Base class for every error raised by the authorization package.

    Catch this type in calling code (typically the UI layer) to handle
    *any* authorization failure the same way::

        try:
            authorization_service.require_permission(
                user_context, Permission.EXPORT_DATA,
                service_name="ExportService", operation="export",
            )
        except AuthorizationError as exc:
            st.error(str(exc), icon="🔒")
    """


class MissingUserContextError(AuthorizationError):
    """Raised when no :class:`~authorization.context.UserContext` was supplied at all."""

    def __init__(self) -> None:
        super().__init__("User context is missing. Unable to process request.")


class UnknownUserError(AuthorizationError):
    """Raised when a user id doesn't match any user known to the platform."""

    def __init__(self, user_id: str) -> None:
        """Build a business-friendly "user not found" message.

        Args:
            user_id: The user id that couldn't be resolved. Kept on the
                exception instance for logging -- never included in the
                message shown to the user.
        """
        self.user_id = user_id
        super().__init__("The requested user account could not be found. Unable to process request.")


class InactiveUserError(AuthorizationError):
    """Raised when the user resolved successfully but is not active."""

    def __init__(self, user_id: str) -> None:
        """Build a business-friendly "user inactive" message.

        Args:
            user_id: The inactive user's id. Kept on the exception
                instance for logging -- never included in the message
                shown to the user.
        """
        self.user_id = user_id
        super().__init__("This user account is currently inactive. Unable to process request.")


class CrossTenantAccessError(AuthorizationError):
    """Raised when a user attempts to act within a tenant other than their own.

    Distinct from :class:`PermissionDeniedError` because this is a
    tenant-isolation violation (Task 11's "Tenant isolation" test
    category), not a missing-permission situation -- a user who is a
    System Administrator in Tenant A still cannot be resolved against
    Tenant B's context unless that same user is *also* registered under
    Tenant B, since a :class:`~authorization.models.User` always belongs
    to exactly one tenant.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        super().__init__("This account is not authorized for the selected organization.")


class PermissionDeniedError(AuthorizationError):
    """Raised when a resolved, active user lacks a required permission."""

    def __init__(self, permission: str) -> None:
        """Build a business-friendly "access denied" message.

        Args:
            permission: The permission key that was required but not
                granted. Kept on the exception instance for logging --
                never included in the message shown to the user.
        """
        self.permission = permission
        super().__init__("You do not have permission to perform this action.")


class UnknownPermissionError(AuthorizationError):
    """Raised when a permission key doesn't match any permission registered
    in the :class:`~authorization.permissions.PermissionRegistry`.

    This is a configuration/programming error (a service or UI call
    site referenced a permission key that was never registered), not an
    end-user-facing authorization failure -- it signals a bug in the
    calling code, not that the current user lacks access.
    """

    def __init__(self, key: str, registered: tuple[str, ...]) -> None:
        self.key = key
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(
            f"'{key}' is not a registered permission. Registered permissions: {registered_list}."
        )


class UnknownRoleError(AuthorizationError):
    """Raised when a role key doesn't match any role registered in the
    :class:`~authorization.roles.RoleRegistry`.

    Also a configuration error, not an end-user-facing failure -- it
    means a :class:`~authorization.models.User` was assigned a role key
    that was never registered.
    """

    def __init__(self, key: str, registered: tuple[str, ...]) -> None:
        self.key = key
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(f"'{key}' is not a registered role. Registered roles: {registered_list}.")


class ProviderNotRegisteredError(AuthorizationError):
    """Raised when an authorization provider name doesn't match any registered provider."""

    def __init__(self, name: str, registered: tuple[str, ...]) -> None:
        self.name = name
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(
            f"No authorization provider named '{name}' is registered. "
            f"Registered providers: {registered_list}."
        )


class NoActiveProviderError(AuthorizationError):
    """Raised when no authorization provider has been marked active yet."""

    def __init__(self) -> None:
        super().__init__(
            "No active authorization provider is configured. Register at least one "
            "provider (see authorization.registry.AuthorizationProviderRegistry.register)."
        )
