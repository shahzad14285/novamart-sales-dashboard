"""Unit tests for utils/formatting.py."""

from __future__ import annotations

from datetime import datetime

from utils.formatting import (
    format_currency,
    format_date,
    format_file_size,
    format_integer,
    format_number_compact,
    format_percentage,
)


def test_format_currency_default() -> None:
    assert format_currency(1234.5) == "$1,234.50"


def test_format_currency_custom_symbol() -> None:
    assert format_currency(10, symbol="€", decimals=0) == "€10"


def test_format_percentage_positive_signed() -> None:
    assert format_percentage(12.34) == "+12.3%"


def test_format_percentage_negative() -> None:
    assert format_percentage(-5.0) == "-5.0%"


def test_format_percentage_unsigned() -> None:
    assert format_percentage(12.34, signed=False) == "12.3%"


def test_format_number_compact_thousands() -> None:
    assert format_number_compact(1200) == "1.2K"


def test_format_number_compact_millions() -> None:
    assert format_number_compact(2_500_000) == "2.5M"


def test_format_number_compact_small() -> None:
    assert format_number_compact(500) == "500"


def test_format_date() -> None:
    dt = datetime(2026, 7, 2)
    assert format_date(dt) == "Jul 02, 2026"


def test_format_integer_thousands_separator() -> None:
    assert format_integer(12345) == "12,345"


def test_format_integer_small() -> None:
    assert format_integer(7) == "7"


def test_format_file_size_bytes() -> None:
    assert format_file_size(500) == "500 B"


def test_format_file_size_kilobytes() -> None:
    assert format_file_size(2048) == "2.0 KB"


def test_format_file_size_megabytes() -> None:
    assert format_file_size(5_242_880) == "5.0 MB"


def test_format_file_size_gigabytes() -> None:
    assert format_file_size(3 * 1024**3) == "3.0 GB"
