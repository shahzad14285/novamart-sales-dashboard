# Upload Center

The Upload Center lets a user drag-and-drop (or browse for) a CSV or
Excel file, have it validated and cleaned automatically, and preview
the result -- all without leaving the Dashboard page.

## Architecture

The Upload Center follows the same layered architecture as the rest of
NovaMart: UI and business logic are kept in separate modules, and
`app.py` / `pages/*.py` never contain data-loading or validation code
directly.

```
pages/1_Dashboard.py            (calls the component, nothing else)
        |
        v
components/upload_center.py     (UI only: widgets, layout, error display)
        |
        v
utils/data_loader.py            (business logic: read, validate, clean)
        |
        v
utils/exceptions.py             (domain exceptions, no Streamlit/pandas)
        |
        v
utils/formatting.py             (presentation-only number formatting)
```

- **`components/upload_center.py`** renders the file picker, the
  success/info/error messages, and the preview -- and nothing else. It
  never calls `pandas.read_csv` / `pandas.read_excel` directly.
- **`utils/data_loader.py`** owns all reading, validating, and cleaning
  logic through the existing `DataLoader` class, extended with a
  `load_uploaded_file()` method for in-memory Streamlit uploads.
- **`utils/exceptions.py`** defines the error types the component
  catches to turn failures into friendly messages instead of
  tracebacks.
- **`utils/formatting.py`** provides `format_integer()` and
  `format_file_size()`, used to display the preview's summary stats.

This means the Upload Center adds zero new business logic of its own:
it is a thin, reusable UI wrapper around the `DataLoader` engine
introduced previously.

## Component Responsibilities

### `components/upload_center.py`

| Function | Responsibility |
|---|---|
| `render_upload_center()` | Public entry point. Orchestrates the section: header, file picker, validation, preview. Returns the cleaned `DataFrame` (or `None`). |
| `_render_header()` | Renders the title and description text. |
| `_render_file_picker()` | Renders the `st.file_uploader` widget (drag-and-drop + browse), restricted to `.csv` / `.xlsx`. |
| `_load_and_validate()` | Calls `DataLoader.load_uploaded_file()` and converts any `DataLoaderError` into an `st.error()` message. |
| `_render_data_preview()` | Renders the 4 summary-stat cards and the first-10-rows table. |

### `utils/data_loader.py`

`DataLoader.load_uploaded_file(uploaded_file, sheet_name=0)` is the
method the Upload Center calls. It mirrors `load_csv()` / `load_excel()`
but reads directly from the in-memory buffer Streamlit provides instead
of a filesystem path, so no file needs to be saved to disk first.

It deliberately is **not** wrapped in `st.cache_data`: Streamlit
creates a new uploaded-file object on every upload (even re-uploading a
file with the same name), so there is no stable cache key, and caching
here risks showing stale data from a previous upload.

The same instance-level configuration (`required_columns`,
`date_columns`, `fill_numeric`, `fill_text`) applies to uploads as it
does to disk-based loads, and the same shared `_finalize()` helper
performs column normalization, required-column validation, date
conversion, and missing-value handling for both code paths -- so
uploaded files and on-disk files are held to identical standards.

## Validation Workflow

1. **User selects/drops a file.** `st.file_uploader` returns either
   `None` (nothing uploaded) or an uploaded-file object with a `.name`
   attribute and file-like `read()` behavior.
2. **No file yet** -> the component shows an informational
   `st.info()` message and returns `None`. Nothing downstream runs.
3. **File present** -> the filename is shown via `st.success()`, then
   handed to `DataLoader.load_uploaded_file()`.
4. Inside the loader:
   - **Missing file** -> `NoFileUploadedError` (defensive; the
     component already checks for `None`, but the loader guards
     against being called directly with no file).
   - **Unsupported extension** (anything but `.csv` / `.xlsx` / `.xls`)
     -> `UnsupportedFileTypeError`.
   - **Unparseable file** (corrupted, wrong format, etc.) -> pandas'
     original exception is wrapped in `DataReadError`.
   - **Missing required columns** (e.g. no `date`, `revenue`, or
     `orders` column, for the default sales loader) -> `MissingColumnsError`.
   - **Success** -> column names are normalized, date columns are
     converted to `datetime` (bad values become `NaT`, never a
     fabricated date), and missing numeric/text cells are filled with
     configurable defaults (`0.0` / `"Unknown"` for the default sales
     loader).
5. **Any exception above** is a subclass of `DataLoaderError`. The
   component catches that single base type, shows `exc`'s
   user-friendly message via `st.error()`, and returns `None` --
   the rest of the page keeps rendering normally.
6. **On success**, the component renders the preview: total rows,
   total columns, missing-value count, memory usage, and the first 10
   rows via `st.dataframe()`.

## Future Improvements

- **Persist uploads**: optionally save validated uploads into `data/`
  (with user confirmation) so they survive a page refresh, instead of
  living only in the current Streamlit session.
- **Column mapping UI**: let users map their own column names to the
  expected schema (e.g. "Order Date" -> `date`) instead of requiring an
  exact match.
- **Multi-sheet Excel support**: currently a single `sheet_name` is
  read; a sheet picker could be shown for multi-sheet workbooks instead
  of defaulting to the first one.
- **Downstream wiring**: once uploaded, the cleaned DataFrame could
  replace `load_sales_data()`'s source for the current session, so KPIs
  and charts on the Home page reflect the uploaded file.
- **File size / row limits**: add explicit guardrails (e.g. reject
  files over N MB or N rows) with a friendly message, to keep the app
  responsive on very large uploads.
- **Upload history**: keep a small session-scoped list of previously
  uploaded files/timestamps for quick re-selection.
