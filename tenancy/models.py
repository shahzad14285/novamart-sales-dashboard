"""Tenant model for the NovaMart Multi-Tenant platform.

Sprint 6.3 -- Multi-Tenant Business Intelligence Platform, Task 1.

A :class:`Tenant` is a plain, immutable value object describing one
organization using the platform. It carries no behavior of its own
(no database access, no validation logic beyond its own field types) --
every existing and future service only ever reads it, matching the
value-object convention already established by ``KPIResult``,
``BusinessInsights``, ``Report``, and ``Recommendation`` elsewhere in
this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class TenantStatus(str, Enum):
    """Whether a tenant is currently allowed to use the platform.

    A plain ``str`` subclass (matching ``services.reporting_service.ReportType``
    and ``services.ai_recommendation_service.RecommendationPriority``), so a
    member compares equal to, and can be constructed from, its
    underlying string value.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class Tenant:
    """An organization using the NovaMart platform.

    Attributes:
        tenant_id: Stable, unique identifier for the tenant (e.g.
            ``"acme-retail"``). Used as the key everywhere a tenant
            needs to be looked up or logged -- never the display name,
            which may change.
        name: Short, machine-friendly name (e.g. ``"acme-retail"``).
            Distinct from ``tenant_id`` only in that a future
            implementation could rotate ``tenant_id`` (a database key)
            while keeping ``name`` stable, or vice versa; today they are
            typically the same value.
        display_name: Human-readable name shown in the UI (e.g.
            ``"Acme Retail Group"``).
        status: Whether the tenant is currently active. Defaults to
            :attr:`TenantStatus.ACTIVE`.
        metadata: Optional, free-form extra data (e.g. a plan tier,
            contact email, region, feature flags) that lets future
            requirements attach new information to a tenant *without*
            requiring a change to this model or to any service that
            already depends on it -- exactly the "Optional Metadata for
            future expansion" this model is required to support.

    Example:
        >>> tenant = Tenant(
        ...     tenant_id="acme-retail",
        ...     name="acme-retail",
        ...     display_name="Acme Retail Group",
        ... )
        >>> tenant.is_active
        True
    """

    tenant_id: str
    name: str
    display_name: str
    status: TenantStatus = TenantStatus.ACTIVE
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Whether this tenant is currently allowed to use the platform."""
        return self.status == TenantStatus.ACTIVE
