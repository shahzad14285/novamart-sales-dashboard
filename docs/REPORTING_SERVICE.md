# Reporting Service

Sprint 6.2 -- Executive Reporting & Export Center, Module 2.

An orchestrator that assembles already-computed business data -- KPI
results, business insights, regional summaries, product summaries --
into a structured `Report` object for downstream consumers. It
computes nothing itself: every number in a report was produced by
another service and simply handed in.

## Architecture

```
services/reporting_service.py
    ReportingServiceError (base exception)
        InvalidReportContextError   -- context isn't a ReportContext
        InvalidReportTypeError      -- report_type isn't a ReportType/str
        UnknownReportTypeError      -- report_type isn't a defined report
        UnknownReportSectionError   -- a report references an unregistered section (config bug)
        MissingReportDataError      -- a required section has no data
    ReportType(str, Enum)            -- EXECUTIVE / WEEKLY / MONTHLY / REGIONAL
    ReportContext   (kpi_results, business_insights, regional_summary, product_summary, metadata)
    ReportMetadata  (title, generated_at, period_label, prepared_for, notes)
    ReportSection   (key, title, content, order)
    Report          (report_type, metadata, sections) + get_section() / section_keys() / is_empty()
    SectionSpec     (key, required)
    ReportingService
        .register_section_builder(key, builder)
        .define_report(report_type, sections)
        .generate_report(report_type, context) -> Report
        .report_types()
sales_reporting_service = ReportingService()   # shared, ready-to-use instance
```

### Why this shape

- **Pure orchestration, no calculation.** Every section builder
  (`_build_kpi_summary_section`, `_build_business_insights_section`,
  `_build_regional_summary_section`, `_build_product_summary_section`)
  only reads a field off `ReportContext` and wraps it in a
  `ReportSection` -- it never sums, averages, or recomputes anything.
  The module imports only the *value objects* `KPIResult` (from
  `utils/kpi_engine.py`) and `BusinessInsights` (from
  `utils/insights.py`) for typing, never their calculation functions.
- **Two registries, matching the pattern already used by
  `utils/kpi_engine.py` (`KPIEngine.register`) and
  `services/export_service.py` (`ExportService.register`):**
  `register_section_builder()` adds a new kind of section;
  `define_report()` declares which sections a report type includes, in
  what order, and whether each is required. Both can be called after
  construction, so extending the service never means subclassing or
  editing `ReportingService` itself.
- **Report types aren't a closed set.** `ReportType` provides the four
  named constants the ticket asks for (with real `Enum` identity, so
  `report.report_type is ReportType.EXECUTIVE` holds for the
  built-ins), but `define_report()` accepts *any* string key. Defining
  `service.define_report("department", (...))` creates a working
  report type on the spot -- this is what makes "department-specific
  reports" (an explicitly named future requirement) additive rather
  than a rework of `ReportType`.
- **Required vs. optional sections, decided once, in one place.**
  Each `SectionSpec` says whether its section is required. A section
  builder never decides this itself -- it only reports "I have data"
  (returns a `ReportSection`) or "I don't" (returns `None`).
  `ReportingService.generate_report()` is the single place that turns
  "no data" into either a graceful omission (optional) or a typed
  `MissingReportDataError` (required). This is what "handle missing
  required sections gracefully" means here: never a raw `KeyError` or
  `AttributeError`, always one of the five documented exceptions.
- **Empty data is handled the same way as missing data.** An empty
  dict/Series passed as `regional_summary`/`product_summary` is
  normalized to `{}` by `_normalize_mapping()` and then treated
  identically to `None` -- no separate "empty" code path was needed.
- **Content is never transformed, only organized.** A `ReportSection`'s
  `content` is the original `KPIResult` dict, the original
  `BusinessInsights` object (by reference, not a copy), or a
  dict-normalized `regional_summary`/`product_summary`. Downstream
  consumers see exactly what the originating service computed.

### Default report definitions (a starting point, not a fixed rule)

| Report type | Required sections | Optional sections |
|---|---|---|
| Executive | KPI Summary, Business Insights | Product Summary, Regional Summary |
| Weekly | KPI Summary | Business Insights |
| Monthly | KPI Summary, Business Insights, Product Summary | Regional Summary |
| Regional | Regional Summary | KPI Summary, Product Summary |

This is a judgment call to give each report type a distinct, sensible
shape (Weekly stays lean for a frequent cadence; Regional centers on
the region breakdown; Monthly treats product performance as essential).
Call `sales_reporting_service.define_report(ReportType.X, (...))` to
change any of this without touching the class.

## Future compatibility

- **Risk Analysis / AI Recommendations / Forecasts / Charts:** add one
  new optional field to `ReportContext` (e.g. `risk_analysis: object |
  None = None`), write one `_build_risk_analysis_section` function
  with the same `(ReportContext) -> ReportSection | None` signature,
  register it, and add a `SectionSpec` to whichever report types
  should include it.
- **Department-specific reports:** call `define_report("department",
  (...))` (or any other name) using already-registered sections, or
  register new ones first. Verified directly in
  `tests/test_reporting_service.py::test_define_new_report_type_end_to_end`.

## Integration changes

