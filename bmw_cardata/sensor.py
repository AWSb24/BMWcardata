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
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import (
    DOMAIN,
    CONF_GCID,
    CONF_VIN,
    get_device_name,
    SIGNAL_CARDATA_UPDATE,
    SIGNAL_CONNECTION_CHANGED,
)

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


def _strip_vehicle_prefix(name: str) -> str:
    """Remove leading 'Vehicle ' / 'Fahrzeug ' prefix from sensor names."""
    if not name:
        return name
    name_lower = name.lower()
    if name_lower.startswith("vehicle "):
        return name[8:].strip() or name
    if name_lower.startswith("fahrzeug "):
        return name[9:].strip() or name
    return name


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
                return _strip_vehicle_prefix(name)
    except Exception:
        pass
    return _strip_vehicle_prefix(fallback)


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

    # CarData sensors are added on demand when MQTT pushes data (no pre-creation of 200+ entities).
    # Only add sensors for the configured VIN (topic VIN must match config).
    # Existing set avoids duplicate (vin, key) in one run; HA deduplicates by unique_id.
    existing: set[tuple[str, str]] = set()
    gcid = (config_entry.data.get(CONF_GCID) or "").strip()
    configured_vin = (config_entry.data.get(CONF_VIN) or "").strip()

    async def _update_device_name(vin: str | None) -> None:
        """Update the single device name to show VIN / GCID."""
        try:
            dev_reg = async_get_device_registry(hass)
            device = dev_reg.async_get_device(identifiers={(DOMAIN, config_entry.entry_id)})
            if device:
                dev_reg.async_update_device(device.id, name=get_device_name(gcid, vin))
        except Exception:
            pass

    def _vin_matches(vin: str) -> bool:
        """Only add entities for the configured VIN."""
        if not configured_vin:
            return True
        return vin == configured_vin

    def _add_entities_for_vin(vin: str) -> list[BMWCarDataSensor]:
        if not _vin_matches(vin):
            return []
        entities: list[BMWCarDataSensor] = []
        for key in store.get_vin_keys(vin):
            key_lower = key.lower()
            if (vin, key_lower) in existing:
                continue
            existing.add((vin, key_lower))
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

    # Initial entities from current store (only for configured VIN)
    for vin in store.all_vins():
        if _vin_matches(vin):
            new_entities = _add_entities_for_vin(vin)
            if new_entities:
                async_add_entities(new_entities)
    # Set initial device name (use configured VIN from config, or first VIN from store)
    display_vin = configured_vin or (store.all_vins()[0] if store.all_vins() else None)
    await _update_device_name(display_vin)

    @callback
    def _on_cardata_update(entry_id: str, vin: str) -> None:
        if entry_id != config_entry.entry_id:
            return
        if not _vin_matches(vin):
            return
        new_entities = _add_entities_for_vin(vin)
        if new_entities:
            async_add_entities(new_entities)
            hass.async_create_task(_update_device_name(vin))

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
        self._attr_name = _strip_vehicle_prefix(_key_to_display_name(key))  # fallback if translation missing
        # Single device for all CarData entities (name shows actual VIN / GCID)
        gcid = (config_entry.data.get(CONF_GCID) or "").strip()
        device_name = get_device_name(gcid, vin if (vin and vin != "__all__") else None)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": device_name,
            "manufacturer": "BMW",
        }
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
        gcid = (config_entry.data.get(CONF_GCID) or "").strip()
        vin = (config_entry.data.get(CONF_VIN) or "").strip()
        if not vin:
            store = self._entry_data.get("store")
            vin = store.all_vins()[0] if (store and store.all_vins()) else None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": get_device_name(gcid, vin),
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
    """Sensor showing the configured VIN or 'VIN does not match' if stream VIN differs."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_name = "VIN"
    _attr_translation_key = "vin"
    _attr_icon = "mdi:car-info"

    VIN_MISMATCH = "VIN does not match"

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
        gcid = (config_entry.data.get(CONF_GCID) or "").strip()
        vin = (config_entry.data.get(CONF_VIN) or "").strip() or (
            self._store.all_vins()[0] if self._store.all_vins() else None
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": get_device_name(gcid, vin),
            "manufacturer": "BMW",
        }
        self._attr_native_value = self._get_vin()

    def _get_vin(self) -> str | None:
        if self._entry_data.get("vin_mismatch"):
            return self.VIN_MISMATCH
        vins = self._store.all_vins()
        return vins[0] if vins else self._config_entry.data.get(CONF_VIN)

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
