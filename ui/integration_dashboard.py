"""Integration Dashboard for the NovaMart Sales Intelligence Dashboard.

Sprint 6.8 -- Integration Platform & API Gateway, Task 10.

Renders the platform's Integration Platform & API Gateway
administration screen: Registered Endpoints, Request History, Rate
Limit Statistics, API Version Usage, Gateway Performance, Validation
Failures, and Integration Provider Status. Mirrors
``ui/automation_dashboard.py`` and ``ui/monitoring_dashboard.py``
exactly in shape and intent -- this module has exactly one
responsibility, presenting already-recorded Gateway activity, and never
issues a request through the Gateway itself.

Request History, Gateway Performance, and Validation Failures are all
read directly from the existing, shared
:data:`~monitoring.service.monitoring_service` (filtered to
``service_name="APIGateway"``) -- Task 9's "Do not introduce a second
monitoring mechanism" means this dashboard has no event log of its
own to query.

This is deliberately an *administration* screen, not a tenant-scoped
one, mirroring the Automation and Monitoring dashboards: an operator
needs to see every endpoint, every tenant's traffic, and every
provider side by side. The active tenant from the sidebar is shown for
session context only.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from components.empty_state import render_empty_state
from integration.models import DEFAULT_RATE_LIMIT_POLICY, RateLimitPolicy
from integration.provider import InMemoryIntegrationProvider
from integration.rate_limiter import rate_limiter
from integration.registry import endpoint_registry, integration_provider_registry
from monitoring.models import EventStatus
from monitoring.service import monitoring_service
from tenancy.context import TenantContext

_SERVICE_NAME = "APIGateway"
_REQUEST_HISTORY_LIMIT = 100
_ALL_FILTER_OPTION = "All"

_EVENT_STATUS_BADGES: dict[EventStatus, str] = {
    EventStatus.SUCCESS: "✅ Success",
    EventStatus.FAILURE: "❌ Failure",
    EventStatus.IN_PROGRESS: "⏳ In Progress",
    EventStatus.WARNING: "⚠️ Warning",
    EventStatus.INFO: "ℹ️ Info",
}


def render_integration_dashboard(tenant_context: TenantContext | None = None) -> None:
    """Render the full Integration Dashboard.

    Args:
        tenant_context: The active tenant for the current session, if
            any. Shown as session context only -- it never scopes or
            filters the platform-wide data below, mirroring
            ``ui.automation_dashboard.render_automation_dashboard``.
    """
    if tenant_context is not None and tenant_context.tenant is not None:
        st.caption(
            f"Signed in under organization: **{tenant_context.tenant.display_name}**  ·  "
            "This page shows API Gateway activity for the whole platform, across every tenant."
        )
    else:
        st.caption("This page shows API Gateway activity for the whole platform, across every tenant.")

    st.markdown('<p class="nm-section-title">🔌 Registered Endpoints</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Every endpoint currently registered with the API Gateway\'s Endpoint Registry.</p>',
        unsafe_allow_html=True,
    )
    _render_registered_endpoints()

    st.divider()
    st.markdown('<p class="nm-section-title">📜 Request History</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Requests received by the API Gateway, newest first -- sourced entirely '
        "from the platform's existing Monitoring service.</p>",
        unsafe_allow_html=True,
    )
    _render_request_history()

    st.divider()
    st.markdown('<p class="nm-section-title">⏱️ Rate Limit Statistics</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Current per-user / per-tenant / per-endpoint request counts against their configured ceilings.</p>',
        unsafe_allow_html=True,
    )
    _render_rate_limit_statistics()

    st.divider()
    st.markdown('<p class="nm-section-title">🔢 API Version Usage</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">How many recorded requests targeted each API version.</p>',
        unsafe_allow_html=True,
    )
    _render_api_version_usage()

    st.divider()
    st.markdown('<p class="nm-section-title">📈 Gateway Performance</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Aggregated operational health for the API Gateway, computed live from Monitoring events.</p>',
        unsafe_allow_html=True,
    )
    _render_gateway_performance()

    st.divider()
    st.markdown('<p class="nm-section-title">🚫 Validation Failures</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Requests rejected during validation, before authentication, authorization, or routing ran.</p>',
        unsafe_allow_html=True,
    )
    _render_validation_failures()

    st.divider()
    st.markdown('<p class="nm-section-title">🔗 Integration Provider Status</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Every channel adapter currently registered, and how many requests it has forwarded.</p>',
        unsafe_allow_html=True,
    )
    _render_provider_status()


# ==============================================================================
# Registered Endpoints
# ==============================================================================


def _render_registered_endpoints() -> None:
    """Render every endpoint currently registered with the Endpoint Registry."""
    endpoints = endpoint_registry.list_endpoints()

    if not endpoints:
        render_empty_state(
            "No endpoints are registered yet. Endpoints appear here as soon as a composition root "
            "(e.g. ``config/integration_setup.py``) registers one.",
            icon="🔌",
        )
        return

    table = pd.DataFrame(
        {
            "Endpoint": [ep.endpoint_key for ep in endpoints],
            "Path": [ep.path for ep in endpoints],
            "Method": [ep.method.value for ep in endpoints],
            "API Version": [ep.api_version for ep in endpoints],
            "Required Permission": [ep.required_permission or "—" for ep in endpoints],
            "Rate Limit": [_format_policy(ep.rate_limit_policy) for ep in endpoints],
            "Description": [ep.description or "—" for ep in endpoints],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"{len(endpoints)} endpoint(s) registered across {len(endpoint_registry.all_versions())} API version(s).")


def _format_policy(policy: RateLimitPolicy | None) -> str:
    """Format a rate limit policy for display, falling back to the Gateway's default."""
    effective = policy or DEFAULT_RATE_LIMIT_POLICY
    suffix = "" if policy is not None else " (default)"
    return f"{effective.requests_per_minute}/min, {effective.requests_per_hour}/hr{suffix}"


