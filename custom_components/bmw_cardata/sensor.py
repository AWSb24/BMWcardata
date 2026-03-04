"""BMW CarData dynamic sensors."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN, SIGNAL_CARDATA_UPDATE, SIGNAL_CONNECTION_CHANGED
from .descriptors import KNOWN_CARDATA_KEYS

# Normalized set so we skip VIN-specific entities when the key matches a known key (any casing)
KNOWN_CARDATA_KEYS_LOWER = {k.lower() for k in KNOWN_CARDATA_KEYS}

_LOGGER = logging.getLogger(__name__)

# Use string literals for device_class/state_class for compatibility across HA versions
KEY_DEVICE_CLASS: dict[str, str] = {
    "fuelPercentage": "percentage",
    "range_km": "distance",
    "vehicle_cabin_infotainment_navigation_currentlocation_latitude": "latitude",
    "vehicle_cabin_infotainment_navigation_currentlocation_longitude": "longitude",
}
KEY_STATE_CLASS: dict[str, str] = {
    "fuelPercentage": "measurement",
    "range_km": "measurement",
}
# Lookup by normalized key (entity keys may be lowercase from store)
KEY_DEVICE_CLASS_NORMALIZED = {k.lower(): v for k, v in KEY_DEVICE_CLASS.items()}
KEY_STATE_CLASS_NORMALIZED = {k.lower(): v for k, v in KEY_STATE_CLASS.items()}


def _entity_translation_key(platform: str, translation_key: str) -> str:
    """Build the flat translation key used by async_get_translations."""
    return f"component.{DOMAIN}.entity.{platform}.{translation_key}.name"


async def _resolve_entity_name(
    hass: HomeAssistant, platform: str, translation_key: str, fallback: str
) -> str:
    """Resolve translated entity name from integration translations."""
    try:
        trans = await async_get_translations(
            hass, hass.config.language or "en", "entity", [DOMAIN]
        )
        if trans:
            name = trans.get(_entity_translation_key(platform, translation_key))
            if name:
                return name
    except Exception:
        pass
    return fallback


def _key_to_display_name(key: str) -> str:
    """Convert key to title case, split camelCase, and remove consecutive duplicate words."""
    # Split camelCase: antiTheftAlarmSystem -> anti theft alarm system (then title)
    parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", key).replace("_", " ").split()
    if not parts:
        return key
    titled = [p.title() for p in parts]
    result = [titled[0]]
    for w in titled[1:]:
        if w.lower() != result[-1].lower():
            result.append(w)
    return " ".join(result)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BMW CarData sensors from the store and add new ones when data arrives."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not entry_data:
        _LOGGER.warning("BMW CarData: No entry_data for entry %s", config_entry.entry_id)
        return
    store = entry_data.get("store")
    if not store:
        return

    # Always add the status sensor first
    status_sensor = BMWCarDataStatusSensor(hass, config_entry, entry_data)
    async_add_entities([status_sensor])

    # VIN sensor - shows the current vehicle VIN once data arrives
    vin_sensor = BMWCarDataVINSensor(hass, config_entry, entry_data)
    async_add_entities([vin_sensor])

    # Pre-create entities for all known CarData descriptors (200+ parameters)
    # dict.fromkeys preserves order, dedupes (descriptors may have duplicates)
    for key in dict.fromkeys(KNOWN_CARDATA_KEYS):
        entity = BMWCarDataSensor(
            hass,
            config_entry,
            entry_data,
            vin="__all__",  # Look up value from any VIN
            key=key,
        )
        async_add_entities([entity])

    existing: set[tuple[str, str]] = {( "__all__", k.lower()) for k in KNOWN_CARDATA_KEYS}

    def _add_entities_for_vin(vin: str) -> list[BMWCarDataSensor]:
        entities: list[BMWCarDataSensor] = []
        for key in store.get_vin_keys(vin):
            if key in KNOWN_CARDATA_KEYS_LOWER:
                continue
            if (vin, key) in existing:
                continue
            existing.add((vin, key))
            entities.append(
                BMWCarDataSensor(
                    hass,
                    config_entry,
                    entry_data,
                    vin,
                    key,
                )
            )
        return entities

    # Initial entities from current store
    for vin in store.all_vins():
        new_entities = _add_entities_for_vin(vin)
        if new_entities:
            async_add_entities(new_entities)

    @callback
    def _on_cardata_update(entry_id: str, vin: str) -> None:
        if entry_id != config_entry.entry_id:
            return
        new_entities = _add_entities_for_vin(vin)
        if new_entities:
            async_add_entities(new_entities)

    config_entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_CARDATA_UPDATE, _on_cardata_update
        )
    )


class BMWCarDataSensor(SensorEntity):
    """Sensor for a single BMW CarData signal (one per VIN + key)."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        entry_data: dict,
        vin: str,
        key: str,
    ) -> None:
        self.hass = hass
        self._config_entry = config_entry
        self._entry_data = entry_data
        self._vin = vin
        self._key = key
        self._store = entry_data["store"]
        self._attr_unique_id = f"{config_entry.entry_id}_cardata_{key.lower()}" if vin == "__all__" else f"{config_entry.entry_id}_{vin}_{key.lower()}"
        self._attr_translation_key = key.lower()
        self._attr_name = _key_to_display_name(key)  # fallback if translation missing
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": config_entry.title or "BMW CarData",
            "manufacturer": "BMW",
        }
        if vin and vin != "__all__" and len(vin) >= 6:
            self._attr_device_info["identifiers"] = {(DOMAIN, f"{config_entry.entry_id}_{vin}")}
            self._attr_device_info["name"] = f"BMW {vin[-6:]}"
        self._attr_device_class = KEY_DEVICE_CLASS_NORMALIZED.get(key.lower())
        self._attr_native_unit_of_measurement = None
        self._attr_state_class = KEY_STATE_CLASS_NORMALIZED.get(key.lower())
        value, unit = self._get_value_and_unit()
        self._attr_native_value = value
        if unit:
            self._attr_native_unit_of_measurement = unit

    def _get_value_and_unit(self) -> tuple[Any, str | None]:
        row = self._store.get(self._vin, self._key)
        if not row:
            if self._vin == "__all__":
                result = self._store.get_first_value_for_key(self._key)
                if result:
                    return (result[1], result[2])
            return (None, None)
        return row

    @callback
    def _on_cardata_update(self, entry_id: str, vin: str) -> None:
        if entry_id != self._config_entry.entry_id:
            return
        if self._vin != "__all__" and vin != self._vin:
            return
        value, unit = self._get_value_and_unit()
        self._attr_native_value = value
        self._attr_native_unit_of_measurement = unit
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Resolve translated name (with has_entity_name=False, translation_key is not used by HA; set name ourselves)
        name = await _resolve_entity_name(
            self.hass, "sensor", self._attr_translation_key, self._attr_name
        )
        if name != self._attr_name:
            self._attr_name = name
            self.async_write_ha_state()
        value, unit = self._get_value_and_unit()
        self._attr_native_value = value
        self._attr_native_unit_of_measurement = unit
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CARDATA_UPDATE, self._on_cardata_update
            )
        )

    @property
    def native_value(self) -> Any:
        return self._attr_native_value


