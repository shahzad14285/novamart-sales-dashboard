"""Automation Dashboard for the NovaMart Sales Intelligence Dashboard.

Sprint 6.7 -- Automation & Notification Platform, Task 10.

Renders the platform's automation visibility and administration screen
entirely from ``automation_service``, ``scheduler``, and
``notification_service`` queries: Recent Events, Event History,
Scheduled Jobs (with a manual "Run Now" trigger -- Task 5), and
Notification History with delivery status. Mirrors
``ui/monitoring_dashboard.py`` exactly in shape and intent: this module
has exactly one responsibility -- presenting already-published
automation data -- and never publishes an event or sends a
notification itself (aside from the explicit, admin-initiated "Run
Now" action, which is the same kind of deliberate write action the
Executive Report Center's "Generate PDF" button already performs).

This is deliberately an *administration* screen, not a tenant-scoped
one, mirroring the Monitoring dashboard: an operator needs to see every
event and every tenant's automation activity side by side. The active
tenant from the sidebar is shown for session context only.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from automation.models import EventProcessingStatus, EventType, ScheduledJob
from automation.scheduler import scheduler
from automation.service import automation_service
from components.empty_state import render_empty_state
from notification.models import NotificationChannel, NotificationMessage, NotificationStatus
from notification.service import notification_service
from tenancy.context import TenantContext

_RECENT_EVENTS_LIMIT = 50
_NOTIFICATION_HISTORY_LIMIT = 50

_EVENT_STATUS_BADGES: dict[EventProcessingStatus, str] = {
    EventProcessingStatus.PUBLISHED: "📣 Published",
    EventProcessingStatus.HANDLED: "✅ Handled",
    EventProcessingStatus.FAILED: "❌ Failed",
}

_NOTIFICATION_STATUS_BADGES: dict[NotificationStatus, str] = {
    NotificationStatus.SENT: "✅ Sent",
    NotificationStatus.FAILED: "❌ Failed",
    NotificationStatus.PENDING: "⏳ Pending",
}

_ALL_FILTER_OPTION = "All"


def render_automation_dashboard(tenant_context: TenantContext | None = None) -> None:
    """Render the full Automation Dashboard.

    Args:
        tenant_context: The active tenant for the current session, if
            any. Shown as session context only -- it never scopes or
            filters the platform-wide data below, mirroring
            ``ui.monitoring_dashboard.render_monitoring_dashboard``.
    """
    if tenant_context is not None and tenant_context.tenant is not None:
        st.caption(
            f"Signed in under organization: **{tenant_context.tenant.display_name}**  ·  "
            "This page shows automation activity for the whole platform, across every tenant."
        )
    else:
        st.caption("This page shows automation activity for the whole platform, across every tenant.")

    st.markdown('<p class="nm-section-title">📣 Recent Events</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">The latest automation events announced by business services, newest first.</p>',
        unsafe_allow_html=True,
    )
    _render_recent_events()

    st.divider()
    st.markdown('<p class="nm-section-title">🗓️ Scheduled Jobs</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Daily, weekly, and monthly automation jobs. Actual background '
        "execution is not enabled in this release -- use Run Now to trigger a job manually.</p>",
        unsafe_allow_html=True,
    )
    _render_scheduled_jobs()

    st.divider()
    st.markdown('<p class="nm-section-title">🔔 Notification History</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Notifications sent (simulated) in response to automation events, with delivery status.</p>',
        unsafe_allow_html=True,
    )
    _render_notification_history()


# ==============================================================================
# Recent Events / Event History
# ==============================================================================


def _render_recent_events() -> None:
    """Render a filterable log of published automation events."""
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        event_type_filter = st.selectbox(
            "Filter by event type",
            options=(_ALL_FILTER_OPTION, *[member.value for member in EventType]),
            key="automation_dashboard_event_type_filter",
        )
    with filter_col2:
        status_filter = st.selectbox(
            "Filter by status",
            options=(_ALL_FILTER_OPTION, *[status.value for status in EventProcessingStatus]),
            format_func=lambda value: value if value == _ALL_FILTER_OPTION else _EVENT_STATUS_BADGES.get(
                EventProcessingStatus(value), value.title()
            ),
            key="automation_dashboard_status_filter",
        )

    events = automation_service.get_events(
        event_type=None if event_type_filter == _ALL_FILTER_OPTION else event_type_filter,
        status=None if status_filter == _ALL_FILTER_OPTION else EventProcessingStatus(status_filter),
        limit=_RECENT_EVENTS_LIMIT,
    )

    if not events:
        render_empty_state(
            "No automation events have been published yet. Events appear here as soon as a "
            "business service announces something happened (an upload, a report, a sign-in, ...).",
            icon="📣",
        )
        return

    table = pd.DataFrame(
        {
            "Timestamp": [_format_timestamp(event.timestamp) for event in events],
            "Tenant": [event.tenant_name or "—" for event in events],
            "Event Type": [_event_type_label(event.event_type) for event in events],
            "Source Service": [event.source_service for event in events],
            "User": [event.user_id or "—" for event in events],
            "Status": [_EVENT_STATUS_BADGES.get(event.status, str(event.status.value)) for event in events],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"Showing the {len(events)} most recent matching event(s).")


def _event_type_label(event_type: EventType | str) -> str:
    """Format an event type for display, whether it's a known member or a future string."""
    value = event_type.value if isinstance(event_type, EventType) else str(event_type)
    return value.replace("_", " ").title()


