"""Request Validation for the NovaMart Integration Platform & API Gateway.

Sprint 6.8 -- Integration Platform & API Gateway, Task 5.

The single place an :class:`~integration.models.IntegrationRequest` is
checked for correctness before :class:`~integration.gateway.APIGateway`
does anything else with it -- mirrors ``tenancy.context.validate_tenant_context``
and ``authorization.service.AuthorizationService.require_permission``'s
shape exactly: one validation choke point, never duplicated per
endpoint handler (coding standard: "Avoid ... Duplicate validation
logic").

Validation happens strictly *before* routing (Task 5: "Validation
should occur before routing") -- :class:`~integration.gateway.APIGateway`
calls :class:`RequestValidator` before it ever asks
:class:`~integration.router.Router` to resolve a handler, so a
malformed request never reaches business logic at all.
"""

from __future__ import annotations

from integration.exceptions import InvalidRequestError
from integration.models import EndpointDefinition, IntegrationRequest
from integration.registry import EndpointRegistry


class RequestValidator:
    """Validates an :class:`~integration.models.IntegrationRequest` against the Endpoint Registry.

    Example:
        >>> validator = RequestValidator()
        >>> validator.validate(request, registry)  # raises InvalidRequestError, or returns the resolved EndpointDefinition
    """

    def validate(self, request: IntegrationRequest, registry: EndpointRegistry) -> EndpointDefinition:
        """Run every validation check for ``request``, in order, and return its resolved endpoint.

        Args:
            request: The inbound request to validate.
            registry: The endpoint registry to validate endpoint
                existence against (Task 3/5 integration point --
                injected rather than imported as a shared singleton, so
                a test can validate against an isolated registry).

        Returns:
            The matching :class:`~integration.models.EndpointDefinition`,
            so :class:`~integration.gateway.APIGateway` doesn't have to
            resolve it a second time for routing.

        Raises:
            InvalidRequestError: If any check fails. Every failure
                reason found is collected into one exception rather
                than raising on the first (Task 5: "Produce
                business-friendly validation errors" -- a caller fixing
                one field at a time against a one-error-per-round-trip
                API is a worse experience than seeing every problem at
                once).
        """
        endpoint_def = self._validate_endpoint_exists(request, registry)

        reasons: list[str] = []
        reasons.extend(self._validate_request_format(request))
        if endpoint_def is not None:
            reasons.extend(self._validate_required_fields(request, endpoint_def))

        if endpoint_def is None:
            reasons.insert(
                0,
                f"No endpoint '{request.endpoint}' is registered for method {request.method.value} "
                f"under API version '{request.api_version}'.",
            )

        if reasons:
            raise InvalidRequestError(tuple(reasons))

        return endpoint_def

    def _validate_endpoint_exists(
        self, request: IntegrationRequest, registry: EndpointRegistry
    ) -> EndpointDefinition | None:
        """Resolve ``request`` against ``registry``, returning ``None`` (not raising) if unresolved.

        Kept as a non-raising lookup so :meth:`validate` can collect an
        "unknown endpoint" failure alongside any format/field failures
        in the same pass, rather than stopping at the first problem.

        Args:
            request: The inbound request.
            registry: The endpoint registry to resolve against.

        Returns:
            The matching :class:`~integration.models.EndpointDefinition`,
            or ``None`` if no registered endpoint matches.
        """
        return registry.find(request.endpoint, request.method, request.api_version)

    def _validate_request_format(self, request: IntegrationRequest) -> tuple[str, ...]:
        """Check structural request fields that don't depend on which endpoint matched.

        Args:
            request: The inbound request.

        Returns:
            A tuple of business-friendly failure descriptions (empty if
            the request format is valid).
        """
        reasons: list[str] = []
        if not request.endpoint or not request.endpoint.strip():
            reasons.append("The 'endpoint' field is required.")
        if not request.api_version or not request.api_version.strip():
            reasons.append("The 'api_version' field is required.")
        if not isinstance(request.payload, dict) and request.payload is not None:
            reasons.append("The 'payload' field must be an object (a mapping of field names to values).")
        return tuple(reasons)

    def _validate_required_fields(
        self, request: IntegrationRequest, endpoint_def: EndpointDefinition
    ) -> tuple[str, ...]:
        """Check that every field ``endpoint_def.required_fields`` names is present in the payload.

        Args:
            request: The inbound request.
            endpoint_def: The resolved endpoint's definition.

        Returns:
            A tuple of business-friendly failure descriptions, one per
            missing field (empty if every required field is present).
        """
        payload = request.payload or {}
        missing = [field_name for field_name in endpoint_def.required_fields if field_name not in payload]
        return tuple(f"The '{field_name}' field is required." for field_name in missing)


#: A shared, ready-to-use validator -- mirrors the stateless-helper
#: pattern of a shared, application-wide instance used elsewhere in this
#: platform. Holds no state of its own, so sharing it is always safe.
request_validator = RequestValidator()
