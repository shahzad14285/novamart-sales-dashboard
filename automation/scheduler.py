"""Scheduler for the NovaMart Automation & Notification Platform.

Sprint 6.7 -- Automation & Notification Platform, Task 5.

A small, framework-agnostic registry of named, schedulable jobs
(daily/weekly/monthly/manual), with support for on-demand ("manual")
execution. Per the ticket: "Actual background execution is not
required. The objective is architectural design." -- so this module
deliberately does not run a background thread, a cron loop, or an
``asyncio`` task. What it *does* provide, fully working today, is
everything a future real scheduler (an OS cron entry, Celery beat,
APScheduler, a cloud function timer) would need to drive:

    - A stable catalogue of jobs (:meth:`Scheduler.register_job`,
      :meth:`Scheduler.list_jobs`).
    - A way to run one right now (:meth:`Scheduler.run_job` -- Task 5:
      "Manual execution", exercised directly by the Automation
      Dashboard's "Run Now" button).
    - A way to ask "which jobs are due" (:meth:`Scheduler.due_jobs`),
      computed from each job's ``frequency`` and ``last_run_at`` --
      the exact question a real scheduler's poll loop would ask on
      every tick. Nothing here polls it automatically; that loop is
      the one piece intentionally left as a future integration point.

Why a framework-agnostic, injectable store (mirroring ``identity.session.SessionManager``)
------------------------------------------------------------------------------------------
:class:`Scheduler` depends only on a plain ``MutableMapping[str, ScheduledJob]``
for its state (defaulting to a plain ``dict``), exactly like
:class:`~identity.session.SessionManager` depends only on a
``MutableMapping[str, SessionInfo]``. This keeps the class framework-independent
(Task 1) while still being trivially usable from Streamlit (which is
never imported here) or a future persistent store.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, MutableMapping

from automation.exceptions import JobAlreadyRegisteredError, UnknownJobError
from automation.models import JobExecutionResult, JobStatus, ScheduledJob, ScheduleFrequency

logger = logging.getLogger("novamart.automation.scheduler")

# A job callback takes no arguments and returns any value the Automation
# Dashboard (or a future workflow) might want to display. Keeping the
# signature uniform (no required arguments) is what makes register_job()
# work for any future job -- a report job, an export job, a cleanup job
# -- without Scheduler needing to know what any of them actually do.
JobCallback = Callable[[], object]

_FREQUENCY_DELTAS: dict[ScheduleFrequency, timedelta | None] = {
    ScheduleFrequency.DAILY: timedelta(days=1),
    ScheduleFrequency.WEEKLY: timedelta(weeks=1),
    ScheduleFrequency.MONTHLY: timedelta(days=30),
    ScheduleFrequency.MANUAL: None,
}


def _utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


class Scheduler:
    """A registry of named jobs, schedulable daily/weekly/monthly, or run manually.

    Example:
        >>> scheduler = Scheduler()
        >>> scheduler.register_job(
        ...     "weekly_executive_report", "Weekly Executive Report", ScheduleFrequency.WEEKLY,
        ...     callback=lambda: "report generated",
        ... )
        >>> result = scheduler.run_job("weekly_executive_report")
        >>> result.status
        <JobStatus.SUCCESS: 'success'>
    """

    def __init__(self, store: MutableMapping[str, ScheduledJob] | None = None) -> None:
        """Create a Scheduler.

        Args:
            store: Where job metadata is kept. Defaults to a plain,
                process-local ``dict``. Tests inject a fresh one to
                avoid sharing state with the application-wide
                :data:`scheduler` singleton; a future deployment could
                inject anything satisfying ``MutableMapping`` (e.g.
                Streamlit session state, a database-backed mapping).
        """
        self._jobs: MutableMapping[str, ScheduledJob] = store if store is not None else {}
        self._callbacks: dict[str, JobCallback] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_job(
        self,
        job_id: str,
        name: str,
        frequency: ScheduleFrequency,
        callback: JobCallback,
        *,
        enabled: bool = True,
    ) -> ScheduledJob:
        """Register a new schedulable job.

        Args:
            job_id: A stable, unique identifier for this job.
            name: Human-readable display name.
            frequency: How often this job is intended to run. See
                :class:`~automation.models.ScheduleFrequency`.
            callback: A zero-argument callable to invoke when this job
                runs (via :meth:`run_job`).
            enabled: Whether this job starts out eligible for
                :meth:`due_jobs`. A disabled job can still be triggered
                manually via :meth:`run_job`.

        Returns:
            The newly registered :class:`~automation.models.ScheduledJob`.

        Raises:
            JobAlreadyRegisteredError: If ``job_id`` is already
                registered.
        """
        if job_id in self._jobs:
            raise JobAlreadyRegisteredError(job_id)

        job = ScheduledJob(
            job_id=job_id,
            name=name,
            frequency=frequency,
            enabled=enabled,
            next_run_at=_next_run_at(frequency, since=_utc_now()),
        )
        self._jobs[job_id] = job
        self._callbacks[job_id] = callback
        return job

    def unregister_job(self, job_id: str) -> None:
        """Remove a job entirely. A no-op if ``job_id`` isn't registered.

        Args:
            job_id: The job id to remove.
        """
        self._jobs.pop(job_id, None)
        self._callbacks.pop(job_id, None)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------
    def get_job(self, job_id: str) -> ScheduledJob:
        """Look up a registered job by id.

        Args:
            job_id: The job id to look up.

        Returns:
            The matching :class:`~automation.models.ScheduledJob`.

        Raises:
            UnknownJobError: If no job is registered under ``job_id``.
        """
        job = self._jobs.get(job_id)
        if job is None:
            raise UnknownJobError(job_id, tuple(self._jobs.keys()))
        return job

    def list_jobs(self) -> tuple[ScheduledJob, ...]:
        """Return every registered job, ordered by job id.

        Returns:
            A tuple of :class:`~automation.models.ScheduledJob` values
            -- the source of the Automation Dashboard's "Scheduled
            Jobs" table (Task 10).
        """
        return tuple(sorted(self._jobs.values(), key=lambda j: j.job_id))

    def due_jobs(self, as_of: datetime | None = None) -> tuple[ScheduledJob, ...]:
        """Return every enabled, non-manual job whose ``next_run_at`` has passed.

        Nothing in this platform calls this on a timer this sprint --
        it exists so a future real scheduler's poll loop has something
        correct to ask (Task 5's "architectural design" objective).

        Args:
            as_of: The instant to check against. Defaults to now.

        Returns:
            A tuple of due jobs, ordered by job id.
        """
        moment = as_of if as_of is not None else _utc_now()
        return tuple(
            job
            for job in self.list_jobs()
            if job.enabled and job.next_run_at is not None and job.next_run_at <= moment
        )

    # ------------------------------------------------------------------
    # Execution -- Task 5 ("manual execution")
    # ------------------------------------------------------------------
    def run_job(self, job_id: str) -> JobExecutionResult:
        """Run a job's callback immediately, regardless of its schedule.

        This is the one execution path this sprint actually exercises
        -- both a future scheduler's automatic trigger and the
        Automation Dashboard's "Run Now" button call exactly this
        method. Updates the job's ``last_run_at``, ``last_status``, and
        (for non-manual jobs) ``next_run_at`` regardless of whether the
        callback succeeded or raised.

        Args:
            job_id: The job to run.

        Returns:
            A :class:`~automation.models.JobExecutionResult` describing
            the outcome. A callback that raises is captured here, not
            re-raised -- a single misbehaving job must never be able to
            take down whatever triggered it (the same resilience
            guarantee :class:`~monitoring.service.MonitoringService`
            and :class:`~automation.service.AutomationService` already
            make for their own failure paths).

        Raises:
            UnknownJobError: If no job is registered under ``job_id``.
        """
        job = self.get_job(job_id)  # validates existence; raises UnknownJobError
        callback = self._callbacks[job_id]

        started_at = _utc_now()
        start = time.perf_counter()
        try:
            result = callback()
            duration_ms = (time.perf_counter() - start) * 1000.0
            status = JobStatus.SUCCESS
            error = None
        except Exception as exc:  # noqa: BLE001 - deliberately captured, never re-raised
            duration_ms = (time.perf_counter() - start) * 1000.0
            result = None
            status = JobStatus.FAILED
            error = str(exc)
            logger.warning("Scheduled job '%s' failed: %s", job_id, exc)

        updated = ScheduledJob(
            job_id=job.job_id,
            name=job.name,
            frequency=job.frequency,
            enabled=job.enabled,
            last_run_at=started_at,
            last_status=status,
            next_run_at=_next_run_at(job.frequency, since=started_at),
        )
        self._jobs[job_id] = updated

        return JobExecutionResult(
            job_id=job_id, status=status, started_at=started_at, duration_ms=duration_ms, result=result, error=error
        )

    def set_enabled(self, job_id: str, enabled: bool) -> ScheduledJob:
        """Enable or disable a job without removing it.

        Args:
            job_id: The job to update.
            enabled: The new enabled state.

        Returns:
            The updated :class:`~automation.models.ScheduledJob`.

        Raises:
            UnknownJobError: If no job is registered under ``job_id``.
        """
        job = self.get_job(job_id)
        updated = ScheduledJob(
            job_id=job.job_id,
            name=job.name,
            frequency=job.frequency,
            enabled=enabled,
            last_run_at=job.last_run_at,
            last_status=job.last_status,
            next_run_at=job.next_run_at,
        )
        self._jobs[job_id] = updated
        return updated

    def clear(self) -> None:
        """Remove every registered job.

        Primarily useful for tests that need a clean scheduler rather
        than the shared, application-wide instance.
        """
        self._jobs.clear()
        self._callbacks.clear()


def _next_run_at(frequency: ScheduleFrequency, *, since: datetime) -> datetime | None:
    """Compute the next run time for ``frequency``, relative to ``since``.

    Args:
        frequency: The job's schedule frequency.
        since: The instant to compute the next run relative to
            (typically "now", or the moment a job just finished
            running).

    Returns:
        ``since + <the frequency's interval>``, or ``None`` for
        :attr:`~automation.models.ScheduleFrequency.MANUAL` jobs, which
        are never automatically "due".
    """
    delta = _FREQUENCY_DELTAS.get(frequency)
    return since + delta if delta is not None else None


# A shared, ready-to-use instance -- mirrors ``identity.session.session_manager``.
# Default demo jobs are registered against this instance by
# ``config.automation_setup`` at composition-root time, not here, so this
# module stays free of any business-specific job definitions.
scheduler = Scheduler()
