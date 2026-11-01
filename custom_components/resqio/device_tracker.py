"""Einsatzposition als Geraetetracker (Datengruppe Koordinaten)."""

from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ResqioEntity, async_setup_dynamic
from .hub import ResqioHub
from .parsing import Kind


class ResqioPositionTracker(ResqioEntity, TrackerEntity):
    _attr_source_type = SourceType.GPS
    _attr_icon = "mdi:map-marker-alert"

    def __init__(self, hub: ResqioHub, slug: str, key: str) -> None:
        super().__init__(hub, slug, key, translation_key="alarm_position")

    @property
    def latitude(self) -> float | None:
        value = self._raw
        return value.get("lat") if isinstance(value, dict) else None

    @property
    def longitude(self) -> float | None:
        value = self._raw
        return value.get("lon") if isinstance(value, dict) else None


def _build(hub: ResqioHub, slug: str, key: str, kind: Kind, ident: str) -> list[Entity]:
    if kind is Kind.ALARM_COORDINATES:
        return [ResqioPositionTracker(hub, slug, key)]
    return []


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await async_setup_dynamic(hass, entry, "device_tracker", async_add_entities, _build)
