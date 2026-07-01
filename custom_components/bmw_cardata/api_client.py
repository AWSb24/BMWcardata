"""BMW CarData REST API client.

Wraps the CarData REST API (https://customer.bmwgroup.com). The API is
container based: to read telematic data you first create a container that
declares which data keys you want, then poll the telematic-data endpoint.

Note: the API is rate limited to 50 requests / 24h (error code CU-429).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from aiohttp import ClientSession

from .const import BMW_API_BASE, BMW_API_VERSION

_LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    """Generic CarData API error."""


class RateLimitError(ApiError):
    """Raised when the API rate limit (CU-429) is hit."""


def descriptor_to_key(name: str) -> str:
    """Convert an API technicalDescriptor (dot notation) to our entity key.

    "vehicle.cabin.infotainment...longitude" -> "vehicle_cabin_infotainment...longitude"
    (the store lower-cases keys itself).
    """
    return name.replace(".", "_")


def key_to_descriptor(key: str) -> str:
    """Convert our entity key (underscores) back to the API dot notation."""
    return key.replace("_", ".")


def iso_to_epoch(timestamp: str | None) -> float | None:
    """Parse an ISO-8601 timestamp (e.g. 2025-07-28T05:16:53.000Z) to epoch seconds."""
    if not timestamp:
        return None
    try:
        value = timestamp.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError):
        return None


def _clean_unit(unit: Any) -> str | None:
    if isinstance(unit, str):
        return unit.strip() or None
    return None


def parse_telematic_response(payload: Any) -> list[tuple[str, Any, str | None, float | None]]:
    """Normalize a telematic-data response into (key, value, unit, timestamp) tuples.

    The API returns ``{"telematicData": {"<descriptor>": {"value", "unit",
    "timestamp"}}}`` (a map keyed by descriptor). A bare list of ``{name, ...}``
    items is also accepted defensively.
    """
    result: list[tuple[str, Any, str | None, float | None]] = []

    container = payload
    if isinstance(payload, dict) and isinstance(payload.get("telematicData"), (dict, list)):
        container = payload["telematicData"]

    if isinstance(container, dict):
        # Map form: key is the descriptor, value carries value/unit/timestamp.
        for name, obj in container.items():
            if not isinstance(obj, dict):
                continue
            result.append(
                (
                    descriptor_to_key(name),
                    obj.get("value"),
                    _clean_unit(obj.get("unit")),
                    iso_to_epoch(obj.get("timestamp")),
                )
            )
    elif isinstance(container, list):
        # List form: each item carries its own name.
        for item in container:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            result.append(
                (
                    descriptor_to_key(name),
                    item.get("value"),
                    _clean_unit(item.get("unit")),
                    iso_to_epoch(item.get("timestamp")),
                )
            )
    return result


class BMWCarDataApiClient:
    """Async client for the BMW CarData REST API.

    The access token is provided lazily via ``token_provider`` so the client
    always uses the most recently refreshed token.
    """

    def __init__(
        self,
        session: ClientSession,
        token_provider: Callable[[], str],
    ) -> None:
        self._session = session
        self._token_provider = token_provider

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        token = (self._token_provider() or "").strip()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-version": BMW_API_VERSION,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        url = f"{BMW_API_BASE}{path}"
        async with self._session.request(
            method, url, headers=headers, json=json_body, params=params
        ) as resp:
            text = await resp.text()
            if resp.status == 429 or "CU-429" in text:
                raise RateLimitError("CarData API rate limit reached (CU-429)")
            if resp.status >= 400:
                _LOGGER.debug(
                    "CarData API %s %s -> %s: %s", method, path, resp.status, text[:500]
                )
                raise ApiError(f"{method} {path} failed with HTTP {resp.status}")
            if not text:
                return None
            try:
                return await resp.json(content_type=None)
            except Exception as err:  # noqa: BLE001 - defensive JSON parse
                raise ApiError(f"Invalid JSON from {path}") from err

    async def get_mappings(self) -> Any:
        """List VINs mapped to the account (PRIMARY/SECONDARY)."""
        return await self._request("GET", "/customers/vehicles/mappings")

    async def get_basic_data(self, vin: str) -> Any:
        """Static vehicle metadata (brand, model, ...)."""
        return await self._request("GET", f"/customers/vehicles/{vin}/basicData")

    async def list_containers(self) -> Any:
        """Return all containers for the user."""
        return await self._request("GET", "/customers/containers")

    async def create_container(
        self,
        descriptors: list[str],
        name: str = "Home Assistant",
        purpose: str = "Home Assistant CarData integration",
    ) -> str | None:
        """Create a container declaring the given technicalDescriptors; return its containerId."""
        body = {
            "name": name,
            "purpose": purpose,
            "technicalDescriptors": descriptors,
        }
        resp = await self._request("POST", "/customers/containers", json_body=body)
        if isinstance(resp, dict):
            return resp.get("containerId") or resp.get("id")
        return None

    async def delete_container(self, container_id: str) -> None:
        """Deactivate a container."""
        await self._request("DELETE", f"/customers/containers/{container_id}")

    async def get_telematic_data(
        self, vin: str, container_id: str
    ) -> list[tuple[str, Any, str | None, float | None]]:
        """Return telematic values (key, value, unit, timestamp) for the given container."""
        resp = await self._request(
            "GET",
            f"/customers/vehicles/{vin}/telematicData",
            params={"containerId": container_id},
        )
        return parse_telematic_response(resp)
