"""Deployment information for the NovaMart Production Platform.

Sprint 6.9 -- Production Readiness Platform, Task 7, Task 10.

A thin, read-only helper that assembles a
:class:`~configuration.models.DeploymentInfo` snapshot from
:class:`~configuration.service.ConfigurationService` -- for the
Operations Dashboard's "Deployment information" section. This module
never decides *how* to deploy anything; see
``docs/PRODUCTION_ARCHITECTURE.md``'s Deployment Strategy section for
that. It only describes, for humans, what is currently running.
"""

from __future__ import annotations

from datetime import datetime, timezone

from configuration.environments import APP_VERSION
from configuration.models import DeploymentInfo
from configuration.service import ConfigurationService, configuration_service as default_configuration_service

_DEPLOYMENT_STRATEGIES: dict[str, str] = {
    "development": "Single local process (`streamlit run app.py`); no build artifact, no HTTPS termination.",
    "testing": "Single staging process behind a reverse proxy; deployed from a tagged build, no external traffic.",
    "production": "Containerized process behind a load balancer with HTTPS termination; deployed from a released, versioned build.",
}


def build_deployment_info(configuration_service: ConfigurationService | None = None) -> DeploymentInfo:
    """Assemble a :class:`~configuration.models.DeploymentInfo` snapshot.

    Args:
        configuration_service: The service to read the active
            environment from. Defaults to the shared
            :data:`~configuration.service.configuration_service`.

    Returns:
        A :class:`~configuration.models.DeploymentInfo` describing the
        currently active environment, application version, and
        deployment strategy.
    """
    service = configuration_service if configuration_service is not None else default_configuration_service
    environment = service.environment
    strategy = _DEPLOYMENT_STRATEGIES.get(environment.value, "Not documented for this environment.")

    return DeploymentInfo(
        environment=environment,
        version=APP_VERSION,
        deployment_strategy=strategy,
        build_metadata={"require_https": str(service.environment_profile.require_https)},
        generated_at=datetime.now(timezone.utc),
    )
