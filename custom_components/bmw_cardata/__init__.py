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
    CONF_VIN,
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
    """Trigger a reconnect to pull fresh data from the BMW CarData stream (one per GCID)."""
    gcid_clients = _gcid_clients(hass)
    refreshed = 0
    for _gcid_key, reg in gcid_clients.items():
        client = reg.get("client")
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


def _gcid_clients(hass: HomeAssistant) -> dict:
    """Return the shared GCID client registry (one MQTT client per GCID)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "_gcid_clients" not in domain_data:
        domain_data["_gcid_clients"] = {}
    return domain_data["_gcid_clients"]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
) -> bool:
    """Set up BMW CarData from a config entry. Shares one MQTT client per GCID."""
    data = config_entry.data
    client_id = data[CONF_CLIENT_ID]
    gcid = (data[CONF_GCID] or "").strip()
    gcid_key = gcid.lower()
    id_token = data[CONF_ID_TOKEN]
    refresh_token = data[CONF_REFRESH_TOKEN]
    token_expires = data.get(CONF_TOKEN_EXPIRES) or 0

    store = CarDataStore()
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "store": store,
        "client": None,
        "config_entry": config_entry,
        "vin_mismatch": False,
    }
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    gcid_registry = _gcid_clients(hass)

    if gcid_key not in gcid_registry:
        # First config entry with this GCID: create the shared client and refresh task
        client: BMWCarDataClient | None = None

        @callback
        def on_connect_changed(connected: bool) -> None:
            for eid in gcid_registry[gcid_key]["entry_ids"]:
                async_dispatcher_send(hass, SIGNAL_CONNECTION_CHANGED, eid, connected)

        @callback
        def on_message(vin: str, event_name: str, payload: dict) -> None:
            if not vin:
                return
            for eid in list(gcid_registry[gcid_key]["entry_ids"]):
                entry_data_e = hass.data.get(DOMAIN, {}).get(eid)
                if not entry_data_e:
                    continue
                cfg = entry_data_e["config_entry"]
                configured_vin = (cfg.data.get(CONF_VIN) or "").strip()
                store_e = entry_data_e["store"]
                if configured_vin and vin != configured_vin:
                    entry_data_e["vin_mismatch"] = True
                    hass.loop.call_soon_threadsafe(
                        lambda _eid=eid: async_dispatcher_send(
                            hass, SIGNAL_CARDATA_UPDATE, _eid, vin
                        )
                    )
                    continue
                entry_data_e["vin_mismatch"] = False
                store_e.ensure_vin(vin)
                parsed = parse_cardata_message(vin, event_name, payload)
                if _LOGGER.isEnabledFor(logging.DEBUG) and parsed:
                    _LOGGER.debug(
                        "CarData received: vin=%s event=%s keys=%s (entry=%s)",
                        vin[:8] + "..." if len(vin) > 8 else vin,
                        event_name,
                        [k for k, _, _ in parsed],
                        eid[:8] + "...",
                    )
                for key, value, unit in parsed:
                    store_e.update(vin, key, value, unit)
                hass.loop.call_soon_threadsafe(
                    lambda _eid=eid: async_dispatcher_send(
                        hass, SIGNAL_CARDATA_UPDATE, _eid, vin
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
            gcid_registry[gcid_key]["client"] = c
            for eid in gcid_registry[gcid_key]["entry_ids"]:
                ed = hass.data.get(DOMAIN, {}).get(eid)
                if ed:
                    ed["client"] = c
            c.start()

        client_thread = threading.Thread(target=run_client, daemon=True)
        gcid_registry[gcid_key] = {
            "client": None,
            "thread": client_thread,
            "entry_ids": {config_entry.entry_id},
        }
        entry_data["client"] = None  # set in run_client for all entries
        client_thread.start()

        async def refresh_task_gcid() -> None:
            last_refresh = time.time()
            while True:
                await asyncio.sleep(60)
                entry_ids = gcid_registry.get(gcid_key, {}).get("entry_ids") or set()
                if not entry_ids:
                    break
                first_id = next(iter(entry_ids), None)
                if not first_id:
                    break
                first_entry = hass.config_entries.async_get_entry(first_id)
                if not first_entry:
                    continue
                d = first_entry.data
                now = int(time.time())
                do_refresh = False
                if (d.get(CONF_TOKEN_EXPIRES) or 0) - now <= (
                    SOFT_REFRESH_MARGIN_SECONDS + CLOCK_SKEW_SECONDS
                ):
                    do_refresh = True
                elif (now - last_refresh) >= HARD_REFRESH_INTERVAL_SECONDS:
                    do_refresh = True
                if not do_refresh:
                    continue
                result = await _refresh_tokens(
                    hass, d.get(CONF_CLIENT_ID, ""), d.get(CONF_REFRESH_TOKEN, "")
                )
                if not result:
                    continue
                last_refresh = now
                for eid in entry_ids:
                    ent = hass.config_entries.async_get_entry(eid)
                    if ent:
                        hass.config_entries.async_update_entry(
                            ent,
                            data={
                                **ent.data,
                                CONF_ID_TOKEN: result["id_token"],
                                CONF_REFRESH_TOKEN: result["refresh_token"],
                                CONF_TOKEN_EXPIRES: result["token_expires"],
                            },
                        )
                reg = gcid_registry.get(gcid_key, {})
                if reg.get("client"):
                    reg["client"].update_tokens(result["id_token"])
                _LOGGER.debug("BMW CarData tokens refreshed (gcid=%s)", gcid_key[:8])

        gcid_registry[gcid_key]["refresh_task"] = hass.async_create_background_task(
            refresh_task_gcid(), f"bmw_cardata_token_refresh_{gcid_key[:8]}"
        )
    else:
        # Another entry with same GCID: reuse the shared client
        gcid_registry[gcid_key]["entry_ids"].add(config_entry.entry_id)
        entry_data["client"] = gcid_registry[gcid_key].get("client")

    await hass.config_entries.async_forward_entry_setups(
        config_entry, ["sensor", "binary_sensor", "device_tracker"]
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
) -> bool:
    """Unload a config entry. Stops the shared client only when the last entry for that GCID is unloaded."""
    gcid = (config_entry.data.get(CONF_GCID) or "").strip().lower()
    gcid_registry = _gcid_clients(hass)
    await hass.config_entries.async_unload_platforms(
        config_entry, ["sensor", "binary_sensor", "device_tracker"]
    )
    if config_entry.entry_id in (hass.data.get(DOMAIN) or {}):
        del hass.data[DOMAIN][config_entry.entry_id]
    if gcid in gcid_registry:
        gcid_registry[gcid]["entry_ids"].discard(config_entry.entry_id)
        if not gcid_registry[gcid]["entry_ids"]:
            client = gcid_registry[gcid].get("client")
            if client:
                client.stop()
            task = gcid_registry[gcid].get("refresh_task")
            if task and not task.done():
                task.cancel()
            del gcid_registry[gcid]
    return True
