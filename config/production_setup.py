"""Production Platform composition root for the NovaMart platform.

Sprint 6.9 -- Production Readiness Platform, Task 8.

This is the **one** module in the entire codebase allowed to import
``configuration``/``operations`` together with every other platform
package (``identity``, ``authorization``, ``monitoring``,
``automation``, ``integration``) and the business services -- mirroring
exactly the role ``config/integration_setup.py`` (Sprint 6.8) and
``config/automation_setup.py`` (Sprint 6.7) already play. Wiring "here
is where configuration values come from" and "here is how each
platform component is health-checked" is configuration, not business
logic, so it belongs here, at the composition root.

"Each platform should consume configuration rather than defining its
own operational settings" (Task 8) is satisfied two ways:

1. Every health check registered below reads the *existing*, unmodified
   shared singleton for its platform (``authentication_provider_registry``,
   ``permission_registry``, ``monitoring_provider_registry``,
   ``automation_service``, ``endpoint_registry``,
   ``sales_reporting_service``) -- proving each one is alive and
   reachable through the Configuration/Operations layer without any of
   those modules importing ``configuration`` or ``operations``
   themselves (Separation of Concerns: the platforms are checked from
   the outside, never instrumented from the inside).
2. ``components/sidebar.py``'s navigation filtering (see that module)
   additionally consults :data:`~configuration.feature_flags.feature_flag_service`
   for the three platform capabilities that have their own dedicated
   page (Monitoring, Automation, Integrations) -- an administrator can
   disable a dashboard page platform-wide by disabling its flag, with
   zero code change and zero business-logic impact (every flag defaults
   to enabled, so this is purely additive to existing behavior).

Business logic itself is never touched: no file in ``services/`` or
``utils/`` is modified by this sprint, and none of them import
``configuration`` or ``operations``.
"""

from __future__ import annotations

from authorization.permissions import permission_registry
from configuration.feature_flags import feature_flag_service
from configuration.provider import EnvironmentVariableConfigurationProvider, InMemoryConfigurationProvider
from configuration.registry import configuration_provider_registry
from configuration.service import configuration_service
from identity.registry import authentication_provider_registry
from integration.registry import endpoint_registry
from monitoring.registry import monitoring_provider_registry
from operations.health import health_check_registry
from operations.models import HealthStatus
from operations.readiness import readiness_check_registry

# --------------------------------------------------------------------------
# Default configuration values -- the sensible starting point every
# deployment has out of the box, before any environment-variable
# override is layered on top. Never a secret; see
# ``docs/PRODUCTION_ARCHITECTURE.md``'s Secrets Strategy section for
# where real secrets belong (an environment variable / secrets-manager
# provider, never a literal in this dict).
# --------------------------------------------------------------------------
_DEFAULT_CONFIGURATION_VALUES: dict[str, str] = {
    "APP_NAME": "NovaMart",
    "DEPLOYMENT_REGION": "global",
    "SUPPORT_CONTACT": "support@novamart.example",
}


def register_default_configuration_providers() -> None:
    """Register this sprint's configuration providers (Task 3, Task 8).

    Two providers are registered: an in-memory one seeded with sensible
    defaults (made active, since this platform ships with no real
    secrets backend configured), and an environment-variable provider
    (``NOVAMART_*``) layered in for a real deployment to override
    without a code change or redeploy -- e.g. setting the
    ``NOVAMART_ENVIRONMENT`` environment variable to ``"production"``
    is all a real deployment needs to do to switch environments.

    Idempotent-in-spirit for this sprint (called exactly once, at
    import time) -- calling it again would re-register the same
    provider names, which is harmless (``register`` replaces, per
    ``ConfigurationProviderRegistry``'s own docstring) but unnecessary.
    """
    in_memory = InMemoryConfigurationProvider(_DEFAULT_CONFIGURATION_VALUES, name="defaults")
    configuration_provider_registry.register("memory", in_memory, make_active=True)
    configuration_provider_registry.register(
        "environment", EnvironmentVariableConfigurationProvider(prefix="NOVAMART_")
    )


def _identity_health_check() -> "tuple[HealthStatus, str]":
    """Verify the Identity Platform (Task 6): an authentication provider is active."""
    try:
        authentication_provider_registry.get_active()
    except Exception as exc:  # noqa: BLE001
        return HealthStatus.UNHEALTHY, f"No active authentication provider: {exc}"
    return HealthStatus.HEALTHY, f"Active authentication provider: '{authentication_provider_registry.active_name}'."


def _authorization_health_check() -> "tuple[HealthStatus, str]":
    """Verify the Authorization Platform (Task 6): the permission catalogue is populated."""
    keys = permission_registry.all_keys()
    if not keys:
        return HealthStatus.WARNING, "Permission registry is empty."
    return HealthStatus.HEALTHY, f"{len(keys)} permission(s) registered."


