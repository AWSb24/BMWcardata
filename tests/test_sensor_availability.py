"""Tests for the 'do not create unavailable entities' filter."""

from __future__ import annotations

import pytest

from custom_components.bmw_cardata.sensor import _has_usable_value


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_unavailable_values_are_filtered(value) -> None:
    """None and empty/whitespace strings must be treated as unavailable."""
    assert _has_usable_value(value) is False


@pytest.mark.parametrize("value", [0, 0.0, False, "0", "off", 42, -1, 3.14, "ok"])
def test_valid_values_are_kept(value) -> None:
    """Falsy-but-valid values (0, 0.0, False) and real values must be kept."""
    assert _has_usable_value(value) is True
