"""Unit tests for utils/helpers.py."""

from __future__ import annotations

from datetime import datetime

import pytest

from utils.helpers import (
    chunk_list,
    generate_sample_dataframe,
    get_greeting_by_time,
    safe_divide,
)


def test_get_greeting_by_time_morning() -> None:
    assert get_greeting_by_time(datetime(2026, 7, 2, 9, 0)) == "Good morning"


def test_get_greeting_by_time_afternoon() -> None:
    assert get_greeting_by_time(datetime(2026, 7, 2, 14, 0)) == "Good afternoon"


def test_get_greeting_by_time_evening() -> None:
    assert get_greeting_by_time(datetime(2026, 7, 2, 20, 0)) == "Good evening"


def test_safe_divide_normal() -> None:
    assert safe_divide(10, 2) == 5.0


def test_safe_divide_by_zero() -> None:
    assert safe_divide(10, 0) == 0.0
    assert safe_divide(10, 0, default=-1) == -1


def test_generate_sample_dataframe_shape() -> None:
    df = generate_sample_dataframe(rows=10)
    assert len(df) == 10
    assert list(df.columns) == ["date", "revenue", "orders"]


def test_chunk_list() -> None:
    assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_list_invalid_size() -> None:
    with pytest.raises(ValueError):
        chunk_list([1, 2, 3], 0)
