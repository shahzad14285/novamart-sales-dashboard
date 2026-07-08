"""Login & Session UI for the NovaMart Identity & Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Tasks 7, 8, 10.

The one place the UI layer touches the ``identity`` package -- every
page gates itself behind :func:`require_authentication`, and the
sidebar renders the current user/session panel via
:func:`render_user_panel`. Mirrors
``components/authorization.py``'s role exactly: a thin, Streamlit-only
translation layer over a framework-agnostic service, never a second
place identity logic is implemented.

Why ``st.session_state``, not a module-level global
------------------------------------------------------
The same reasoning ``components/tenant_selector.py`` and
``components/authorization.py`` already document applies here
unchanged: a Streamlit server process serves multiple browser sessions
concurrently from the same Python process, so a module-level "current
session id" would leak one browser's session into another's request.
``st.session_state`` is keyed per browser session by Streamlit itself
-- this module stores exactly one string (the ``session_id`` a
:class:`~identity.session.SessionManager` already tracks centrally)
under one key, the same "store a pointer, not the record" pattern
those two modules use for the active tenant and active user
selections. See ``identity/session.py``'s module docstring for how
this satisfies Task 5's "use Streamlit session state only as a storage
mechanism" without ``identity/`` itself importing Streamlit.

"Redirecting" without a second page
----------------------------------------
Task 10 asks for unauthenticated users to be "redirected" to a login
page. This app is a Streamlit multipage app where every page already
gates itself behind :func:`require_authentication` immediately after
its own page configuration -- so rather than introduce a literal extra
``pages/0_Login.py`` and juggle ``st.switch_page`` redirects on every
protected page, an unauthenticated (or expired) visit to *any* page
renders the login screen in that exact page's place and stops --
functionally identical to a redirect (the visitor sees only the login
screen, nothing else), with one implementation instead of one per page.
"""

from __future__ import annotations

import streamlit as st

# Imported for its side effect: populates the active authentication
# provider from config.credentials.CREDENTIAL_DEFINITIONS as soon as
# this module loads.
import config.credentials  # noqa: F401
from config.credentials import DEMO_PASSWORD
from config.constants import COMPANY_NAME
from config.settings import APP_ICON
from identity.exceptions import AuthenticationError, SessionExpiredError
from identity.models import UserIdentity
from identity.service import authentication_service

_SESSION_ID_KEY = "novamart_session_id"


def get_current_session_id() -> str | None:
    """Return the current browser session's identity session id, if any.

    Read by ``components/authorization.py`` to resolve "who is
    currently signed in" without this module and that one creating a
    module-load-time circular import -- see that module's
    ``get_active_user_context`` for the (deferred-import) call site.

    Returns:
        The ``session_id`` string stored for this browser session, or
        ``None`` if nobody has signed in yet (or they've signed out).
    """
    return st.session_state.get(_SESSION_ID_KEY)


def is_authenticated() -> bool:
    """Return ``True`` if the current browser session has a valid, signed-in session.

    A non-raising check -- prefer :func:`require_authentication` at
    the top of a page, which also handles rendering the login screen
    and stopping; this is for callers that only need a yes/no answer.

    Returns:
        ``True`` if the current session is authenticated and not
        expired, ``False`` otherwise.
    """
    return authentication_service.is_authenticated(get_current_session_id())


def require_authentication() -> UserIdentity:
    """Gate a page behind authentication: call once, immediately after page config.

    Must be called before :func:`~components.sidebar.render_sidebar`
    (Task 8: "Authentication must complete successfully before
    authorization begins") on every page, including ``app.py``. If the
    current browser session has no valid session, this renders the
    full login screen in place of the page and calls ``st.stop()`` --
    nothing below this call runs for an unauthenticated visitor.

    On success, this is also the one point in a page's render where
    the session's sliding expiration window is extended and a
    "Session Refreshed" monitoring event is recorded (Task 9) -- see
    :meth:`~identity.service.AuthenticationService.refresh_session`.
    Every other call site that needs the current identity (e.g.
    ``components/authorization.py``) reads it back via the cheaper,
    non-recording :meth:`~identity.service.AuthenticationService.get_current_user`
    instead of calling this a second time.

    Returns:
        The authenticated :class:`~identity.models.UserIdentity`.
        Never actually returns for an unauthenticated visitor -- the
        function raises via ``st.stop()`` first.
    """
    session_id = get_current_session_id()
    try:
        authentication_service.refresh_session(session_id)
        identity = authentication_service.get_current_user(session_id)
    except AuthenticationError as exc:
        st.session_state.pop(_SESSION_ID_KEY, None)
        notice = str(exc) if isinstance(exc, SessionExpiredError) else None
        _render_login_screen(notice=notice)
        st.stop()
        raise  # pragma: no cover - unreachable; st.stop() halts the script above
    return identity


