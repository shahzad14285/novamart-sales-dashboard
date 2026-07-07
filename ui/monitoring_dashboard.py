"""Administration / Monitoring dashboard for the NovaMart Sales Intelligence Dashboard.

Sprint 6.4 -- Observability & Monitoring Service, Task 9.

Renders the platform's operational visibility screen entirely from
``monitoring_service`` queries: Platform Overview, Service Statistics,
Tenant Activity, and a Recent Events log. This module has exactly one
responsibility -- presenting already-computed monitoring data -- and
never records an event itself; every number shown here is *read*
through the same :data:`~monitoring.service.monitoring_service` every
business service already reports *into* (Tasks 3-8), so this page
requires zero special-casing per service and automatically reflects
any future service that starts calling ``time_operation``.

This is deliberately an *administration* screen, not a tenant-scoped
one: unlike the Dashboard/Sales/Products/Customers/Reports pages
(which show one organization's own data), an operator needs to see
every service's health and every tenant's activity side by side to
spot a platform-wide problem or a single noisy tenant. The active
tenant from the sidebar is shown for session context only -- it never
filters what this page displays.

The Monitoring dashboard does NOT:
    - Record monitoring events (that's every business service, via
      ``monitoring_service.time_operation``/``record_*``).
    - Decide how events are stored (that's a
      :class:`~monitoring.provider.MonitoringProvider`).
    - Filter data by the currently active tenant -- an admin overview
      must show every tenant, which is the entire point of the
      "Tenant Activity" section below.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from components.empty_state import render_empty_state
from monitoring.models import EventStatus, EventType, MonitoringEvent, ServiceHealth, TenantActivity
from monitoring.service import monitoring_service
from tenancy.context import TenantContext
from utils.formatting import format_integer

_RECENT_EVENTS_LIMIT = 50

_STATUS_BADGES: dict[EventStatus, str] = {
    EventStatus.SUCCESS: "✅ Success",
    EventStatus.FAILURE: "❌ Failure",
    EventStatus.WARNING: "⚠️ Warning",
    EventStatus.IN_PROGRESS: "⏳ In progress",
    EventStatus.INFO: "ℹ️ Info",
}

_EVENT_TYPE_LABELS: dict[EventType, str] = {
    EventType.OPERATION_STARTED: "Started",
    EventType.OPERATION_COMPLETED: "Completed",
    EventType.OPERATION_FAILED: "Failed",
    EventType.WARNING: "Warning",
    EventType.INFO: "Info",
}

_ALL_FILTER_OPTION = "All"


def render_monitoring_dashboard(tenant_context: TenantContext | None = None) -> None:
    """Render the full Administration / Monitoring dashboard.

    Args:
        tenant_context: The active tenant for the current session, if
            any. Shown as session context only (a caption noting which
            organization is currently selected in the sidebar) -- it
            never scopes or filters the platform-wide data below,
            since this is an administration screen meant to show every
            tenant and every service at once.
    """
    if tenant_context is not None and tenant_context.tenant is not None:
        st.caption(
            f"Signed in under organization: **{tenant_context.tenant.display_name}**  ·  "
            "This page shows operational data for the whole platform, across every tenant."
        )
    else:
        st.caption("This page shows operational data for the whole platform, across every tenant.")

    st.markdown('<p class="nm-section-title">🩺 Platform Overview</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Aggregated across every monitored service and tenant.</p>',
        unsafe_allow_html=True,
    )
    _render_platform_overview()

    st.divider()
    st.markdown('<p class="nm-section-title">🧩 Service Statistics</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Per-service request volume, reliability, and latency.</p>',
        unsafe_allow_html=True,
    )
    _render_service_statistics()

    st.divider()
    st.markdown('<p class="nm-section-title">🏢 Tenant Activity</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Operations recorded per organization, across every service.</p>',
        unsafe_allow_html=True,
    )
    _render_tenant_activity()

    st.divider()
    st.markdown('<p class="nm-section-title">📜 Recent Events</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">The latest recorded operations, newest first.</p>',
        unsafe_allow_html=True,
    )
    _render_recent_events()


# ==============================================================================
# Platform Overview
# ==============================================================================


def _render_platform_overview() -> None:
    """Render the four platform-wide headline metrics as bordered cards."""
    stats = monitoring_service.get_platform_stats()

    if stats.total_operations == 0:
        render_empty_state(
            "No monitored operations have been recorded yet. Numbers will appear here as soon "
            "as the platform's services start processing requests.",
            icon="🩺",
        )
        return

    columns = st.columns(4)
    with columns[0]:
        with st.container(border=True):
            st.metric("Total Operations", format_integer(stats.total_operations))
    with columns[1]:
        with st.container(border=True):
            st.metric("Successful Operations", format_integer(stats.successful_operations))
    with columns[2]:
        with st.container(border=True):
            st.metric("Failed Operations", format_integer(stats.failed_operations))
    with columns[3]:
        with st.container(border=True):
            st.metric("Average Response Time", _format_duration_ms(stats.average_duration_ms))


# ==============================================================================
# Service Statistics
# ==============================================================================


def _render_service_statistics() -> None:
    """Render a table of per-service request volume, reliability, and latency."""
    service_health = monitoring_service.get_all_service_health()

    if not service_health:
        render_empty_state(
            "No service has recorded any monitored operations yet.",
            icon="🧩",
        )
        return

    table = pd.DataFrame(
        {
            "Service": [health.service_name for health in service_health],
            "Total Requests": [health.total_executions for health in service_health],
            "Success Rate": [_format_success_rate(health) for health in service_health],
            "Avg. Duration": [_format_duration_ms(health.average_duration_ms) for health in service_health],
            "Warnings": [health.warning_count for health in service_health],
            "Last Activity": [_format_timestamp(health.last_execution) for health in service_health],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)


def _format_success_rate(health: ServiceHealth) -> str:
    """Format a service's success rate as a percentage string, or "-" with no finished runs."""
    if health.total_executions == 0:
        return "—"
    rate = (health.successful_executions / health.total_executions) * 100
    return f"{rate:.1f}%"


