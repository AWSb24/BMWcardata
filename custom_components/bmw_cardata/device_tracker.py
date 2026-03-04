"""BMW CarData device tracker for vehicle position on map."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN, SIGNAL_CARDATA_UPDATE

KEY_LATITUDE = "vehicle_cabin_infotainment_navigation_currentLocation_latitude"
KEY_LONGITUDE = "vehicle_cabin_infotainment_navigation_currentLocation_longitude"

_LOGGER = logging.getLogger(__name__)


def _parse_float(value: Any) -> float | None:
    """Parse value to float, return None if invalid."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BMW CarData device tracker for vehicle position."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not entry_data:
        _LOGGER.warning("BMW CarData: No entry_data for entry %s", config_entry.entry_id)
        return
    store = entry_data.get("store")
    if not store:
        return

    tracker = BMWCarDataDeviceTracker(hass, config_entry, entry_data)
    async_add_entities([tracker])


class BMWCarDataDeviceTracker(TrackerEntity):
    """Device tracker for BMW vehicle position from CarData stream."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_source_type = SourceType.GPS
    _attr_translation_key = "vehicle"

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        entry_data: dict,
    ) -> None:
        self.hass = hass
        self._config_entry = config_entry
        self._entry_data = entry_data
        self._store = entry_data["store"]
        self._attr_name = "Vehicle"
        self._attr_unique_id = f"{config_entry.entry_id}_location"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": config_entry.title or "BMW CarData",
            "manufacturer": "BMW",
        }
        self._update_position()

    def _update_position(self) -> None:
        """Update latitude/longitude from store."""
        lat_result = self._store.get_first_value_for_key(KEY_LATITUDE)
        lon_result = self._store.get_first_value_for_key(KEY_LONGITUDE)
        lat = _parse_float(lat_result[1]) if lat_result else None
        lon = _parse_float(lon_result[1]) if lon_result else None
        self._attr_latitude = lat
        self._attr_longitude = lon

    @callback
    def _on_cardata_update(self, entry_id: str, vin: str) -> None:
        if entry_id != self._config_entry.entry_id:
            return
        self._update_position()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        try:
            trans = await async_get_translations(
                self.hass,
                self.hass.config.language or "en",
                "entity",
                [DOMAIN],
            )
            if trans:
                key = f"component.{DOMAIN}.entity.device_tracker.{self._attr_translation_key}.name"
                if name := trans.get(key):
                    self._attr_name = name
        except Exception:
            pass
        self._update_position()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CARDATA_UPDATE, self._on_cardata_update
            )
        )
