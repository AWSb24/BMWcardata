"""Config flow for BMW CarData integration."""

from __future__ import annotations

import hashlib
import base64
import re
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client

from .const import (
    DOMAIN,
    BMW_DEVICE_CODE_URL,
    BMW_TOKEN_URL,
    BMW_SCOPES,
    CONF_CLIENT_ID,
    CONF_GCID,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_ID_TOKEN,
    CONF_TOKEN_EXPIRES,
)


def _is_placeholder_uuid(value: str) -> bool:
    """Check if value is empty or the placeholder 11111111-1111-1111-1111-111111111111."""
    if not value or not value.strip():
        return True
    stripped = value.strip()
    return bool(re.match(r"^1{8}-1{4}-1{4}-1{4}-1{12}$", stripped.replace(" ", "")))


def _validate_guid(value: str) -> bool:
    """Validate GUID format."""
    try:
        uuid.UUID(value.strip())
        return True
    except (ValueError, AttributeError):
        return False


def _pkce_code_verifier() -> str:
    """Generate a PKCE code verifier (43-128 chars)."""
    return base64.urlsafe_b64encode(bytes(96))[:64].decode("ascii").rstrip("=")


def _pkce_code_challenge(verifier: str) -> str:
    """Generate S256 code challenge from verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def _request_device_code(
    hass: HomeAssistant, client_id: str, code_challenge: str
) -> dict[str, Any] | None:
    """Request device code from BMW OAuth."""
    session = aiohttp_client.async_get_clientsession(hass)
    data = {
        "client_id": client_id,
        "scope": BMW_SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    async with session.post(
        BMW_DEVICE_CODE_URL,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    ) as resp:
        if resp.status != 200:
            return None
        return await resp.json()


async def _poll_token(
    hass: HomeAssistant,
    client_id: str,
    device_code: str,
    code_verifier: str,
    interval: int,
) -> dict[str, Any] | None:
    """Poll token endpoint until user authorizes or error."""
    import asyncio
    session = aiohttp_client.async_get_clientsession(hass)
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    while True:
        async with session.post(
            BMW_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            result = await resp.json()
        error = result.get("error")
        if not error:
            return result
        if error == "authorization_pending":
            await asyncio.sleep(interval)
            continue
        if error == "slow_down":
            interval = interval + 5
            await asyncio.sleep(interval)
            continue
        return None


class BMWCarDataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BMW CarData."""

    VERSION = 1

    def __init__(self) -> None:
        self._device_code: str | None = None
        self._code_verifier: str | None = None
        self._verification_uri_complete: str | None = None
        self._interval: int = 5
        self._client_id: str | None = None
        self._gcid: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return BMWCarDataOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the start of the config flow."""
        return await self.async_step_credentials(user_input)

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step: collect Client ID and GCID."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = (user_input.get(CONF_CLIENT_ID) or "").strip()
            gcid = (user_input.get(CONF_GCID) or "").strip()

            if _is_placeholder_uuid(client_id):
                errors["base"] = "invalid_credentials"
            elif not _validate_guid(client_id):
                errors["base"] = "invalid_credentials"
            elif _is_placeholder_uuid(gcid):
                errors["base"] = "invalid_credentials"
            else:
                self._client_id = client_id
                self._gcid = gcid
                code_verifier = _pkce_code_verifier()
                code_challenge = _pkce_code_challenge(code_verifier)
                device_resp = await _request_device_code(
                    self.hass, self._client_id, code_challenge
                )
                if not device_resp or "device_code" not in device_resp:
                    errors["base"] = "device_flow_failed"
                else:
                    self._device_code = device_resp["device_code"]
                    self._code_verifier = code_verifier
                    self._verification_uri_complete = device_resp.get(
                        "verification_uri_complete"
                    ) or (
                        device_resp.get("verification_uri", "")
                        + "?user_code="
                        + device_resp.get("user_code", "")
                    )
                    self._interval = int(device_resp.get("interval", 5))
                    return await self.async_step_device_flow()

        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLIENT_ID,
                        default=user_input.get(CONF_CLIENT_ID) if user_input else "",
                    ): str,
                    vol.Required(
                        CONF_GCID,
                        default=user_input.get(CONF_GCID) if user_input else "",
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_device_flow(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the verification URL and wait for user to complete login."""
        if not self._client_id or not self._device_code or not self._code_verifier:
            return self.async_abort(reason="invalid_flow")

        if user_input is not None:
            tokens = await _poll_token(
                self.hass,
                self._client_id,
                self._device_code,
                self._code_verifier,
                self._interval,
            )
            if not tokens:
                return self.async_show_form(
                    step_id="device_flow",
                    data_schema=vol.Schema({}),
                    errors={"base": "device_flow_failed"},
                    description_placeholders={
                        "verification_url": self._verification_uri_complete or "",
                    },
                )

            id_token = (tokens.get("id_token") or "").strip()
            refresh_token = (tokens.get("refresh_token") or "").strip()
            access_token = (tokens.get("access_token") or "").strip()
            expires_in = int(tokens.get("expires_in", 3600))
            import time
            token_expires = int(time.time()) + expires_in

            await self.async_set_unique_id(self._gcid.lower())
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"BMW CarData ({self._gcid[:8]}…)",
                data={
                    CONF_CLIENT_ID: self._client_id,
                    CONF_GCID: self._gcid,
                    CONF_ID_TOKEN: id_token,
                    CONF_REFRESH_TOKEN: refresh_token,
                    CONF_ACCESS_TOKEN: access_token,
                    CONF_TOKEN_EXPIRES: token_expires,
                },
            )

        return self.async_show_form(
            step_id="device_flow",
            data_schema=vol.Schema({}),
            description_placeholders={
                "verification_url": self._verification_uri_complete or "",
            },
        )


class BMWCarDataOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle BMW CarData options (reauthentication)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow. Config entry is passed by the framework but the base OptionsFlow does not accept it."""
        super().__init__()
        self._device_code: str | None = None
        self._code_verifier: str | None = None
        self._verification_uri_complete: str | None = None
        self._interval: int = 5

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask user if they want to reauthenticate, then request device code and go to verification step."""
        if user_input is not None:
            entry = self.config_entry
            data = entry.data
            client_id = (data.get(CONF_CLIENT_ID) or "").strip()
            gcid = (data.get(CONF_GCID) or "").strip()
            if not client_id or not gcid:
                return self.async_abort(reason="cannot_connect")
            code_verifier = _pkce_code_verifier()
            code_challenge = _pkce_code_challenge(code_verifier)
            device_resp = await _request_device_code(self.hass, client_id, code_challenge)
            if not device_resp or "device_code" not in device_resp:
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema({}),
                    errors={"base": "device_flow_failed"},
                )
            self._device_code = device_resp["device_code"]
            self._code_verifier = code_verifier
            self._verification_uri_complete = device_resp.get(
                "verification_uri_complete"
            ) or (
                device_resp.get("verification_uri", "")
                + "?user_code="
                + device_resp.get("user_code", "")
            )
            self._interval = int(device_resp.get("interval", 5))
            return await self.async_step_reauth_verify()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
        )

    async def async_step_reauth_verify(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show verification URL and poll for tokens; on success update config entry and show success step."""
        if not self._device_code or not self._code_verifier:
            return self.async_abort(reason="cannot_connect")

        entry = self.config_entry
        client_id = (entry.data.get(CONF_CLIENT_ID) or "").strip()

        if user_input is not None:
            tokens = await _poll_token(
                self.hass,
                client_id,
                self._device_code,
                self._code_verifier,
                self._interval,
            )
            if not tokens:
                return self.async_show_form(
                    step_id="reauth_verify",
                    data_schema=vol.Schema({}),
                    errors={"base": "device_flow_failed"},
                    description_placeholders={
                        "verification_url": self._verification_uri_complete or "",
                    },
                )

            import time
            id_token = (tokens.get("id_token") or "").strip()
            refresh_token = (tokens.get("refresh_token") or "").strip()
            access_token = (tokens.get("access_token") or "").strip()
            expires_in = int(tokens.get("expires_in", 3600))
            token_expires = int(time.time()) + expires_in

            new_data = {
                **entry.data,
                CONF_ID_TOKEN: id_token,
                CONF_REFRESH_TOKEN: refresh_token,
                CONF_ACCESS_TOKEN: access_token,
                CONF_TOKEN_EXPIRES: token_expires,
            }
            self.hass.config_entries.async_update_entry(entry, data=new_data)

            # Notify running client to use new tokens so it reconnects without restart
            entry_data = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if entry_data and entry_data.get("client"):
                entry_data["client"].update_tokens(id_token)

            return await self.async_step_reauth_success()

        return self.async_show_form(
            step_id="reauth_verify",
            data_schema=vol.Schema({}),
            description_placeholders={
                "verification_url": self._verification_uri_complete or "",
            },
        )

    async def async_step_reauth_success(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show success message; user clicks Submit to close."""
        if user_input is not None:
            return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_success",
            data_schema=vol.Schema({}),
        )
