"""Integration Platform & API Gateway for the NovaMart Sales Intelligence Dashboard.

Sprint 6.8 -- Integration Platform & API Gateway.

A small, framework-agnostic package (no Streamlit dependency anywhere
in it) that becomes the single entry point for every future external
integration -- ERP systems, CRM platforms, mobile apps, web portals,
partner systems, BI tools, external automation platforms. See
``docs/INTEGRATION_ARCHITECTURE.md`` for the full design rationale.

Typical usage from an :class:`~integration.provider.IntegrationProvider`
(never from a business service, and never from inside this package
itself)::

    from integration.gateway import api_gateway, build_request
    from integration.models import RequestMethod

    request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET)
    response = api_gateway.handle_request(request, session_id=session_id)

Typical usage from a composition-root wiring module (never from a
business service)::

    from integration.gateway import api_gateway
    from integration.models import EndpointDefinition, RequestMethod
    from integration.registry import endpoint_registry

    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="kpi.retrieve", path="/api/v1/kpi",
            method=RequestMethod.GET, api_version="v1",
            required_permission="view_dashboard",
        ),
        handler=_handle_kpi_retrieve,
    )
"""

from __future__ import annotations

from integration.exceptions import (
    DuplicateEndpointError,
    EndpointNotFoundError,
    GatewayAuthenticationError,
    GatewayAuthorizationError,
    IntegrationError,
    InvalidRequestError,
    ProviderNotRegisteredError,
    RateLimitExceededError,
)
from integration.gateway import APIGateway, api_gateway, build_request
from integration.models import (
    DEFAULT_RATE_LIMIT_POLICY,
    EndpointDefinition,
    IntegrationChannel,
    IntegrationRequest,
    IntegrationResponse,
    RateLimitPolicy,
    RateLimitStatus,
    RequestMethod,
    ResponseStatus,
)
from integration.provider import InMemoryIntegrationProvider, IntegrationProvider
from integration.rate_limiter import RateLimiter, rate_limiter
from integration.registry import (
    EndpointRegistry,
    IntegrationProviderRegistry,
    endpoint_registry,
    integration_provider_registry,
)
from integration.router import Router, router
from integration.validation import RequestValidator, request_validator

__all__ = [
    "DEFAULT_RATE_LIMIT_POLICY",
    "APIGateway",
    "DuplicateEndpointError",
    "EndpointDefinition",
    "EndpointNotFoundError",
    "EndpointRegistry",
    "GatewayAuthenticationError",
    "GatewayAuthorizationError",
    "InMemoryIntegrationProvider",
    "IntegrationChannel",
    "IntegrationError",
    "IntegrationProvider",
    "IntegrationProviderRegistry",
    "IntegrationRequest",
    "IntegrationResponse",
    "InvalidRequestError",
    "ProviderNotRegisteredError",
    "RateLimitExceededError",
    "RateLimitPolicy",
    "RateLimitStatus",
    "RateLimiter",
    "RequestMethod",
    "RequestValidator",
    "ResponseStatus",
    "Router",
    "api_gateway",
    "build_request",
    "endpoint_registry",
    "integration_provider_registry",
    "rate_limiter",
    "request_validator",
    "router",
]
