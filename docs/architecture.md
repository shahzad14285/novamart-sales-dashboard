# NovaMart Architecture

## Overview

NovaMart follows a clean, layered architecture that separates UI from
business logic so the app can scale as new pages and data sources are
added.

## Layers

**config/** -- Static configuration only (settings, constants). No
Streamlit or business logic imports. Everything else reads from here
instead of hard-coding values.

**utils/** -- Framework-agnostic business logic:
- `data_loader.py` -- the only module that reads data from disk/APIs.
- `calculations.py` -- pure functions for KPIs and metrics (pandas in,
  numbers out). Fully unit-testable without Streamlit.
- `formatting.py` -- number/date/currency presentation helpers.
- `helpers.py` -- small generic utilities with no domain logic.

**components/** -- Reusable Streamlit UI building blocks (`sidebar.py`,
`header.py`, `footer.py`). Render UI only; delegate any calculation to
`utils/`.

**pages/** -- One file per navigable page (Dashboard, Sales, Products,
Customers, Reports). Each page composes `components/` + `utils/` and
contains no business logic of its own.

**app.py** -- The Home page and Streamlit entry point. Thin
composition root: page config, layout, and calls into the layers above.

## Data Flow

```
data/ (CSV/API) -> utils/data_loader.py -> utils/calculations.py -> pages/*.py, app.py -> components/*.py (render)
```

## Extending the App

- New page: add a module to `pages/`, update `config/constants.py`
  `NAV_ITEMS`, and follow the pattern in an existing page.
- New data source: add a loader function to `utils/data_loader.py`.
- New metric: add a pure function to `utils/calculations.py` and cover
  it with a test in `tests/`.
