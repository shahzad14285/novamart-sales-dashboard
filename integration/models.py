"""Integration Platform value objects for the NovaMart Integration Platform & API Gateway.

Sprint 6.8 -- Integration Platform & API Gateway, Task 4.

Every type here is a plain, immutable value object -- no behavior, no
storage, no Streamlit dependency -- matching the convention already
established by ``automation.models.AutomationEvent`` and
``notification.models.NotificationMessage``. :class:`IntegrationRequest`
is the single record :class:`~integration.gateway.APIGateway` receives
from an external caller; :class:`IntegrationResponse` is the single,
standardized record it returns. :class:`EndpointDefinition` is the
value object :class:`~integration.registry.EndpointRegistry` hands back
to describe one registered route.

Business services never construct an :class:`IntegrationRequest` or
:class:`IntegrationResponse` directly -- :class:`~integration.gateway.APIGateway`
is the only place either is built, which is what guarantees every
request's ``request_id``/``timestamp`` and every response's
``processing_time_ms`` are generated consistently regardless of which
external channel produced the request (the identical guarantee
``automation.events.build_event`` already makes for automation events).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class RequestMethod(str, Enum):
    """Which HTTP-style verb an :class:`IntegrationRequest` represents.

    A plain ``str`` subclass, matching every other enum in this
    platform. NovaMart does not run a real HTTP server this sprint
    ("Do NOT implement a production HTTP server. The objective is
    architecture.") -- these values exist so a future REST provider
    (see :mod:`integration.provider`) has a stable vocabulary to map
    real HTTP verbs onto, and so :class:`~integration.registry.EndpointRegistry`
    can distinguish, e.g., a ``GET`` "retrieve KPIs" endpoint from a
    ``POST`` "generate report" endpoint at the same path.
    """

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class ResponseStatus(str, Enum):
    """The standardized outcome of one :class:`IntegrationResponse` (Task 2: "standardized responses").

    Every failure mode the Gateway can produce gets its own member so a
    caller (or the Integration Dashboard) can distinguish "your request
    was malformed" from "you're not allowed to do that" from "you're
    calling too fast" without parsing a free-form message string.
    """

    SUCCESS = "success"
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    ERROR = "error"


class IntegrationChannel(str, Enum):
    """Which external channel/system an :class:`~integration.provider.IntegrationProvider` represents (Task 7).

    Every channel this sprint's ticket names as a future integration
    target has a member here -- only :attr:`REST_API` is exercised by
    this sprint's in-memory demo provider, but every future channel
    already has somewhere to plug in via
    :class:`~integration.registry.IntegrationProviderRegistry`, exactly
    like :class:`notification.models.NotificationChannel` before it.
    """

    REST_API = "rest_api"
    WEBHOOK = "webhook"
    ERP_CONNECTOR = "erp_connector"
    CRM_CONNECTOR = "crm_connector"
    POWER_BI = "power_bi"
    SALESFORCE = "salesforce"
    SAP = "sap"
    MS_DYNAMICS = "ms_dynamics"


@dataclass(frozen=True)
class IntegrationRequest:
    """One immutable record of an inbound request from an external caller.

    Attributes:
        request_id: A unique identifier for this request (a UUID4 hex
            string), assigned once at receipt time -- see
            :func:`integration.gateway.new_request_id`.
        api_version: The API version the caller targeted (e.g.
            ``"v1"``), used by
            :class:`~integration.registry.EndpointRegistry` to resolve
            the correct endpoint when the same logical endpoint has
            multiple versions registered.
        endpoint: The logical endpoint key the caller targeted (e.g.
            ``"kpi.retrieve"``), matching
            :attr:`EndpointDefinition.endpoint_key`. Deliberately a
            stable key, not a raw URL path, since this platform never
            parses a real HTTP path this sprint.
        method: Which verb this request represents. See
            :class:`RequestMethod`.
        tenant_id: The tenant this request is attributable to, or
            ``None`` if not yet resolved/known. Kept separate from
            ``tenant_name`` since it's the stable key used for
            filtering/rate-limiting (mirrors
            ``automation.models.AutomationEvent.tenant_id``).
        tenant_name: The tenant's human-readable display name, if
            known.
        user_id: The external caller's resolved identity (Sprint 6.6),
            if known at request-construction time. May be ``None`` on
            arrival and filled in by
            :class:`~integration.gateway.APIGateway` during
            authentication -- see
            :meth:`~integration.gateway.APIGateway.handle_request`.
        payload: Free-form, endpoint-specific request data (e.g.
            ``{"report_type": "executive"}``). Never inspected by the
            Gateway or Router themselves -- only by
            :class:`~integration.validation.RequestValidator` (for
            required-field checks) and the endpoint's own handler.
        timestamp: When the request was received, in UTC.

    Example:
        >>> from integration.gateway import build_request
        >>> request = build_request(
        ...     endpoint="kpi.retrieve", method=RequestMethod.GET, payload={},
        ... )
        >>> request.method
        <RequestMethod.GET: 'GET'>
    """

    request_id: str
    api_version: str
    endpoint: str
    method: RequestMethod
    timestamp: datetime
    tenant_id: str | None = None
    tenant_name: str | None = None
    user_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IntegrationResponse:
    """One immutable, standardized response returned by :class:`~integration.gateway.APIGateway` (Task 2, Task 4).

    Every path through :meth:`~integration.gateway.APIGateway.handle_request`
    -- success or any failure mode -- returns exactly this shape, which
    is what "standardized responses" means: an external caller (or a
    future REST/webhook provider translating this into an HTTP
    response) never needs to branch on which internal component
    produced the failure.

    Attributes:
        request_id: The originating :class:`IntegrationRequest`'s id,
            for correlation.
        status: The outcome. See :class:`ResponseStatus`.
        message: A short, business-friendly, human-readable summary
            (e.g. ``"Report generated successfully."`` or ``"Rate
            limit exceeded. Try again in 12 seconds."``).
        data: The endpoint handler's result, on success. ``None`` on
            any failure.
        errors: Zero or more business-friendly error strings (e.g.
            field-level validation messages). Empty on success.
        processing_time_ms: How long the Gateway took to handle this
            request end to end, in milliseconds.
        created_at: When this response was constructed (UTC).
    """

    request_id: str
    status: ResponseStatus
    message: str
    created_at: datetime
    data: object = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    processing_time_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        """Return ``True`` if this response represents a successful request."""
        return self.status == ResponseStatus.SUCCESS


@dataclass(frozen=True)
class EndpointDefinition:
    """A registered route's immutable metadata (Task 3).

    :class:`~integration.registry.EndpointRegistry` itself owns the
    actual handler callable a matching request is dispatched to
    (callables aren't meaningfully immutable/displayable value data, so
    they're kept out of this dataclass entirely -- the identical design
    decision ``automation.models.ScheduledJob`` already makes for its
    callback, storing it separately inside
    ``automation.scheduler.Scheduler``).

    Attributes:
        endpoint_key: Stable identifier for this endpoint (e.g.
            ``"kpi.retrieve"``), used by
            :class:`IntegrationRequest.endpoint` and by
            :class:`~integration.router.Router` to resolve a handler.
        path: A human-readable, REST-style path this endpoint would be
            reachable at in a future real HTTP server (e.g.
            ``"/api/v1/kpi"``) -- descriptive only this sprint, never
            parsed.
        method: Which verb this endpoint accepts. See
            :class:`RequestMethod`.
        api_version: Which API version this registration applies to
            (e.g. ``"v1"``). The same ``endpoint_key`` may be
            registered under multiple versions simultaneously (Task 3:
            "Support API versioning") -- see
            :meth:`~integration.registry.EndpointRegistry.register`.
        required_permission: The permission key
            (``authorization.permissions``) a caller must hold to
            reach this endpoint, or ``None`` for a publicly reachable
            endpoint (none are, this sprint, but the field exists for
            a future public health-check style endpoint).
        rate_limit_policy: The :class:`RateLimitPolicy` this endpoint
            is throttled under. Defaults to
            :data:`~integration.models.DEFAULT_RATE_LIMIT_POLICY` when
            not given at registration time.
        description: A short, human-readable explanation, suitable for
            an admin-facing endpoint catalogue (Task 10: "Registered
            endpoints").
        required_fields: Payload keys this endpoint's request must
            include, validated by
            :class:`~integration.validation.RequestValidator` before
            routing (Task 5).
    """

    endpoint_key: str
    path: str
    method: RequestMethod
    api_version: str
    required_permission: str | None = None
    rate_limit_policy: "RateLimitPolicy | None" = None
    description: str = ""
    required_fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RateLimitPolicy:
    """How many requests a caller may make in a rolling window (Task 6).

    Attributes:
        requests_per_minute: Maximum requests allowed in any rolling
            60-second window.
        requests_per_hour: Maximum requests allowed in any rolling
            3600-second window.
    """

    requests_per_minute: int
    requests_per_hour: int


#: The default policy applied to any endpoint that doesn't specify its
#: own -- generous enough not to interfere with normal use, strict
#: enough to demonstrate real throttling in a test or demo.
DEFAULT_RATE_LIMIT_POLICY = RateLimitPolicy(requests_per_minute=60, requests_per_hour=1000)


@dataclass(frozen=True)
class RateLimitStatus:
    """The outcome of one :meth:`~integration.rate_limiter.RateLimiter.check` call.

    Attributes:
        allowed: Whether this request is permitted to proceed.
        limit_key: The identifier (typically ``user:<id>`` or
            ``tenant:<id>``) this decision was evaluated against.
        requests_this_minute: How many requests ``limit_key`` has made
            in the current rolling minute, including this one if
            ``allowed`` is ``True``.
        requests_this_hour: How many requests ``limit_key`` has made in
            the current rolling hour, including this one if ``allowed``
            is ``True``.
        retry_after_seconds: How long the caller should wait before
            retrying, or ``0.0`` when ``allowed`` is ``True``.
    """

    allowed: bool
    limit_key: str
    requests_this_minute: int
    requests_this_hour: int
    retry_after_seconds: float = 0.0
