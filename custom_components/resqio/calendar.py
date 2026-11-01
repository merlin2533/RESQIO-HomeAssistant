"""Kalender: Veranstaltungen, Reservierungen je Fahrzeug und Summe der Wehr.

Quelle sind Listen-Topics (hoechstens 20 Eintraege). Je Wehr getrennt, keine Mischung.
Reservierungen zeigen nur den Zeitraum; Namen und Zweck gibt es nicht.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .entity import ResqioEntity, async_setup_dynamic
from .hub import ResqioHub
from .parsing import Kind, humanize_slug


class ResqioCalendar(ResqioEntity, CalendarEntity):
    def __init__(
        self,
        hub: ResqioHub,
        slug: str,
        key: str,
        kind: Kind,
        *,
        translation_key: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(hub, slug, key, translation_key=translation_key, name=name)
        self._kind = kind
        self._attr_icon = "mdi:calendar-clock"

    def _events(self) -> list[CalendarEvent]:
        raw = self._raw
        if not isinstance(raw, list):
            return []
        events: list[CalendarEvent] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            start: datetime | None = item.get("start")
            end: datetime | None = item.get("end")
            if start is None or end is None:
                continue
            if self._kind is Kind.EVENT_UPCOMING:
                summary = item.get("title") or "Veranstaltung"
                location = item.get("location")
            else:
                summary = "Reservierung"
                location = None
            events.append(CalendarEvent(summary=summary, start=start, end=end, location=location))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.utcnow()
        upcoming = [event for event in self._events() if event.end >= now]
        return min(upcoming, key=lambda event: event.start) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [event for event in self._events() if event.start < end_date and event.end > start_date]


def _build(hub: ResqioHub, slug: str, key: str, kind: Kind, ident: str) -> list[Entity]:
    if kind is Kind.EVENT_UPCOMING:
        return [ResqioCalendar(hub, slug, key, kind, translation_key="events_calendar")]
    if kind is Kind.RESERVATIONS_ALL:
        return [ResqioCalendar(hub, slug, key, kind, translation_key="reservations_all")]
    if kind is Kind.RESERVATIONS_VEHICLE:
        # Der Name kommt nicht aus dem Topic; angezeigt wird die Fahrzeugkennung.
        return [ResqioCalendar(hub, slug, key, kind, name=f"Reservierungen {humanize_slug(ident)}")]
    return []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    await async_setup_dynamic(hass, entry, "calendar", async_add_entities, _build)
