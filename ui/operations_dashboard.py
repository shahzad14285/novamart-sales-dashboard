"""Operations Dashboard for the NovaMart Sales Intelligence Dashboard.

Sprint 6.9 -- Production Readiness Platform, Task 10.

Renders the platform's production-readiness administration screen:
Current Environment, Active Configuration Provider, Feature Flags,
Health Status, Readiness Status, Configuration Summary, and Deployment
Information. Mirrors ``ui/integration_dashboard.py`` and
``ui/automation_dashboard.py`` exactly in shape and intent -- this
module has exactly one responsibility, presenting the current
configuration/health/readiness state, and never mutates platform state
itself except through the explicit, admin-initiated Feature Flag
toggle buttons (the same kind of deliberate write action the
Automation Dashboard's "Run Now" button already performs).

Administrator access only (Task 10) -- enforced by the calling page
(``pages/10_Operations.py``) requiring the existing ``manage_platform``
permission, granted only to the System Administrator role.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from components.empty_state import render_empty_state
from configuration.feature_flags import feature_flag_registry, feature_flag_service
from configuration.service import configuration_service
from operations.deployment import build_deployment_info
from operations.health import health_check_service
from operations.models import HealthStatus
from operations.readiness import readiness_service

_HEALTH_STATUS_BADGES: dict[HealthStatus, str] = {
    HealthStatus.HEALTHY: "✅ Healthy",
    HealthStatus.WARNING: "⚠️ Warning",
    HealthStatus.UNHEALTHY: "❌ Unhealthy",
}

_CONFIG_SUMMARY_KEYS: tuple[str, ...] = ("APP_NAME", "DEPLOYMENT_REGION", "SUPPORT_CONTACT")


def render_operations_dashboard() -> None:
    """Render the full Operations Dashboard."""
    st.caption(
        "This page shows platform-wide configuration, health, and readiness state, "
        "sourced live from the Configuration, Health Check, and Readiness services."
    )

    st.markdown('<p class="nm-section-title">🌐 Current Environment</p>', unsafe_allow_html=True)
    _render_environment_summary()

    st.divider()
    st.markdown('<p class="nm-section-title">🗄️ Active Configuration Provider</p>', unsafe_allow_html=True)
    _render_provider_summary()

    st.divider()
    st.markdown('<p class="nm-section-title">🚩 Feature Flags</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Toggle a platform capability on or off. Changes apply immediately, platform-wide.</p>',
        unsafe_allow_html=True,
    )
    _render_feature_flags()

    st.divider()
    st.markdown('<p class="nm-section-title">🩺 Health Status</p>', unsafe_allow_html=True)
    _render_health_status()

    st.divider()
    st.markdown('<p class="nm-section-title">✅ Readiness Status</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="nm-section-subtitle">Ready means Healthy <em>and</em> every readiness check (e.g. required '
        "configuration present) has passed -- a platform can be Healthy but still Not Ready.</p>",
        unsafe_allow_html=True,
    )
    _render_readiness_status()

    st.divider()
    st.markdown('<p class="nm-section-title">📋 Configuration Summary</p>', unsafe_allow_html=True)
    _render_configuration_summary()

    st.divider()
    st.markdown('<p class="nm-section-title">🚀 Deployment Information</p>', unsafe_allow_html=True)
    _render_deployment_information()


# ==============================================================================
# Current Environment
# ==============================================================================


def _render_environment_summary() -> None:
    """Render the active environment and its declared operational profile."""
    profile = configuration_service.environment_profile
    metric_cols = st.columns(4)
    with metric_cols[0]:
        st.metric("Environment", configuration_service.environment.value.title())
    with metric_cols[1]:
        st.metric("Logging Level", profile.logging_level.value.upper())
    with metric_cols[2]:
        st.metric("API Rate Limit", f"{profile.api_rate_limit_requests_per_minute}/min")
    with metric_cols[3]:
        st.metric("HTTPS Required", "Yes" if profile.require_https else "No")
    if profile.description:
        st.caption(profile.description)


# ==============================================================================
# Active Configuration Provider
# ==============================================================================


def _render_provider_summary() -> None:
    """Render which configuration provider is active, and every provider registered."""
    active = configuration_service.active_provider_name()
    registered = configuration_service.registered_provider_names()
    st.metric("Active Provider", active or "None")
    st.caption(f"Registered providers: {', '.join(registered) if registered else 'none'}.")


# ==============================================================================
# Feature Flags
# ==============================================================================


def _render_feature_flags() -> None:
    """Render every feature flag with its current state and a toggle button."""
    flags = feature_flag_service.all_flags()
    if not flags:
        render_empty_state("No feature flags are registered.", icon="🚩")
        return

    for key, enabled in flags:
        with st.container(border=True):
            name_col, status_col, action_col = st.columns([3, 2, 2])
            with name_col:
                definition = feature_flag_registry.get(key)
                st.markdown(f"**{key}**")
                if definition is not None and definition.description:
                    st.caption(definition.description)
            with status_col:
                st.caption("✅ Enabled" if enabled else "🚫 Disabled")
            with action_col:
                button_label = "Disable" if enabled else "Enable"
                if st.button(button_label, key=f"operations_dashboard_toggle_{key}", use_container_width=True):
                    if enabled:
                        feature_flag_service.disable(key)
                    else:
                        feature_flag_service.enable(key)
                    st.rerun()


# ==============================================================================
# Health Status
# ==============================================================================


def _render_health_status() -> None:
    """Render the aggregated platform health report."""
    report = health_check_service.check_all()
    st.metric("Overall Platform Health", _HEALTH_STATUS_BADGES.get(report.overall_status, report.overall_status.value))

    if not report.components:
        render_empty_state("No health checks are registered.", icon="🩺")
        return

    table = pd.DataFrame(
        {
            "Component": [component.component for component in report.components],
            "Status": [_HEALTH_STATUS_BADGES.get(component.status, component.status.value) for component in report.components],
            "Message": [component.message for component in report.components],
            "Checked At": [_format_timestamp(component.checked_at) for component in report.components],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)


# ==============================================================================
# Readiness Status
# ==============================================================================


def _render_readiness_status() -> None:
    """Render the platform readiness report, distinct from health."""
    report = readiness_service.evaluate()
    st.metric("Ready to Serve Traffic", "✅ Ready" if report.ready else "🚫 Not Ready")

    if not report.checks:
        render_empty_state("No readiness checks are registered.", icon="✅")
        return

    table = pd.DataFrame(
        {
            "Check": [check.check_name.replace("_", " ").title() for check in report.checks],
            "Passed": ["✅ Yes" if check.passed else "🚫 No" for check in report.checks],
            "Message": [check.message for check in report.checks],
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)


# ==============================================================================
# Configuration Summary
# ==============================================================================


def _render_configuration_summary() -> None:
    """Render every well-known configuration key with its resolved value and source."""
    rows = []
    for key in _CONFIG_SUMMARY_KEYS:
        detail = configuration_service.describe(key)
        rows.append(
            {
                "Key": detail.key,
                "Value": detail.value if detail.found else "(not set)",
                "Source": detail.source or "—",
                "Found": "✅ Yes" if detail.found else "🚫 No",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ==============================================================================
# Deployment Information
# ==============================================================================


def _render_deployment_information() -> None:
    """Render the current deployment snapshot: environment, version, strategy."""
    info = build_deployment_info(configuration_service)
    metric_cols = st.columns(2)
    with metric_cols[0]:
        st.metric("Version", info.version)
    with metric_cols[1]:
        st.metric("Environment", info.environment.value.title())
    st.caption(f"**Deployment strategy:** {info.deployment_strategy}")
    if info.build_metadata:
        st.caption(f"Build metadata: {dict(info.build_metadata)}")


# ==============================================================================
# Shared formatting helpers
# ==============================================================================


def _format_timestamp(value: datetime | None) -> str:
    """Format a UTC timestamp for display, or "-" if there isn't one."""
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
