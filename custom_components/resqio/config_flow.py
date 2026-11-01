"""Einrichtung: Kopplung per Code (Normalfall) oder manuell mit Zugangsdaten."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv  # noqa: F401 - Selektoren laden
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CAPABILITIES_PATH,
    CONF_CODE,
    CONF_URL,
    DEFAULT_BROKER_PORT,
    DOMAIN,
    PAIRING_EXCHANGE_PATH,
)
from .hub import probe_connection
from .parsing import (
    ConnectionSettings,
    InvalidSettings,
    build_settings,
    normalize_pairing_code,
    normalize_server_url,
    parse_departments_text,
    parse_pairing_response,
)

HTTP_TIMEOUT_SECONDS = 15
CAPABILITIES_TIMEOUT_SECONDS = 5

PAIRING_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_CODE): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
    }
)

MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required("broker_host"): TextSelector(),
        vol.Required("broker_port", default=DEFAULT_BROKER_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required("broker_tls", default=False): BooleanSelector(),
        vol.Required("username"): TextSelector(),
        vol.Required("password"): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        vol.Required("topic_root", default="HomeAssistant"): TextSelector(),
        vol.Required("departments"): TextSelector(),
        vol.Optional("ca_pem"): TextSelector(TextSelectorConfig(multiline=True)),
    }
)


async def _exchange_code(hass: HomeAssistant, url: str, code: str) -> Any:
    """POST {url}/api/ha-bridge/pairing/exchange. Fehler bleiben neutral."""
    session = async_get_clientsession(hass)
    try:
        async with (
            asyncio.timeout(HTTP_TIMEOUT_SECONDS),
            session.post(
                f"{url}{PAIRING_EXCHANGE_PATH}",
                json={"code": code},
                headers={"Accept": "application/json"},
            ) as response,
        ):
            if response.status == 429:
                raise InvalidSettings("rate_limited")
            if response.status != 200:
                raise InvalidSettings("pairing_failed")
            return await response.json(content_type=None)
    except InvalidSettings:
        raise
    except ValueError as err:
        raise InvalidSettings("invalid_response") from err
    except (ClientError, TimeoutError, OSError) as err:
        raise InvalidSettings("cannot_connect") from err


async def _fetch_server_version(hass: HomeAssistant, url: str) -> str | None:
    """Optional und fail-open: jeder Fehler ergibt None, nie ein Abbruch der Einrichtung."""
    session = async_get_clientsession(hass)
    try:
        async with (
            asyncio.timeout(CAPABILITIES_TIMEOUT_SECONDS),
            session.get(f"{url}{CAPABILITIES_PATH}", headers={"Accept": "application/json"}) as response,
        ):
            if response.status != 200:
                return None
            data = await response.json(content_type=None)
    except (ClientError, TimeoutError, OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return str(version)[:32] if isinstance(version, (str, int)) else None


class ResqioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["pairing", "manual"])

    async def async_step_pairing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_server_url(user_input[CONF_URL])
                code = normalize_pairing_code(user_input[CONF_CODE])
                payload = await _exchange_code(self.hass, url, code)
                settings = parse_pairing_response(payload, url)
                version = await _fetch_server_version(self.hass, url)
                settings = replace(settings, server_version=version)
                await self._async_check_connection(settings)
            except InvalidSettings as err:
                errors["base"] = err.key
            else:
                return await self._async_create(settings)
        return self.async_show_form(step_id="pairing", data_schema=PAIRING_SCHEMA, errors=errors)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                departments = parse_departments_text(str(user_input["departments"]))
                settings = build_settings(
                    {
                        **user_input,
                        "broker_port": int(user_input["broker_port"]),
                        "departments": [{"slug": d.slug, "name": d.name} for d in departments],
                    }
                )
                await self._async_check_connection(settings)
            except InvalidSettings as err:
                errors["base"] = err.key
            else:
                return await self._async_create(settings)
        return self.async_show_form(step_id="manual", data_schema=MANUAL_SCHEMA, errors=errors)

    async def _async_check_connection(self, settings: ConnectionSettings) -> None:
        """Prueft Erreichbarkeit und Login gegen den Broker, bevor etwas gespeichert wird."""
        error = await self.hass.async_add_executor_job(probe_connection, settings)
        if error is not None:
            raise InvalidSettings(error)

    async def _async_create(self, settings: ConnectionSettings) -> ConfigFlowResult:
        await self.async_set_unique_id(settings.username)
        self._abort_if_unique_id_configured()
        names = ", ".join(dept.name for dept in settings.departments)
        return self.async_create_entry(title=f"RESQIO {names}", data=settings.to_entry_data())
