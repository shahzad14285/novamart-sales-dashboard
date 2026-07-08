"""Authorization UI helper for the NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 9.
Updated in Sprint 6.6 -- Identity & Authentication Framework, Task 8,
to source "who is the current user" from a real, authenticated
identity session instead of a demo picker -- see "Sourcing the active
user" below.

The one place the UI layer resolves "who is the current user" and
checks "are they allowed to do this" -- every page and component that
needs authorization calls into this module rather than importing
``authorization.service`` directly, so there is exactly one
implementation of that resolution and exactly one implementation of
what an "Access Denied" message looks like (Task 9: "Avoid duplicated
authorization checks").

Sourcing the active user (Sprint 6.6)
-------------------------------------------
Prior to Sprint 6.6, this module owned its own "Signed In As (Demo)"
selectbox and session-state key, standing in for real authentication.
Now that ``identity/`` provides real sign-in and session validation,
:func:`get_active_user_context` resolves ``user_id`` from the current
browser session's authenticated identity
(``identity.service.authentication_service.get_current_user``) instead.
This is a deliberately narrow, surgical change: the
:class:`~authorization.service.AuthorizationService` this module wraps,
the :class:`~authorization.context.UserContext` type it returns, and
every one of the dozens of call sites using
:func:`is_authorized`/:func:`require_permission_ui` elsewhere in the
app are completely unchanged -- only *where the user id comes from*
was updated, keeping the identity and authorization packages
themselves fully decoupled (this module is the one place, at the UI
layer, allowed to bridge them -- see
``docs/IDENTITY_ARCHITECTURE.md``'s "Authentication vs Authorization"
section). The demo selectbox is gone; the "which user" question is
now answered by an actual login (``components/auth.py``).
"""

from __future__ import annotations

import streamlit as st

# Imported for its side effect: populates the active authorization
# provider from config.users.USER_DEFINITIONS as soon as this module loads.
import config.users  # noqa: F401
from authorization.context import UserContext
from authorization.exceptions import AuthorizationError
from authorization.permissions import permission_registry
from authorization.service import authorization_service
from identity.exceptions import AuthenticationError
from identity.service import authentication_service
from tenancy.context import TenantContext


def get_active_user_context(tenant_context: TenantContext | None = None) -> UserContext:
    """Return the current session's active :class:`UserContext`.

    Resolves the signed-in identity from the current browser session
    (via ``identity.service.authentication_service``, using the
    session id ``components/auth.py`` stores in ``st.session_state``),
    then resolves that identity's ``user_id`` into a
    :class:`~authorization.context.UserContext` exactly as before
    Sprint 6.6 -- see the module docstring's "Sourcing the active user"
    section.

    Safe to call many times per page render (it performs a cheap,
    non-recording session read, not a full re-authentication) --
    mirrors ``components.tenant_selector.get_active_tenant_context``.

    Args:
        tenant_context: The currently active tenant, used to resolve
            tenant isolation (a user signed in while a different
            tenant is active is treated as having no permissions,
            rather than crashing the page -- see
            :func:`_resolve_user_context`).

    Returns:
        The active :class:`~authorization.context.UserContext` for this
        session, or an empty context if nobody is signed in, the
        session has expired, or the resolved user isn't authorized for
        the active tenant.
    """
    # Deferred import: components.auth needs get_active_user_context
    # (this function) to display a role on its user panel, and this
    # function needs components.auth's session id getter -- a genuine
    # two-way relationship between two same-tier UI modules. Deferring
    # both sides' imports to call time avoids a module-load-time
    # circular import; see components/auth.py::render_user_panel for
    # the matching deferred import on the other side.
    from components.auth import get_current_session_id

    session_id = get_current_session_id()
    try:
        identity = authentication_service.get_current_user(session_id)
    except AuthenticationError:
        return UserContext.empty()
    return _resolve_user_context(identity.user_id, tenant_context, show_errors=False)


