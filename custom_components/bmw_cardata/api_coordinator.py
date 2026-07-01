"""Polling coordinator for the BMW CarData REST API.

Used in API and Mixed modes. Ensures a container exists (declaring the data
keys we want), then periodically polls telematic data into the shared store.
Requests are kept minimal because the API allows only 50 calls / 24h.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import ApiError, BMWCarDataApiClient, RateLimitError, key_to_descriptor
from .const import (
    API_POLL_DEFAULT_MINUTES,
    API_POLL_MIN_MINUTES,
    CONF_ACCESS_TOKEN,
    CONF_API_POLL_INTERVAL,
    CONF_CONTAINER_ID,
    CONF_VIN,
    DOMAIN,
    SIGNAL_CARDATA_UPDATE,
)
from .descriptors import KNOWN_CARDATA_KEYS

_LOGGER = logging.getLogger(__name__)


def resolve_interval_minutes(config_entry: ConfigEntry) -> int:
    """Return the configured poll interval in minutes, floored to the API minimum."""
    raw = config_entry.options.get(
        CONF_API_POLL_INTERVAL,
        config_entry.data.get(CONF_API_POLL_INTERVAL, API_POLL_DEFAULT_MINUTES),
    )
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = API_POLL_DEFAULT_MINUTES
    return max(minutes, API_POLL_MIN_MINUTES)


class CarDataApiCoordinator(DataUpdateCoordinator[int]):
    """Polls the REST API and writes results into the shared store."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        entry_data: dict,
        client: BMWCarDataApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_api",
            update_interval=timedelta(minutes=resolve_interval_minutes(config_entry)),
        )
        self._config_entry = config_entry
        self._entry_data = entry_data
        self._client = client
        self._store = entry_data["store"]

    @property
    def _vin(self) -> str:
        return (self._config_entry.data.get(CONF_VIN) or "").strip()

    async def _ensure_container(self) -> str | None:
        """Return a usable container id, creating one if we do not have it yet."""
        container_id = self._config_entry.data.get(CONF_CONTAINER_ID)
        if container_id:
            return container_id
        descriptors = [key_to_descriptor(k) for k in KNOWN_CARDATA_KEYS]
        container_id = await self._client.create_container(descriptors)
        if container_id:
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data={**self._config_entry.data, CONF_CONTAINER_ID: container_id},
            )
            _LOGGER.debug("BMW CarData: created API container %s", container_id)
        return container_id

    async def _async_update_data(self) -> int:
        vin = self._vin
        if not vin:
            return 0
        access_token = (self._config_entry.data.get(CONF_ACCESS_TOKEN) or "").strip()
        if not access_token:
            raise UpdateFailed("No access token available for CarData API")

        try:
            container_id = await self._ensure_container()
            if not container_id:
                raise UpdateFailed("Could not create/find a CarData API container")
            rows = await self._client.get_telematic_data(vin, container_id)
        except RateLimitError:
            # 50/24h exhausted - keep last values, try again next interval.
            _LOGGER.warning(
                "BMW CarData API rate limit reached (CU-429); skipping this poll"
            )
            return 0
        except ApiError as err:
            # A stale container (auto-deleted after 29 days) is the usual cause;
            # forget it so the next poll recreates it.
            if self._config_entry.data.get(CONF_CONTAINER_ID):
                data = dict(self._config_entry.data)
                data.pop(CONF_CONTAINER_ID, None)
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=data
                )
            raise UpdateFailed(str(err)) from err

        self._store.ensure_vin(vin)
        applied = 0
        for key, value, unit, timestamp in rows:
            if self._store.update(vin, key, value, unit, timestamp):
                applied += 1
        async_dispatcher_send(
            self.hass, SIGNAL_CARDATA_UPDATE, self._config_entry.entry_id, vin
        )
        _LOGGER.debug(
            "BMW CarData API poll: %d/%d values applied for %s",
            applied,
            len(rows),
            vin[:8] + "..." if len(vin) > 8 else vin,
        )
        return applied
