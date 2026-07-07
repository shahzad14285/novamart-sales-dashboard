"""Multi-tenant foundation for the NovaMart Sales Intelligence Dashboard.

This package is the platform's new, centralized tenancy layer, sitting
below every existing layer (``utils/``, ``services/``, ``components/``,
``ui/``, ``pages/``) so any of them can depend on it without creating a
circular import. It has no Streamlit, pandas, or business-logic
dependency of its own -- it only knows about tenants, not sales data --
so it can be imported from the pure calculation layer (``utils/``) just
as safely as from a UI page.

Public surface:
    - :class:`~tenancy.models.Tenant` / :class:`~tenancy.models.TenantStatus`
      -- the reusable tenant model (Task 1).
    - :class:`~tenancy.context.TenantContext` and
      :func:`~tenancy.context.validate_tenant_context` -- the
      centralized tenant context and the single validation/logging
      choke point every tenant-aware service calls (Tasks 2, 4, 5).
    - :class:`~tenancy.registry.TenantRegistry` /
      ``tenancy.registry.tenant_registry`` -- the configuration-driven
      tenant registry (Task 6); see ``config/tenants.py`` for where
      tenants are actually declared.
    - :mod:`tenancy.exceptions` -- business-friendly, non-technical
      error messages raised on validation failure (Task 4).

Adding tenant awareness to a new, future service means importing
:class:`~tenancy.context.TenantContext` and calling
:func:`~tenancy.context.validate_tenant_context` once at the top of its
entry point -- nothing here needs to change to support it. See
``docs/MULTI_TENANT_ARCHITECTURE.md`` for the full developer guide.
"""

from __future__ import annotations

from tenancy.context import TenantContext, validate_tenant_context
from tenancy.exceptions import (
    InactiveTenantError,
    MissingTenantContextError,
    TenantContextError,
    TenantNotFoundError,
)
from tenancy.models import Tenant, TenantStatus
from tenancy.registry import TenantRegistry, tenant_registry

__all__ = [
    "Tenant",
    "TenantStatus",
    "TenantContext",
    "validate_tenant_context",
    "TenantContextError",
    "MissingTenantContextError",
    "TenantNotFoundError",
    "InactiveTenantError",
    "TenantRegistry",
    "tenant_registry",
]
