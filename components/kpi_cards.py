"""Reusable KPI card grid component.

Renders a row (or grid) of KPI metric cards from the
:class:`~utils.kpi_engine.KPIResult` objects produced by
``utils/kpi_engine.py``. Like the rest of ``components/``, this module
is UI-only: it lays out ``st.metric`` widgets and never computes a KPI
value itself.
"""

from __future__ import annotations

import streamlit as st

from utils.kpi_engine import KPIResult


def render_kpi_cards(results: dict[str, KPIResult], columns_per_row: int = 3) -> None:
    """Render KPI results as a grid of bordered metric cards.

    Uses the same ``st.metric`` inside ``st.container(border=True)``
    styling already established on the Home page and in the Upload
    Center's data preview, so KPI cards look consistent everywhere in
    the app.

    Args:
        results: KPI results keyed by KPI key, as returned by
            :meth:`~utils.kpi_engine.KPIEngine.calculate_all`.
        columns_per_row: How many cards to place per row before
            wrapping to a new row.
    """
    items = list(results.values())
    if not items:
        st.info("No KPIs available yet.", icon="📄")
        return

    for row_start in range(0, len(items), columns_per_row):
        row_items = items[row_start : row_start + columns_per_row]
        columns = st.columns(columns_per_row)
        for column, kpi in zip(columns, row_items):
            with column:
                _render_single_kpi_card(kpi)


def _render_single_kpi_card(kpi: KPIResult) -> None:
    """Render one KPI as a bordered metric card.

    Args:
        kpi: The KPI result to display.
    """
    with st.container(border=True):
        label = f"{kpi.icon} {kpi.label}".strip()
        st.metric(label=label, value=kpi.formatted, help=kpi.help_text or None)
