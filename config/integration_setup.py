"""Integration Platform composition root for the NovaMart platform.

Sprint 6.8 -- Integration Platform & API Gateway, Task 8.

This is the **one** module in the entire codebase allowed to import
both ``integration`` and the existing business services (``utils``,
``services``) together -- mirroring exactly the role
``config/automation_setup.py`` already plays for ``automation`` and
``notification`` (Sprint 6.7), and ``config/credentials.py`` plays for
``identity`` and ``authorization`` (Sprint 6.6). Wiring "endpoint X
calls business service Y" is configuration, not business logic, so it
belongs here, at the composition root -- not inside ``integration/``
(which must stay framework- and business-logic-independent) and not
inside the business services themselves (Task 8: "Business services
should remain unaware of external callers").

Each handler below is a **thin adapter**: it does nothing except (1)
gather the inputs an existing, unmodified service already requires and
(2) call that service exactly as any Streamlit page already does. No
business logic is duplicated or reimplemented here. Because this
sprint ships no real HTTP layer ("Do NOT implement a production HTTP
server. The objective is architecture."), there is no uploaded
dataset attached to an inbound request -- these demo handlers use
``utils.helpers.generate_sample_dataframe`` as a stand-in data source,
exactly like Sprint 6.7's demo scheduled jobs illustrated the
Scheduler -> AutomationService round trip without a real report
pipeline behind them.

Imported once, for its side effect, from ``components/sidebar.py`` --
see that module's imports for the exact same pattern
``config.automation_setup`` already uses.
"""

from __future__ import annotations

from authorization.permissions import (
    EXPORT_DATA,
    GENERATE_PDF,
    GENERATE_REPORTS,
    USE_AI_RECOMMENDATIONS,
    VIEW_DASHBOARD,
)
from integration.models import EndpointDefinition, IntegrationRequest, RequestMethod
from integration.registry import endpoint_registry
from services.ai_recommendation_service import RecommendationContext, sales_ai_recommendation_service
from services.export_service import sales_export_service
from services.pdf_generator_service import sales_pdf_generator_service
from services.reporting_service import ReportContext, sales_reporting_service
from tenancy.context import TenantContext
from tenancy.registry import tenant_registry
from utils.helpers import generate_sample_dataframe
from utils.insights import generate_business_insights
from utils.kpi_engine import sales_kpi_engine

# The tenant every demo endpoint below is scoped to, in the absence of
# a real external caller supplying one. A future REST/webhook provider
# would instead resolve this from the inbound request (e.g. an API
# key -> tenant lookup); nothing about that changes how the endpoint
# handlers below call into the existing, unmodified business services.
_DEMO_TENANT_ID = "novamart-hq"
_DEFAULT_DEMO_ROWS = 30


def _demo_tenant_context() -> TenantContext:
    """Resolve the demo tenant context every handler below is scoped to."""
    return TenantContext(tenant=tenant_registry.get(_DEMO_TENANT_ID))


def _demo_dataframe(request: IntegrationRequest):
    """Build a stand-in dataset for a demo handler from ``request.payload``.

    Args:
        request: The inbound request. An optional ``"rows"`` payload
            key controls how many sample rows are generated.
    """
    rows = request.payload.get("rows", _DEFAULT_DEMO_ROWS)
    try:
        rows = int(rows)
    except (TypeError, ValueError):
        rows = _DEFAULT_DEMO_ROWS
    return generate_sample_dataframe(rows=rows)


# --------------------------------------------------------------------------
# Endpoint handlers -- each a thin adapter over one existing service.
# --------------------------------------------------------------------------


def _handle_kpi_retrieve(request: IntegrationRequest) -> dict:
    """Adapter for ``kpi.retrieve``: calls :data:`~utils.kpi_engine.sales_kpi_engine` unmodified."""
    tenant_context = _demo_tenant_context()
    df = _demo_dataframe(request)
    results = sales_kpi_engine.calculate_all(df, tenant_context=tenant_context)
    return {
        "kpis": [
            {"key": key, "label": result.label, "value": result.value, "formatted": result.formatted}
            for key, result in results.items()
        ]
    }


def _build_demo_report(request: IntegrationRequest, tenant_context: TenantContext):
    """Shared helper: assemble a demo :class:`~services.reporting_service.Report`.

    Used by both ``report.generate`` and ``pdf.generate`` -- each
    handler independently gathers and assembles its own report rather
    than one handler depending on another's output, since a Gateway
    request is handled in isolation (Task 8).
    """
    report_type = request.payload.get("report_type", "executive")
    df = _demo_dataframe(request)
    kpi_results = sales_kpi_engine.calculate_all(df, tenant_context=tenant_context)
    insights = generate_business_insights(df, tenant_context=tenant_context)
    context = ReportContext(kpi_results=kpi_results, business_insights=insights)
    return sales_reporting_service.generate_report(report_type, context, tenant_context=tenant_context)


