# PDF Generator Service

Sprint 6.2 -- Executive Reporting & Export Center, Module 4.

Converts an already-assembled `Report` (from the Reporting Service)
into a professional PDF document. It computes nothing and assembles
nothing -- every value it prints was produced elsewhere and simply
handed in.

## Architecture

```
services/pdf_generator_service.py
    PDFGeneratorServiceError (base exception)
        InvalidReportInputError     -- input isn't a Report
        InvalidBrandingConfigError  -- branding isn't a PDFBrandingConfig
        PDFRenderingError           -- a section (or the document) failed to render
    PDFBrandingConfig  (company_name, logo_path, primary_color, accent_color,
                        footer_text, watermark_text, show_cover_page,
                        show_page_numbers, show_table_of_contents, page_size)
    PDFResult          (content, file_extension="pdf", mime_type="application/pdf", page_count)
    PDFGeneratorService
        .register_content_renderer(content_type, renderer)
        .generate_pdf(report, branding=None) -> PDFResult
sales_pdf_generator_service = PDFGeneratorService()   # shared, ready-to-use instance
```

### Why this shape -- and why it isn't a copy of Module 3's provider pattern

Module 3 (AI Recommendation Service) needed a swappable-*provider*
abstraction because its ticket explicitly forbade depending on any one
AI vendor and named concrete, genuinely interchangeable backends (GPT,
Claude, Gemini). This module's future-compatibility list is different
in kind: logo, corporate colors, headers/footers, page numbers,
watermarks, cover page, table of contents. None of that is "swap the
rendering engine" -- it's "add more visual/branding elements to the
same renderer over time." A `PDFRenderer` strategy interface would
have added indirection to solve a problem nobody asked for (multiple
PDF backends), while leaving the real extensibility need (more
branding knobs, more section content types) no easier to satisfy.

So this module depends directly on one well-established library,
**reportlab** (already available in this environment, `4.5.1`) --
the same way `ExportService` depends directly on `pandas`/`openpyxl`
rather than hiding them behind an interface -- and channels its two
*actual* extension axes into purpose-built seams instead:

1. **Branding/presentation knobs** (the ticket's explicit future list)
   are every field of `PDFBrandingConfig`, threaded through every
   rendering step. Turning on a watermark, changing the corporate
   color, or supplying a logo is a config change, never a code change.
2. **New section content types** (e.g. a future `RecommendationBatch`
   or `risk_analysis` object once those are added to `Report`) are
   handled by `register_content_renderer()` -- the same registry
   pattern already used by `KPIEngine.register`,
   `ExportService.register`, and
   `ReportingService.register_section_builder`. Adding a renderer for
   a new content type never requires touching `PDFGeneratorService`.

Every future-compatibility item named in the ticket is wired as a
**real, working mechanism today**, not a placeholder comment, so using
it later is configuration, not a redesign:

| Future item | How it's already wired |
|---|---|
| Cover page | `PDFBrandingConfig.show_cover_page` (default `True`) -- title, period, audience, timestamp |
| Corporate colors | `primary_color` / `accent_color` hex fields, used for headings and table styling |
| Headers/footers, page numbers | `show_page_numbers` + `footer_text`, drawn via reportlab's `onFirstPage`/`onLaterPages` canvas callback |
| Watermark | `watermark_text` -- stamped diagonally across every page when set |
| Table of contents | `show_table_of_contents` -- a real, two-pass (`multiBuild`) ToC with accurate page numbers, not just a title list |
| Company logo | `logo_path` -- rendered on the cover page if the file is readable; silently skipped otherwise (a bad logo asset never breaks a report) |

### Content rendering

`ReportSection.content` varies by section (`dict[str, KPIResult]` for
KPI summaries, `dict[str, float]` for regional/product summaries, a
`BusinessInsights` object for insights). Rather than branching on
`section.key` (which would break the moment a new report type reuses
an existing content shape under a new key), the service dispatches on
`type(section.content)`:

- `dict` -> inspects the first value: `KPIResult` values render as a
  "KPI / Value" table using each result's own `.formatted` string
  (never recomputed); anything else renders as a "Name / Revenue"
  table, sorted by value, formatted with the shared
  `utils/formatting.format_currency` -- pure presentation, not a
  calculation.
- `BusinessInsights` -> a "Metric / Value" table covering every field,
  including product/region insights only when
  `product_insights_available`/`region_insights_available` is `True`.
- Anything else (including any future content type with no registered
  renderer) -> falls back to a plain-text rendering of `str(content)`,
  so an unrecognized future section degrades gracefully instead of
  breaking the whole report.

KPI icons (`KPI_ICONS`, emoji characters) are deliberately **not**
printed: reportlab's base-14 PDF fonts have no emoji glyphs, and
printing them renders as broken "tofu" boxes rather than a clean icon.

### Error handling

- `InvalidReportInputError` / `InvalidBrandingConfigError` reject the
  wrong input type before any rendering starts.
- An **empty report** (`report.is_empty()`) is not an error: it
  produces a valid, cover-paged PDF with a "No data is available for
  this report" placeholder, mirroring how the Reporting Service treats
  missing optional data as an omission, not a failure.
- `PDFRenderingError` wraps any unexpected failure while rendering one
  section (naming the section's key) or the document as a whole
  (`section_key="document"`), so a bug in a custom-registered renderer
  is never silently swallowed.

## Confirmation against the agreed architecture

- [x] `services/pdf_generator_service.py` created; only
      `requirements.txt` (adding `reportlab`) was also touched -- no
      other production file modified.
- [x] Receives an already-assembled `Report`; never modifies or
      recalculates its content -- confirmed by inspection: every
      renderer reads `section.content`/`report.metadata` and only
      formats it for display.
- [x] Preserves report structure and section order: sections are
      rendered in `report.sections` order (already assigned by
      `ReportingService`), unchanged here.
- [x] Returns a `PDFResult` (bytes + MIME type + page count) usable by
      a future Executive Report Center, Notification/Email Service, or
      download button -- the same shape as `ExportResult`.
- [x] Does not read uploaded files, calculate KPIs, generate business
      insights, generate AI recommendations, assemble reports, export
      CSV/Excel/JSON, or send emails -- confirmed by inspection: no
      imports from `utils/data_loader.py`, `utils/calculations.py`,
      `utils/kpi_engine.py`'s calculation functions,
      `utils/insights.py`'s `generate_business_insights`,
      `services/ai_recommendation_service.py`, or
      `services/export_service.py`; no email code anywhere in the module.
- [x] Single Responsibility Principle (PDF rendering only), clean
      architecture (`services/` depends on `services.reporting_service`
      and `utils/` value objects only, never the reverse), independent
      of the UI (no Streamlit import), strong type hints throughout,
      thorough docstrings.
- [x] Validates input types (`InvalidReportInputError`,
      `InvalidBrandingConfigError`); handles empty reports gracefully
      (valid placeholder PDF, not an exception); meaningful, typed
      custom exceptions (three, all subclassing
      `PDFGeneratorServiceError`).
- [x] Extensible for future branding (a config object, not a redesign)
      and future section content types (a registry, not a redesign) --
      both verified in tests without modifying `PDFGeneratorService`.

## Automated tests

`tests/test_pdf_generator_service.py` (21 tests) builds its `Report`
input from the real `services.reporting_service` /
`utils.kpi_engine` / `utils.insights` modules (with pandas), and
inspects the *actual rendered PDF text* via `pdfplumber` rather than
only checking "no exception was raised". Covers: valid PDF byte output
and MIME type, cover page content (title/period/audience), section
order, KPI/insights/regional/product content correctness (including
that raw emoji icons are never printed), footer and page numbers,
custom branding (company name, footer text), disabling the cover page
and page numbers, watermark text appearing on every page, a working
table of contents with real page numbers, empty-report and
empty-section-content graceful handling, all input-validation error
paths, registering a renderer for a brand-new content type end to end,
an unregistered content type falling back to plain text instead of
raising, a renderer exception being wrapped in `PDFRenderingError`, and
the shared instance. Verified via `python3 -m py_compile` across the
whole project plus running the *actual* test file (not a rewritten
stand-in) through a minimal pytest-compatible shim implementing
`@pytest.fixture` and `pytest.raises` -- real `pytest` isn't installed
in this offline sandbox -- all 21 passed.

## Manual test cases

| # | Steps | Expected result |
|---|-------|------------------|
| 1 | Build an Executive `Report` from real KPI/insights/regional/product data, call `generate_pdf(report)` | Returns a `PDFResult` with `content` starting `%PDF`, `mime_type="application/pdf"`, `page_count >= 1`. |
| 2 | Open the generated PDF | Cover page shows company name, report title, period label, and "Prepared for:" audience; body pages show KPI Summary, Business Insights, Product Summary, Regional Summary in that order, each as a clean two-column table with no broken icon glyphs. |
| 3 | Call `generate_pdf(report, branding=PDFBrandingConfig(show_cover_page=False))` | PDF has one fewer page; content starts directly with the first section, no "Prepared for" text. |
| 4 | Call `generate_pdf(report, branding=PDFBrandingConfig(watermark_text="DRAFT"))` | Every page shows a diagonal, semi-transparent "DRAFT" watermark. |
| 5 | Call `generate_pdf(report, branding=PDFBrandingConfig(show_table_of_contents=True))` | A "Table of Contents" page lists every section title with its correct starting page number. |
| 6 | Call `generate_pdf(report, branding=PDFBrandingConfig(company_name="Acme Retail", footer_text="Acme Confidential"))` | Cover page shows "Acme Retail"; every page's footer reads "Acme Confidential" instead of the default. |
| 7 | Generate a report where every optional section is absent (`report.is_empty()` is `True`), call `generate_pdf` | Returns a valid PDF (no exception) containing "No data is available for this report." |
| 8 | Call `generate_pdf({"not": "a report"})` or `generate_pdf(report, branding="not a config")` | Raise `InvalidReportInputError` / `InvalidBrandingConfigError` respectively, naming the wrong type received. |
| 9 | Register a new content-type renderer via `register_content_renderer(MyType, my_renderer)`, build a `Report` with a section whose `content` is a `MyType` instance, call `generate_pdf` | The custom renderer's output appears in the PDF -- no change to `PDFGeneratorService` was needed. |
| 10 | Build a `Report` with a section whose content has no registered renderer, call `generate_pdf` | Succeeds; the section's title and a plain-text rendering of its content both appear (graceful fallback, not an error). |