# ==============================================================================
# Tenant Activity
# ==============================================================================


def _render_tenant_activity() -> None:
    """Render operations-per-tenant, the most active tenant, and each tenant's last activity."""
    activities = monitoring_service.get_tenant_activity()

    if not activities:
        render_empty_state(
            "No tenant-attributed operations have been recorded yet.",
            icon="🏢",
        )
        return

    most_active = monitoring_service.most_active_tenant()
    if most_active is not None:
        with st.container(border=True):
            st.metric(
                "Most Active Tenant",
                most_active.tenant_name,
                help=f"{format_integer(most_active.operation_count)} operation(s) recorded.",
            )

    table_col, chart_col = st.columns([2, 3])
    table = pd.DataFrame(
        {
            "Tenant": [activity.tenant_name for activity in activities],
            "Operations": [activity.operation_count for activity in activities],
            "Last Activity": [_format_timestamp(activity.last_activity) for activity in activities],
        }
    )
    with table_col:
        st.dataframe(table, use_container_width=True, hide_index=True)
    with chart_col:
        chart_data = pd.DataFrame(
            {"Operations": [activity.operation_count for activity in activities]},
            index=[activity.tenant_name for activity in activities],
        )
        st.bar_chart(chart_data)


# ==============================================================================
# Recent Events
# ==============================================================================


def _render_recent_events() -> None:
    """Render a filterable log of the most recently recorded monitoring events."""
    service_names = tuple(health.service_name for health in monitoring_service.get_all_service_health())

    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        service_filter = st.selectbox(
            "Filter by service",
            options=(_ALL_FILTER_OPTION, *service_names),
            key="monitoring_dashboard_service_filter",
        )
    with filter_col2:
        status_filter = st.selectbox(
            "Filter by status",
            options=(_ALL_FILTER_OPTION, *[status.value for status in EventStatus]),
            format_func=lambda value: value if value == _ALL_FILTER_OPTION else _STATUS_BADGES.get(
                EventStatus(value), value.title()
            ),
            key="monitoring_dashboard_status_filter",
        )

    events = monitoring_service.get_events(
        service_name=None if service_filter == _ALL_FILTER_OPTION else service_filter,
        status=None if status_filter == _ALL_FILTER_OPTION else EventStatus(status_filter),
        limit=_RECENT_EVENTS_LIMIT,
    )

    if not events:
        render_empty_state("No events match the current filters.", icon="📜")
        return

    table = pd.DataFrame(
        {
            "Timestamp": [_format_timestamp(event.timestamp) for event in events],
            "Tenant": [event.tenant_name or "—" for event in events],
            "Service": [event.service_name for event in events],
            "Operation": [event.operation for event in events],
            "Type": [_EVENT_TYPE_LABELS.get(event.event_type, str(event.event_type.value)) for event in events],
            "Status": [_STATUS_BADGES.get(event.status, str(event.status.value)) for event in events],
            "Duration": [_format_duration_ms(event.duration_ms) for event in events],
            "Message": [event.message or "" for event in events],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"Showing the {len(events)} most recent matching event(s).")


# ==============================================================================
# Shared formatting helpers
# ==============================================================================


def _format_duration_ms(value: float | None) -> str:
    """Format a millisecond duration for display, or "-" if never measured.

    Args:
        value: A duration in milliseconds, or ``None``.

    Returns:
        ``"—"`` if ``value`` is ``None``; otherwise ``"123 ms"`` for
        sub-second durations or ``"1.23 s"`` once it reaches a full
        second, so the dashboard never shows an unwieldy number of
        decimal places for very fast operations.
    """
    if value is None:
        return "—"
    if value < 1000:
        return f"{value:.0f} ms"
    return f"{value / 1000:.2f} s"


def _format_timestamp(value: datetime | None) -> str:
    """Format a UTC timestamp for display, or "-" if there isn't one.

    Args:
        value: A timezone-aware UTC datetime, or ``None``.

    Returns:
        ``"—"`` if ``value`` is ``None``; otherwise a
        ``"Jul 07, 2026 14:32 UTC"``-style string.
    """
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