# ==============================================================================
# Request History (sourced entirely from monitoring_service -- Task 9)
# ==============================================================================


def _get_gateway_events(limit: int | None = None):
    """Fetch every recorded APIGateway monitoring event, newest first."""
    return monitoring_service.get_events(service_name=_SERVICE_NAME, limit=limit)


def _render_request_history() -> None:
    """Render a filterable log of every APIGateway monitoring event."""
    events = _get_gateway_events(limit=_REQUEST_HISTORY_LIMIT)

    if not events:
        render_empty_state(
            "No requests have been received yet. Requests appear here as soon as a caller "
            "(an IntegrationProvider forwarding on behalf of a REST client, webhook, or connector) "
            "reaches the API Gateway.",
            icon="📜",
        )
        return

    operations = sorted({event.operation for event in events})
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        operation_filter = st.selectbox(
            "Filter by lifecycle step",
            options=(_ALL_FILTER_OPTION, *operations),
            key="integration_dashboard_operation_filter",
        )
    with filter_col2:
        status_filter = st.selectbox(
            "Filter by outcome",
            options=(_ALL_FILTER_OPTION, *[status.value for status in EventStatus]),
            format_func=lambda value: value if value == _ALL_FILTER_OPTION else _EVENT_STATUS_BADGES.get(
                EventStatus(value), value.title()
            ),
            key="integration_dashboard_status_filter",
        )

    filtered = [
        event
        for event in events
        if (operation_filter == _ALL_FILTER_OPTION or event.operation == operation_filter)
        and (status_filter == _ALL_FILTER_OPTION or event.status.value == status_filter)
    ]

    if not filtered:
        render_empty_state("No requests match the selected filters.", icon="📜")
        return

    table = pd.DataFrame(
        {
            "Timestamp": [_format_timestamp(event.timestamp) for event in filtered],
            "Tenant": [event.tenant_name or "—" for event in filtered],
            "Lifecycle Step": [event.operation.replace("_", " ").title() for event in filtered],
            "Outcome": [_EVENT_STATUS_BADGES.get(event.status, str(event.status.value)) for event in filtered],
            "Duration (ms)": [f"{event.duration_ms:.1f}" if event.duration_ms is not None else "—" for event in filtered],
            "Endpoint": [event.metadata.get("endpoint", "—") for event in filtered],
            "Message": [event.message or "—" for event in filtered],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(filtered)} of {len(events)} recorded request event(s).")


# ==============================================================================
# Rate Limit Statistics
# ==============================================================================


def _render_rate_limit_statistics() -> None:
    """Render current usage for every caller/endpoint pair the Rate Limiter has seen."""
    keys = rate_limiter.tracked_keys()

    if not keys:
        render_empty_state(
            "No requests have been rate-limit-checked yet. Usage appears here once a request "
            "reaches the Gateway's rate limiting step.",
            icon="⏱️",
        )
        return

    endpoint_policies = {ep.endpoint_key: (ep.rate_limit_policy or DEFAULT_RATE_LIMIT_POLICY) for ep in endpoint_registry.list_endpoints()}

    rows = []
    for key in keys:
        scope = key.rsplit(":", 1)[-1] if ":" in key else "*"
        policy = endpoint_policies.get(scope, DEFAULT_RATE_LIMIT_POLICY)
        status = rate_limiter.stats(key, policy)
        rows.append(
            {
                "Caller / Endpoint": key,
                "Requests (last min)": f"{status.requests_this_minute} / {policy.requests_per_minute}",
                "Requests (last hr)": f"{status.requests_this_hour} / {policy.requests_per_hour}",
                "Currently Allowed": "✅ Yes" if status.allowed else "🚫 No",
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"Tracking {len(keys)} distinct caller/endpoint combination(s).")


# ==============================================================================
# API Version Usage
# ==============================================================================


def _render_api_version_usage() -> None:
    """Render a breakdown of recorded requests by API version."""
    events = _get_gateway_events()
    receive_events = [event for event in events if event.operation == "receive_request"]

    if not receive_events:
        render_empty_state("No requests have been received yet.", icon="🔢")
        return

    version_counts = Counter(event.metadata.get("api_version", "unknown") for event in receive_events)
    table = pd.DataFrame(
        {"API Version": list(version_counts.keys()), "Request Count": list(version_counts.values())}
    ).sort_values("API Version").reset_index(drop=True)
    st.dataframe(table, use_container_width=True, hide_index=True)


# ==============================================================================
# Gateway Performance
# ==============================================================================


def _render_gateway_performance() -> None:
    """Render aggregated operational health for the API Gateway (mirrors the Monitoring dashboard)."""
    health = monitoring_service.get_service_health(_SERVICE_NAME)

    if health.total_executions == 0 and health.warning_count == 0:
        render_empty_state("No completed or failed Gateway operations have been recorded yet.", icon="📈")
        return

    metric_cols = st.columns(4)
    with metric_cols[0]:
        st.metric("Total Executions", health.total_executions)
    with metric_cols[1]:
        st.metric("Successful", health.successful_executions)
    with metric_cols[2]:
        st.metric("Failed", health.failed_executions)
    with metric_cols[3]:
        avg = f"{health.average_duration_ms:.1f} ms" if health.average_duration_ms is not None else "—"
        st.metric("Avg. Duration", avg)

    if health.last_execution is not None:
        st.caption(f"Last activity: {_format_timestamp(health.last_execution)}")


# ==============================================================================
# Validation Failures
# ==============================================================================


def _render_validation_failures() -> None:
    """Render every request rejected during validation, before routing."""
    events = _get_gateway_events()
    failures = [event for event in events if event.operation == "validate_request"]

    if not failures:
        render_empty_state("No validation failures have been recorded.", icon="🚫")
        return

    table = pd.DataFrame(
        {
            "Timestamp": [_format_timestamp(event.timestamp) for event in failures],
            "Tenant": [event.tenant_name or "—" for event in failures],
            "Endpoint": [event.metadata.get("endpoint", "—") for event in failures],
            "Reason": [event.message or "—" for event in failures],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"{len(failures)} validation failure(s) recorded.")


# ==============================================================================
# Integration Provider Status
# ==============================================================================


def _render_provider_status() -> None:
    """Render every registered channel and its provider's traffic, if trackable."""
    channels = integration_provider_registry.registered_channels()

    if not channels:
        render_empty_state("No integration providers are registered yet.", icon="🔗")
        return

    rows = []
    for channel in channels:
        provider = integration_provider_registry.get(channel)
        forwarded_count = "—"
        if isinstance(provider, InMemoryIntegrationProvider):
            forwarded_count = str(len(provider.forwarded_requests()))
        rows.append({"Channel": channel, "Provider": provider.name, "Forwarded Requests": forwarded_count})

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"{len(channels)} channel(s) with a registered provider.")


# ==============================================================================
# Shared formatting helpers
# ==============================================================================


def _format_timestamp(value: datetime | None) -> str:
    """Format a UTC timestamp for display, or "-" if there isn't one."""
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
