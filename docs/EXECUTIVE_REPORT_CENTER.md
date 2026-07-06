# Executive Report Center

Sprint 6.2 -- Executive Reporting & Export Center, Module 5.

The orchestration layer that ties the four Sprint 6.2 services into
one screen: assemble the report, review AI-generated recommendations,
generate/download a PDF, and export the underlying data. It computes
nothing itself -- every number, recommendation, PDF byte, and export
byte on this screen was produced by an existing service.

## Architecture

```
ui/executive_report_center.py
    render_executive_report_center(df=None)          -- single entry point
        _acquire_dataset()                            -- Upload Center + Filter Panel (reused as-is)
        _render_report_controls()                     -- report type + "prepared for"
        _build_report_context(df, report_type, who)   -- invokes KPIEngine / insights / analytics
        sales_reporting_service.generate_report(...)  -- Reporting Service (Module 2)
        st.tabs(["Executive Report", "AI Recommendations", "PDF Export", "Data Export"])
            _render_report_tab(report)                 -- dispatches sections to render_kpi_cards /
                                                           render_business_insights_from_value / a table+chart
            _render_recommendations_tab(context, report) -- AI Recommendation Service (Module 3)
            _render_pdf_export_tab(report, row_count)  -- PDF Generator Service (Module 4)
            _render_data_export_tab(df)                -- Export Service (Module 1)

pages/5_Reports.py -- thin wrapper: page config + header/sidebar/footer + render_executive_report_center()
```

Minimal integration changes made alongside the new file:

- `components/analytics/insights.py` -- split `render_business_insights(df)`
  into itself (unchanged for existing callers) plus a new
  `render_business_insights_from_value(insights)` that renders the same
  cards from an *already-computed* `BusinessInsights` object. Re-exported
  from `components/analytics/__init__.py`.
- `pages/5_Reports.py` -- replaced the disabled placeholder with a call
  to `render_executive_report_center()`.

### Why this shape

**Where the dataset comes from.** The four services this module
coordinates all explicitly must not read uploaded files -- but nothing
in *this* ticket's "must NOT" list says that, because something has to
own it, and every page in this app already owns it itself (the
Dashboard page renders its own Upload Center + Filter Panel rather
than reading from a shared store). This module follows that same
precedent instead of inventing a new one, with widget keys scoped to
this module so it can coexist with the Dashboard page in the same
session. A caller that already has a filtered DataFrame can pass it
via the optional `df` parameter and skip that step entirely.

**Why `st.session_state` appears here, when no other module in this
app uses it.** Streamlit reruns the whole script on every widget
interaction. A "Generate PDF" button click computes the PDF on one
run; the `st.download_button` that lets the user actually download it
needs those bytes on the *next* run (and every run after, until a new
PDF is generated or the report changes). That's a one-screen,
self-contained need, not a shared app-wide store, so it's kept to two
module-prefixed keys (`executive_report_center_pdf_result`,
`executive_report_center_export_result`), each paired with a small
fingerprint (`_cache_tag`) so switching report type, uploading a new
file, or changing filters invalidates a stale generated artifact
instead of offering a download that no longer matches what's on screen.

**Why `_build_report_context` calls `sales_kpi_engine.calculate_all`,
`generate_business_insights`, and `calculate_revenue_by_group`
directly.** This is not "calculating KPIs" in the sense the ticket's
"must NOT" list means (re-deriving a formula) -- it's invoking the
exact entry points `docs/REPORTING_SERVICE.md` already documents as
the intended integration for a future "Reports" page. The Reporting
Service was deliberately built to never calculate anything itself; by
design, *some* caller has to supply its `ReportContext`, and this
module is that caller.

**Section rendering dispatches on content type, not section key** --
`_render_section_content` checks `dict` of `KPIResult` vs.
`BusinessInsights` vs. plain `dict` (regional/product summaries), the
same approach `services/pdf_generator_service.py` uses for the same
reason: a section's content shape is stable regardless of which report
type or future section key produced it, so a new report type reusing
an existing content shape needs no change here.

## Future compatibility

| Future item | Seam already in place |
|---|---|
| Notification/Email Service | `PDFResult`/`ExportResult` already sit in `st.session_state` after generation -- an "Email this report" button is one new call with those same bytes. |
| Scheduled report generation | `_build_report_context` / `generate_report` / `generate_recommendations` / `generate_pdf` are plain function calls, not entangled in widget callbacks -- a scheduler can call the same sequence headlessly. |
| Report history | Report type + branding are small, serializable objects already -- persisting "the last N reports" is additive. |
| Saved report templates | `PDFBrandingConfig` is already a plain dataclass -- a named preset is just persisting one instance. |
| Additional export formats | The format selector reads `sales_export_service.supported_formats()`, not a hard-coded list -- a new registered format appears automatically. |
| Role-based access | Each action (view report / view recommendations / generate PDF / export data) is already an independently callable section -- gating one is wrapping that call, not restructuring the module. |

