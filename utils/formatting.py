"""Formatting utilities for presenting numbers, currency, and dates.

Kept free of Streamlit imports so these functions can be unit tested
in isolation and reused by any presentation layer.
"""

from __future__ import annotations

from datetime import datetime

from config.constants import DEFAULT_CURRENCY_SYMBOL, DEFAULT_DISPLAY_DATE_FORMAT


def format_currency(value: float, symbol: str = DEFAULT_CURRENCY_SYMBOL, decimals: int = 2) -> str:
    """Format a numeric value as a currency string.

    Args:
        value: The numeric amount to format.
        symbol: Currency symbol to prefix. Defaults to the app's
            configured currency symbol.
        decimals: Number of decimal places to display.

    Returns:
        A formatted currency string, e.g. ``"$12,345.67"``.
    """
    return f"{symbol}{value:,.{decimals}f}"


def format_percentage(value: float, decimals: int = 1, signed: bool = True) -> str:
    """Format a fractional or whole-number value as a percentage string.

    Args:
        value: The percentage value (e.g. 12.5 for 12.5%).
        decimals: Number of decimal places to display.
        signed: Whether to prefix positive values with a "+" sign, which
            is useful for delta/growth indicators.

    Returns:
        A formatted percentage string, e.g. ``"+12.5%"`` or ``"-3.2%"``.
    """
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_number_compact(value: float) -> str:
    """Format a large number in a compact, human-readable form.

    Examples: ``1200`` -> ``"1.2K"``, ``2500000`` -> ``"2.5M"``.

    Args:
        value: The numeric value to compact.

    Returns:
        A compacted string representation of the number.
    """
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"


def format_date(value: datetime, date_format: str = DEFAULT_DISPLAY_DATE_FORMAT) -> str:
    """Format a datetime object into a display-friendly string.

    Args:
        value: The datetime (or date) object to format.
        date_format: A ``strftime``-compatible format string.

    Returns:
        The formatted date string.
    """
    return value.strftime(date_format)


def format_integer(value: int) -> str:
    """Format an integer with thousands separators.

    Intended for exact counts (rows, columns, missing values) where a
    compacted "1.2K" form (see :func:`format_number_compact`) would be
    less precise than the user likely wants.

    Args:
        value: The integer to format.

    Returns:
        A formatted string, e.g. ``12345`` -> ``"12,345"``.
    """
    return f"{value:,}"


def format_file_size(num_bytes: int) -> str:
    """Format a byte count into a human-readable size string.

    Args:
        num_bytes: Size in bytes (e.g. from ``DataFrame.memory_usage``).

    Returns:
        A formatted string, e.g. ``500`` -> ``"500 B"``,
        ``2048`` -> ``"2.0 KB"``, ``5_242_880`` -> ``"5.0 MB"``.
    """
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"
