"""Tenant Registry -- configuration-driven tenant registration.

Sprint 6.3 -- Multi-Tenant Business Intelligence Platform, Task 6.

Mirrors the registry pattern already used throughout this codebase --
:meth:`~utils.kpi_engine.KPIEngine.register`,
:meth:`~services.export_service.ExportService.register`,
:meth:`~services.reporting_service.ReportingService.register_section_builder` /
:meth:`~services.reporting_service.ReportingService.define_report`, and
:meth:`~services.pdf_generator_service.PDFGeneratorService.register_content_renderer`
-- so onboarding a new tenant is the same kind of operation as adding a
new KPI, export format, report section, or PDF content renderer: one
``register()`` call with a plain data object, never a hardcoded
``if tenant == "..."`` branch anywhere in the codebase.

The registry itself holds no tenant-specific logic -- it is a generic
lookup table. *Which* tenants exist is declared separately, in
``config/tenants.py``, keeping "the mechanism" (this file) and "the
configuration" (``config/tenants.py``) cleanly separated, per this
project's Separation of Concerns principle.
"""

from __future__ import annotations

from typing import Iterable

from tenancy.exceptions import TenantNotFoundError
from tenancy.models import Tenant


class TenantRegistry:
    """A configuration-driven registry of every tenant known to the platform.

    Example:
        >>> registry = TenantRegistry()
        >>> registry.register(Tenant(tenant_id="acme-retail", name="acme-retail", display_name="Acme Retail Group"))
        >>> registry.get("acme-retail").display_name
        'Acme Retail Group'

        # Onboarding a new tenant later is a registration call, never a
        # code change to any service:
        >>> registry.register(Tenant(tenant_id="globex", name="globex", display_name="Globex Corporation"))
    """

    def __init__(self) -> None:
        """Create an empty tenant registry."""
        self._tenants: dict[str, Tenant] = {}

    def register(self, tenant: Tenant) -> None:
        """Register (or replace) a tenant under its ``tenant_id``.

        Calling this again with an already-registered ``tenant_id``
        replaces that tenant's record -- useful for updating a
        tenant's status (e.g. deactivating one) without restarting
        the registry.

        Args:
            tenant: The tenant to register.
        """
        self._tenants[tenant.tenant_id] = tenant

    def register_many(self, tenants: Iterable[Tenant]) -> None:
        """Register every tenant in ``tenants``.

        Args:
            tenants: An iterable of tenants to register, typically the
                declarative list from ``config/tenants.py``.
        """
        for tenant in tenants:
            self.register(tenant)

    def get(self, tenant_id: str) -> Tenant | None:
        """Look up a tenant by id.

        Args:
            tenant_id: The tenant id to look up.

        Returns:
            The matching :class:`~tenancy.models.Tenant`, or ``None``
            if no tenant is registered under that id.
        """
        return self._tenants.get(tenant_id)

    def get_or_raise(self, tenant_id: str) -> Tenant:
        """Look up a tenant by id, raising a business-friendly error if unknown.

        Args:
            tenant_id: The tenant id to look up.

        Returns:
            The matching :class:`~tenancy.models.Tenant`.

        Raises:
            TenantNotFoundError: If no tenant is registered under
                ``tenant_id``.
        """
        tenant = self.get(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(tenant_id)
        return tenant

    def all_tenants(self) -> tuple[Tenant, ...]:
        """Return every registered tenant, active or not."""
        return tuple(self._tenants.values())

    def active_tenants(self) -> tuple[Tenant, ...]:
        """Return only the tenants currently marked active.

        The natural source for a tenant-selector UI, so an inactive
        tenant is never even offered as a choice.
        """
        return tuple(tenant for tenant in self._tenants.values() if tenant.is_active)

    def clear(self) -> None:
        """Remove every registered tenant.

        Primarily useful for tests that need a clean registry rather
        than the shared, application-wide instance.
        """
        self._tenants.clear()


# A shared, ready-to-use instance -- mirrors ``sales_kpi_engine``,
# ``sales_export_service``, ``sales_reporting_service``,
# ``sales_ai_recommendation_service``, and
# ``sales_pdf_generator_service``. Populated from ``config/tenants.py``
# (imported for its side effect wherever the app starts up), so callers
# elsewhere in the app can import this directly instead of constructing
# their own registry.
tenant_registry = TenantRegistry()
