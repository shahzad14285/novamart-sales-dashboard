"""Unit tests for services/export_service.py.

services/export_service.py has no Streamlit dependency, so these tests
run against the real module (with real pandas/openpyxl) -- no
mocking/stubbing required.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from services.export_service import (
    ExportResult,
    ExportService,
    InvalidExportInputError,
    UnsupportedExportFormatError,
    sales_export_service,
)
from tenancy.context import TenantContext
from tenancy.models import Tenant


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """A small, deterministic DataFrame for testing."""
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "revenue": [100.0, 200.0, 300.0],
            "product": ["Widget", "Gadget", "Widget"],
        }
    )


@pytest.fixture
def tenant_context() -> TenantContext:
    """A valid, active TenantContext -- Multi-Tenant Sprint 6.3 requires one for export()."""
    return TenantContext(tenant=Tenant(tenant_id="test-tenant", name="test-tenant", display_name="Test Tenant"))


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """A valid but empty DataFrame (has columns, zero rows)."""
    return pd.DataFrame(columns=["date", "revenue", "product"])


# --------------------------------------------------------------------------
# export_csv
# --------------------------------------------------------------------------


def test_export_csv_returns_export_result(sample_df: pd.DataFrame) -> None:
    service = ExportService()
    result = service.export_csv(sample_df)

    assert isinstance(result, ExportResult)
    assert result.file_extension == "csv"
    assert result.mime_type == "text/csv"
    assert isinstance(result.content, bytes)


def test_export_csv_content_matches_dataframe(sample_df: pd.DataFrame) -> None:
    service = ExportService()
    result = service.export_csv(sample_df)

    text = result.content.decode("utf-8")
    assert "revenue" in text
    assert "Widget" in text
    assert text.count("\n") >= 3  # header + 3 data rows (allowing trailing newline)


def test_export_csv_handles_empty_dataframe_gracefully(empty_df: pd.DataFrame) -> None:
    service = ExportService()
    result = service.export_csv(empty_df)

    text = result.content.decode("utf-8")
    assert "date" in text and "revenue" in text and "product" in text
    # Header only -- no data rows.
    assert len(text.strip().splitlines()) == 1


def test_export_csv_does_not_mutate_input(sample_df: pd.DataFrame) -> None:
    service = ExportService()
    before = sample_df.copy(deep=True)
    service.export_csv(sample_df)
    pd.testing.assert_frame_equal(sample_df, before)


def test_export_csv_invalid_input_raises() -> None:
    service = ExportService()
    with pytest.raises(InvalidExportInputError):
        service.export_csv({"not": "a dataframe"})


def test_export_csv_none_input_raises() -> None:
    service = ExportService()
    with pytest.raises(InvalidExportInputError):
        service.export_csv(None)


# --------------------------------------------------------------------------
# export_excel
# --------------------------------------------------------------------------


def test_export_excel_returns_export_result(sample_df: pd.DataFrame) -> None:
    service = ExportService()
    result = service.export_excel(sample_df)

    assert isinstance(result, ExportResult)
    assert result.file_extension == "xlsx"
    assert "spreadsheetml" in result.mime_type
    assert isinstance(result.content, bytes)
    assert len(result.content) > 0


def test_export_excel_content_is_readable_workbook(sample_df: pd.DataFrame) -> None:
    from io import BytesIO

    service = ExportService()
    result = service.export_excel(sample_df)

    roundtrip = pd.read_excel(BytesIO(result.content))
    assert list(roundtrip["product"]) == ["Widget", "Gadget", "Widget"]
    assert roundtrip["revenue"].sum() == 600.0


def test_export_excel_handles_empty_dataframe_gracefully(empty_df: pd.DataFrame) -> None:
    from io import BytesIO

    service = ExportService()
    result = service.export_excel(empty_df)

    roundtrip = pd.read_excel(BytesIO(result.content))
    assert roundtrip.empty
    assert list(roundtrip.columns) == ["date", "revenue", "product"]


def test_export_excel_invalid_input_raises() -> None:
    service = ExportService()
    with pytest.raises(InvalidExportInputError):
        service.export_excel([1, 2, 3])


# --------------------------------------------------------------------------
# export_json
# --------------------------------------------------------------------------


def test_export_json_returns_export_result(sample_df: pd.DataFrame) -> None:
    service = ExportService()
    result = service.export_json(sample_df)

    assert isinstance(result, ExportResult)
    assert result.file_extension == "json"
    assert result.mime_type == "application/json"


def test_export_json_content_is_valid_and_matches_dataframe(sample_df: pd.DataFrame) -> None:
    service = ExportService()
    result = service.export_json(sample_df)

    parsed = json.loads(result.content.decode("utf-8"))
    assert isinstance(parsed, list)
    assert len(parsed) == 3
    assert parsed[0]["product"] == "Widget"
    assert parsed[1]["revenue"] == 200.0


def test_export_json_handles_empty_dataframe_gracefully(empty_df: pd.DataFrame) -> None:
    service = ExportService()
    result = service.export_json(empty_df)

    parsed = json.loads(result.content.decode("utf-8"))
    assert parsed == []


def test_export_json_invalid_input_raises() -> None:
    service = ExportService()
    with pytest.raises(InvalidExportInputError):
        service.export_json("definitely not a dataframe")


# --------------------------------------------------------------------------
# export() dispatcher / registry
# --------------------------------------------------------------------------


def test_export_dispatches_to_csv(sample_df: pd.DataFrame, tenant_context: TenantContext) -> None:
    service = ExportService()
    result = service.export(sample_df, "csv", tenant_context=tenant_context)
    assert result.file_extension == "csv"


def test_export_is_case_insensitive_and_trims_whitespace(
    sample_df: pd.DataFrame, tenant_context: TenantContext
) -> None:
    service = ExportService()
    result = service.export(sample_df, "  CSV  ", tenant_context=tenant_context)
    assert result.file_extension == "csv"


def test_export_xlsx_and_excel_keys_both_work(sample_df: pd.DataFrame, tenant_context: TenantContext) -> None:
    service = ExportService()
    assert service.export(sample_df, "excel", tenant_context=tenant_context).file_extension == "xlsx"
    assert service.export(sample_df, "xlsx", tenant_context=tenant_context).file_extension == "xlsx"


def test_export_unsupported_format_raises(sample_df: pd.DataFrame, tenant_context: TenantContext) -> None:
    service = ExportService()
    with pytest.raises(UnsupportedExportFormatError):
        service.export(sample_df, "pdf", tenant_context=tenant_context)


def test_supported_formats_lists_all_default_formats() -> None:
    service = ExportService()
    assert set(service.supported_formats()) == {"csv", "excel", "xlsx", "json"}


def test_register_adds_a_new_format(sample_df: pd.DataFrame, tenant_context: TenantContext) -> None:
    service = ExportService()

    def _export_xml(df: pd.DataFrame) -> ExportResult:
        # parser="etree" avoids an extra dependency on lxml -- this is
        # just a test double proving the registry is extensible; the
        # real export_xml() (a future module) can choose either parser.
        xml_text = df.to_xml(index=False, parser="etree")
        return ExportResult(content=xml_text.encode("utf-8"), file_extension="xml", mime_type="application/xml")

    service.register("xml", _export_xml)

    assert "xml" in service.supported_formats()
    result = service.export(sample_df, "xml", tenant_context=tenant_context)
    assert result.file_extension == "xml"
    assert b"<data>" in result.content or b"<row>" in result.content


def test_register_can_override_an_existing_format(sample_df: pd.DataFrame, tenant_context: TenantContext) -> None:
    service = ExportService()
    calls = []

    def _custom_csv(df: pd.DataFrame) -> ExportResult:
        calls.append(True)
        return ExportResult(content=b"custom", file_extension="csv", mime_type="text/csv")

    service.register("csv", _custom_csv)
    result = service.export(sample_df, "csv", tenant_context=tenant_context)

    assert calls == [True]
    assert result.content == b"custom"


# --------------------------------------------------------------------------
# Shared instance
# --------------------------------------------------------------------------


def test_shared_instance_is_an_export_service() -> None:
    assert isinstance(sales_export_service, ExportService)


def test_shared_instance_exports_csv(sample_df: pd.DataFrame, tenant_context: TenantContext) -> None:
    result = sales_export_service.export(sample_df, "csv", tenant_context=tenant_context)
    assert result.file_extension == "csv"


# --------------------------------------------------------------------------
# Multi-Tenant Sprint 6.3 -- tenant validation on export()
# --------------------------------------------------------------------------


def test_export_without_tenant_context_raises(sample_df: pd.DataFrame) -> None:
    from tenancy.exceptions import MissingTenantContextError

    service = ExportService()
    with pytest.raises(MissingTenantContextError):
        service.export(sample_df, "csv")


def test_export_with_inactive_tenant_raises(sample_df: pd.DataFrame) -> None:
    from tenancy.exceptions import InactiveTenantError
    from tenancy.models import TenantStatus

    inactive_context = TenantContext(
        tenant=Tenant(tenant_id="inactive-tenant", name="inactive-tenant", display_name="Inactive Co", status=TenantStatus.INACTIVE)
    )
    service = ExportService()
    with pytest.raises(InactiveTenantError):
        service.export(sample_df, "csv", tenant_context=inactive_context)