# ==============================================================================
# Scheduled Jobs
# ==============================================================================


def _render_scheduled_jobs() -> None:
    """Render every registered scheduled job with a manual Run Now trigger (Task 5)."""
    jobs = scheduler.list_jobs()

    if not jobs:
        render_empty_state("No scheduled jobs are registered.", icon="🗓️")
        return

    for job in jobs:
        _render_job_row(job)


def _render_job_row(job: ScheduledJob) -> None:
    """Render one scheduled job as a bordered row: name, cadence, last run, status, Run Now."""
    with st.container(border=True):
        name_col, freq_col, last_run_col, status_col, action_col = st.columns([3, 2, 3, 2, 2])
        with name_col:
            st.markdown(f"**{job.name}**")
            st.caption(job.job_id)
        with freq_col:
            st.caption(f"Frequency: {job.frequency.value.title()}")
            st.caption("Enabled" if job.enabled else "Disabled")
        with last_run_col:
            st.caption(f"Last run: {_format_timestamp(job.last_run_at)}")
            st.caption(f"Next due: {_format_timestamp(job.next_run_at)}")
        with status_col:
            st.caption(_job_status_badge(job))
        with action_col:
            if st.button("Run Now", key=f"automation_dashboard_run_{job.job_id}", use_container_width=True):
                result = automation_service.trigger_scheduled_job(job.job_id)
                if result.error is None:
                    st.success(f"'{job.name}' ran successfully.", icon="✅")
                else:
                    st.error(f"'{job.name}' failed: {result.error}", icon="⚠️")
                st.rerun()


def _job_status_badge(job: ScheduledJob) -> str:
    """Format a scheduled job's last-run status for display."""
    from automation.models import JobStatus

    return {
        JobStatus.NEVER_RUN: "⏸️ Never run",
        JobStatus.SUCCESS: "✅ Success",
        JobStatus.FAILED: "❌ Failed",
    }.get(job.last_status, str(job.last_status.value))


# ==============================================================================
# Notification History
# ==============================================================================


def _render_notification_history() -> None:
    """Render a filterable log of sent/attempted notifications with delivery status."""
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        channel_filter = st.selectbox(
            "Filter by channel",
            options=(_ALL_FILTER_OPTION, *[channel.value for channel in NotificationChannel]),
            key="automation_dashboard_channel_filter",
        )
    with filter_col2:
        status_filter = st.selectbox(
            "Filter by delivery status",
            options=(_ALL_FILTER_OPTION, *[status.value for status in NotificationStatus]),
            format_func=lambda value: value if value == _ALL_FILTER_OPTION else _NOTIFICATION_STATUS_BADGES.get(
                NotificationStatus(value), value.title()
            ),
            key="automation_dashboard_notification_status_filter",
        )

    history = notification_service.get_history(
        channel=None if channel_filter == _ALL_FILTER_OPTION else NotificationChannel(channel_filter),
        status=None if status_filter == _ALL_FILTER_OPTION else NotificationStatus(status_filter),
        limit=_NOTIFICATION_HISTORY_LIMIT,
    )

    if not history:
        render_empty_state(
            "No notifications have been sent yet. Notifications appear here once an automation "
            "event with a configured route is published.",
            icon="🔔",
        )
        return

    table = pd.DataFrame(
        {
            "Sent At": [_format_timestamp(message.sent_at or message.created_at) for message in history],
            "Channel": [message.channel.value.title() for message in history],
            "Recipient": [message.recipient for message in history],
            "Subject": [message.subject for message in history],
            "Status": [_NOTIFICATION_STATUS_BADGES.get(message.status, str(message.status.value)) for message in history],
            "Error": [message.error or "" for message in history],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"Showing the {len(history)} most recent matching notification(s).")

    _render_notification_detail(history)


def _render_notification_detail(history: tuple[NotificationMessage, ...]) -> None:
    """Render an expandable detail view for the most recent notification's full body."""
    if not history:
        return
    latest = history[0]
    with st.expander(f"Preview: {latest.subject}"):
        st.caption(f"To: {latest.recipient}  ·  Channel: {latest.channel.value.title()}")
        st.write(latest.body)


# ==============================================================================
# Shared formatting helpers
# ==============================================================================


def _format_timestamp(value: datetime | None) -> str:
    """Format a UTC timestamp for display, or "-" if there isn't one."""
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
