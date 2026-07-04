"""Shared empty-state component for the NovaMart dashboard.

A single, consistently styled way to say "there's nothing to show
yet" -- no file uploaded, no data for this view, an optional column
isn't in the dataset -- instead of every module rolling its own
``st.info``/``st.caption`` markup. This component is purely
presentational: callers still decide *when* to show an empty state and
*what* the message says; nothing about data loading, filtering, or
calculations changes.
"""

from __future__ import annotations

import streamlit as st


def render_empty_state(message: str, icon: str = "📄") -> None:
    """Render a centered, muted "empty state" panel.

    Args:
        message: The guidance text to show (e.g. "Upload a dataset to
            see your KPIs calculated live.").
        icon: A single emoji shown above the message.
    """
    st.markdown(
        f"""
        <div class="nm-empty-state">
            <div class="nm-empty-state-icon">{icon}</div>
            <p class="nm-empty-state-text">{message}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
