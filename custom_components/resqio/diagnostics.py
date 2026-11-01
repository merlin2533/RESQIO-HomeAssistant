"""Diagnosedaten. Passwort und Benutzername werden entfernt, Werte nicht ausgegeben."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CA_PEM
from .hub import ResqioHub

TO_REDACT = {"password", "username", CONF_CA_PEM}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry[ResqioHub]) -> dict[str, Any]:
    hub = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "hub": hub.snapshot(),
    }
