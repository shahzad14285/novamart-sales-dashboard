"""Integration Provider abstraction for the NovaMart Integration Platform & API Gateway.

Sprint 6.8 -- Integration Platform & API Gateway, Task 7.

An **integration provider** is a thin channel adapter that sits in
*front* of :class:`~integration.gateway.APIGateway`, translating one
external channel's native call shape into an
:class:`~integration.models.IntegrationRequest` and handing it to the
Gateway -- the reverse dependency direction from
:class:`notification.provider.NotificationProvider` (which the
*service* calls out to). This is what Task 7's "The API Gateway must
remain provider-independent" means concretely:
:class:`~integration.gateway.APIGateway` never imports this module,
never knows a provider exists, and never changes when a new channel is
added. A provider satisfying :class:`IntegrationProvider` is free to
call :meth:`~integration.gateway.APIGateway.handle_request` however it
likes -- synchronously in-process (this sprint's
:class:`InMemoryIntegrationProvider`), from a future REST framework's
view function, from a future webhook receiver, or from a future
ERP/CRM/BI connector's polling loop.

This sprint ships :class:`InMemoryIntegrationProvider`, which
*simulates* an external channel calling in -- it never opens a network
socket ("Do NOT implement a production HTTP server. The objective is
architecture."), it just forwards an already-built
:class:`~integration.models.IntegrationRequest` straight to the
Gateway and returns its :class:`~integration.models.IntegrationResponse`
unchanged. Future providers -- a REST adapter (Flask/FastAPI view
functions that parse a real HTTP request into an
:class:`~integration.models.IntegrationRequest`), a webhook receiver, an
ERP connector, a CRM connector, a Microsoft Power BI connector, a
Salesforce connector, a SAP connector, or a Microsoft Dynamics
connector -- are added by writing one new class that satisfies
:class:`IntegrationProvider` and registering it under the appropriate
channel key via
:meth:`~integration.registry.IntegrationProviderRegistry.register`.
Nothing in :class:`~integration.gateway.APIGateway` needs to change.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from integration.models import IntegrationRequest, IntegrationResponse

if TYPE_CHECKING:
    from integration.gateway import APIGateway


@runtime_checkable
class IntegrationProvider(Protocol):
    """Interface every external channel adapter must satisfy.

    A structural ``Protocol``, so a class satisfies this interface
    simply by having a compatible ``name`` property and ``submit``
    method -- no inheritance required, exactly like
    :class:`~notification.provider.NotificationProvider` and
    :class:`~identity.provider.AuthenticationProvider`.
    """

    @property
    def name(self) -> str:
        """A short, human-readable name for this provider (for traceability)."""
        ...

    def submit(self, gateway: "APIGateway", request: IntegrationRequest) -> IntegrationResponse:
        """Hand ``request`` to ``gateway`` and return its response.

        Args:
            gateway: The API Gateway this provider forwards requests
                into. Passed in explicitly (rather than the provider
                holding a reference to a shared singleton) so the exact
                same provider implementation works unmodified against
                any :class:`~integration.gateway.APIGateway` instance
                -- the application's real gateway, or a fresh one a
                test constructs.
            request: The already-translated request to submit.

        Returns:
            Whatever :meth:`~integration.gateway.APIGateway.handle_request`
            returns -- this method never needs its own error handling,
            since the Gateway itself never raises (see
            ``docs/INTEGRATION_ARCHITECTURE.md``).
        """
        ...


class InMemoryIntegrationProvider:
    """Default integration provider: forwards a request straight into the Gateway, in-process.

    Simulates the simplest possible external channel -- a caller that
    already has a well-formed
    :class:`~integration.models.IntegrationRequest` and hands it
    directly to the Gateway, with no real network hop. Sufficient for a
    single-process Streamlit deployment, for tests, and for this
    sprint's architectural objective (Task 7: "Implement an in-memory
    provider").

    Keeps a thread-safe log of every request it has forwarded, mirroring
    :class:`~notification.provider.InMemoryNotificationProvider`'s
    ``sent_messages()`` -- useful for tests and for the Integration
    Dashboard's "Integration provider status" section.

    A single instance of this provider is registered under every
    :class:`~integration.models.IntegrationChannel` this sprint ships
    with (see ``integration/registry.py``), so every channel "works"
    today via simulation, while each channel remains independently
    swappable later -- registering a real
    ``SalesforceConnectorProvider`` under just the ``"salesforce"`` key
    later requires zero change to this class or to
    :class:`~integration.gateway.APIGateway`.

    Example:
        >>> provider = InMemoryIntegrationProvider()
        >>> response = provider.submit(gateway, request)
        >>> response.status
        <ResponseStatus.SUCCESS: 'success'>
    """

    name = "In-Memory Simulated Provider"

    def __init__(self) -> None:
        """Create a provider with an empty forwarding log."""
        self._forwarded: list[tuple[IntegrationRequest, IntegrationResponse]] = []
        self._lock = threading.Lock()

    def submit(self, gateway: "APIGateway", request: IntegrationRequest) -> IntegrationResponse:
        """Forward ``request`` straight to ``gateway.handle_request`` and record the exchange.

        Args:
            gateway: The API Gateway to forward the request into.
            request: The request to forward.

        Returns:
            The Gateway's :class:`~integration.models.IntegrationResponse`,
            unchanged.
        """
        response = gateway.handle_request(request)
        with self._lock:
            self._forwarded.append((request, response))
        return response

    def forwarded_requests(self) -> tuple[tuple[IntegrationRequest, IntegrationResponse], ...]:
        """Return every ``(request, response)`` pair this provider has forwarded, newest first.

        Mainly useful for tests and for an admin screen that wants to
        inspect provider-level traffic without going through the
        Gateway's own monitoring-backed history.
        """
        with self._lock:
            return tuple(reversed(self._forwarded))

    def clear(self) -> None:
        """Remove every recorded forwarding.

        Primarily useful for tests that need a clean provider rather
        than one accumulating requests across an entire test run.
        """
        with self._lock:
            self._forwarded.clear()
