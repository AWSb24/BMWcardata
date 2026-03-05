"""
BMW CarData MQTT client and token refresh.

Connects to BMW's MQTT broker using GCID + id_token (JWT),
subscribes to GCID/+, parses JSON payloads and notifies listeners.
Runs token refresh in the background (soft: before expiry, hard: every 45 min).
"""

from __future__ import annotations

import json
import ssl
import threading
import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

import logging

from .const import (
    BMW_MQTT_HOST,
    BMW_MQTT_PORT,
    BMW_MQTT_KEEPALIVE,
)

_LOGGER = logging.getLogger(__name__)

# Standard VIN length; topic segment used as VIN only when length matches to avoid short IDs (e.g. B35835) creating extra devices
_VIN_LENGTH = 17


def _looks_like_vin(value: str) -> bool:
    """True if value could be a VIN (17 alphanumeric chars)."""
    return len(value) == _VIN_LENGTH and value.isalnum()


def _sanitize_key(key: str) -> str:
    """Sanitize a data key for use as entity id (dots -> underscores)."""
    return key.replace(".", "_").replace(" ", "_")


def _flatten_data(
    data: dict,
    prefix: str = "",
) -> dict[str, dict]:
    """
    Flatten nested data: { "vehicle": { "drivetrain": { "x": {"value": 1} } } }
    -> { "vehicle.drivetrain.x": {"value": 1} }.
    Leaf nodes must be dicts with a "value" key.
    """
    result: dict[str, dict] = {}
    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and "value" in v:
            result[path] = v
        elif isinstance(v, dict):
            result.update(_flatten_data(v, path))
    return result


class BMWCarDataClient:
    """
    BMW CarData MQTT client. Runs in a thread; callbacks are invoked from that thread.
    Use hass.loop.call_soon_threadsafe to schedule HA updates on the main loop.
    """

    def __init__(
        self,
        client_id: str,
        gcid: str,
        id_token: str,
        on_connect_changed: Callable[[bool], None],
        on_message: Callable[[str, str, dict[str, Any]], None],
    ) -> None:
        self.client_id = client_id
        self.gcid = gcid
        self._id_token = id_token
        self._on_connect_changed = on_connect_changed
        self._on_message = on_message
        self._client: mqtt.Client | None = None
        self._connected = False
        self._running = False
        self._lock = threading.Lock()

    def update_tokens(self, id_token: str) -> None:
        """Update the id_token (call from main thread after refresh)."""
        with self._lock:
            self._id_token = id_token
        if self._client:
            self._client.username_pw_set(self.gcid, id_token)

    def _get_id_token(self) -> str:
        with self._lock:
            return self._id_token

    def _set_tokens(
        self, id_token: str, refresh_token: str, token_expires: int
    ) -> None:
        pass  # unused; refresh is done in integration

    def _maybe_refresh(self) -> bool:
        return True  # refresh is done in integration

    def _do_refresh(self) -> bool:
        return True

    def _on_connect(
        self, _client: mqtt.Client, _userdata: Any, _flags: Any, rc: int, *args: Any
    ) -> None:
        if rc == 0:
            self._connected = True
            self._on_connect_changed(True)
            topic = f"{self.gcid}/#"
            _client.subscribe(topic, qos=1)
        else:
            self._connected = False
            self._on_connect_changed(False)

    def _on_disconnect(
        self, _client: mqtt.Client, _userdata: Any, rc: int, *args: Any
    ) -> None:
        self._connected = False
        self._on_connect_changed(False)

    def _on_message_cb(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        msg: mqtt.MQTTMessage,
        *args: Any,
    ) -> None:
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8") if msg.payload else "{}"
            _LOGGER.debug("MQTT message: topic=%s payload=%s", topic, payload)
            data = json.loads(payload)
            vin = data.get("vin") or ""
            if not vin and "/" in topic:
                parts = topic.split("/")
                if len(parts) >= 2 and _looks_like_vin(parts[1]):
                    vin = parts[1]
            event_name = ""
            if "/" in topic:
                parts = topic.split("/")
                if len(parts) >= 3:
                    event_name = parts[2]
            self._on_message(vin, event_name, data)
        except Exception:
            pass

    def _create_client(self) -> mqtt.Client:
        with self._lock:
            id_token = self._id_token
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=self.client_id,
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message_cb
        client.username_pw_set(self.gcid, id_token)
        client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
        )
        client.reconnect_delay_set(min_delay=1, max_delay=120)
        return client

    def start(self) -> None:
        """Start the MQTT client (connect in a loop). Call from a dedicated thread."""
        self._running = True
        while self._running:
            self._client = self._create_client()
            try:
                self._client.connect_async(
                    BMW_MQTT_HOST, BMW_MQTT_PORT, BMW_MQTT_KEEPALIVE
                )
                self._client.loop_forever()
            except Exception:
                pass
            finally:
                if self._client:
                    try:
                        self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None
                self._connected = False
                self._on_connect_changed(False)
            if self._running:
                time.sleep(5)

    def stop(self) -> None:
        """Stop the client loop."""
        self._running = False
        if self._client:
            self._client.disconnect()

    def trigger_reconnect(self) -> None:
        """
        Disconnect the current MQTT client to force a reconnect.
        Useful to pull fresh data from the stream (BMW may send state on reconnect).
        Safe to call from any thread.
        """
        if self._client:
            self._client.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._connected


def parse_cardata_message(vin: str, event_name: str, payload: dict) -> list[tuple[str, Any, str | None]]:
    """
    Parse BMW CarData JSON payload into (key, value, unit) tuples.
    key is sanitized for entity id (e.g. vehicle_cabin_infotainment_...).
    Expects payload.data to be a dict of { "vehicle.x.y.z": { "value": ..., "unit": ... } }.
    """
    result: list[tuple[str, Any, str | None]] = []
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        if _LOGGER.isEnabledFor(logging.DEBUG) and payload:
            _LOGGER.debug("CarData payload has no 'data' dict: keys=%s", list(payload.keys()))
        return result
    if _LOGGER.isEnabledFor(logging.DEBUG) and not data and payload:
        _LOGGER.debug("CarData payload has empty data: top-level keys=%s", list(payload.keys()))
    # Support both flat and nested payloads
    flat_data = _flatten_data(data)
    for prop_name, prop_obj in flat_data.items():
        if not isinstance(prop_obj, dict):
            continue
        if "value" not in prop_obj:
            continue
        value = prop_obj["value"]
        unit = prop_obj.get("unit") or prop_obj.get("units")
        if isinstance(unit, str):
            unit = unit.strip() or None
        else:
            unit = None
        key = _sanitize_key(prop_name)
        result.append((key, value, unit))
    return result
