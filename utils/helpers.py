"""Generic, reusable helper functions with no domain-specific logic.

These helpers are intentionally small and dependency-light so they can
be reused by any layer of the application (utils, components, pages).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd


def get_greeting_by_time(now: datetime | None = None) -> str:
    """Return a time-appropriate greeting string.

    Args:
        now: The datetime to base the greeting on. Defaults to the
            current local time when not provided.

    Returns:
        A greeting such as "Good morning", "Good afternoon", or
        "Good evening".
    """
    current_hour = (now or datetime.now()).hour
    if current_hour < 12:
        return "Good morning"
    if current_hour < 18:
        return "Good afternoon"
    return "Good evening"


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide two numbers, guarding against division by zero.

    Args:
        numerator: The dividend.
        denominator: The divisor.
        default: Value returned when ``denominator`` is zero.

    Returns:
        The division result, or ``default`` if the denominator is zero.
    """
    if not denominator:
        return default
    return numerator / denominator


def generate_sample_dataframe(rows: int = 30, seed: int = 42) -> pd.DataFrame:
    """Generate a deterministic sample sales DataFrame for placeholders.

    This is used by pages/components that need something visual before
    real data pipelines are wired in. It is not meant for production
    reporting.

    Args:
        rows: Number of daily records to generate.
        seed: Random seed for reproducibility.

    Returns:
        A DataFrame with columns: ``date``, ``revenue``, ``orders``.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=rows, freq="D")
    revenue = rng.normal(loc=12000, scale=2500, size=rows).clip(min=1000)
    orders = rng.integers(low=80, high=260, size=rows)

    return pd.DataFrame({"date": dates, "revenue": revenue.round(2), "orders": orders})


def chunk_list(items: list, size: int) -> list[list]:
    """Split a list into equally sized chunks.

    Args:
        items: The list to split.
        size: Maximum size of each chunk.

    Returns:
        A list of sub-lists, each with at most ``size`` elements.
    """
    if size <= 0:
        raise ValueError("size must be a positive integer")
    return [items[i : i + size] for i in range(0, len(items), size)]
