"""Application-wide settings for the NovaMart Sales Intelligence Dashboard.

Centralizes page configuration, theme colors, and filesystem paths so
that any module needing these values imports them from a single source
of truth instead of hard-coding them.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Filesystem paths
# --------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
ASSETS_DIR: Path = BASE_DIR / "assets"
SAMPLE_SALES_CSV: Path = DATA_DIR / "sample_sales.csv"

# --------------------------------------------------------------------------
# Streamlit page configuration
# --------------------------------------------------------------------------
APP_NAME = "NovaMart"
APP_ICON = "🛒"
PAGE_LAYOUT = "wide"
SIDEBAR_STATE = "expanded"

PAGE_CONFIG: dict[str, object] = {
    "page_title": f"{APP_NAME} | Sales Intelligence Dashboard",
    "page_icon": APP_ICON,
    "layout": PAGE_LAYOUT,
    "initial_sidebar_state": SIDEBAR_STATE,
}

# --------------------------------------------------------------------------
# Professional blue business theme
# --------------------------------------------------------------------------
# Mirrors the palette defined in .streamlit/config.toml. Kept here as well
# so Python components (cards, charts) can reference the same colors.
THEME_COLORS: dict[str, str] = {
    "primary": "#1565C0",       # Primary brand blue
    "primary_dark": "#0D47A1",  # Deep blue for headers / emphasis
    "primary_light": "#42A5F5", # Light blue for accents / hover states
    "background": "#FFFFFF",
    "secondary_background": "#F0F4F8",
    "text": "#1A1A2E",
    "muted_text": "#5A6472",
    "success": "#2E7D32",
    "warning": "#ED6C02",
    "danger": "#C62828",
    "border": "#DCE3EA",
}

# Plotly chart color sequence, matched to the theme.
CHART_COLOR_SEQUENCE: list[str] = [
    THEME_COLORS["primary"],
    THEME_COLORS["primary_light"],
    THEME_COLORS["primary_dark"],
    "#90CAF9",
    "#1E88E5",
]
