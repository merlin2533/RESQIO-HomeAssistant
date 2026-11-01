"""RESQIO-Integration fuer Home Assistant: reiner MQTT-Empfaenger, keine Veroeffentlichung."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError

from .hub import ResqioHub
from .parsing import ConnectionSettings, InvalidSettings

FIRST_CONNECT_WAIT_SECONDS = 10

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

    def _start_reauth() -> None:
        # Nach dem Setup: Anmeldeablehnung im laufenden Betrieb fuehrt zur Neukopplung.
        if entry.state is not ConfigEntryState.SETUP_IN_PROGRESS:
            entry.async_start_reauth(hass)

    hub = ResqioHub(hass, entry.entry_id, settings, on_auth_failed=_start_reauth)
    entry.runtime_data = hub

    # Erst die Plattformen registrieren, dann verbinden: retained Nachrichten
    # kommen sofort nach dem Abonnieren und muessen Entitaeten finden.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await hub.async_start()
    entry.async_on_unload(hub.async_stop)

    # Beim ersten Verbinden kurz auf die Antwort des Brokers warten: lehnt er die Anmeldung ab,
    # meldet Home Assistant das als Anmeldeproblem (Neukopplung) statt endlos zu wiederholen.
    await hub.async_wait_first_result(FIRST_CONNECT_WAIT_SECONDS)
    if hub.auth_failed:
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        raise ConfigEntryAuthFailed("Der RESQIO-Zugang wurde abgelehnt. Bitte neu koppeln.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[ResqioHub]) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
