"""Centralized Tenant Context for the NovaMart Multi-Tenant platform.

Sprint 6.3 -- Multi-Tenant Business Intelligence Platform, Tasks 2, 4, 5.

:class:`TenantContext` is the single source of truth for "which tenant
is this unit of work scoped to". It carries at most one
:class:`~tenancy.models.Tenant` and knows how to validate itself; it
does not know about Streamlit, sessions, or any particular service.

:func:`validate_tenant_context` is the one choke point every
tenant-aware service (Upload Center, Data Loader, KPI Engine, Business
Insights, Reporting Service, AI Recommendation Service, PDF Generator,
Export Service, Executive Report Center) calls before doing any real
work. Centralizing it here means:

- Task 4 (validation) is implemented exactly once, not duplicated nine
  times across nine different services.
- Task 5 (logging) happens automatically as a side effect of
  validation, so every service call is traceable the same way, with no
  service needing its own logging code.
- A future tenant-aware service only needs to call this one function,
  never re-implement the validation rules.

Why this is a plain class, not a global singleton
----------------------------------------------------
A single module-level ``TenantContext`` instance shared by the whole
process would leak across *concurrent* users: a Streamlit server
process serves multiple browser sessions from the same Python process,
so a plain global would let one tenant's active-tenant selection bleed
into another tenant's request the moment two sessions overlap -- the
exact failure this sprint exists to prevent. Instead, ``TenantContext``
is designed to be instantiated per unit of work (per Streamlit session,
in this app -- see ``components/tenant_selector.py``, which stores the
selected tenant id in ``st.session_state`` rather than a module
global) and passed explicitly into each service call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from tenancy.exceptions import InactiveTenantError, MissingTenantContextError, TenantContextError
from tenancy.models import Tenant

logger = logging.getLogger("novamart.tenancy")


class TenantContext:
    """Holds the tenant a unit of work (a service call, a page render) is scoped to.

    Immutable by convention (nothing here mutates ``_tenant`` after
    construction) -- to change tenants, construct a new
    :class:`TenantContext` rather than reassigning an existing one, so
    a reference held by one part of the app can never unexpectedly
    start pointing at a different tenant.

    Example:
        >>> context = TenantContext(tenant=my_tenant)
        >>> context.has_tenant()
        True
        >>> context.require_active_tenant().tenant_id
        'acme-retail'

        >>> empty = TenantContext.empty()
        >>> empty.has_tenant()
        False
    """

    def __init__(self, tenant: Tenant | None = None) -> None:
        """Create a tenant context, optionally already bound to a tenant.

        Args:
            tenant: The active tenant for this context, or ``None`` for
                an empty context (e.g. before a user has selected a
                tenant, or in an unauthenticated request).
        """
        self._tenant = tenant

    @property
    def tenant(self) -> Tenant | None:
        """The bound tenant, or ``None`` if this context is empty."""
        return self._tenant

    def has_tenant(self) -> bool:
        """Return ``True`` if a tenant is bound to this context (active or not)."""
        return self._tenant is not None

    def require_active_tenant(self) -> Tenant:
        """Validate this context and return its tenant.

        Returns:
            The bound, active :class:`~tenancy.models.Tenant`.

        Raises:
            MissingTenantContextError: If no tenant is bound at all.
            InactiveTenantError: If the bound tenant exists but is not active.
        """
        if self._tenant is None:
            raise MissingTenantContextError()
        if not self._tenant.is_active:
            raise InactiveTenantError(self._tenant.tenant_id)
        return self._tenant

    @classmethod
    def for_tenant(cls, tenant: Tenant) -> "TenantContext":
        """Build a context already bound to ``tenant``."""
        return cls(tenant=tenant)

    @classmethod
    def empty(cls) -> "TenantContext":
        """Build a context bound to no tenant (validation will always fail)."""
        return cls(tenant=None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        tenant_id = self._tenant.tenant_id if self._tenant else None
        return f"TenantContext(tenant_id={tenant_id!r})"


def validate_tenant_context(
    tenant_context: "TenantContext | None",
    *,
    service_name: str,
    operation: str,
) -> Tenant:
    """Validate a tenant context before a service processes a request.

    This is the single validation-and-logging choke point every
    tenant-aware service calls first, before running any business
    logic (Task 4). It always logs a structured line containing the
    tenant id (or ``"-"`` if none was available), the service name, the
    operation, the timestamp, and the outcome (Task 5) -- regardless of
    whether validation succeeds or fails.

    Args:
        tenant_context: The context supplied by the caller. ``None``
            means the caller didn't supply one at all (e.g. an older
            call site that hasn't been updated, or a request that
            never resolved an active tenant).
        service_name: The name of the calling service, for logging
            (e.g. ``"ReportingService"``).
        operation: The name of the operation being performed, for
            logging (e.g. ``"generate_report"``).

    Returns:
        The validated, active :class:`~tenancy.models.Tenant`.

    Raises:
        MissingTenantContextError: If ``tenant_context`` is ``None`` or
            is bound to no tenant.
        InactiveTenantError: If the bound tenant is not active.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    if tenant_context is None:
        _log(tenant_id="-", service_name=service_name, operation=operation, timestamp=timestamp, outcome="REJECTED")
        raise MissingTenantContextError()

    try:
        tenant = tenant_context.require_active_tenant()
    except TenantContextError:
        tenant_id = tenant_context.tenant.tenant_id if tenant_context.tenant else "-"
        _log(tenant_id=tenant_id, service_name=service_name, operation=operation, timestamp=timestamp, outcome="REJECTED")
        raise

    _log(tenant_id=tenant.tenant_id, service_name=service_name, operation=operation, timestamp=timestamp, outcome="OK")
    return tenant


def _log(*, tenant_id: str, service_name: str, operation: str, timestamp: str, outcome: str) -> None:
    """Write one structured log line for a tenant-validation attempt.

    Kept as a single private helper so every log line emitted anywhere
    in the platform has an identical shape -- tenant id, service name,
    operation, timestamp, outcome -- which is what makes these lines
    useful for both day-to-day debugging and a future audit trail
    (Task 5), regardless of which of the nine tenant-aware services
    produced them.

    Args:
        tenant_id: The tenant id involved, or ``"-"`` if none.
        service_name: The service performing the operation.
        operation: The operation being performed.
        timestamp: An ISO-8601 UTC timestamp.
        outcome: ``"OK"`` or ``"REJECTED"``.
    """
    message = (
        f"tenant_id={tenant_id} service={service_name} operation={operation} "
        f"timestamp={timestamp} outcome={outcome}"
    )
    if outcome == "OK":
        logger.info(message)
    else:
        logger.warning(message)