**None required.** `ReportingService` doesn't read files, call
`KPIEngine`, call `generate_business_insights`, or call
`ExportService` -- it only accepts their *outputs* via
`ReportContext`. No existing page, component, or the Export Service
from Module 1 needed any change. A future "Reports" page would look
like:

```python
from services.reporting_service import ReportContext, sales_reporting_service
from utils.kpi_engine import sales_kpi_engine
from utils.insights import generate_business_insights

context = ReportContext(
    kpi_results=sales_kpi_engine.calculate_all(filtered_df),
    business_insights=generate_business_insights(filtered_df),
    regional_summary=filtered_df.groupby("region")["revenue"].sum(),
    product_summary=filtered_df.groupby("product")["revenue"].sum(),
)
report = sales_reporting_service.generate_report("executive", context)
for section in report.sections:
    st.subheader(section.title)
    st.write(section.content)
```

## Confirmation against the agreed architecture

- [x] `services/reporting_service.py` created; no other production
      file modified.
- [x] Assembles KPI results, business insights, regional summaries,
      and product summaries into a structured `Report`; defines
      section order per report type via `SectionSpec` tuples.
- [x] Supports Executive, Weekly, Monthly, and Regional reports, each
      with its own section order and required/optional rules.
- [x] Returns a structured `Report` object (dataclass, with
      `get_section`/`section_keys`/`is_empty` convenience methods) for
      downstream consumers.
- [x] Receives already-prepared data only -- confirmed by inspection:
      no imports from `utils/data_loader.py`, `utils/calculations.py`,
      `utils/kpi_engine.py`'s calculation functions,
      `utils/insights.py`'s `generate_business_insights`,
      `utils/filters.py`, or `services/export_service.py`; no PDF or
      email code anywhere in the module.
- [x] Single Responsibility Principle (assembly only), DRY (one
      `_normalize_mapping` helper reused by both summary sections, one
      `generate_report` loop handles every report type), clean
      architecture (`services/` depends on `utils/` value objects only,
      never the reverse), small reusable methods, thorough docstrings.
- [x] Validates input types (`InvalidReportContextError`,
      `InvalidReportTypeError`).
- [x] Handles missing required sections and empty report data via
      `MissingReportDataError`, and omits missing optional sections
      gracefully.
- [x] Meaningful, typed custom exceptions (five, all subclassing
      `ReportingServiceError`).
- [x] Extensible design verified in tests: a new section
      (`risk_analysis`) and a new report type (`"department"`) were
      both added at runtime with zero changes to `ReportingService`.

## Automated tests

`tests/test_reporting_service.py` (25 tests) builds its inputs from the
real `utils.kpi_engine`/`utils.insights` modules (with pandas) rather
than hand-rolled stand-ins, and covers: all four report types'
happy paths, string/case-insensitive report-type dispatch, required-
section-missing errors (with the right report type/section named on
the exception), optional-section omission, content fidelity (KPI/
insights objects passed through unchanged, regional/product summaries
normalized from a pandas `Series` to a `dict`), contiguous section
ordering when optional sections are skipped, fully-empty-context and
empty-mapping handling, all four input-validation error paths,
registering a new section builder, and defining a brand-new report
type. Verified via `python3 -m py_compile` across the whole project
plus a 29-assertion battery run directly against the real
`pandas`/`utils.kpi_engine`/`utils.insights` code (pytest itself isn't
installed in this offline sandbox) -- all passed.

## Manual test cases

| # | Steps | Expected result |
|---|-------|------------------|
| 1 | Build a `ReportContext` with `kpi_results` and `business_insights` from a real filtered dataset, call `generate_report("executive", context)` | Returns a `Report` with sections `("kpi_summary", "business_insights")`, in that order. |
| 2 | Same context, also add `regional_summary` and `product_summary`, regenerate the Executive report | Now includes all four sections, in the order Executive is defined: KPI, Insights, Product, Regional. |
| 3 | Call `generate_report("weekly", context)` with only `kpi_results` set | Succeeds with just the KPI Summary section; no error for the missing (optional) Business Insights. |
| 4 | Call `generate_report("monthly", context)` with `product_summary` left out | Raises `MissingReportDataError` naming `"monthly"` and `"product_summary"`. |
| 5 | Call `generate_report("regional", ReportContext())` (nothing provided) | Raises `MissingReportDataError` naming `"regional_summary"`. |
| 6 | Call `generate_report("EXECUTIVE", context)` and `generate_report(" executive ", context)` | Both succeed identically -- report type lookup is case-insensitive and trims whitespace. |
| 7 | Call `generate_report(42, context)` or `generate_report("executive", {"not": "a context"})` | Raise `InvalidReportTypeError` / `InvalidReportContextError` respectively, naming the wrong type received. |
| 8 | Call `generate_report("quarterly", context)` | Raises `UnknownReportTypeError` listing the currently defined report types. |
| 9 | Inspect `report.get_section("business_insights").content` | Is the *same* `BusinessInsights` object passed into the context (identity check), confirming no data was recomputed or copied. |
| 10 | Register a new section builder and call `service.define_report("department", (SectionSpec("product_summary", required=True),))`, then `generate_report("department", context)` | Works immediately, returning a report with just the product summary section -- no change to `ReportingService` was needed. |
