"""Tests for CarDataStore timestamp handling (mixed-mode 'newest wins')."""

from __future__ import annotations

from custom_components.bmw_cardata import CarDataStore


def test_newest_timestamp_wins() -> None:
    store = CarDataStore()
    assert store.update("VIN", "k", "first", None, timestamp=100.0) is True
    # Older timestamp must be ignored.
    assert store.update("VIN", "k", "older", None, timestamp=50.0) is False
    assert store.get("VIN", "k") == ("first", None)
    # Newer timestamp wins.
    assert store.update("VIN", "k", "newer", None, timestamp=150.0) is True
    assert store.get("VIN", "k") == ("newer", None)


def test_missing_timestamp_always_overwrites() -> None:
    store = CarDataStore()
    store.update("VIN", "k", "a")
    store.update("VIN", "k", "b")
    assert store.get("VIN", "k") == ("b", None)


def test_timestamped_value_then_untimestamped_overwrites() -> None:
    # A stream value without a timestamp still overwrites (legacy behavior).
    store = CarDataStore()
    store.update("VIN", "k", "api", None, timestamp=100.0)
    assert store.update("VIN", "k", "stream", None) is True
    assert store.get("VIN", "k") == ("stream", None)