## Confirmation against the agreed architecture

- [x] `ui/executive_report_center.py` created. Minimal integration
      changes: `components/analytics/insights.py` (new exported
      function, existing function unchanged), `components/analytics/__init__.py`
      (re-export), `pages/5_Reports.py` (placeholder replaced with the
      real screen).
- [x] Coordinates the Reporting Service, AI Recommendation Service,
      PDF Generator, and Export Service; presents one screen to view
      the report, view recommendations, generate/download a PDF, and
      export CSV/Excel/JSON.
- [x] Does not calculate KPIs, generate business insights, generate AI
      recommendations, assemble reports, generate PDFs, export files,
      or send emails itself -- confirmed by inspection: every number
      comes from `sales_kpi_engine.calculate_all`,
      `generate_business_insights`, or `calculate_revenue_by_group`
      (existing entry points, not reimplemented); report assembly is
      `sales_reporting_service.generate_report(...)`; recommendations
      are `sales_ai_recommendation_service.generate_recommendations(...)`;
      PDF bytes are `sales_pdf_generator_service.generate_pdf(...)`;
      export bytes are `sales_export_service.export(...)`. No email
      code anywhere in the module.
- [x] Follows the layered architecture (`ui/` orchestrates
      `services/` + `components/`, never the reverse), Single
      Responsibility Principle (coordination and presentation only),
      UI logic kept separate from business logic, reuses existing
      services/components rather than reimplementing them, strong type
      hints, thorough docstrings.
- [x] Matches the existing NovaMart UI: same `.nm-section-title`/
      `.nm-section-subtitle` header pattern, same bordered-card and
      `st.tabs` styling already defined in `components/theme.py`, same
      Upload Center + Filter Panel used verbatim, same
      `render_empty_state` component for "nothing to show yet".

## Automated tests

No `pytest` file was added for this module, matching this project's
established pattern: every other Streamlit UI module in
`components/`/`pages/` (which also has no automated tests, since
`streamlit` isn't installed in this offline sandbox and UI modules
need Streamlit's script runner to test meaningfully) relies on manual
test cases instead, while the underlying *logic* layer
(`utils/kpi_engine.py`, `utils/insights.py`, `utils/analytics.py`, and
the Sprint 6.2 services) already has full `pytest` coverage that this
module calls into unchanged.

In place of execution, verification here was: `python3 -m py_compile`
across the whole project, plus a headless dry run using a
minimal Streamlit-API stub (`st.tabs`, `st.columns`, `st.selectbox`,
`st.button`, `st.download_button`, `st.session_state`, etc., all
implemented as thin no-ops/return-value hooks) that exercises the
*real* module's control flow end to end: default load, switching
report type, generating a PDF and downloading it, exporting CSV and
downloading it, an empty dataset, a dataset with no product/region
columns, and confirming a previously generated PDF is silently dropped
(not offered for download) once the report type changes underneath it.
All scenarios completed without error and produced the expected
`st.success`/`st.download_button` calls.

## Manual test cases

| # | Steps | Expected result |
|---|-------|------------------|
| 1 | Open the Reports page with no data uploaded | Shows the Upload Center; no report controls or tabs yet. |
| 2 | Upload a valid sales file, apply no filters | Report controls appear; the Executive Report tab shows KPI cards, Business Insights cards, Product Summary, and Regional Summary in that order. |
| 3 | Change "Report type" to Weekly / Monthly / Regional | The Executive Report tab updates to that type's sections (e.g. Regional shows only the Regional Summary if the dataset has no other data required). |
| 4 | Enter "Board of Directors" in "Prepared for" | The report's header caption shows "Prepared for: Board of Directors". |
| 5 | Open the "AI Recommendations" tab | Shows a provider caption ("Provider: Rule-Based Engine") and one card per recommendation, highest priority first, each with an observation and suggested action. |
| 6 | Open "PDF Export", expand "Branding options", set a watermark, click "Generate PDF" | A success message with the page count appears, followed by a working "Download PDF" button; the downloaded file opens as a valid PDF with the watermark applied. |
| 7 | After generating a PDF, switch "Report type" to a different type | The PDF download button disappears (the stale PDF is silently dropped) until "Generate PDF" is clicked again. |
| 8 | Open "Data Export", choose CSV/Excel/JSON, click "Export data" | A success message with the byte count appears, followed by a working "Download file" button producing a valid file in the chosen format. |
| 9 | Apply a filter that narrows the dataset to zero rows | The Report Center shows the "no data" empty state instead of a broken report. |
| 10 | Upload a dataset with no `product`/`region` columns | The Executive Report tab shows only the sections that don't need those columns (no crash); AI Recommendations still generates a baseline summary. |
