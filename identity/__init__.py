"""NovaMart Identity & Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework.

A framework-agnostic package (no Streamlit dependency anywhere in this
package) answering exactly one question: "who is this, and are they
currently signed in." Deliberately independent of
``authorization/`` -- see ``docs/IDENTITY_ARCHITECTURE.md``'s
"Authentication vs Authorization" section -- which answers the
separate question of "what is this already-signed-in user allowed to
do."

Public API, re-exported here so callers don't need to know this
package's internal module layout:

    from identity import (
        AuthenticationService, authentication_service,
        AuthenticationProvider, InMemoryAuthenticationProvider,
        AuthenticationProviderRegistry, authentication_provider_registry,
        SessionManager, session_manager,
        UserIdentity, IdentityStatus, LoginStatus, SessionInfo, AuthenticationResult,
        AuthenticationError, InvalidCredentialsError, InactiveIdentityError,
        SessionNotFoundError, SessionExpiredError, NotAuthenticatedError,
        ProviderNotRegisteredError, NoActiveProviderError,
    )
"""

from __future__ import annotations

from identity.exceptions import (
    AuthenticationError,
    InactiveIdentityError,
    InvalidCredentialsError,
    NoActiveProviderError,
    NotAuthenticatedError,
    ProviderNotRegisteredError,
    SessionExpiredError,
    SessionNotFoundError,
)
from identity.models import AuthenticationResult, IdentityStatus, LoginStatus, SessionInfo, UserIdentity
from identity.provider import AuthenticationProvider, InMemoryAuthenticationProvider
from identity.registry import AuthenticationProviderRegistry, authentication_provider_registry
from identity.service import AuthenticationService, authentication_service
from identity.session import SessionManager, session_manager

__all__ = [
    "AuthenticationError",
    "InactiveIdentityError",
    "InvalidCredentialsError",
    "NoActiveProviderError",
    "NotAuthenticatedError",
    "ProviderNotRegisteredError",
    "SessionExpiredError",
    "SessionNotFoundError",
    "AuthenticationResult",
    "IdentityStatus",
    "LoginStatus",
    "SessionInfo",
    "UserIdentity",
    "AuthenticationProvider",
    "InMemoryAuthenticationProvider",
    "AuthenticationProviderRegistry",
    "authentication_provider_registry",
    "AuthenticationService",
    "authentication_service",
    "SessionManager",
    "session_manager",
]
