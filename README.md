# NovaMart -- Sales Intelligence Dashboard

A production-ready Streamlit foundation for NovaMart's internal sales
intelligence dashboard, built with clean architecture, modular code,
and a professional blue business theme.

## Features

- Home page with company branding, KPI section, and chart section
- Sidebar navigation across Dashboard, Sales, Products, Customers, and Reports
- Placeholder pages ready for data integration
- Clean separation of UI, business logic, configuration, and data access
- Reusable components (sidebar, header, footer)
- Unit-tested calculation and formatting utilities

## Requirements

- Python 3.14+
- pip

## Getting Started

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
streamlit run app.py
```

The app will open at `http://localhost:8501`.

## Project Structure

```
NovaMart/
├── app.py                 # Home page / Streamlit entry point
├── requirements.txt
├── README.md
├── .gitignore
│
├── assets/                # Images, logos, static files
├── components/            # Reusable UI components (sidebar, header, footer)
├── config/                # Settings and constants (no business logic)
├── data/                  # Sample / local data files
├── docs/                  # Architecture and design docs
├── pages/                 # Dashboard, Sales, Products, Customers, Reports
├── tests/                 # Unit tests for utils/
└── utils/                 # Business logic: data loading, calculations, formatting, helpers
```

See `docs/architecture.md` for a full description of the layering and
data flow.

## Running Tests

```bash
pytest tests/
```

## Extending the App

- **New page**: add a module to `pages/`, register it in
  `config/constants.py` (`NAV_ITEMS`).
- **New data source**: add a loader function to `utils/data_loader.py`.
- **New metric**: add a pure function to `utils/calculations.py` with a
  matching test in `tests/`.

## Theme

NovaMart uses a professional blue business theme, configured in
`.streamlit/config.toml` and `config/settings.py` (`THEME_COLORS`).
