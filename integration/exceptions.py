"""Integration-related exceptions for the NovaMart Integration Platform & API Gateway.

Sprint 6.8 -- Integration Platform & API Gateway.

Mirrors the ``<Package>Error`` base-class convention already used by
``automation.exceptions.AutomationError``,
``notification.exceptions.NotificationError``, and
``identity.exceptions.AuthenticationError``: catch
:class:`IntegrationError` in calling code to handle any integration
failure with a single ``except`` clause.

These exceptions are raised only for genuine *misuse* of the
integration API (a duplicate endpoint registration, an unknown
provider channel) or for conditions
:class:`~integration.gateway.APIGateway` deliberately catches and
translates into a standardized :class:`~integration.models.IntegrationResponse`
(an unknown endpoint, a failed validation, a rate limit rejection) --
:meth:`~integration.gateway.APIGateway.handle_request` never lets one
of these propagate out to an external caller; see
``docs/INTEGRATION_ARCHITECTURE.md`` for the full rationale.
"""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for every error raised by the integration package."""


class EndpointNotFoundError(IntegrationError):
    """Raised when a request targets an endpoint/version/method combination that isn't registered."""

    def __init__(self, endpoint: str, method: str, api_version: str) -> None:
        """Build a clear "which route couldn't be resolved" message.

        Args:
            endpoint: The requested endpoint key.
            method: The requested HTTP-style method.
            api_version: The requested API version.
        """
        self.endpoint = endpoint
        self.method = method
        self.api_version = api_version
        super().__init__(
            f"No endpoint '{endpoint}' registered for method {method} under API version '{api_version}'."
        )


class DuplicateEndpointError(IntegrationError):
    """Raised when :meth:`~integration.registry.EndpointRegistry.register` is called with a duplicate combination."""

    def __init__(self, endpoint: str, method: str, api_version: str) -> None:
        """Build a message identifying the conflicting registration.

        Args:
            endpoint: The endpoint key that was already registered.
            method: The method that was already registered.
            api_version: The API version that was already registered.
        """
        self.endpoint = endpoint
        self.method = method
        self.api_version = api_version
        super().__init__(
            f"Endpoint '{endpoint}' is already registered for method {method} under API version "
            f"'{api_version}'. Use a different endpoint_key/method/api_version, or unregister first."
        )


class InvalidRequestError(IntegrationError):
    """Raised when a request fails validation (Task 5) -- missing/invalid fields."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        """Build a message listing every validation failure found.

        Args:
            reasons: One or more business-friendly validation failure
                descriptions.
        """
        self.reasons = reasons
        joined = "; ".join(reasons) if reasons else "the request was invalid"
        super().__init__(f"Request validation failed: {joined}.")


class RateLimitExceededError(IntegrationError):
    """Raised internally when a caller has exceeded their configured rate limit (Task 6)."""

    def __init__(self, limit_key: str, retry_after_seconds: float) -> None:
        """Build a message telling the caller how long to wait.

        Args:
            limit_key: The identifier that was throttled (e.g.
                ``"user:jane.doe"``).
            retry_after_seconds: How long to wait before retrying.
        """
        self.limit_key = limit_key
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Rate limit exceeded for '{limit_key}'. Try again in {retry_after_seconds:.0f} second(s)."
        )


class ProviderNotRegisteredError(IntegrationError):
    """Raised when an integration channel has no registered provider."""

    def __init__(self, channel: str, registered: tuple[str, ...]) -> None:
        """Build a message listing what *is* registered, for easy debugging.

        Args:
            channel: The channel key that was requested.
            registered: The channel keys currently registered.
        """
        self.channel = channel
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(
            f"No integration provider is registered for channel '{channel}'. "
            f"Registered channels: {registered_list}."
        )


class GatewayAuthenticationError(IntegrationError):
    """Raised internally when a request's caller could not be authenticated."""

    def __init__(self, reason: str) -> None:
        """Build a clear "why authentication failed" message.

        Args:
            reason: A short, business-friendly description.
        """
        self.reason = reason
        super().__init__(f"Authentication failed: {reason}.")


class GatewayAuthorizationError(IntegrationError):
    """Raised internally when an authenticated caller lacks the permission an endpoint requires."""

    def __init__(self, permission: str) -> None:
        """Build a message identifying the missing permission.

        Args:
            permission: The permission key that was required.
        """
        self.permission = permission
        super().__init__(f"Caller does not hold the required permission '{permission}'.")
