"""Tenant configuration for the NovaMart Multi-Tenant platform.

Sprint 6.3 -- Multi-Tenant Business Intelligence Platform, Task 6.

This is the *only* place a tenant is declared. Onboarding a new tenant
-- or deactivating an existing one -- means adding or editing one
:class:`~tenancy.models.Tenant` entry in :data:`TENANT_DEFINITIONS`
below. No other file in the codebase branches on a tenant id (no
``if tenant == "acme-retail":`` anywhere), so this file is the single
configuration surface the "Adding a new tenant should require
configuration only" requirement refers to.

In a future iteration, :data:`TENANT_DEFINITIONS` could just as easily
be loaded from a database, a JSON/YAML file, or an admin API instead
of a Python literal -- nothing outside this module needs to change
either way, since every consumer only ever calls
``tenancy.registry.tenant_registry.get(...)`` /
``.active_tenants()``, never reads this list directly.
"""

from __future__ import annotations

from tenancy.models import Tenant, TenantStatus
from tenancy.registry import tenant_registry

# --------------------------------------------------------------------------
# Tenant declarations -- add/edit an entry here to onboard, rename, or
# deactivate a tenant. Never add conditional logic elsewhere.
# --------------------------------------------------------------------------
TENANT_DEFINITIONS: tuple[Tenant, ...] = (
    Tenant(
        tenant_id="novamart-hq",
        name="novamart-hq",
        display_name="NovaMart Headquarters",
        status=TenantStatus.ACTIVE,
        metadata={"plan": "enterprise", "region": "global"},
    ),
    Tenant(
        tenant_id="acme-retail",
        name="acme-retail",
        display_name="Acme Retail Group",
        status=TenantStatus.ACTIVE,
        metadata={"plan": "standard", "region": "na"},
    ),
    Tenant(
        tenant_id="globex-demo",
        name="globex-demo",
        display_name="Globex Demo Account",
        status=TenantStatus.INACTIVE,
        metadata={"plan": "trial", "region": "emea"},
    ),
)


def register_default_tenants() -> None:
    """Register every tenant declared in :data:`TENANT_DEFINITIONS`.

    Called once, below, at import time -- mirroring how every
    ``services/*.py`` module builds and exposes a ready-to-use shared
    instance (``sales_kpi_engine``, ``sales_export_service``, ...) as
    soon as it is imported. Any module that needs the tenant registry
    populated should ``import config.tenants`` (even if only for its
    side effect) before resolving a tenant.
    """
    tenant_registry.register_many(TENANT_DEFINITIONS)


register_default_tenants()
