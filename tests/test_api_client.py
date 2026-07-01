"""Tests for the REST API client helpers and mode/scope logic."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.bmw_cardata.api_client import (
    descriptor_to_key,
    iso_to_epoch,
    key_to_descriptor,
    parse_telematic_response,
)
from custom_components.bmw_cardata.api_coordinator import resolve_interval_minutes
from custom_components.bmw_cardata.const import (
    API_POLL_MIN_MINUTES,
    MODE_API,
    MODE_MIXED,
    MODE_MQTT,
    scopes_for_mode,
)


def test_descriptor_key_roundtrip() -> None:
    key = "vehicle_drivetrain_electricEngine_charging_status"
    descriptor = "vehicle.drivetrain.electricEngine.charging.status"
    assert key_to_descriptor(key) == descriptor
    assert descriptor_to_key(descriptor) == key


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("not-a-date", None),
        ("2025-07-28T05:16:53.000Z", 1753679813.0),
    ],
)
def test_iso_to_epoch(value, expected) -> None:
    assert iso_to_epoch(value) == expected


def test_parse_telematic_response_list_and_wrapped() -> None:
    item = {
        "name": "vehicle.cabin.x.longitude",
        "value": "9.49",
        "unit": "degrees",
        "timestamp": "2025-07-28T05:16:53.000Z",
    }
    expected = [("vehicle_cabin_x_longitude", "9.49", "degrees", 1753679813.0)]
    # Bare list and object-wrapped list are both accepted.
    assert parse_telematic_response([item]) == expected
    assert parse_telematic_response({"telematicData": [item]}) == expected


def test_parse_telematic_skips_items_without_name() -> None:
    rows = parse_telematic_response([{"value": "1"}, {"name": "a.b", "value": 2}])
    assert rows == [("a_b", 2, None, None)]


def test_scopes_for_mode() -> None:
    assert "cardata:streaming:read" in scopes_for_mode(MODE_MQTT)
    assert "cardata:api:read" not in scopes_for_mode(MODE_MQTT)
    assert "cardata:api:read" in scopes_for_mode(MODE_API)
    assert "cardata:streaming:read" not in scopes_for_mode(MODE_API)
    mixed = scopes_for_mode(MODE_MIXED)
    assert "cardata:api:read" in mixed and "cardata:streaming:read" in mixed


def test_interval_is_floored_to_api_minimum() -> None:
    entry = SimpleNamespace(options={"api_poll_interval": 1}, data={})
    assert resolve_interval_minutes(entry) == API_POLL_MIN_MINUTES
    entry = SimpleNamespace(options={}, data={"api_poll_interval": 120})
    assert resolve_interval_minutes(entry) == 120
