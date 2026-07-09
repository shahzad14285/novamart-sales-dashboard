"""Rate Limiter for the NovaMart Integration Platform & API Gateway.

Sprint 6.8 -- Integration Platform & API Gateway, Task 6.

A small, framework-agnostic, in-memory rate limiter
(Task 6: "Use an in-memory implementation"). Supports both
requests-per-minute and requests-per-hour ceilings, evaluated
independently for the calling user *and* their tenant (Task 6:
"Per-user limits", "Per-tenant limits") -- either axis being exceeded
blocks the request.

Business services never know rate limits exist (Task 6). This module
is called exactly once, by :class:`~integration.gateway.APIGateway`,
after authentication and authorization have already resolved *who* is
calling -- no business service in ``services/`` imports this module or
is even aware it exists.

Why an injectable store (mirrors ``automation.scheduler.Scheduler``)
------------------------------------------------------------------------
:class:`RateLimiter` depends only on a plain
``MutableMapping[str, list[datetime]]`` for its state (defaulting to a
``dict``), exactly like :class:`~automation.scheduler.Scheduler`
depends only on a ``MutableMapping[str, ScheduledJob]``. This keeps the
class framework-independent while remaining trivially usable from
Streamlit (never imported here) or a future persistent store (e.g.
Redis, for a multi-process deployment), and lets every test inject a
fresh store instead of sharing the application-wide
:data:`rate_limiter` singleton.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import MutableMapping

from integration.models import IntegrationRequest, RateLimitPolicy, RateLimitStatus

_ONE_MINUTE = timedelta(minutes=1)
_ONE_HOUR = timedelta(hours=1)


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


class RateLimiter:
    """A sliding-window, in-memory rate limiter, keyed per caller (Task 6).

    Example:
        >>> limiter = RateLimiter()
        >>> policy = RateLimitPolicy(requests_per_minute=2, requests_per_hour=100)
        >>> limiter.check("user:jane.doe", policy).allowed
        True
        >>> limiter.check("user:jane.doe", policy).allowed
        True
        >>> limiter.check("user:jane.doe", policy).allowed
        False
    """

    def __init__(self, store: MutableMapping[str, list[datetime]] | None = None) -> None:
        """Create a Rate Limiter.

        Args:
            store: Where each caller's recent request timestamps are
                kept. Defaults to a plain, process-local ``dict``.
                Tests inject a fresh one to avoid sharing state with
                the application-wide :data:`rate_limiter` singleton; a
                future multi-process deployment could inject anything
                satisfying ``MutableMapping`` (e.g. a Redis-backed
                mapping).
        """
        self._store: MutableMapping[str, list[datetime]] = store if store is not None else {}
        self._lock = threading.Lock()

    def check(self, limit_key: str, policy: RateLimitPolicy, *, as_of: datetime | None = None) -> RateLimitStatus:
        """Record one request attempt for ``limit_key`` and decide whether it's allowed.

        A sliding window: only timestamps within the last minute/hour
        (relative to ``as_of``) count toward each ceiling. If the
        request is allowed, its timestamp is recorded immediately (so
        back-to-back calls correctly see each other); if it is
        rejected, nothing is recorded, so a rejected caller isn't
        penalized twice.

        Args:
            limit_key: A stable identifier for the caller being
                throttled (e.g. ``"user:jane.doe"`` or
                ``"tenant:acme-retail"``).
            policy: The ceilings to enforce.
            as_of: The instant to evaluate against. Defaults to now;
                exposed for deterministic tests.

        Returns:
            A :class:`~integration.models.RateLimitStatus` describing
            the decision.
        """
        moment = as_of if as_of is not None else _utc_now()

        with self._lock:
            history = self._store.setdefault(limit_key, [])
            # Prune anything older than the widest window this policy
            # cares about -- keeps the store bounded instead of growing
            # forever for a long-lived caller.
            history[:] = [ts for ts in history if moment - ts <= _ONE_HOUR]

            requests_this_minute = sum(1 for ts in history if moment - ts <= _ONE_MINUTE)
            requests_this_hour = len(history)

            over_minute_limit = requests_this_minute >= policy.requests_per_minute
            over_hour_limit = requests_this_hour >= policy.requests_per_hour

            if over_minute_limit or over_hour_limit:
                retry_after = self._retry_after_seconds(history, policy, moment, over_minute_limit)
                return RateLimitStatus(
                    allowed=False,
                    limit_key=limit_key,
                    requests_this_minute=requests_this_minute,
                    requests_this_hour=requests_this_hour,
                    retry_after_seconds=retry_after,
                )

            history.append(moment)
            return RateLimitStatus(
                allowed=True,
                limit_key=limit_key,
                requests_this_minute=requests_this_minute + 1,
                requests_this_hour=requests_this_hour + 1,
            )

    def evaluate(
        self, request: IntegrationRequest, policy: RateLimitPolicy
    ) -> RateLimitStatus:
        """Check both the calling user's and their tenant's rate limits for one request.

        Task 6: "Per-user limits" and "Per-tenant limits" are both
        enforced -- either being exceeded blocks the request. Checks
        the user first (the more specific, typically tighter-scoped
        limit); the tenant check only runs if the user check passed,
        so a single request never gets double-charged against both
        counters when it was going to be rejected anyway.

        Counters are scoped **per endpoint** (``user:<id>:<endpoint>`` /
        ``tenant:<id>:<endpoint>``), not globally across every endpoint a
        user calls. This is deliberate: since each
        :class:`~integration.models.EndpointDefinition` may carry its
        own :class:`~integration.models.RateLimitPolicy` (Task 3/6), a
        shared global counter would let a burst against one
        generously-limited endpoint spuriously trip a different,
        strictly-limited endpoint's ceiling for the same caller. Scoping
        per endpoint keeps each endpoint's policy meaningful on its own
        terms -- see ``docs/INTEGRATION_ARCHITECTURE.md``'s Rate
        Limiting section for the full rationale.

        Args:
            request: The request being evaluated. Must already have
                ``user_id``/``tenant_id`` resolved (i.e. this is called
                after authentication -- see
                :meth:`~integration.gateway.APIGateway.handle_request`).
            policy: The ceilings to enforce for both axes.

        Returns:
            The first disallowed :class:`~integration.models.RateLimitStatus`
            found, or the user-scoped (falling back to tenant-scoped, or
            a shared ``"anonymous"`` bucket if neither is known) allowed
            status otherwise.
        """
        scope = request.endpoint or "*"

        if request.user_id:
            user_status = self.check(f"user:{request.user_id}:{scope}", policy)
            if not user_status.allowed:
                return user_status
        else:
            user_status = None

        if request.tenant_id:
            tenant_status = self.check(f"tenant:{request.tenant_id}:{scope}", policy)
            if not tenant_status.allowed:
                return tenant_status
            if user_status is None:
                return tenant_status

        if user_status is not None:
            return user_status

        return self.check(f"anonymous:{scope}", policy)

    def stats(self, limit_key: str, policy: RateLimitPolicy, *, as_of: datetime | None = None) -> RateLimitStatus:
        """Return ``limit_key``'s current usage without recording a new attempt.

        Used by the Integration Dashboard's "Rate limit statistics"
        section (Task 10) -- a read-only peek, never itself consuming
        one of the caller's allotted requests.

        Args:
            limit_key: The identifier to inspect.
            policy: The ceilings to report usage against.
            as_of: The instant to evaluate against. Defaults to now.

        Returns:
            A :class:`~integration.models.RateLimitStatus` reflecting
            current usage; ``allowed`` reflects whether a *next*
            request would currently be permitted.
        """
        moment = as_of if as_of is not None else _utc_now()
        with self._lock:
            history = list(self._store.get(limit_key, []))
            history = [ts for ts in history if moment - ts <= _ONE_HOUR]
            requests_this_minute = sum(1 for ts in history if moment - ts <= _ONE_MINUTE)
            requests_this_hour = len(history)
        allowed = requests_this_minute < policy.requests_per_minute and requests_this_hour < policy.requests_per_hour
        return RateLimitStatus(
            allowed=allowed,
            limit_key=limit_key,
            requests_this_minute=requests_this_minute,
            requests_this_hour=requests_this_hour,
        )

    def tracked_keys(self) -> tuple[str, ...]:
        """Return every caller key with any recorded request history, sorted.

        Used by the Integration Dashboard to list which users/tenants
        currently have rate-limit activity to show.
        """
        with self._lock:
            return tuple(sorted(self._store.keys()))

    def clear(self) -> None:
        """Remove every caller's recorded history.

        Primarily useful for tests that need a clean limiter rather
        than the shared, application-wide instance.
        """
        with self._lock:
            self._store.clear()

    @staticmethod
    def _retry_after_seconds(
        history: list[datetime], policy: RateLimitPolicy, moment: datetime, over_minute_limit: bool
    ) -> float:
        """Estimate how many seconds until the oldest counted request ages out of the relevant window.

        Args:
            history: The caller's (already-pruned) request timestamps.
            policy: The ceilings being enforced.
            moment: The instant the check is being evaluated at.
            over_minute_limit: Whether the per-minute ceiling (rather
                than the per-hour ceiling) was the one exceeded --
                determines which window's oldest entry to measure
                against.

        Returns:
            Seconds until the caller is expected to be allowed again,
            rounded up to a whole second, never negative.
        """
        window = _ONE_MINUTE if over_minute_limit else _ONE_HOUR
        relevant = [ts for ts in history if moment - ts <= window]
        if not relevant:
            return 0.0
        oldest = min(relevant)
        remaining = (oldest + window) - moment
        return max(0.0, remaining.total_seconds())


# A shared, ready-to-use instance -- mirrors ``automation.scheduler.scheduler``.
rate_limiter = RateLimiter()
