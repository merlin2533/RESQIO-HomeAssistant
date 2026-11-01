"""Sensoren: Alarmdaten, Fahrzeuge, Personal (Zahlen), Wartung, Veranstaltungen, Sperrungen."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ResqioEntity, ResqioStateMixin, async_setup_dynamic, jsonable
from .hub import ResqioHub
from .parsing import MAX_STATE_LENGTH, PERSONNEL_METRICS, FmsValue, Kind, humanize_slug


def _field(name: str) -> Callable[[Any], Any]:
    return lambda value: value.get(name) if isinstance(value, dict) else None


def _identity(value: Any) -> Any:
    return value


def _as_count(value: Any) -> int | None:
    return len(value) if isinstance(value, list) else None


def _alarm_status(value: Any) -> str | None:
    if value is None:
        return None
    return "alarm" if value else "idle"


def _fms_label(value: Any) -> str | None:
    return value.label if isinstance(value, FmsValue) else None


def _category_count(value: Any) -> int | None:
    return value.get("count") if isinstance(value, dict) else None


def _title(value: Any) -> str | None:
    return value.get("title") if isinstance(value, dict) else None


def _gauge_value(value: Any) -> float | None:
    return value.get("value") if isinstance(value, dict) else None


def _news_title(value: Any) -> str | None:
    return value[0].get("title") if isinstance(value, list) and value else None


def _named_count(value: Any) -> int | None:
    return value.get("count") if isinstance(value, dict) else None


class ResqioSensor(ResqioStateMixin, ResqioEntity, SensorEntity):
    """Ein Sensor, dessen Wert aus dem zuletzt empfangenen Topic-Wert gezogen wird."""

    def __init__(
        self,
        hub: ResqioHub,
        slug: str,
        key: str,
        extract: Callable[[Any], Any],
        *,
        field: str = "",
        translation_key: str | None = None,
        name: str | None = None,
        device_class: SensorDeviceClass | None = None,
        state_class: SensorStateClass | None = None,
        attributes: Callable[[Any], dict[str, Any]] | None = None,
        icon: str | None = None,
    ) -> None:
        super().__init__(hub, slug, key, field=field, translation_key=translation_key, name=name)
        self._extract = extract
        self._attributes_fn = attributes
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_icon = icon

    @property
    def native_value(self) -> Any:
        return self.truncate(self._extract(self._raw))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs: dict[str, Any] = {}
        if self._attributes_fn is not None:
            attrs.update(self._attributes_fn(self._raw))
        if isinstance(self._raw, str) and len(self._raw) > MAX_STATE_LENGTH:
            attrs["volltext"] = self._raw
        return attrs or None


def _build(hub: ResqioHub, slug: str, key: str, kind: Kind, ident: str) -> list[Entity]:
    reading = hub.reading(slug, key)
    value = reading.value if reading is not None else None

    match kind:
        case Kind.ALARM_STATE:
            return [ResqioSensor(hub, slug, key, _alarm_status, translation_key="alarm_status", icon="mdi:fire-truck")]

        case Kind.ALARM_ACTIVE:
            return [
                ResqioSensor(hub, slug, key, _field("keyword"), field="keyword", translation_key="keyword", icon="mdi:alert-outline"),
                ResqioSensor(hub, slug, key, _field("category"), field="category", translation_key="category", icon="mdi:tag-outline"),
                ResqioSensor(
                    hub, slug, key, _field("alarm_time"), field="alarm_time",
                    translation_key="alarm_time", device_class=SensorDeviceClass.TIMESTAMP,
                ),
            ]

        case Kind.ALARM_LOCATION:
            return [ResqioSensor(hub, slug, key, _identity, translation_key="location", icon="mdi:map-marker")]

        case Kind.ALARM_TEXT:
            return [ResqioSensor(hub, slug, key, _identity, translation_key="alarm_text", icon="mdi:text-box-outline")]

        case Kind.ALARM_VEHICLE_COUNT:
            return [
                ResqioSensor(
                    hub, slug, key, _identity, translation_key="vehicles_out",
                    state_class=SensorStateClass.MEASUREMENT, icon="mdi:fire-truck",
                )
            ]

        case Kind.VEHICLE_FMS:
            display = (value.name if isinstance(value, FmsValue) and value.name else None) or ident
            return [
                ResqioSensor(
                    hub, slug, key, _fms_label,
                    name=f"{display} FMS",
                    attributes=lambda v: {"fms": v.fms, "fahrzeug": v.name} if isinstance(v, FmsValue) else {},
                    icon="mdi:car-emergency",
                )
            ]

        case Kind.PERSONNEL if ident in PERSONNEL_METRICS:
            return [
                ResqioSensor(
                    hub, slug, key, _identity, translation_key=f"personnel_{ident}",
                    state_class=SensorStateClass.MEASUREMENT, icon="mdi:account-group",
                )
            ]

        case Kind.MAINTENANCE_TOTAL:
            return [
                ResqioSensor(
                    hub, slug, key, _identity, translation_key="maintenance_open_total",
                    state_class=SensorStateClass.MEASUREMENT, icon="mdi:wrench-clock",
                )
            ]

        case Kind.MAINTENANCE_CATEGORY:
            category = value.get("name") if isinstance(value, dict) and value.get("name") else humanize_slug(ident)
            return [
                ResqioSensor(
                    hub, slug, key, _category_count,
                    name=f"Wartungen offen: {category}",
                    state_class=SensorStateClass.MEASUREMENT,
                    attributes=lambda _v, c=category: {"kategorie": c, "kategorie_slug": ident},
                    icon="mdi:wrench-clock",
                )
            ]

        case Kind.EVENT_NEXT:
            return [
                ResqioSensor(
                    hub, slug, key, _title, translation_key="events_next",
                    attributes=lambda v: jsonable(v) if isinstance(v, dict) else {},
                    icon="mdi:calendar-star",
                )
            ]

        case Kind.DEFECTS_TOTAL:
            return [
                ResqioSensor(
                    hub, slug, key, _identity, translation_key="defects_open_total",
                    state_class=SensorStateClass.MEASUREMENT, icon="mdi:alert-circle-outline",
                )
            ]

        case Kind.DEFECTS_CATEGORY:
            category = value.get("name") if isinstance(value, dict) and value.get("name") else ident
            return [
                ResqioSensor(
                    hub, slug, key, _named_count,
                    name=f"Mängel offen: {category}",
                    state_class=SensorStateClass.MEASUREMENT,
                    attributes=lambda _v, c=category: {"kategorie": c, "kategorie_id": ident},
                    icon="mdi:alert-circle-outline",
                )
            ]

        case Kind.DEFECTS_SEVERITY:
            return [
                ResqioSensor(
                    hub, slug, key, _identity,
                    name=f"Mängel offen: {ident.capitalize()}",
                    state_class=SensorStateClass.MEASUREMENT,
                    attributes=lambda _v: {"schweregrad": ident},
                    icon="mdi:alert-octagon-outline",
                )
            ]

        case Kind.GAUGE:
            name = value.get("name") if isinstance(value, dict) and value.get("name") else humanize_slug(ident)
            return [
                ResqioSensor(
                    hub, slug, key, _gauge_value,
                    name=f"Pegel {name}",
                    state_class=SensorStateClass.MEASUREMENT,
                    attributes=lambda v: {
                        "einheit": v.get("unit") if isinstance(v, dict) else None,
                        "gemessen_am": jsonable(v.get("measured_at")) if isinstance(v, dict) else None,
                    },
                    icon="mdi:waves",
                )
            ]

        case Kind.NEWS_LATEST:
            return [
                ResqioSensor(
                    hub, slug, key, _news_title, translation_key="news_latest",
                    attributes=lambda v: {"meldungen": jsonable(v)} if isinstance(v, list) else {},
                    icon="mdi:newspaper-variant-outline",
                )
            ]

        case Kind.EVENT_UPCOMING:
            return [
                ResqioSensor(
                    hub, slug, key, _as_count, translation_key="events_upcoming",
                    state_class=SensorStateClass.MEASUREMENT,
                    attributes=lambda v: {"veranstaltungen": jsonable(v)} if isinstance(v, list) else {},
                    icon="mdi:calendar-multiple",
                )
            ]

        case Kind.ROAD_CLOSURES:
            return [
                ResqioSensor(
                    hub, slug, key, _as_count, translation_key="road_closures",
                    state_class=SensorStateClass.MEASUREMENT,
                    attributes=lambda v: {"sperrungen": jsonable(v)} if isinstance(v, list) else {},
                    icon="mdi:road-variant",
                )
            ]
    return []


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    await async_setup_dynamic(hass, entry, "sensor", async_add_entities, _build)