def _resolve_user_context(
    user_id: str, tenant_context: TenantContext | None, *, show_errors: bool
) -> UserContext:
    """Resolve ``user_id`` into a :class:`UserContext`, degrading gracefully on failure.

    An authorization failure while merely *resolving the current user*
    (an unknown id, an inactive account, a cross-tenant mismatch after
    the tenant selector changed) must never crash the sidebar or the
    page underneath it -- it should simply result in "no permissions",
    letting every downstream :func:`is_authorized`/:func:`require_permission_ui`
    check fail closed and show its own business-friendly message.

    Args:
        user_id: The user id to resolve (already authenticated by the
            identity layer by the time this is called).
        tenant_context: The currently active tenant.
        show_errors: Whether to render an inline ``st.warning`` when
            resolution fails. Currently always called with ``False``
            (the sole remaining call site, :func:`get_active_user_context`,
            may run many times per render) -- kept as a parameter
            rather than removed so a future single "resolved once per
            page" call site can opt back into surfacing the warning,
            without changing this function's signature.

    Returns:
        The resolved context, or an empty one on any failure.
    """
    try:
        return authorization_service.build_context(user_id, tenant_context=tenant_context)
    except AuthorizationError as exc:
        if show_errors:
            st.warning(str(exc), icon="⚠️")
        return UserContext.empty()


def is_authorized(permission: str, *, tenant_context: TenantContext | None = None) -> bool:
    """Return ``True`` if the current session's user holds ``permission``.

    A non-raising check for hiding rather than blocking -- the source
    of truth for filtering sidebar navigation
    (:func:`~components.sidebar.render_sidebar`) and for conditionally
    rendering a button/tab that shouldn't even be offered to a user
    without the capability behind it.

    Args:
        permission: The permission key to check for.
        tenant_context: The currently active tenant. Only needed if the
            caller hasn't already resolved a :class:`UserContext` for
            this run; prefer passing an already-resolved context to
            :meth:`authorization.service.AuthorizationService.has_permission`
            directly when one is already in hand, to avoid re-resolving
            the user on every check within the same page render.

    Returns:
        ``True`` if the current user holds ``permission``, ``False``
        otherwise.
    """
    user_context = get_active_user_context(tenant_context)
    return authorization_service.has_permission(user_context, permission)


def require_permission_ui(
    permission: str,
    *,
    service_name: str,
    operation: str,
    tenant_context: TenantContext | None = None,
    user_context: UserContext | None = None,
) -> bool:
    """Gate a UI action behind ``permission``, rendering "Access Denied" on failure.

    The single reusable helper Task 9 asks for: every protected page or
    component calls this once, at the point where it would otherwise
    start doing real work, and simply stops (``return``s) if it comes
    back ``False`` -- the "Access Denied" message is already on screen,
    so the caller never needs to construct its own.

    Args:
        permission: The permission key required to proceed.
        service_name: The name of the page/component being protected,
            for the audit trail (e.g. ``"MonitoringDashboard"``).
        operation: The name of the action being protected, for the
            audit trail (e.g. ``"view"``).
        tenant_context: The currently active tenant.
        user_context: An already-resolved :class:`UserContext`, if the
            caller has one in hand (avoids re-resolving the user).
            Defaults to resolving it from the current session.

    Returns:
        ``True`` if access is granted (nothing was rendered -- the
        caller should proceed normally). ``False`` if access was
        denied (a business-friendly message has already been rendered
        -- the caller should stop rendering anything further for this
        action).
    """
    context = user_context if user_context is not None else get_active_user_context(tenant_context)
    try:
        authorization_service.require_permission(
            context, permission, service_name=service_name, operation=operation, tenant_context=tenant_context
        )
        return True
    except AuthorizationError:
        _render_access_denied(permission)
        return False


def _render_access_denied(permission: str) -> None:
    """Render a consistent, business-friendly "Access Denied" panel.

    Args:
        permission: The permission that was required, used only to
            look up a human-readable description for the message --
            never a raw permission key or other technical detail.
    """
    registered = permission_registry.get(permission)
    capability = registered.description if registered is not None else "this feature"
    st.markdown(
        f"""
        <div class="nm-empty-state">
            <div class="nm-empty-state-icon">🔒</div>
            <p class="nm-empty-state-text">
                <strong>Access Denied.</strong><br />
                Your current role does not include permission to {capability.lower().rstrip('.')}.
                Contact your Tenant Administrator if you believe this is a mistake.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
