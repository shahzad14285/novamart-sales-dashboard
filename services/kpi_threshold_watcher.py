"""KPI Threshold Watcher for the NovaMart Sales Intelligence Dashboard.

Sprint 6.7 -- Automation & Notification Platform, Task 8.

A small, new, additive module answering the Business Goal's "Notify
executives when KPIs fall below thresholds" -- deliberately kept
separate from ``utils/kpi_engine.py`` rather than added to it, per this
sprint's explicit constraint: "Do NOT modify business logic." KPI
*calculation* is, and remains, entirely owned by
:class:`~utils.kpi_engine.KPIEngine`; this module only *reads* already-computed
:class:`~utils.kpi_engine.KPIResult` values and announces
(:class:`~automation.models.EventType.KPI_THRESHOLD_REACHED`) when one
falls below a configured minimum. It never recalculates a KPI, and a
threshold breach never blocks or alters anything the KPI Engine itself
returns -- this is pure, side-effect-only observation layered on top of
already-existing values, the same non-invasive pattern every other
Sprint 6.7 event-publishing call site follows (see
``docs/AUTOMATION_ARCHITECTURE.md``).

Threshold values are demo defaults, not a business rule handed down by
this ticket -- a real deployment would source them from tenant-specific
configuration instead of the hard-coded table below, which is exactly
why they're exposed as a plain, overridable dict rather than buried in
a function body.
"""

from __future__ import annotations

from typing import Mapping

from automation.models import AutomationEvent, EventType
from automation.service import automation_service
from tenancy.context import TenantContext
from utils.kpi_engine import KPIResult

_SOURCE_SERVICE = "KPIThresholdWatcher"

# Demo default minimum-acceptable values, keyed by KPI key (matching
# config.constants.KPI_* keys). A KPI not listed here is never checked
# -- silently skipped, not an error, since not every KPI has a
# meaningful "too low" threshold (e.g. KPI_HIGHEST_REVENUE_DAY isn't a
# number that failing a floor makes sense for).
DEFAULT_KPI_THRESHOLDS: dict[str, float] = {
    "total_revenue": 1000.0,
    "avg_order_value": 10.0,
}


def check_kpi_thresholds(
    kpi_results: Mapping[str, KPIResult],
    *,
    thresholds: Mapping[str, float] | None = None,
    tenant_context: TenantContext | None = None,
    user_id: str | None = None,
) -> tuple[AutomationEvent, ...]:
    """Compare already-computed KPI results against configured thresholds and publish breaches.

    Args:
        kpi_results: KPI results exactly as returned by
            :meth:`~utils.kpi_engine.KPIEngine.calculate_all` -- never
            recomputed here.
        thresholds: Minimum acceptable values, keyed by KPI key.
            Defaults to :data:`DEFAULT_KPI_THRESHOLDS`. A future
            tenant-specific settings screen would pass its own table
            here instead of relying on the module default.
        tenant_context: The active tenant, if any, attached to each
            published event.
        user_id: The identity viewing this report, if known, attached
            to each published event.

    Returns:
        A tuple of the :class:`~automation.models.AutomationEvent`
        values published for each KPI that fell below its threshold
        (possibly empty -- not every call finds a breach, and that is
        the common, healthy case).
    """
    active_thresholds = thresholds if thresholds is not None else DEFAULT_KPI_THRESHOLDS
    published: list[AutomationEvent] = []

    for kpi_key, minimum in active_thresholds.items():
        result = kpi_results.get(kpi_key)
        if result is None or not isinstance(result.value, (int, float)):
            continue
        if result.value >= minimum:
            continue

        event = automation_service.publish(
            EventType.KPI_THRESHOLD_REACHED,
            source_service=_SOURCE_SERVICE,
            payload={
                "kpi_key": kpi_key,
                "kpi_label": result.label,
                "value": result.formatted,
                "threshold": minimum,
            },
            tenant_context=tenant_context,
            user_id=user_id,
        )
        published.append(event)

    return tuple(published)
