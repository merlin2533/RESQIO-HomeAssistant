"""RESQIO-Integration fuer Home Assistant: reiner MQTT-Empfaenger, keine Veroeffentlichung."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.const import Platform

from .hub import ResqioHub
from .parsing import ConnectionSettings, InvalidSettings

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.DEVICE_TRACKER,
]

type ResqioConfigEntry = ConfigEntry[ResqioHub]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry[ResqioHub]) -> bool:
    try:
        settings = ConnectionSettings.from_entry_data(entry.data)
    except InvalidSettings as err:
        raise ConfigEntryError(f"Gespeicherte Zugangsdaten sind ungueltig ({err.key})") from err

    hub = ResqioHub(hass, entry.entry_id, settings)
    entry.runtime_data = hub

    # Erst die Plattformen registrieren, dann verbinden: retained Nachrichten
    # kommen sofort nach dem Abonnieren und muessen Entitaeten finden.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await hub.async_start()
    entry.async_on_unload(hub.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[ResqioHub]) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
