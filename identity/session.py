"""Session Manager for the NovaMart Identity & Authentication Framework.

Sprint 6.6 -- Identity & Authentication Framework, Task 5.

Owns the full lifecycle of a :class:`~identity.models.SessionInfo`:
creation, validation, activity tracking, expiration, and destruction.
This is the *only* place session lifecycle logic is implemented -- no
page, component, or business service ever computes an expiration time
or mutates a session record itself.

Framework-independent by construction, Streamlit-backed by injection
-------------------------------------------------------------------------
The ticket asks for two things that sound like they pull in opposite
directions: "Keep session logic inside the Identity layer" and "Use
the existing Streamlit session state only as a storage mechanism."
:class:`SessionManager` resolves this the same way every other
provider in this codebase resolves "where does the data actually
live": it depends only on the ``MutableMapping[str, SessionInfo]``
protocol from :mod:`collections.abc` -- satisfied by a plain ``dict``
*and* by ``st.session_state`` (Streamlit's session-state object already
implements the mapping protocol) -- injected via the constructor
(Dependency Injection). ``identity/session.py`` itself never imports
Streamlit; the *default* store is a plain ``dict`` (so this module,
and every test that uses it, works with no UI framework installed at
all). ``components/auth.py`` -- the one place in the UI layer allowed
to import Streamlit *and* the identity package together -- is where a
real deployment would inject ``st.session_state`` as the store if it
needed every session's *storage bytes* to physically live in Streamlit's
own state rather than this process's memory.

In this release, the shared, module-level :data:`session_manager`
below uses the default in-process ``dict`` store (mirroring
``authorization.provider.InMemoryAuthorizationProvider`` and
``monitoring.provider.InMemoryMonitoringProvider``, both of which are
also process-local by default) -- and ``st.session_state`` is what
every browser session uses to remember *which* ``session_id`` is
theirs (a single string, via ``components/auth.py``), the same
"store a pointer, not the record" pattern
``components/tenant_selector.py`` and ``components/authorization.py``
already establish for the active tenant and active user selections.
This is what actually gives each concurrent browser session its own
isolated identity, exactly as those two modules' docstrings already
explain for their own selections -- a session *id* is only useful once
looked up centrally, which is exactly what lets a real, multi-process
deployment swap this default ``dict`` for a shared, injected store
(e.g. Redis) with zero change to the lifecycle logic below.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import MutableMapping

from identity.exceptions import SessionExpiredError, SessionNotFoundError
from identity.models import SessionInfo

DEFAULT_SESSION_TIMEOUT_MINUTES = 30


class SessionManager:
    """Creates, validates, and expires authenticated sessions.

    Example:
        >>> manager = SessionManager()
        >>> session = manager.create_session("jane.doe")
        >>> manager.validate_session(session.session_id).user_id
        'jane.doe'
        >>> manager.destroy_session(session.session_id)
        >>> manager.get_session(session.session_id) is None
        True
    """

    def __init__(
        self,
        *,
        timeout_minutes: int = DEFAULT_SESSION_TIMEOUT_MINUTES,
        store: MutableMapping[str, SessionInfo] | None = None,
    ) -> None:
        """Create a Session Manager.

        Args:
            timeout_minutes: How long a session remains valid after
                its last recorded activity (a "sliding" expiration --
                see :meth:`record_activity`). Defaults to 30 minutes.
            store: The mapping used to persist session records. When
                omitted, a plain in-process ``dict`` is used (the
                normal case for application code and for every test).
                A caller integrating this with Streamlit can inject
                ``st.session_state`` (or any other
                ``MutableMapping``-compatible object) here instead --
                see the module docstring.
        """
        self._store: MutableMapping[str, SessionInfo] = store if store is not None else {}
        self._timeout = timedelta(minutes=timeout_minutes)
        self._lock = threading.Lock()

    def create_session(self, user_id: str) -> SessionInfo:
        """Create and store a brand-new session for ``user_id``.

        Args:
            user_id: The identity this session belongs to.

        Returns:
            The newly created :class:`~identity.models.SessionInfo`.
        """
        now = _utc_now()
        session = SessionInfo(
            session_id=uuid.uuid4().hex,
            user_id=user_id,
            created_at=now,
            last_activity_at=now,
            expires_at=now + self._timeout,
        )
        with self._lock:
            self._store[session.session_id] = session
        return session

    def get_session(self, session_id: str | None) -> SessionInfo | None:
        """Look up a session by id without validating it.

        Args:
            session_id: The session id to look up, or ``None``.

        Returns:
            The matching :class:`~identity.models.SessionInfo`, or
            ``None`` if ``session_id`` is falsy or unknown. Does not
            check expiration -- see :meth:`validate_session` for that.
        """
        if not session_id:
            return None
        with self._lock:
            return self._store.get(session_id)

    def validate_session(self, session_id: str | None) -> SessionInfo:
        """Return ``session_id``'s session if it exists and has not expired.

        A read-only check: never touches ``last_activity_at`` or
        ``expires_at``. Use :meth:`record_activity` when the caller
        wants validation *and* a sliding-expiration touch in one call.

        Args:
            session_id: The session id to validate, or ``None``.

        Returns:
            The valid :class:`~identity.models.SessionInfo`.

        Raises:
            SessionNotFoundError: If ``session_id`` is falsy or does
                not match any known session.
            SessionExpiredError: If the session was found but its
                expiration instant has passed (the expired session is
                also removed from the store as a side effect, so a
                second lookup with the same id raises
                :class:`SessionNotFoundError` instead).
        """
        session = self.get_session(session_id)
        if session is None:
            raise SessionNotFoundError()
        if session.is_expired:
            self.destroy_session(session_id)
            raise SessionExpiredError(session.user_id)
        return session

    def record_activity(self, session_id: str | None) -> SessionInfo:
        """Validate a session, then extend it based on this activity.

        Implements the "sliding expiration" behavior Task 5 asks for
        ("Update last activity", "Handle session expiration" together):
        every call that represents real user activity both confirms
        the session is still valid *and* pushes its expiration instant
        forward by another full timeout window from now.

        Args:
            session_id: The session id to touch.

        Returns:
            The updated :class:`~identity.models.SessionInfo`.

        Raises:
            SessionNotFoundError: If ``session_id`` is falsy or unknown.
            SessionExpiredError: If the session had already expired.
        """
        session = self.validate_session(session_id)
        now = _utc_now()
        updated = replace(session, last_activity_at=now, expires_at=now + self._timeout)
        with self._lock:
            self._store[session_id] = updated
        return updated

    def destroy_session(self, session_id: str | None) -> None:
        """Remove a session, if it exists.

        A no-op (not an error) when ``session_id`` is falsy or already
        unknown -- signing out twice, or signing out a session that
        already expired, should never raise.

        Args:
            session_id: The session id to remove.
        """
        if not session_id:
            return
        with self._lock:
            self._store.pop(session_id, None)

    def clear(self) -> None:
        """Remove every stored session.

        Primarily useful for tests that need a clean manager rather
        than one accumulating sessions across an entire test run.
        """
        with self._lock:
            self._store.clear()


def _utc_now() -> datetime:
    """Return the current UTC time.

    A tiny local helper so ``identity/session.py`` has no dependency on
    any other package in this codebase, keeping it framework- and
    package-independent per Task 1.
    """
    return datetime.now(timezone.utc)


# A shared, ready-to-use instance -- mirrors
# ``monitoring.service.monitoring_service`` and
# ``authorization.service.authorization_service``. Every real call site
# uses this instance (via ``identity.service.AuthenticationService``'s
# default constructor argument) rather than constructing its own
# SessionManager, so every session is tracked in one place.
session_manager = SessionManager()