class BMWCarDataStatusSensor(SensorEntity):
    """Sensor showing CarData connection status (always present)."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_name = "Status"
    _attr_translation_key = "status"

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        entry_data: dict,
    ) -> None:
        self.hass = hass
        self._config_entry = config_entry
        self._entry_data = entry_data
        self._attr_unique_id = f"{config_entry.entry_id}_status"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": config_entry.title or "BMW CarData",
            "manufacturer": "BMW",
        }
        self._attr_native_value = self._get_connection_state()

    def _get_connection_state(self) -> str:
        coordinator = self._entry_data.get("connection_coordinator")
        if coordinator is not None and coordinator.data is True:
            return "Connected"
        client = self._entry_data.get("client")
        if client and getattr(client, "is_connected", False):
            return "Connected"
        return "Disconnected"

    @callback
    def _handle_connection_changed(self, entry_id: str, connected: bool) -> None:
        if entry_id == self._config_entry.entry_id:
            self._attr_native_value = "Connected" if connected else "Disconnected"
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        name = await _resolve_entity_name(
            self.hass, "sensor", self._attr_translation_key, self._attr_name
        )
        if name != self._attr_name:
            self._attr_name = name
            self.async_write_ha_state()
        self._attr_native_value = self._get_connection_state()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONNECTION_CHANGED, self._handle_connection_changed
            )
        )

    @property
    def native_value(self) -> Any:
        return self._attr_native_value


class BMWCarDataVINSensor(SensorEntity):
    """Sensor showing the current vehicle VIN (from received CarData)."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_name = "VIN"
    _attr_translation_key = "vin"
    _attr_icon = "mdi:car-info"

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
        self._attr_unique_id = f"{config_entry.entry_id}_vin"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": config_entry.title or "BMW CarData",
            "manufacturer": "BMW",
        }
        self._attr_native_value = self._get_vin()

    def _get_vin(self) -> str | None:
        vins = self._store.all_vins()
        return vins[0] if vins else None

    @callback
    def _on_cardata_update(self, entry_id: str, vin: str) -> None:
        if entry_id == self._config_entry.entry_id:
            self._attr_native_value = self._get_vin()
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        name = await _resolve_entity_name(
            self.hass, "sensor", self._attr_translation_key, self._attr_name
        )
        if name != self._attr_name:
            self._attr_name = name
            self.async_write_ha_state()
        self._attr_native_value = self._get_vin()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CARDATA_UPDATE, self._on_cardata_update
            )
        )

    @property
    def native_value(self) -> Any:
        return self._attr_native_value
