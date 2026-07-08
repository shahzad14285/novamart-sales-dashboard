"""Identity-related exceptions for the NovaMart Identity & Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Task 3.

Every message on these exceptions is written to be shown directly to
an end user (e.g. via ``st.error``) -- professional and
business-friendly, with no usernames, session ids, stack traces, or
other implementation detail included in the message text itself. That
detail is still captured, but only in the structured log line
:class:`~identity.service.AuthenticationService` writes and in the
monitoring event it records -- never in text that reaches the screen.

Mirrors the ``<Package>Error`` base-class convention already used by
``authorization.exceptions.AuthorizationError``,
``tenancy.exceptions.TenantContextError``, and
``monitoring.exceptions.MonitoringError``: catch
:class:`AuthenticationError` in calling code to handle any
authentication failure with a single ``except`` clause.

Deliberately vague credential-failure message
-------------------------------------------------
:class:`InvalidCredentialsError` is raised for *both* an unknown
username and a correct username with the wrong password, with the
exact same message either way. This is a standard security practice
(not an oversight): if the two cases produced different messages, an
attacker could enumerate valid usernames one guess at a time. The
distinction is still preserved for logging/monitoring via each error's
private ``reason`` -- it just never reaches the message text.
"""

from __future__ import annotations


class AuthenticationError(Exception):
    """Base class for every error raised by the identity package.

    Catch this type in calling code (typically the UI layer) to handle
    *any* authentication failure the same way::

        try:
            result = authentication_service.sign_in(username, password)
        except AuthenticationError as exc:
            st.error(str(exc), icon="🔒")
    """


class InvalidCredentialsError(AuthenticationError):
    """Raised when a sign-in attempt's username/password does not check out.

    Covers both an unknown username and a known username with the
    wrong password -- see the module docstring for why these are never
    distinguished in the message shown to the user.
    """

    def __init__(self, reason: str = "invalid credentials") -> None:
        """Build a deliberately generic "invalid credentials" message.

        Args:
            reason: A short, machine-readable reason kept on the
                exception instance for logging only (e.g.
                ``"unknown username"`` or ``"incorrect password"``) --
                never included in the message shown to the user.
        """
        self.reason = reason
        super().__init__("The username or password you entered is incorrect.")


class InactiveIdentityError(AuthenticationError):
    """Raised when credentials check out but the identity is not active."""

    def __init__(self, user_id: str) -> None:
        """Build a business-friendly "account inactive" message.

        Args:
            user_id: The inactive identity's id. Kept on the exception
                instance for logging -- never included in the message
                shown to the user.
        """
        self.user_id = user_id
        super().__init__("This account is currently inactive. Please contact your administrator.")


class SessionNotFoundError(AuthenticationError):
    """Raised when a session id doesn't match any known session.

    Covers both "never signed in" and "signed out" -- there is no
    session to find either way.
    """

    def __init__(self) -> None:
        super().__init__("You are not signed in. Please sign in to continue.")


class SessionExpiredError(AuthenticationError):
    """Raised when a session was found but has passed its expiration."""

    def __init__(self, user_id: str | None = None) -> None:
        """Build a business-friendly "session expired" message.

        Args:
            user_id: The affected identity's id, if known. Kept on the
                exception instance for logging/monitoring -- never
                included in the message shown to the user.
        """
        self.user_id = user_id
        super().__init__("Your session has expired. Please sign in again.")


class NotAuthenticatedError(AuthenticationError):
    """Raised when an action requires a signed-in identity and none is available."""

    def __init__(self) -> None:
        super().__init__("You must be signed in to continue.")


class ProviderNotRegisteredError(AuthenticationError):
    """Raised when an authentication provider name doesn't match any registered provider."""

    def __init__(self, name: str, registered: tuple[str, ...]) -> None:
        self.name = name
        registered_list = ", ".join(sorted(registered)) if registered else "none"
        super().__init__(
            f"No authentication provider named '{name}' is registered. "
            f"Registered providers: {registered_list}."
        )


class NoActiveProviderError(AuthenticationError):
    """Raised when no authentication provider has been marked active yet."""

    def __init__(self) -> None:
        super().__init__(
            "No active authentication provider is configured. Register at least one "
            "provider (see identity.registry.AuthenticationProviderRegistry.register)."
        )
