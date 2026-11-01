"""Alarm-Ereignis (neu, nachalarmiert, beendet) als Event-Entitaet.

Das Topic ist nicht retained. Ausgeloest wird nur bei Live-Nachrichten (siehe hub.py).
"""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import signal_alarm_event
from .entity import ResqioEntity, async_setup_dynamic
from .hub import ResqioHub
from .parsing import ALARM_EVENT_TYPES, Kind


class ResqioAlarmEvent(ResqioEntity, EventEntity):
    _attr_event_types: ClassVar[list[str]] = list(ALARM_EVENT_TYPES)
    _attr_icon = "mdi:bell-ring"

    def __init__(self, hub: ResqioHub, slug: str, key: str) -> None:
        super().__init__(hub, slug, key, translation_key="alarm_event")

    @property
    def available(self) -> bool:
        return self._hub.connected

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_alarm_event(self._hub.entry_id), self._handle_event)
        )

    @callback
    def _handle_event(self, slug: str, event_type: str) -> None:
        if slug != self._slug:
            return
        self._trigger_event(event_type, {"department": slug})
        self.async_write_ha_state()


def _build(hub: ResqioHub, slug: str, key: str, kind: Kind, ident: str) -> list[Entity]:
    if kind is Kind.ALARM_EVENT:
        return [ResqioAlarmEvent(hub, slug, key)]
    return []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    await async_setup_dynamic(hass, entry, "event", async_add_entities, _build)
