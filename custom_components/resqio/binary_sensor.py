"""Binaersensoren: Alarm aktiv und Verbindung zur RESQIO-Bridge."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .entity import ResqioEntity, async_setup_dynamic
from .hub import ResqioHub
from .parsing import HEARTBEAT_MAX_AGE_SECONDS, Kind


class ResqioAlarmBinarySensor(ResqioEntity, BinarySensorEntity):
    _attr_icon = "mdi:fire-alert"

    def __init__(self, hub: ResqioHub, slug: str, key: str) -> None:
        super().__init__(hub, slug, key, translation_key="alarm_active")

    @property
    def is_on(self) -> bool:
        return self._raw is True


class ResqioBridgeBinarySensor(ResqioEntity, BinarySensorEntity):
    """`on` solange der Heartbeat des Servers frisch ist (hoechstens 2 Minuten alt).

    Kein LWT: ein ausbleibender Heartbeat macht die Entitaet nach Ablauf der Frist unavailable.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, hub: ResqioHub, slug: str, key: str) -> None:
        super().__init__(hub, slug, key, translation_key="bridge_online")
        self._expiry_unsub: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_expiry)
        self._schedule_expiry()

    @callback
    def _handle_update(self, slug: str | None, key: str | None) -> None:
        if slug is None or (slug == self._slug and key == self._key):
            self._schedule_expiry()
        super()._handle_update(slug, key)

    @property
    def _beat(self) -> datetime | None:
        raw = self._raw
        return raw if isinstance(raw, datetime) else None

    @property
    def _fresh(self) -> bool:
        beat = self._beat
        if beat is None:
            return False
        return (dt_util.utcnow() - beat).total_seconds() <= HEARTBEAT_MAX_AGE_SECONDS

    @property
    def available(self) -> bool:
        return self._hub.connected and self._fresh

    @property
    def is_on(self) -> bool:
        return self._fresh

    def _cancel_expiry(self) -> None:
        if self._expiry_unsub is not None:
            self._expiry_unsub()
            self._expiry_unsub = None

    def _schedule_expiry(self) -> None:
        self._cancel_expiry()
        beat = self._beat
        if beat is None:
            return
        expiry = beat + timedelta(seconds=HEARTBEAT_MAX_AGE_SECONDS)
        if expiry <= dt_util.utcnow():
            return
        self._expiry_unsub = async_track_point_in_time(self.hass, self._on_expired, expiry)

    @callback
    def _on_expired(self, _now: datetime) -> None:
        self._expiry_unsub = None
        self.async_write_ha_state()


def _build(hub: ResqioHub, slug: str, key: str, kind: Kind, ident: str) -> list[Entity]:
    if kind is Kind.ALARM_STATE:
        return [ResqioAlarmBinarySensor(hub, slug, key)]
    if kind is Kind.AVAILABILITY:
        return [ResqioBridgeBinarySensor(hub, slug, key)]
    return []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    await async_setup_dynamic(hass, entry, "binary_sensor", async_add_entities, _build)
