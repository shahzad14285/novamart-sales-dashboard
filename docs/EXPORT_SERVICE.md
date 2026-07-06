# Export Service

Sprint 6.2 -- Executive Reporting & Export Center, Module 1.

A reusable, framework-agnostic service that converts an already
processed pandas DataFrame into CSV, Excel, or JSON and returns the
exported content to the caller. It introduces a new top-level
`services/` package, sitting alongside `utils/` (business calculations)
and `components/`/`pages/` (Streamlit UI), reserved for cross-cutting
application services that are neither.

## Architecture

```
services/export_service.py
    ExportServiceError (base exception)
        InvalidExportInputError      -- input isn't a pandas DataFrame
        UnsupportedExportFormatError -- export() got an unregistered format
    ExportResult   (frozen dataclass: content bytes + file_extension + mime_type)
    ExportService
        .export_csv(df)     -> ExportResult
        .export_excel(df)   -> ExportResult
        .export_json(df)    -> ExportResult
        .export(df, format) -> ExportResult   (registry dispatcher)
        .register(format, exporter)           (add/override a format)
        .supported_formats()
sales_export_service = ExportService()   # shared, ready-to-use instance
```

### Why this shape

- **Single Responsibility Principle.** `ExportService` does exactly
  one thing -- format conversion. It takes a DataFrame it is handed
  and returns bytes; it never opens a file, never touches
  `utils/data_loader.py`, `utils/filters.py`, or `utils/kpi_engine.py`,
  and never builds a report or a PDF. Each `export_*` method is small
  and does one conversion; a shared `_validate_dataframe()` helper is
  the only logic reused across all three (DRY).
- **Registry pattern, matching `utils/kpi_engine.py`.** `KPIEngine`
  already established the pattern this codebase uses for "a fixed set
  of built-ins today, arbitrary extensions later without touching the
  class": a `register(key, func)` method plus a dict looked up by
  `calculate_all`/`calculate`. `ExportService` follows the identical
  shape (`register(format, exporter)` + `export(df, format)`), so
  extending it with `export_xml()`, `export_parquet()`, or
  `export_api_payload()` later is: write one method with the signature
  `(df: pd.DataFrame) -> ExportResult`, then call
  `service.register("xml", service.export_xml)` inside
  `_register_default_exporters()`. No existing method, caller, or test
  needs to change. `tests/test_export_service.py` proves this by
  registering a throwaway XML exporter at test time and confirming it
  works immediately.
- **`ExportResult` value object**, mirroring the `KPIResult`/
  `FilterField` dataclass pattern already used elsewhere in the app.
  Every exporter returns the same shape (`content: bytes`,
  `file_extension`, `mime_type`), so a caller doesn't need
  format-specific handling to, for example, wire a result into a
  Streamlit `st.download_button(data=result.content,
  file_name=f"export.{result.file_extension}", mime=result.mime_type)`.
- **No data mutation.** Every exporter calls a read-only pandas method
  (`to_csv`/`to_excel`/`to_json`) on the DataFrame it receives and
  never reassigns, sorts, fills, or filters it. `tests/test_export_service.py`
  explicitly asserts the input DataFrame is byte-for-byte unchanged
  after `export_csv()`.
- **Empty DataFrames are not an error.** pandas' own `to_csv`/
  `to_excel`/`to_json` already produce well-formed, header-only output
  for a zero-row DataFrame, so `_validate_dataframe()` only rejects
  non-DataFrame input (including `None`) and otherwise passes empty
  frames straight through -- no special-case branching needed to
  satisfy "handle empty DataFrames gracefully".

## Integration changes

**None required for this module.** `ExportService` is intentionally
UI-agnostic and was not wired into any page or component -- this
ticket scoped "Module 1 -- Export Service" as the conversion engine
only; the sprint name ("Executive Reporting & Export Center") implies
a future module will add the UI (an Export Center page/section with
download buttons) that calls `sales_export_service.export(...)`. No
existing file was modified to integrate it, and no new dependency was
needed: `openpyxl` (required for `export_excel`) is already in
`requirements.txt`.

When that UI module is built, the integration point is a single call:

```python
from services.export_service import sales_export_service

result = sales_export_service.export(filtered_df, "csv")
st.download_button(
    "Download CSV",
    data=result.content,
    file_name=f"novamart_export.{result.file_extension}",
    mime=result.mime_type,
)
```

