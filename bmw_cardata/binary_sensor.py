"""BMW CarData connection status binary sensor."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, CONF_GCID, CONF_VIN, get_device_name, SIGNAL_CONNECTION_CHANGED

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CarData connection binary sensor."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not entry_data:
        _LOGGER.warning("BMW CarData: No entry_data for entry %s", config_entry.entry_id)
        return

    coordinator = ConnectionCoordinator(hass, config_entry, entry_data)
    # Set initial state without requiring first_refresh (avoids dependency on client thread)
    coordinator.async_set_updated_data(False)
    entry_data["connection_coordinator"] = coordinator
    async_add_entities([BMWCarDataConnectionSensor(coordinator, config_entry)])
    _LOGGER.debug("BMW CarData: Added connection binary sensor")


class ConnectionCoordinator(DataUpdateCoordinator[bool]):
    """Coordinator that tracks BMW CarData connection status."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, entry_data: dict
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self._config_entry = config_entry
        self._entry_data = entry_data
        self._connected = False

    @callback
    def async_set_connected(self, connected: bool) -> None:
        """Update connection state (called from dispatcher)."""
        if self._connected != connected:
            self._connected = connected
            self.async_set_updated_data(connected)

    async def _async_update_data(self) -> bool:
        """Return current connection state."""
        client = self._entry_data.get("client")
        if client and hasattr(client, "is_connected"):
            return client.is_connected
        return self._connected


class BMWCarDataConnectionSensor(BinarySensorEntity):
    """Binary sensor for BMW CarData stream connection."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = False
    _attr_name = "CarData stream"
    _attr_translation_key = "cardata_stream"

    def __init__(
        self, coordinator: ConnectionCoordinator, config_entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_connection"
        gcid = (config_entry.data.get(CONF_GCID) or "").strip()
        vin = (config_entry.data.get(CONF_VIN) or "").strip()
        if not vin and coordinator._entry_data:
            store = coordinator._entry_data.get("store")
            vin = store.all_vins()[0] if (store and store.all_vins()) else None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": get_device_name(gcid, vin),
            "manufacturer": "BMW",
        }

    @property
    def is_on(self) -> bool:
        return self._coordinator.data if self._coordinator.data is not None else False

    @callback
    def _handle_connection_changed(self, entry_id: str, connected: bool) -> None:
        if entry_id == self._config_entry.entry_id:
            self._coordinator.async_set_connected(connected)
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
                key = f"component.{DOMAIN}.entity.binary_sensor.{self._attr_translation_key}.name"
                if name := trans.get(key):
                    self._attr_name = name
        except Exception:
            pass
        client = self._coordinator._entry_data.get("client")
        if client and hasattr(client, "is_connected"):
            self._coordinator.async_set_connected(client.is_connected)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONNECTION_CHANGED, self._handle_connection_changed
            )
        )
