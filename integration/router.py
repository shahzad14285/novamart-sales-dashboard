"""Request Routing for the NovaMart Integration Platform & API Gateway.

Sprint 6.8 -- Integration Platform & API Gateway, Task 2/3 support.

:class:`Router` is the thin dispatch layer between
:class:`~integration.gateway.APIGateway` and a resolved endpoint's
handler callable. It owns exactly one responsibility -- "given an
already-validated request, find and call the right handler" -- and
deliberately does nothing else: no authentication, no authorization, no
rate limiting, no monitoring (those are the Gateway's job, run before
and around routing). Kept as its own class (rather than folded into
:class:`~integration.gateway.APIGateway`) so routing concerns and
gateway-orchestration concerns stay independently testable, mirroring
how :class:`~automation.scheduler.Scheduler` stays separate from
:class:`~automation.service.AutomationService` even though the service
calls it.
"""

from __future__ import annotations

from integration.exceptions import EndpointNotFoundError
from integration.models import IntegrationRequest
from integration.registry import EndpointRegistry, endpoint_registry


class Router:
    """Resolves a validated request to its endpoint and invokes the registered handler.

    Example:
        >>> router = Router(endpoint_registry)
        >>> result = router.route(request)
    """

    def __init__(self, registry: EndpointRegistry) -> None:
        """Create a Router bound to a specific :class:`~integration.registry.EndpointRegistry`.

        Args:
            registry: The endpoint registry to resolve handlers
                against. Injected (Dependency Injection) rather than
                imported as a module-level singleton, so a test can
                route against an isolated registry.
        """
        self._registry = registry

    def route(self, request: IntegrationRequest) -> object:
        """Resolve ``request`` to a handler and invoke it, returning the handler's raw result.

        Args:
            request: An already-validated, already-authenticated,
                already-authorized, already-rate-limit-checked request
                (Task 5: "Validation should occur before routing" --
                and, by construction in
                :meth:`~integration.gateway.APIGateway.handle_request`,
                every other Gateway responsibility happens before
                routing too).

        Returns:
            Whatever the endpoint's handler returns -- opaque to the
            Router, which never inspects it. The Gateway wraps this in
            a standardized :class:`~integration.models.IntegrationResponse`.

        Raises:
            EndpointNotFoundError: If no endpoint matches. In normal
                operation this should never happen (the Gateway already
                validated endpoint existence before calling this), but
                it is not swallowed here -- an unexpected mismatch
                between validation and routing is a genuine bug the
                Gateway's own error handling (Task 2) should surface,
                not hide.
        """
        _definition, handler = self._registry.resolve(request.endpoint, request.method, request.api_version)
        return handler(request)


# A shared, ready-to-use instance bound to the shared endpoint registry
# -- mirrors ``automation.scheduler.scheduler``. Application code (the
# default-constructed ``APIGateway``) uses this; tests inject their own
# ``Router`` over an isolated registry instead.
router = Router(endpoint_registry)