def _handle_report_generate(request: IntegrationRequest) -> dict:
    """Adapter for ``report.generate``: calls :data:`~services.reporting_service.sales_reporting_service` unmodified."""
    tenant_context = _demo_tenant_context()
    report = _build_demo_report(request, tenant_context)
    return {
        "report_type": str(report.report_type),
        "sections": list(report.section_keys()),
        "is_empty": report.is_empty(),
    }


def _handle_pdf_generate(request: IntegrationRequest) -> dict:
    """Adapter for ``pdf.generate``: calls :data:`~services.pdf_generator_service.sales_pdf_generator_service` unmodified."""
    tenant_context = _demo_tenant_context()
    report = _build_demo_report(request, tenant_context)
    pdf_result = sales_pdf_generator_service.generate_pdf(report, tenant_context=tenant_context)
    return {
        "page_count": pdf_result.page_count,
        "size_bytes": len(pdf_result.content),
        "mime_type": pdf_result.mime_type,
    }


def _handle_export_request(request: IntegrationRequest) -> dict:
    """Adapter for ``export.request``: calls :data:`~services.export_service.sales_export_service` unmodified."""
    tenant_context = _demo_tenant_context()
    df = _demo_dataframe(request)
    export_format = request.payload.get("format", "csv")
    result = sales_export_service.export(df, export_format, tenant_context=tenant_context)
    return {"format": result.file_extension, "size_bytes": len(result.content), "mime_type": result.mime_type}


def _handle_ai_recommendations(request: IntegrationRequest) -> dict:
    """Adapter for ``ai.recommendations``: calls :data:`~services.ai_recommendation_service.sales_ai_recommendation_service` unmodified."""
    tenant_context = _demo_tenant_context()
    df = _demo_dataframe(request)
    kpi_results = sales_kpi_engine.calculate_all(df, tenant_context=tenant_context)
    insights = generate_business_insights(df, tenant_context=tenant_context)
    context = RecommendationContext(kpi_results=kpi_results, business_insights=insights)
    batch = sales_ai_recommendation_service.generate_recommendations(context, tenant_context=tenant_context)
    return {
        "provider": batch.provider_name,
        "count": len(batch.recommendations),
        "recommendations": [
            {
                "title": rec.title,
                "observation": rec.observation,
                "suggested_action": rec.suggested_action,
                "priority": str(rec.priority),
                "category": rec.category,
            }
            for rec in batch.recommendations
        ],
    }


def register_default_endpoints() -> None:
    """Register this sprint's demo endpoints (Task 8) with the shared endpoint registry.

    Routes are data, not code (Task 3: "Routes should be configurable
    rather than hardcoded") -- adding a real endpoint later means
    adding another :meth:`~integration.registry.EndpointRegistry.register`
    call here, never branching inside :class:`~integration.gateway.APIGateway`
    or :class:`~integration.router.Router`.
    """
    if endpoint_registry.list_endpoints():
        return

    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="kpi.retrieve",
            path="/api/v1/kpi",
            method=RequestMethod.GET,
            api_version="v1",
            required_permission=VIEW_DASHBOARD,
            description="Retrieve computed KPI results for the active tenant's dataset.",
        ),
        handler=_handle_kpi_retrieve,
    )
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="report.generate",
            path="/api/v1/reports",
            method=RequestMethod.POST,
            api_version="v1",
            required_permission=GENERATE_REPORTS,
            description="Generate a business report (executive, weekly, monthly, or regional).",
        ),
        handler=_handle_report_generate,
    )
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="pdf.generate",
            path="/api/v1/pdf",
            method=RequestMethod.POST,
            api_version="v1",
            required_permission=GENERATE_PDF,
            description="Render a business report to PDF.",
        ),
        handler=_handle_pdf_generate,
    )
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="export.request",
            path="/api/v1/export",
            method=RequestMethod.POST,
            api_version="v1",
            required_permission=EXPORT_DATA,
            required_fields=("format",),
            description="Export the active tenant's dataset to CSV, Excel, or JSON.",
        ),
        handler=_handle_export_request,
    )
    endpoint_registry.register(
        EndpointDefinition(
            endpoint_key="ai.recommendations",
            path="/api/v1/ai/recommendations",
            method=RequestMethod.GET,
            api_version="v1",
            required_permission=USE_AI_RECOMMENDATIONS,
            description="Generate AI-driven business recommendations for the active tenant's dataset.",
        ),
        handler=_handle_ai_recommendations,
    )


register_default_endpoints()