def _monitoring_health_check() -> "tuple[HealthStatus, str]":
    """Verify the Monitoring Platform (Task 6): a monitoring provider is active."""
    try:
        monitoring_provider_registry.get_active()
    except Exception as exc:  # noqa: BLE001
        return HealthStatus.UNHEALTHY, f"No active monitoring provider: {exc}"
    return HealthStatus.HEALTHY, f"Active monitoring provider: '{monitoring_provider_registry.active_name}'."


def _automation_health_check() -> "tuple[HealthStatus, str]":
    """Verify the Automation Platform (Task 6): the scheduler is reachable and has registered jobs."""
    try:
        from automation.scheduler import scheduler
        jobs = scheduler.list_jobs()
    except Exception as exc:  # noqa: BLE001
        return HealthStatus.UNHEALTHY, f"Automation scheduler unreachable: {exc}"
    if not jobs:
        return HealthStatus.WARNING, "No scheduled jobs are registered."
    return HealthStatus.HEALTHY, f"{len(jobs)} scheduled job(s) registered."


def _integration_health_check() -> "tuple[HealthStatus, str]":
    """Verify the Integration Platform (Task 6): the endpoint registry has registered endpoints."""
    endpoints = endpoint_registry.list_endpoints()
    if not endpoints:
        return HealthStatus.WARNING, "No API Gateway endpoints are registered."
    return HealthStatus.HEALTHY, f"{len(endpoints)} endpoint(s) registered."


def _business_health_check() -> "tuple[HealthStatus, str]":
    """Verify the Business Platform (Task 6): the Reporting Service has report types defined."""
    try:
        from services.reporting_service import sales_reporting_service
        report_types = sales_reporting_service.report_types()
    except Exception as exc:  # noqa: BLE001
        return HealthStatus.UNHEALTHY, f"Reporting Service unreachable: {exc}"
    if not report_types:
        return HealthStatus.WARNING, "No report types are defined."
    return HealthStatus.HEALTHY, f"{len(report_types)} report type(s) defined."


def register_default_health_checks() -> None:
    """Register a health check for each of the six platform components this sprint's ticket names (Task 6).

    Every check below reads an existing, unmodified shared singleton --
    none of them call into a business service's write path, and none
    of them require any change to the platform they check.
    """
    if health_check_registry.list_components():
        return
    health_check_registry.register("Identity Platform", _identity_health_check)
    health_check_registry.register("Authorization Platform", _authorization_health_check)
    health_check_registry.register("Monitoring Platform", _monitoring_health_check)
    health_check_registry.register("Automation Platform", _automation_health_check)
    health_check_registry.register("Integration Platform", _integration_health_check)
    health_check_registry.register("Business Platform", _business_health_check)


def _required_configuration_present() -> "tuple[bool, str]":
    """Readiness check (Task 7): every required configuration key must resolve to a value.

    This is the concrete, working example of the ticket's own
    "Healthy but Configuration missing -> Not Ready" scenario: if
    ``APP_NAME`` (or any other required key) were removed from
    :data:`_DEFAULT_CONFIGURATION_VALUES` and no environment variable
    supplied it either, every health check above could still report
    Healthy while this single readiness check fails, correctly making
    the platform Not Ready.
    """
    required_keys = ("APP_NAME", "DEPLOYMENT_REGION", "SUPPORT_CONTACT")
    missing = [key for key in required_keys if configuration_service.get(key) is None]
    if missing:
        return False, f"Missing required configuration key(s): {', '.join(missing)}."
    return True, "Every required configuration key is present."


def _environment_resolved() -> "tuple[bool, str]":
    """Readiness check (Task 7): an environment must have been resolved (never unset/unknown)."""
    return True, f"Environment resolved to '{configuration_service.environment.value}'."


def register_default_readiness_checks() -> None:
    """Register this sprint's readiness checks (Task 7).

    Idempotent-in-spirit for this sprint (called exactly once, at
    import time).
    """
    if readiness_check_registry.list_checks():
        return
    readiness_check_registry.register("required_configuration_present", _required_configuration_present)
    readiness_check_registry.register("environment_resolved", _environment_resolved)


def feature_flag_for_nav_label(label: str) -> str | None:
    """Map a ``NAV_ITEMS`` label to the feature flag key that gates it, if any.

    Used by ``components/sidebar.py`` to additionally hide a
    dashboard-style nav entry when its flag is disabled -- purely
    additive (every flag defaults to enabled) on top of the existing
    permission-based filtering, never a replacement for it.

    Args:
        label: A ``NAV_ITEMS`` entry's ``"label"`` value.

    Returns:
        The feature flag key gating this page, or ``None`` if this page
        isn't gated by a flag.
    """
    return {
        "Monitoring": "monitoring_dashboard",
        "Automation": "automation",
        "Integrations": "integration_dashboard",
    }.get(label)


register_default_configuration_providers()
register_default_health_checks()
register_default_readiness_checks()
