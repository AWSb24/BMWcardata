"""
BMW CarData integration.

Connects to BMW CarData MQTT stream (no local MQTT broker required),
exposes vehicle data as Home Assistant sensors and a connection binary sensor.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .bmw_client import BMWCarDataClient, parse_cardata_message
from .const import (
    DOMAIN,
    BMW_TOKEN_URL,
    CONF_CLIENT_ID,
    CONF_GCID,
    CONF_ID_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES,
    SIGNAL_CARDATA_UPDATE,
    SIGNAL_CONNECTION_CHANGED,
    SOFT_REFRESH_MARGIN_SECONDS,
    HARD_REFRESH_INTERVAL_SECONDS,
    CLOCK_SKEW_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_REQUEST_REFRESH = "request_refresh"


async def _handle_request_refresh(hass: HomeAssistant, call: ServiceCall) -> None:
    """Trigger a reconnect to pull fresh data from the BMW CarData stream."""
    refreshed = 0
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state != ConfigEntryState.LOADED:
            continue
        entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        client = entry_data.get("client") if entry_data else None
        if isinstance(client, BMWCarDataClient):
            client.trigger_reconnect()
            refreshed += 1
    _LOGGER.debug("BMW CarData: triggered reconnect for %d client(s)", refreshed)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the BMW CarData integration (registers services and brand assets)."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_REQUEST_REFRESH,
        lambda call: _handle_request_refresh(hass, call),
    )
    # Register brand folder so icon/logo are served for the Config menu (Settings > Integrations).
    # The frontend requests /api/brands/integration/{domain}/icon.png; register at that path so our icon is used.
    brand_path = Path(__file__).parent / "brand"
    if brand_path.is_dir():
        try:
            from homeassistant.components.http import StaticPathConfig
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(f"/api/{DOMAIN}/brand", str(brand_path), False),
                    StaticPathConfig(f"/api/brands/integration/{DOMAIN}", str(brand_path), False),
                ]
            )
        except (ImportError, AttributeError):
            pass
    return True


def _jwt_exp_unix(jwt: str) -> int:
    """Extract exp claim from JWT."""
    try:
        parts = jwt.split(".")
        if len(parts) < 2:
            return 0
        payload_b64 = parts[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload_b64 = payload_b64.replace("-", "+").replace("_", "/")
        payload = base64.b64decode(payload_b64)
        data = json.loads(payload)
        return int(data.get("exp", 0))
    except Exception:
        return 0


async def _refresh_tokens(
    hass: HomeAssistant,
    client_id: str,
    refresh_token: str,
) -> dict[str, Any] | None:
    """Refresh BMW OAuth tokens."""
    session = aiohttp_client.async_get_clientsession(hass)
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    try:
        async with session.post(
            BMW_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                return None
            result = await resp.json()
            if result.get("error"):
                return None
            id_token = (result.get("id_token") or "").strip()
            new_refresh = (result.get("refresh_token") or "").strip()
            expires_in = int(result.get("expires_in", 3600))
            token_expires = int(time.time()) + expires_in
            return {
                "id_token": id_token,
                "refresh_token": new_refresh or refresh_token,
                "token_expires": token_expires,
            }
    except Exception as e:
        _LOGGER.warning("Token refresh failed: %s", e)
        return None


class CarDataStore:
    """In-memory store for CarData signals: vin -> key -> (value, unit)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, tuple[Any, str | None]]] = {}
        self._lock = threading.Lock()

    def ensure_vin(self, vin: str) -> None:
        """Register a VIN so it appears in all_vins() even before data arrives."""
        with self._lock:
            if vin and vin not in self._data:
                self._data[vin] = {}

    def update(self, vin: str, key: str, value: Any, unit: str | None = None) -> None:
        with self._lock:
            if vin not in self._data:
                self._data[vin] = {}
            self._data[vin][key.lower()] = (value, unit)

    def get(self, vin: str, key: str) -> tuple[Any, str | None] | None:
        with self._lock:
            if vin not in self._data:
                return None
            return self._data[vin].get(key.lower())

    def get_vin_keys(self, vin: str) -> list[str]:
        with self._lock:
            if vin not in self._data:
                return []
            return list(self._data[vin].keys())

    def all_vins(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())

    def get_first_value_for_key(self, key: str) -> tuple[str, Any, str | None] | None:
        """Return (vin, value, unit) for the first VIN that has this key, or None."""
        with self._lock:
            key_lower = key.lower()
            for vin, keys_data in self._data.items():
                if key_lower in keys_data:
                    val, unit = keys_data[key_lower]
                    return (vin, val, unit)
            return None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
) -> bool:
    """Set up BMW CarData from a config entry."""
    data = config_entry.data
    client_id = data[CONF_CLIENT_ID]
    gcid = data[CONF_GCID]
    id_token = data[CONF_ID_TOKEN]
    refresh_token = data[CONF_REFRESH_TOKEN]
    token_expires = data.get(CONF_TOKEN_EXPIRES) or 0

    store = CarDataStore()
    client: BMWCarDataClient | None = None
    client_thread: threading.Thread | None = None

    @callback
    def on_connect_changed(connected: bool) -> None:
        async_dispatcher_send(
            hass, SIGNAL_CONNECTION_CHANGED, config_entry.entry_id, connected
        )

    @callback
    def on_message(vin: str, event_name: str, payload: dict) -> None:
        if vin:
            store.ensure_vin(vin)
        parsed = parse_cardata_message(vin, event_name, payload)
        if _LOGGER.isEnabledFor(logging.DEBUG) and parsed:
            _LOGGER.debug(
                "CarData received: vin=%s event=%s keys=%s",
                vin[:8] + "..." if len(vin) > 8 else vin,
                event_name,
                [k for k, _, _ in parsed],
            )
        for key, value, unit in parsed:
            store.update(vin, key, value, unit)
        hass.loop.call_soon_threadsafe(
            lambda: async_dispatcher_send(
                hass, SIGNAL_CARDATA_UPDATE, config_entry.entry_id, vin
            )
        )

    def run_client() -> None:
        nonlocal client
        c = BMWCarDataClient(
            client_id=client_id,
            gcid=gcid,
            id_token=id_token,
            on_connect_changed=lambda connected: hass.loop.call_soon_threadsafe(
                on_connect_changed, connected
            ),
            on_message=lambda vin, ev, pl: hass.loop.call_soon_threadsafe(
                lambda v=vin, e=ev, p=pl: on_message(v, e, p)
            ),
        )
        client = c
        entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
        if entry_data:
            entry_data["client"] = c
        c.start()

    client_thread = threading.Thread(target=run_client, daemon=True)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "store": store,
        "client": None,
        "config_entry": config_entry,
    }
    client_thread.start()

    async def refresh_task() -> None:
        nonlocal id_token, refresh_token, token_expires
        last_refresh = time.time()
        while True:
            await asyncio.sleep(60)
            now = int(time.time())
            do_refresh = False
            if (token_expires - now) <= (SOFT_REFRESH_MARGIN_SECONDS + CLOCK_SKEW_SECONDS):
                do_refresh = True
            elif (now - last_refresh) >= HARD_REFRESH_INTERVAL_SECONDS:
                do_refresh = True
            if not do_refresh:
                continue
            result = await _refresh_tokens(hass, client_id, refresh_token)
            if result:
                id_token = result["id_token"]
                refresh_token = result["refresh_token"]
                token_expires = result["token_expires"]
                last_refresh = now
                hass.config_entries.async_update_entry(
                    config_entry,
                    data={
                        **config_entry.data,
                        CONF_ID_TOKEN: id_token,
                        CONF_REFRESH_TOKEN: refresh_token,
                        CONF_TOKEN_EXPIRES: token_expires,
                    },
                )
                entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
                if entry_data and entry_data.get("client"):
                    entry_data["client"].update_tokens(id_token)
                _LOGGER.debug("BMW CarData tokens refreshed")

    hass.async_create_background_task(
        refresh_task(), "bmw_cardata_token_refresh"
    )

    await hass.config_entries.async_forward_entry_setups(
        config_entry, ["sensor", "binary_sensor", "device_tracker"]
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
) -> bool:
    """Unload a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if entry_data and entry_data.get("client"):
        entry_data["client"].stop()
    await hass.config_entries.async_unload_platforms(
        config_entry, ["sensor", "binary_sensor", "device_tracker"]
    )
    if DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]:
        del hass.data[DOMAIN][config_entry.entry_id]
    return True
