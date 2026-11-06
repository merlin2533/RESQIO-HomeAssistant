"""Einrichtung: Kopplung per Code (Normalfall) oder manuell mit Zugangsdaten."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv  # noqa: F401 - Selektoren laden
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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
    DEFAULT_WS_PATH,
    TRANSPORT_TCP,
    TRANSPORTS,
    ConnectionSettings,
    InvalidSettings,
    build_settings,
    normalize_pairing_code,
    normalize_server_url,
    parse_departments_text,
    parse_pairing_response,
    parse_server_version,
    parse_tls_warning,
)

HTTP_TIMEOUT_SECONDS = 15
CAPABILITIES_TIMEOUT_SECONDS = 5


def _pairing_schema(default_url: str | None = None) -> vol.Schema:
    url_key = vol.Required(CONF_URL, default=default_url) if default_url else vol.Required(CONF_URL)
    return vol.Schema(
        {
            url_key: TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
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
        vol.Required("broker_transport", default=TRANSPORT_TCP): SelectSelector(
            SelectSelectorConfig(
                options=list(TRANSPORTS),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="broker_transport",
            )
        ),
        vol.Optional("ws_path", default=DEFAULT_WS_PATH): TextSelector(),
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
    return parse_server_version(data)


class ResqioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        # Der Code ist nur einmal gueltig. Das Ergebnis des Tauschs bleibt deshalb im Flow, damit
        # eine fehlgeschlagene Broker-Pruefung ohne neuen Code wiederholt werden kann.
        self._exchanged: tuple[str, str, ConnectionSettings, str | None] | None = None
        self._pending: ConnectionSettings | None = None
        self._tls_detail = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["pairing", "manual"])

    async def async_step_pairing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_pairing_step("pairing", user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_pairing_step("reauth_confirm", user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_pairing_step("reconfigure", user_input)

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
                return await self._async_complete(settings)
        return self.async_show_form(step_id="manual", data_schema=MANUAL_SCHEMA, errors=errors)

    async def async_step_tls_notice(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Hinweis auf eine unverschluesselte Verbindung; erst nach Bestaetigung wird gespeichert."""
        if self._pending is None:
            return self.async_abort(reason="unknown")
        if user_input is not None:
            return await self._async_complete(self._pending)
        return self.async_show_form(
            step_id="tls_notice",
            data_schema=vol.Schema({}),
            description_placeholders={"detail": self._tls_detail},
        )

    async def _async_pairing_step(self, step_id: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                settings, warning = await self._async_pair(user_input)
            except InvalidSettings as err:
                errors["base"] = err.key
            else:
                if warning is not None:
                    self._pending = settings
                    self._tls_detail = warning
                    return await self.async_step_tls_notice()
                return await self._async_complete(settings)
        return self.async_show_form(
            step_id=step_id,
            data_schema=_pairing_schema(self._known_server_url()),
            errors=errors,
        )

    def _known_server_url(self) -> str | None:
        """Bei Neukopplung und Umkonfiguration ist die bisherige Adresse vorbelegt."""
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
        elif self.source == SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
        else:
            return None
        url = entry.data.get("server_url")
        return url if isinstance(url, str) and url else None

    async def _async_pair(self, user_input: dict[str, Any]) -> tuple[ConnectionSettings, str | None]:
        url = normalize_server_url(user_input[CONF_URL])
        code = normalize_pairing_code(user_input[CONF_CODE])
        cached = self._exchanged
        if cached is not None and cached[0] == url and cached[1] == code:
            _, _, settings, warning = cached
        else:
            payload = await _exchange_code(self.hass, url, code)
            settings = parse_pairing_response(payload, url)
            settings = replace(settings, server_version=await _fetch_server_version(self.hass, url))
            warning = parse_tls_warning(payload)
            self._exchanged = (url, code, settings, warning)
        await self._async_check_connection(settings)
        return settings, warning

    async def _async_check_connection(self, settings: ConnectionSettings) -> None:
        """Prueft Erreichbarkeit und Login gegen den Broker, bevor etwas gespeichert wird."""
        error = await self.hass.async_add_executor_job(probe_connection, settings)
        if error is not None:
            raise InvalidSettings(error)

    async def _async_complete(self, settings: ConnectionSettings) -> ConfigFlowResult:
        """Legt den Eintrag an oder aktualisiert den bestehenden (Neukopplung, Umkonfiguration)."""
        await self.async_set_unique_id(settings.username)
        names = ", ".join(dept.name for dept in settings.departments)
        title = f"RESQIO {names}"
        data = settings.to_entry_data()
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data, title=title, reason="reauth_successful"
            )
        if self.source == SOURCE_RECONFIGURE:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=data, title=title, reason="reconfigure_successful"
            )
        # Erneutes Koppeln desselben Zugangs: Zugangsdaten im bestehenden Eintrag aktualisieren.
        updates = {key: value for key, value in data.items() if value is not None or key == "ca_pem"}
        self._abort_if_unique_id_configured(updates=updates)
        return self.async_create_entry(title=title, data=data)
