"""API Gateway for the NovaMart Integration Platform.

Sprint 6.8 -- Integration Platform & API Gateway, Tasks 1, 2, 9.

The single entry point every external caller (a future REST client, a
webhook receiver, an ERP/CRM/BI connector -- see
:mod:`integration.provider`) goes through to reach anything inside
NovaMart. This module has exactly one responsibility -- orchestrating
the full request lifecycle (receive, validate, authenticate, authorize,
rate-limit, route, monitor, respond) -- and deliberately does nothing
else.

The API Gateway does NOT:
    - Contain any business logic. Every endpoint handler this sprint
      wires up (see ``config/integration_setup.py``) is a thin adapter
      that calls an already-existing, unmodified business service --
      the Gateway itself never knows what a KPI or a report is.
    - Decide *how* a request arrived (that's an
      :class:`~integration.provider.IntegrationProvider`, which calls
      *into* this module -- see that module's docstring for why the
      dependency points the other way, satisfying Task 7's "The API
      Gateway must remain provider-independent").
    - Re-implement authentication or authorization. It delegates to the
      exact same :data:`~identity.service.authentication_service` and
      :data:`~authorization.service.authorization_service` every
      Streamlit page already uses (Business Services must never be
      exposed directly to external systems -- but the *rules* for who
      may do what are not duplicated, only re-entered through a new
      front door).
    - Ever let a validation, authentication, authorization, rate-limit,
      or handler failure raise out to the caller. Every one of those is
      caught here and translated into a standardized
      :class:`~integration.models.IntegrationResponse` (Task 2: "Return
      standardized responses") -- the identical resilience guarantee
      :class:`~automation.service.AutomationService` and
      :class:`~notification.service.NotificationService` already make.

Request lifecycle (Task 2's responsibilities, in the order they run)
------------------------------------------------------------------------
1. **Receive** -- :meth:`APIGateway.handle_request` is called with an
   already-constructed :class:`~integration.models.IntegrationRequest`
   (see :func:`build_request`).
2. **Validate** -- :class:`~integration.validation.RequestValidator`
   confirms the endpoint exists and the payload is well-formed *before*
   anything else runs (Task 5).
3. **Authenticate** -- the caller's identity is resolved via
   :data:`~identity.service.authentication_service`.
4. **Authorize** -- the resolved identity's permissions are checked
   against the endpoint's ``required_permission`` via
   :data:`~authorization.service.authorization_service`.
5. **Rate limit** -- :data:`~integration.rate_limiter.rate_limiter`
   checks both the caller's user- and tenant-scoped ceilings (Task 6).
6. **Route** -- :class:`~integration.router.Router` dispatches to the
   endpoint's registered handler.
7. **Monitor** -- every one of the above steps records a monitoring
   event via the existing, shared
   :data:`~monitoring.service.monitoring_service` (Task 9) -- no second
   monitoring mechanism is introduced.
8. **Respond** -- a standardized
   :class:`~integration.models.IntegrationResponse` is returned,
   success or failure alike.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

from authorization.context import UserContext
from authorization.exceptions import AuthorizationError
from authorization.service import AuthorizationService, authorization_service as default_authorization_service
from identity.exceptions import AuthenticationError
from identity.service import AuthenticationService, authentication_service as default_authentication_service
from integration.exceptions import (
    EndpointNotFoundError,
    IntegrationError,
    InvalidRequestError,
)
from integration.models import (
    DEFAULT_RATE_LIMIT_POLICY,
    IntegrationRequest,
    IntegrationResponse,
    RequestMethod,
    ResponseStatus,
)
from integration.rate_limiter import RateLimiter, rate_limiter as default_rate_limiter
from integration.registry import EndpointRegistry, endpoint_registry as default_endpoint_registry
from integration.router import Router
from integration.validation import RequestValidator, request_validator as default_request_validator
from monitoring.service import monitoring_service
from tenancy.context import TenantContext
from tenancy.registry import tenant_registry

logger = logging.getLogger("novamart.integration.gateway")

_SERVICE_NAME = "APIGateway"
_DEFAULT_API_VERSION = "v1"


def new_request_id() -> str:
    """Generate a new, unique integration request id (UUID4 hex, mirrors ``automation.events.new_event_id``)."""
    return uuid.uuid4().hex


def build_request(
    *,
    endpoint: str,
    method: RequestMethod | str = RequestMethod.POST,
    api_version: str = _DEFAULT_API_VERSION,
    payload: dict | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> IntegrationRequest:
    """Construct a fully-populated :class:`~integration.models.IntegrationRequest`.

    The single place ``request_id`` and ``timestamp`` are generated --
    mirrors :func:`automation.events.build_event` exactly. A future
    :class:`~integration.provider.IntegrationProvider` (a REST adapter
    parsing a real HTTP request, a webhook receiver) calls this once it
    has translated its native payload into these keyword arguments.

    Args:
        endpoint: The target endpoint key.
        method: The HTTP-style method. Accepts a plain string as well
            as a :class:`~integration.models.RequestMethod` member.
        api_version: The target API version.
        payload: The request body/parameters.
        tenant_id: The caller's tenant, if already known.
        user_id: The caller's identity, if already known (typically
            unresolved at this point -- see
            :meth:`APIGateway.handle_request`, which fills this in
            during authentication if it wasn't supplied).

    Returns:
        A new, immutable :class:`~integration.models.IntegrationRequest`.
    """
    return IntegrationRequest(
        request_id=new_request_id(),
        api_version=api_version,
        endpoint=endpoint,
        method=RequestMethod(method) if not isinstance(method, RequestMethod) else method,
        timestamp=datetime.now(timezone.utc),
        tenant_id=tenant_id,
        user_id=user_id,
        payload=dict(payload) if payload else {},
    )


class APIGateway:
    """Centralized entry point orchestrating the full request lifecycle (Task 2).

    Example:
        >>> gateway = APIGateway()
        >>> request = build_request(endpoint="kpi.retrieve", method=RequestMethod.GET)
        >>> response = gateway.handle_request(request, session_id=session_id)
        >>> response.status
        <ResponseStatus.SUCCESS: 'success'>
    """

    def __init__(
        self,
        *,
        endpoint_registry: EndpointRegistry | None = None,
        router: Router | None = None,
        validator: RequestValidator | None = None,
        rate_limiter: RateLimiter | None = None,
        authentication_service: AuthenticationService | None = None,
        authorization_service: AuthorizationService | None = None,
        default_rate_limit_policy=DEFAULT_RATE_LIMIT_POLICY,
    ) -> None:
        """Create an API Gateway.

        Args:
            endpoint_registry: The endpoint catalogue to validate/route
                against. Defaults to the shared
                :data:`~integration.registry.endpoint_registry`.
            router: The router to dispatch validated requests through.
                Defaults to a :class:`~integration.router.Router` bound
                to ``endpoint_registry`` (or the shared
                :data:`~integration.router.router` if
                ``endpoint_registry`` was also omitted).
            validator: The validator to check requests with. Defaults
                to the shared
                :data:`~integration.validation.request_validator`.
            rate_limiter: The rate limiter to enforce ceilings with.
                Defaults to the shared
                :data:`~integration.rate_limiter.rate_limiter`.
            authentication_service: Used to resolve the caller's
                identity. Defaults to the shared
                :data:`~identity.service.authentication_service`.
            authorization_service: Used to resolve the caller's
                permissions. Defaults to the shared
                :data:`~authorization.service.authorization_service`.
            default_rate_limit_policy: The policy applied to any
                endpoint that doesn't specify its own.
        """
        if endpoint_registry is not None:
            self._endpoint_registry = endpoint_registry
            self._router = router if router is not None else Router(endpoint_registry)
        else:
            self._endpoint_registry = default_endpoint_registry
            self._router = router if router is not None else Router(default_endpoint_registry)

        self._validator = validator if validator is not None else default_request_validator
        self._rate_limiter = rate_limiter if rate_limiter is not None else default_rate_limiter
        self._authentication_service = (
            authentication_service if authentication_service is not None else default_authentication_service
        )
        self._authorization_service = (
            authorization_service if authorization_service is not None else default_authorization_service
        )
        self._default_rate_limit_policy = default_rate_limit_policy

    def handle_request(
        self,
        request: IntegrationRequest,
        *,
        session_id: str | None = None,
        user_context: UserContext | None = None,
        tenant_context: TenantContext | None = None,
    ) -> IntegrationResponse:
        """Run ``request`` through the full lifecycle and return a standardized response.

        This method never raises. Every failure mode (validation,
        authentication, authorization, rate limiting, or the handler
        itself) is caught here and translated into an
        :class:`~integration.models.IntegrationResponse` with an
        appropriate :class:`~integration.models.ResponseStatus`.

        Args:
            request: The inbound request, typically built via
                :func:`build_request` by an
                :class:`~integration.provider.IntegrationProvider`.
            session_id: The caller's identity-session id (Sprint 6.6),
                used to authenticate via
                :data:`~identity.service.authentication_service` when
                ``user_context`` isn't already supplied.
            user_context: An already-resolved
                :class:`~authorization.context.UserContext`, if the
                caller has one in hand (avoids re-resolving the user --
                mirrors every other service in this platform that
                accepts an optional, already-resolved context).
            tenant_context: An already-resolved
                :class:`~tenancy.context.TenantContext`. If omitted,
                resolved from ``request.tenant_id`` via the shared
                tenant registry when possible.

        Returns:
            A fully-populated :class:`~integration.models.IntegrationResponse`.
        """
        start = time.perf_counter()
        monitoring_service.record_completed(
            service_name=_SERVICE_NAME,
            operation="receive_request",
            tenant_context=tenant_context,
            message=f"Request received for endpoint '{request.endpoint}' ({request.method.value}, {request.api_version})",
            metadata={"request_id": request.request_id, "endpoint": request.endpoint, "api_version": request.api_version},
        )

        resolved_tenant_context = self._resolve_tenant_context(request, tenant_context)

        # -- 1. Validate (Task 5: before routing, before auth) --------
        try:
            endpoint_def = self._validator.validate(request, self._endpoint_registry)
        except InvalidRequestError as exc:
            return self._fail(
                request, ResponseStatus.VALIDATION_ERROR, "Request validation failed.", exc.reasons,
                operation="validate_request", tenant_context=resolved_tenant_context, start=start,
            )

        # -- 2. Authenticate -------------------------------------------
        try:
            resolved_user_context, resolved_request = self._authenticate(
                request, session_id=session_id, user_context=user_context, tenant_context=resolved_tenant_context
            )
        except AuthenticationError as exc:
            return self._fail(
                request, ResponseStatus.UNAUTHORIZED, "Authentication failed.", (str(exc),),
                operation="authenticate", tenant_context=resolved_tenant_context, start=start,
            )

        # -- 3. Authorize ------------------------------------------------
        if endpoint_def.required_permission is not None:
            try:
                self._authorization_service.require_permission(
                    resolved_user_context, endpoint_def.required_permission,
                    service_name=_SERVICE_NAME, operation=f"route:{endpoint_def.endpoint_key}",
                    tenant_context=resolved_tenant_context,
                )
            except AuthorizationError as exc:
                return self._fail(
                    request, ResponseStatus.FORBIDDEN, "Access denied.", (str(exc),),
                    operation="authorize", tenant_context=resolved_tenant_context, start=start,
                )

        # -- 4. Rate limit (Task 6) --------------------------------------
        policy = endpoint_def.rate_limit_policy or self._default_rate_limit_policy
        rate_status = self._rate_limiter.evaluate(resolved_request, policy)
        if not rate_status.allowed:
            monitoring_service.record_failure(
                service_name=_SERVICE_NAME, operation="rate_limit",
                error=f"Rate limit exceeded for '{rate_status.limit_key}'",
                tenant_context=resolved_tenant_context,
                metadata={"request_id": request.request_id, "limit_key": rate_status.limit_key},
            )
            return self._fail(
                request, ResponseStatus.RATE_LIMITED,
                f"Rate limit exceeded. Try again in {rate_status.retry_after_seconds:.0f} second(s).",
                (), operation="rate_limit", tenant_context=resolved_tenant_context, start=start, record_failure=False,
            )

        # -- 5. Route ------------------------------------------------------
        try:
            data = self._router.route(resolved_request)
        except EndpointNotFoundError as exc:
            # By construction this should never happen (validation already
            # confirmed the endpoint exists) -- treated as a genuine
            # platform error rather than caller error if it ever does.
            return self._fail(
                request, ResponseStatus.NOT_FOUND, "Endpoint could not be resolved.", (str(exc),),
                operation="route_request", tenant_context=resolved_tenant_context, start=start,
            )
        except IntegrationError as exc:
            return self._fail(
                request, ResponseStatus.ERROR, "The request could not be completed.", (str(exc),),
                operation="route_request", tenant_context=resolved_tenant_context, start=start,
            )
        except Exception as exc:  # noqa: BLE001 - a handler failure must never crash the Gateway
            logger.warning("Endpoint handler for '%s' failed: %s", request.endpoint, exc)
            return self._fail(
                request, ResponseStatus.ERROR, "The request could not be completed.", (str(exc),),
                operation="route_request", tenant_context=resolved_tenant_context, start=start,
            )

        # -- 6. Respond ------------------------------------------------------
        duration_ms = (time.perf_counter() - start) * 1000.0
        monitoring_service.record_completed(
            service_name=_SERVICE_NAME, operation="route_request",
            duration_ms=duration_ms, tenant_context=resolved_tenant_context,
            message=f"Routed '{request.endpoint}' successfully.",
            metadata={"request_id": request.request_id, "endpoint": request.endpoint, "api_version": request.api_version},
        )
        return IntegrationResponse(
            request_id=request.request_id,
            status=ResponseStatus.SUCCESS,
            message="Request completed successfully.",
            created_at=datetime.now(timezone.utc),
            data=data,
            processing_time_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _authenticate(
        self,
        request: IntegrationRequest,
        *,
        session_id: str | None,
        user_context: UserContext | None,
        tenant_context: TenantContext | None,
    ) -> tuple[UserContext, IntegrationRequest]:
        """Resolve the caller's identity and permissions, returning an updated request.

        Args:
            request: The inbound request.
            session_id: The caller's identity-session id, if given.
            user_context: An already-resolved context, if given.
            tenant_context: The resolved tenant context, if any.

        Returns:
            A ``(user_context, request)`` tuple, where ``request`` has
            ``user_id``/``tenant_id`` filled in from the resolved
            identity if they weren't already present.

        Raises:
            AuthenticationError: If no valid identity could be resolved.
        """
        from dataclasses import replace

        if user_context is None:
            identity = self._authentication_service.get_current_user(session_id)
            user_context = self._authorization_service.build_context(identity.user_id, tenant_context=tenant_context)
            user_id = identity.user_id
        else:
            user_id = user_context.user.user_id if user_context.user is not None else None

        if request.user_id is None and user_id is not None:
            request = replace(request, user_id=user_id)
        if request.tenant_id is None and tenant_context is not None and tenant_context.tenant is not None:
            request = replace(request, tenant_id=tenant_context.tenant.tenant_id, tenant_name=tenant_context.tenant.display_name)

        return user_context, request

    def _resolve_tenant_context(
        self, request: IntegrationRequest, tenant_context: TenantContext | None
    ) -> TenantContext | None:
        """Resolve a :class:`~tenancy.context.TenantContext` for this request, if possible.

        Args:
            request: The inbound request.
            tenant_context: An already-resolved context, if given.

        Returns:
            ``tenant_context`` unchanged if given; otherwise a context
            built from ``request.tenant_id`` via the shared tenant
            registry, or ``None`` if neither is available/resolvable.
        """
        if tenant_context is not None:
            return tenant_context
        if not request.tenant_id:
            return None
        tenant = tenant_registry.get(request.tenant_id)
        return TenantContext(tenant=tenant) if tenant is not None else None

    def _fail(
        self,
        request: IntegrationRequest,
        status: ResponseStatus,
        message: str,
        errors: tuple[str, ...],
        *,
        operation: str,
        tenant_context: TenantContext | None,
        start: float,
        record_failure: bool = True,
    ) -> IntegrationResponse:
        """Build a standardized failure response and record it to monitoring (Task 9).

        Args:
            request: The originating request.
            status: The failure status to report.
            message: A short, business-friendly summary.
            errors: Zero or more detailed error strings.
            operation: The lifecycle step that failed, for monitoring.
            tenant_context: The resolved tenant context, if any.
            start: The ``time.perf_counter()`` value captured at the
                start of :meth:`handle_request`, used to compute
                ``processing_time_ms``.
            record_failure: Whether to also record a monitoring
                failure event here. ``False`` for callers (like the
                rate-limit path) that already recorded their own,
                more specific failure event.

        Returns:
            The standardized failure :class:`~integration.models.IntegrationResponse`.
        """
        duration_ms = (time.perf_counter() - start) * 1000.0
        if record_failure:
            monitoring_service.record_failure(
                service_name=_SERVICE_NAME, operation=operation,
                error="; ".join(errors) if errors else message,
                duration_ms=duration_ms, tenant_context=tenant_context,
                metadata={"request_id": request.request_id, "endpoint": request.endpoint},
            )
        return IntegrationResponse(
            request_id=request.request_id,
            status=status,
            message=message,
            created_at=datetime.now(timezone.utc),
            errors=errors,
            processing_time_ms=duration_ms,
        )


# A shared, ready-to-use instance -- mirrors
# ``automation.service.automation_service`` and
# ``notification.service.notification_service``. Every
# ``IntegrationProvider`` forwards into this instance rather than
# constructing its own ``APIGateway``, so every request is resolved
# against the same endpoint catalogue, rate limiter, and services.
api_gateway = APIGateway()
