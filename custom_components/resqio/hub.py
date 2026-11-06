"""Verbindung zum RESQIO-MQTT-Broker (nur lesen) und Verteilung der Nachrichten.

Die Integration verbindet sich mit eigenen Zugangsdaten zum RESQIO-Broker, nicht
ueber die MQTT-Integration von Home Assistant. Sie abonniert je Wehr
`<root>/<slug>/#` und veroeffentlicht nie etwas.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import signal_alarm_event, signal_new_topic, signal_update
from .parsing import ConnectionSettings, Kind, Reading, decode_reading, make_client_id

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 10
KEEPALIVE_SECONDS = 30
# Obergrenze fuer unterschiedliche Topics je Zugang (Schutz vor unbegrenztem Wachstum).
MAX_READINGS = 1000
# MQTT-Reasoncodes fuer ungueltige Zugangsdaten bzw. nicht autorisiert (MQTT 3.1.1 / 5).
_AUTH_FAILURE_CODES = {4, 5, 134, 135}


def build_ssl_context(ca_pem: str | None) -> ssl.SSLContext:
    """Muss im Executor laufen (blockierende Zertifikatsladung)."""
    if ca_pem:
        return ssl.create_default_context(cadata=ca_pem)
    return ssl.create_default_context()


def _new_client(settings: ConnectionSettings, client_id: str) -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set(settings.username, settings.password)
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    return client


def probe_connection(settings: ConnectionSettings) -> str | None:
    """Testet Erreichbarkeit und Login. Blockierend, im Executor aufrufen.

    Gibt None bei Erfolg zurueck, sonst den Fehlerschluessel `invalid_auth` oder
    `cannot_connect`. Die Meldung bleibt bewusst neutral.
    """
    outcome: dict[str, str | None] = {"error": "cannot_connect"}
    done = threading.Event()

    def on_connect(_client: Any, _userdata: Any, _flags: Any, reason: Any, _props: Any) -> None:
        if reason.is_failure:
            outcome["error"] = "invalid_auth" if reason.value in _AUTH_FAILURE_CODES else "cannot_connect"
        else:
            outcome["error"] = None
        done.set()

    client = _new_client(settings, make_client_id(settings.username, "probe"))
    client.on_connect = on_connect
    try:
        if settings.broker_tls:
            client.tls_set_context(build_ssl_context(settings.ca_pem))
        client.connect_async(settings.broker_host, settings.broker_port, KEEPALIVE_SECONDS)
        client.loop_start()
        if not done.wait(CONNECT_TIMEOUT_SECONDS):
            return "cannot_connect"
        return outcome["error"]
    except (OSError, ValueError):
        return "cannot_connect"
    finally:
        client.loop_stop()
        client.disconnect()


class ResqioHub:
    """Haelt die Verbindung und den letzten Wert je Topic (Schluessel: Slug + Topic-Rest)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        settings: ConnectionSettings,
        on_auth_failed: Callable[[], None] | None = None,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.settings = settings
        self.connected = False
        self.auth_failed = False
        self._on_auth_failed = on_auth_failed
        self._first_result = asyncio.Event()
        self.readings: dict[tuple[str, str], Reading] = {}
        self.last_message_at: dict[str, datetime] = {}
        self.message_count = 0
        self._client: mqtt.Client | None = None

    # ------------------------------------------------------------------ Lebenszyklus

    async def async_start(self) -> None:
        ssl_context = None
        if self.settings.broker_tls:
            ssl_context = await self.hass.async_add_executor_job(build_ssl_context, self.settings.ca_pem)
        client = _new_client(self.settings, make_client_id(self.settings.username))
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.on_subscribe = self._on_subscribe
        if ssl_context is not None:
            client.tls_set_context(ssl_context)
        client.connect_async(self.settings.broker_host, self.settings.broker_port, KEEPALIVE_SECONDS)
        client.loop_start()
        self._client = client

    async def async_wait_first_result(self, timeout: float) -> None:
        """Wartet, bis der Broker die erste Verbindung angenommen oder abgelehnt hat (Zeitablauf: kein Fehler)."""
        try:
            async with asyncio.timeout(timeout):
                await self._first_result.wait()
        except TimeoutError:
            return

    async def async_stop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        await self.hass.async_add_executor_job(_shutdown, client)
        self._set_connected(False)

    # ------------------------------------------------------------------ Abfragen

    @property
    def base_id(self) -> str:
        """Stabiler Teil aller Entitaets-IDs dieses Zugangs (der MQTT-Benutzername)."""
        return self.settings.username

    def department_name(self, slug: str) -> str:
        return self.settings.department_name(slug)

    def reading(self, slug: str, key: str) -> Reading | None:
        return self.readings.get((slug, key))

    def snapshot(self) -> dict[str, Any]:
        """Fuer Diagnosedaten: keine Werte, nur Struktur und Zeitstempel."""
        return {
            "connected": self.connected,
            "message_count": self.message_count,
            "last_message_at": {slug: when.isoformat() for slug, when in self.last_message_at.items()},
            "topics": sorted(
                {f"{slug}/{key}": reading.value is not None for (slug, key), reading in self.readings.items()}.items()
            ),
        }

    # ------------------------------------------------------------------ paho-Callbacks (Thread)

    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason: Any, _props: Any) -> None:
        if reason.is_failure:
            _LOGGER.warning("RESQIO-Broker hat die Verbindung abgelehnt (Code %s)", reason.value)
            if reason.value in _AUTH_FAILURE_CODES:
                # Falsche oder gesperrte Zugangsdaten werden durch Wiederholen nie richtig:
                # Schleife beenden und die Neukopplung anstossen.
                client.disconnect()
                self.hass.loop.call_soon_threadsafe(self._handle_auth_failure)
            return
        # Vor dem Abonnieren verwerfen: retained Nachrichten liefern den aktuellen Stand,
        # alles Uebrige waere nach einer Unterbrechung veraltet.
        self.hass.loop.call_soon_threadsafe(self._reset_readings)
        for topic_filter in self.settings.topic_filters():
            client.subscribe(topic_filter, qos=1)
        self.hass.loop.call_soon_threadsafe(self._set_connected, True)
        self.hass.loop.call_soon_threadsafe(self._first_result.set)

    def _on_disconnect(self, *_args: Any) -> None:
        self.hass.loop.call_soon_threadsafe(self._set_connected, False)

    def _on_subscribe(self, _client: Any, _userdata: Any, _mid: Any, reason_codes: Any, _props: Any) -> None:
        if any(getattr(code, "is_failure", False) for code in reason_codes):
            _LOGGER.warning("RESQIO-Broker hat ein Abonnement abgelehnt; Zugang und Wehr-Freigabe pruefen")

    def _on_message(self, _client: Any, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        self.hass.loop.call_soon_threadsafe(
            self._handle_message,
            message.topic,
            bytes(message.payload),
            bool(message.retain),
        )

    # ------------------------------------------------------------------ Loop-Thread

    @callback
    def _reset_readings(self) -> None:
        self.readings.clear()
        self.last_message_at.clear()
        async_dispatcher_send(self.hass, signal_update(self.entry_id), None, None)

    @callback
    def _handle_auth_failure(self) -> None:
        already = self.auth_failed
        self.auth_failed = True
        self._set_connected(False)
        self._first_result.set()
        if not already and self._on_auth_failed is not None:
            self._on_auth_failed()

    @callback
    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        async_dispatcher_send(self.hass, signal_update(self.entry_id), None, None)

    @callback
    def _handle_message(self, topic: str, payload: bytes, retained: bool) -> None:
        reading = decode_reading(self.settings.topic_root, topic, payload, retained)
        if reading is None:
            return
        self.message_count += 1
        self.last_message_at[reading.slug] = dt_util.utcnow()
        key = (reading.slug, reading.key)

        if reading.kind is Kind.ALARM_EVENT and reading.value and not reading.retained:
            # Ein Alarm-Ereignis loest nur aus, wenn es live ankommt. Retained Nachrichten
            # beim Verbinden waeren sonst ein falscher Alarm beim Start von Home Assistant.
            async_dispatcher_send(self.hass, signal_alarm_event(self.entry_id), reading.slug, reading.value)

        previous = self.readings.get(key)
        if previous is None and len(self.readings) >= MAX_READINGS:
            return
        self.readings[key] = reading
        if previous is None and reading.value is not None:
            async_dispatcher_send(self.hass, signal_new_topic(self.entry_id), key)
        async_dispatcher_send(self.hass, signal_update(self.entry_id), reading.slug, reading.key)


def _shutdown(client: mqtt.Client) -> None:
    client.loop_stop()
    client.disconnect()
