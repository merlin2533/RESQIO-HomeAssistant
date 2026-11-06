"""Gemeinsame Basis fuer alle Entitaeten und das dynamische Anlegen.

Entitaeten entstehen erst, wenn das zugehoerige Topic eintrifft (Datengruppen
sind serverseitig abschaltbar). Beim Start von Home Assistant werden Entitaeten,
die schon in der Entity-Registry stehen, sofort wieder angelegt, damit Automationen
nach einem Neustart nicht ins Leere zeigen.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, MODEL, signal_new_topic, signal_update
from .hub import ResqioHub
from .parsing import MAX_STATE_LENGTH, Kind, classify_path

BuildFn = Callable[[ResqioHub, str, str, Kind, str], list[Entity]]


def jsonable(value: Any) -> Any:
    """Wandelt datetime-Werte fuer State-Attribute in ISO-Text um."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


class ResqioEntity(Entity):
    """Eine Entitaet, die an einem Topic (Wehr-Slug + Topic-Rest) haengt."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hub: ResqioHub,
        slug: str,
        key: str,
        *,
        field: str = "",
        translation_key: str | None = None,
        name: str | None = None,
    ) -> None:
        self._hub = hub
        self._slug = slug
        self._key = key
        self._field = field
        self._attr_translation_key = translation_key
        self._attr_name = name
        # Trennzeichen "|": Benutzername enthaelt es nicht (Validierung), Topic-Reste schon eher.
        self._attr_unique_id = "|".join([hub.base_id, slug, key, field])
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{hub.base_id}:{slug}")},
            name=f"RESQIO {hub.department_name(slug)}",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_update(self._hub.entry_id), self._handle_update)
        )

    @callback
    def _handle_update(self, slug: str | None, key: str | None) -> None:
        if slug is None or (slug == self._slug and key == self._key):
            self.async_write_ha_state()

    @property
    def _raw(self) -> Any:
        reading = self._hub.reading(self._slug, self._key)
        return reading.value if reading is not None else None

    @property
    def available(self) -> bool:
        return self._hub.connected and self._raw is not None


DIAGNOSTIC_PREFIX = "diagnostic"


class ResqioDiagnosticEntity(ResqioEntity):
    """Diagnose-Entitaet zur Verbindung. Haengt an keinem Topic und ist immer verfuegbar.

    Der Schluessel beginnt mit `diagnostic/`; die Wiederherstellung aus der Registry ueberspringt
    ihn (kein Topic), weil diese Entitaeten beim Plattform-Setup ohnehin direkt angelegt werden.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: ResqioHub, slug: str, field: str, translation_key: str) -> None:
        super().__init__(hub, slug, f"{DIAGNOSTIC_PREFIX}/{field}", field=field, translation_key=translation_key)

    @property
    def available(self) -> bool:
        return True

    @callback
    def _handle_update(self, slug: str | None, key: str | None) -> None:
        if slug is None or slug == self._slug:
            self.async_write_ha_state()


class ResqioStateMixin:
    """Kuerzt Zustaende auf die Home-Assistant-Grenze und legt den Volltext in Attribute."""

    @staticmethod
    def truncate(value: Any) -> Any:
        if isinstance(value, str) and len(value) > MAX_STATE_LENGTH:
            return value[: MAX_STATE_LENGTH - 1] + "…"
        return value


async def async_setup_dynamic(
    hass: HomeAssistant,
    entry: ConfigEntry,
    platform: str,
    async_add_entities: AddEntitiesCallback,
    build: BuildFn,
) -> None:
    """Legt Entitaeten an, sobald ihr Topic eintrifft, und stellt bekannte wieder her."""
    hub: ResqioHub = entry.runtime_data
    known: set[str] = set()

    def _add(entities: list[Entity]) -> None:
        fresh = [e for e in entities if e.unique_id not in known]
        known.update(e.unique_id for e in fresh if e.unique_id)
        if fresh:
            async_add_entities(fresh)

    @callback
    def _on_new_topic(key: tuple[str, str]) -> None:
        reading = hub.readings.get(key)
        if reading is None:
            return
        _add(build(hub, reading.slug, reading.key, reading.kind, reading.ident))

    # Wiederherstellung aus der Entity-Registry (ohne Topic-Wert: unavailable bis Nachricht).
    registry = er.async_get(hass)
    restore_ids: set[str] = set()
    restore_keys: set[tuple[str, str]] = set()
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != platform or not reg_entry.unique_id:
            continue
        parsed = _parse_unique_id(reg_entry.unique_id, hub.base_id)
        if parsed is None:
            continue
        slug, key = parsed
        restore_ids.add(reg_entry.unique_id)
        restore_keys.add((slug, key))
    for slug, key in sorted(restore_keys):
        classified = classify_path(tuple(key.split("/")))
        if classified is None:
            continue
        kind, ident = classified
        restored = build(hub, slug, key, kind, ident)
        async_add_entities([e for e in restored if e.unique_id in restore_ids])
        known.update(e.unique_id for e in restored if e.unique_id in restore_ids)

    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_topic(entry.entry_id), _on_new_topic))
    # Topics, die schon vor dem Plattform-Setup eingetroffen sind.
    for key in list(hub.readings):
        _on_new_topic(key)


def _parse_unique_id(unique_id: str, base_id: str) -> tuple[str, str] | None:
    """Umkehrung von ResqioEntity-unique_id: `base|slug|key|field`. Key darf "|" enthalten."""
    parts = unique_id.split("|")
    if len(parts) < 4 or parts[0] != base_id:
        return None
    slug = parts[1]
    key = "|".join(parts[2:-1])
    return (slug, key) if slug and key else None