def render_user_panel(tenant_context: object | None = None) -> object:
    """Render the signed-in user's name, role, active tenant, session status, and a Sign Out button.

    Task 10: "Displaying the current user's name and role", "Showing
    the active tenant", "Displaying session status". Intended to be
    called once per page, from
    :func:`~components.sidebar.render_sidebar`, immediately after the
    tenant selector -- mirroring exactly where
    ``render_user_switcher`` (Sprint 6.5) used to render, now replaced
    by this real, authenticated panel.

    Args:
        tenant_context: The currently active
            :class:`~tenancy.context.TenantContext`, used both to
            resolve the authorization context (for the role label) and
            to display the active organization's name.

    Returns:
        The resolved :class:`~authorization.context.UserContext` for
        the signed-in user, so :func:`~components.sidebar.render_sidebar`
        can keep using it to filter navigation exactly as before --
        this function is a drop-in replacement for
        ``render_user_switcher``'s return value.
    """
    # Deferred import: components.authorization.get_active_user_context
    # needs get_current_session_id (above) to resolve "who is signed
    # in", and this function needs that resolved UserContext back to
    # display a role -- a genuine two-way relationship between two
    # same-tier UI modules. Deferring both sides' imports to call time
    # (the identical technique components/sidebar.py already uses for
    # authorization_service) avoids a module-load-time circular import
    # without either module depending on the other structurally.
    from components.authorization import get_active_user_context

    session_id = get_current_session_id()
    identity = authentication_service.get_current_user(session_id)
    user_context = get_active_user_context(tenant_context)

    st.markdown('<p class="nm-eyebrow">Signed In</p>', unsafe_allow_html=True)
    st.markdown(f"**{identity.display_name}**")
    st.caption(_format_role(user_context))
    if tenant_context is not None and getattr(tenant_context, "tenant", None) is not None:
        st.caption(f"Organization: {tenant_context.tenant.display_name}")
    st.caption(_format_session_status(session_id))

    if st.button("Sign Out", key="novamart_logout_button", use_container_width=True):
        authentication_service.sign_out(session_id)
        st.session_state.pop(_SESSION_ID_KEY, None)
        st.rerun()

    return user_context


def _render_login_screen(*, notice: str | None = None) -> None:
    """Render the full login screen: branding, a business-friendly notice, and the login form.

    Args:
        notice: An optional business-friendly message shown above the
            form (e.g. "Your session has expired. Please sign in
            again.") -- never a raw exception or technical detail.
    """
    st.markdown(
        f'<p class="nm-section-title">{APP_ICON} Sign in to {COMPANY_NAME}</p>', unsafe_allow_html=True
    )
    st.markdown(
        '<p class="nm-section-subtitle">Sign in with your NovaMart account to continue.</p>',
        unsafe_allow_html=True,
    )

    if notice:
        st.warning(notice, icon="⏱️")

    _render_login_form()
    _render_demo_accounts_hint()


def _render_login_form() -> None:
    """Render the username/password form and handle a submission.

    Task 7: "Username", "Password", "Sign In button", "Business-friendly
    validation messages". A blank field is caught here, before ever
    calling the Authentication Service, so an empty submission gets an
    immediate, specific message rather than a generic "invalid
    credentials" one.
    """
    with st.form("novamart_login_form", clear_on_submit=False):
        username = st.text_input("Username", key="novamart_login_username")
        password = st.text_input("Password", type="password", key="novamart_login_password")
        submitted = st.form_submit_button("Sign In", use_container_width=True)

    if not submitted:
        return

    if not username.strip() or not password:
        st.error("Please enter both a username and a password.", icon="⚠️")
        return

    try:
        result = authentication_service.sign_in(username.strip(), password)
    except AuthenticationError as exc:
        st.error(str(exc), icon="🔒")
        return

    st.session_state[_SESSION_ID_KEY] = result.session.session_id
    st.rerun()


def _render_demo_accounts_hint() -> None:
    """Render a collapsible hint listing the demo accounts and shared password.

    Task 7: "Use demo users only." There is no self-registration and
    no password reset in this release, so without this hint nobody
    running the demo could discover a valid login -- shown openly
    (not a security concern, since these are seeded, non-production
    demo accounts; see ``config/credentials.py``).
    """
    from config.credentials import CREDENTIAL_DEFINITIONS

    with st.expander("Demo accounts"):
        st.caption("This is a demonstration login. Every account below shares the same password.")
        st.markdown(f"**Password for every account:** `{DEMO_PASSWORD}`")
        for identity, _password in CREDENTIAL_DEFINITIONS:
            status_note = "" if identity.is_active else " _(inactive -- for testing a blocked sign-in)_"
            st.markdown(f"- `{identity.username}` -- {identity.display_name}{status_note}")


def _format_role(user_context: object) -> str:
    """Format a resolved :class:`~authorization.context.UserContext`'s role(s) for display.

    Args:
        user_context: The resolved authorization context.

    Returns:
        A human-readable, comma-separated list of role display names,
        or a fallback string if no role could be resolved.
    """
    from authorization.roles import role_registry

    user = getattr(user_context, "user", None)
    if user is None:
        return "No role assigned"
    names = []
    for role_key in user.roles:
        role = role_registry.get(role_key)
        if role is not None:
            names.append(role.display_name)
    return ", ".join(names) if names else "No role assigned"


def _format_session_status(session_id: str | None) -> str:
    """Format a human-readable session status line for the user panel.

    Args:
        session_id: The current browser session's identity session id.

    Returns:
        A short status string, e.g. ``"Session active · expires in 29 min"``.
    """
    try:
        session = authentication_service.validate_session(session_id)
    except AuthenticationError:
        return "Session status unavailable"
    minutes_remaining = max(1, round(session.remaining_seconds / 60))
    return f"Session active · expires in {minutes_remaining} min"