## Confirmation against the agreed architecture

- [x] `services/export_service.py` created; no other production file
      modified.
- [x] Accepts a processed pandas DataFrame; exports CSV, Excel, JSON;
      returns the content to the caller via `ExportResult`.
- [x] Does not read uploaded files, calculate KPIs, modify business
      data, apply filters, generate reports, generate PDFs, or perform
      AI recommendations -- confirmed by inspection (no imports from
      `utils/data_loader.py`, `utils/kpi_engine.py`, or
      `utils/filters.py`, and no report/PDF/AI code anywhere in the
      module).
- [x] Single Responsibility Principle, DRY (shared validation helper,
      shared Excel/registry logic), clean architecture (new `services/`
      layer, no dependency on `components/`/`pages/`), small reusable
      methods, clear docstrings on every class/method.
- [x] Validates input is a DataFrame, raising `InvalidExportInputError`
      for anything else (including `None`).
- [x] Handles empty DataFrames gracefully (verified for all three
      formats).
- [x] Raises meaningful, typed exceptions (`InvalidExportInputError`,
      `UnsupportedExportFormatError`), both subclasses of
      `ExportServiceError` for single-`except` handling.
- [x] Extensible design verified by registering a throwaway
      `export_xml` at test time with zero changes to `ExportService`.

## Automated tests

`tests/test_export_service.py` (23 tests) covers: successful export
for each of the three formats, output round-tripped back through
pandas to confirm correctness (not just "didn't crash"), empty-
DataFrame handling for all three formats, confirmation the input
DataFrame is not mutated, invalid-input errors (wrong type and
`None`), the `export()` dispatcher (case-insensitivity, whitespace
trimming, the `excel`/`xlsx` alias), `UnsupportedExportFormatError` for
an unregistered format, `supported_formats()`, registering a new format
at runtime, overriding an existing format at runtime, and the shared
`sales_export_service` instance.

Since the sandbox has no network access, these were verified two ways:
`python3 -m py_compile` across the whole project (confirms every
module -- old and new -- still imports cleanly), and a 36-assertion
battery executed directly against the real `pandas`/`openpyxl`
libraries already installed (`pytest` itself isn't installed in this
offline sandbox, so the test file's cases were also run as plain
Python assertions to get real, non-mocked confirmation). All 36 passed.

## Manual test cases

| # | Steps | Expected result |
|---|-------|------------------|
| 1 | `ExportService().export_csv(df)` with a normal DataFrame | Returns an `ExportResult` with `file_extension="csv"`, `mime_type="text/csv"`, and `content` that decodes to a valid CSV with a header row and one row per DataFrame row. |
| 2 | `ExportService().export_excel(df)` with a normal DataFrame, then reopen the bytes with `pd.read_excel` | Reopened DataFrame matches the original data (same values, same row count). |
| 3 | `ExportService().export_json(df)` with a normal DataFrame | `content` decodes to valid JSON; `json.loads(...)` returns a list of row objects matching the DataFrame's rows/values. |
| 4 | Call `export_csv`/`export_excel`/`export_json` with a DataFrame that has columns but zero rows | Each returns a valid, well-formed result (header-only CSV, header-only worksheet, `"[]"` JSON) -- no exception raised. |
| 5 | Call any `export_*` method with a `list`, `dict`, plain string, or `None` instead of a DataFrame | Raises `InvalidExportInputError` with a message naming the type that was actually received. |
| 6 | `ExportService().export(df, "csv")`, `"CSV"`, and `"  csv  "` | All three return the same CSV result -- format lookup is case-insensitive and trims whitespace. |
| 7 | `ExportService().export(df, "excel")` and `ExportService().export(df, "xlsx")` | Both return an `.xlsx` result via the same exporter. |
| 8 | `ExportService().export(df, "pdf")` (or any unregistered format) | Raises `UnsupportedExportFormatError` listing the currently supported formats. |
| 9 | Register a new exporter, e.g. `service.register("xml", my_xml_exporter)`, then call `service.export(df, "xml")` | The new format works immediately; `service.supported_formats()` includes `"xml"`; no existing method needed to change. |
| 10 | Export a DataFrame, then compare it (`DataFrame.equals`) to a copy taken before the export call | Identical -- confirms the export methods never mutate the caller's data. |
