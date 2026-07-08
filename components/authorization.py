"""Authorization UI helper for the NovaMart Permission-Based Authorization Framework.

Sprint 6.5 -- Permission-Based Authorization Framework, Task 9.

The one place the UI layer resolves "who is the current user" and
checks "are they allowed to do this" -- every page and component that
needs authorization calls into this module rather than importing
``authorization.service`` directly, so there is exactly one
implementation of "how the demo user switcher works" and exactly one
implementation of what an "Access Denied" message looks like (Task 9:
"Avoid duplicated authorization checks").

Why ``st.session_state``, not a module-level global
------------------------------------------------------
The same reasoning ``components/tenant_selector.py`` documents applies
here unchanged: a Streamlit server process serves multiple browser
sessions concurrently from the same Python process, so a module-level
"current user" would leak one session's identity into another's
request. ``st.session_state`` is keyed per browser session by
Streamlit itself, so storing the selection there is what actually
gives each concurrent user their own isolated identity.

A stand-in for real authentication
-------------------------------------
There is no real login in this release -- the Target Architecture in
``docs/AUTHORIZATION_ARCHITECTURE.md`` explicitly marks "Authentication"
as a future integration point. Until then, :func:`render_user_switcher`
lets the person running the demo pick "who they currently are" from the
directory seeded by ``config/users.py``, exactly the same stand-in role
``components/tenant_selector.py`` already plays for "which organization
is active" in the absence of real multi-tenant request routing. When
real authentication arrives, only :func:`get_active_user_context`'s
*implementation* needs to change (resolving a verified session/token
into a user id instead of reading a selectbox) -- its signature, and
every one of the dozens of call sites using
:func:`is_authorized`/:func:`require_permission_ui` elsewhere in the
app, stays exactly the same.
"""

from __future__ import annotations

import streamlit as st

# Imported for its side effect: populates the active authorization
# provider from config.users.USER_DEFINITIONS as soon as this module loads.
import config.users  # noqa: F401
from authorization.context import UserContext
from authorization.exceptions import AuthorizationError
from authorization.permissions import permission_registry
from authorization.registry import authorization_provider_registry
from authorization.service import authorization_service
from tenancy.context import TenantContext

_SESSION_KEY = "novamart_active_user_id"


def render_user_switcher(tenant_context: TenantContext | None = None) -> UserContext:
    """Render the demo user picker and return the resolved :class:`UserContext`.

    Intended to be called once per page, from
    :func:`~components.sidebar.render_sidebar` (already invoked by
    every page) immediately after the tenant selector, so no page needs
    to render this a second time and every downstream check reads a
    context resolved against the currently-selected tenant.

    Args:
        tenant_context: The currently active tenant, used to resolve
            tenant isolation (a non-platform-wide user selected while a
            different tenant is active is shown a warning and treated
            as having no permissions, rather than crashing the sidebar
            -- see :func:`get_active_user_context`).

    Returns:
        A :class:`~authorization.context.UserContext` bound to
        whichever user is currently selected in this browser session,
        or an empty context if no user is configured or the selection
        is invalid for the active tenant.
    """
    provider = authorization_provider_registry.get_active()
    all_users = provider.list_users()

    st.markdown('<p class="nm-eyebrow">Signed In As (Demo)</p>', unsafe_allow_html=True)

    if not all_users:
        st.info("No demo users are configured.", icon="👤")
        return UserContext.empty()

    options = [user.user_id for user in all_users]
    labels = {user.user_id: user.display_name for user in all_users}

    previous_selection = st.session_state.get(_SESSION_KEY)
    default_index = options.index(previous_selection) if previous_selection in options else 0

    selected_id = st.selectbox(
        "User",
        options=options,
        index=default_index,
        format_func=lambda user_id: labels[user_id],
        key="novamart_user_selectbox",
        label_visibility="collapsed",
        help="Stands in for real sign-in until authentication is integrated. "
        "Every menu item, button, and page you can access is scoped to this user's role.",
    )
    st.session_state[_SESSION_KEY] = selected_id

    return _resolve_user_context(selected_id, tenant_context, show_errors=True)


def get_active_user_context(tenant_context: TenantContext | None = None) -> UserContext:
    """Return the current session's active :class:`UserContext` without re-rendering the picker.

    Useful for a component or page that needs the resolved user but
    isn't the one responsible for drawing the selectbox (which
    :func:`~components.sidebar.render_sidebar` already does once per
    page) -- mirrors
    ``components.tenant_selector.get_active_tenant_context``.

    Args:
        tenant_context: The currently active tenant, used to resolve
            tenant isolation exactly as :func:`render_user_switcher` does.

    Returns:
        The active :class:`~authorization.context.UserContext` for this
        session, or an empty context if nothing has been selected yet
        or the selection is invalid.
    """
    selected_id = st.session_state.get(_SESSION_KEY)
    if not selected_id:
        return UserContext.empty()
    return _resolve_user_context(selected_id, tenant_context, show_errors=False)


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
        user_id: The user id to resolve.
        tenant_context: The currently active tenant.
        show_errors: Whether to render an inline ``st.warning`` when
            resolution fails (``True`` from the switcher itself, so the
            person driving the demo sees *why* nothing is authorized;
            ``False`` from :func:`get_active_user_context`, so the same
            warning isn't duplicated on every component that merely
            reads the already-resolved context).

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
