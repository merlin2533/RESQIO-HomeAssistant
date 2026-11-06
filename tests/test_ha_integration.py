"""Tests fuer Hub, Kopplungsablauf und Kalender. Brauchen Home Assistant und paho-mqtt (sonst uebersprungen)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("paho.mqtt.client")

from custom_components.resqio import config_flow
from custom_components.resqio import hub as hub_module
from custom_components.resqio.calendar import ResqioCalendar
from custom_components.resqio.parsing import (
    FmsValue,
    InvalidSettings,
    Kind,
    Reading,
    build_settings,
)


def _settings() -> Any:
    return build_settings(
        {
            "broker_host": "mqtt.example.de",
            "broker_port": 8883,
            "broker_tls": True,
            "username": "ha_test",
            "password": "geheim",
            "topic_root": "HomeAssistant",
            "departments": [{"slug": "hauptwache", "name": "Hauptwache"}],
        }
    )


def _hass() -> Any:
    hass = MagicMock()
    hass.loop.call_soon_threadsafe = lambda func, *args: func(*args)
    return hass


def _reason(value: int, *, failure: bool) -> Any:
    return SimpleNamespace(value=value, is_failure=failure)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(hub_module, "async_dispatcher_send", lambda _hass, *args: calls.append(args))
    return calls


@pytest.mark.parametrize("code", [4, 5, 134, 135])
def test_auth_rejection_stops_reconnect_and_requests_reauth(code: int, sent: list[tuple[Any, ...]]) -> None:
    started: list[bool] = []
    hub = hub_module.ResqioHub(_hass(), "entry", _settings(), on_auth_failed=lambda: started.append(True))
    client = MagicMock()
    hub._on_connect(client, None, None, _reason(code, failure=True), None)
    client.disconnect.assert_called_once()
    client.subscribe.assert_not_called()
    assert hub.auth_failed is True and hub.connected is False
    assert started == [True]
    # Wiederholte Ablehnung startet die Neukopplung nicht erneut.
    hub._on_connect(client, None, None, _reason(code, failure=True), None)
    assert started == [True]


def test_other_connect_failure_keeps_retrying(sent: list[tuple[Any, ...]]) -> None:
    started: list[bool] = []
    hub = hub_module.ResqioHub(_hass(), "entry", _settings(), on_auth_failed=lambda: started.append(True))
    client = MagicMock()
    hub._on_connect(client, None, None, _reason(3, failure=True), None)  # Server nicht verfuegbar
    client.disconnect.assert_not_called()
    assert hub.auth_failed is False and started == []


def test_connect_discards_stale_readings_before_subscribing(sent: list[tuple[Any, ...]]) -> None:
    hub = hub_module.ResqioHub(_hass(), "entry", _settings())
    hub.readings[("hauptwache", "alarm/state")] = Reading("hauptwache", "alarm/state", Kind.ALARM_STATE, "", True, True)
    hub.last_message_at["hauptwache"] = object()  # type: ignore[assignment]
    order: list[str] = []
    client = MagicMock()
    client.subscribe.side_effect = lambda *_a, **_k: order.append(f"subscribe:{len(hub.readings)}")
    hub._on_connect(client, None, None, _reason(0, failure=False), None)
    assert order == ["subscribe:0"]
    assert hub.readings == {} and hub.last_message_at == {}
    assert hub.connected is True
    assert ("resqio_update_entry", None, None) in sent


def test_first_result_wait_returns_after_timeout() -> None:
    hub = hub_module.ResqioHub(MagicMock(), "entry", _settings())
    asyncio.run(hub.async_wait_first_result(0.01))
    assert hub.auth_failed is False


# --------------------------------------------------------------------------- Kopplungsablauf


def test_pairing_exchange_is_not_repeated_after_broker_check_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    exchanges: list[tuple[str, str]] = []
    payload = {
        "broker_host": "mqtt.example.de",
        "broker_port": 8883,
        "broker_tls": False,
        "username": "ha_test",
        "password": "geheim",
        "departments": [{"slug": "hauptwache", "name": "Hauptwache"}],
        "tls_warning": True,
    }

    async def fake_exchange(_hass: Any, url: str, code: str) -> Any:
        exchanges.append((url, code))
        return payload

    async def fake_version(_hass: Any, _url: str) -> str | None:
        return "6.12.3"

    results = iter(["cannot_connect", None])

    async def executor(_func: Any, _settings: Any) -> str | None:
        return next(results)

    monkeypatch.setattr(config_flow, "_exchange_code", fake_exchange)
    monkeypatch.setattr(config_flow, "_fetch_server_version", fake_version)
    flow = config_flow.ResqioConfigFlow()
    flow.hass = SimpleNamespace(async_add_executor_job=executor)  # type: ignore[assignment]
    user_input = {"url": "https://resqio.example.de/", "code": "abcd-1234"}

    with pytest.raises(InvalidSettings) as failure:
        asyncio.run(flow._async_pair(user_input))
    assert failure.value.key == "cannot_connect"

    settings, warning = asyncio.run(flow._async_pair(user_input))
    assert exchanges == [("https://resqio.example.de", "ABCD1234")]  # nur ein Tausch
    assert settings.server_version == "6.12.3"
    assert warning == ""  # tls_warning wird angezeigt (Text leer, Server meldete nur true)


# --------------------------------------------------------------------------- Kalender


def _calendar(hub: Any, ident: str = "lf-10") -> ResqioCalendar:
    return ResqioCalendar(
        hub, "hauptwache", f"reservations/vehicle/{ident}", Kind.RESERVATIONS_VEHICLE, vehicle_id=ident
    )


def _hub_with(*readings: Reading) -> Any:
    hub = hub_module.ResqioHub(MagicMock(), "entry", _settings())
    for reading in readings:
        hub.readings[(reading.slug, reading.key)] = reading
    return hub


def _reservation(ident: str, value: Any) -> Reading:
    return Reading("hauptwache", f"reservations/vehicle/{ident}", Kind.RESERVATIONS_VEHICLE, ident, value, True)


def test_calendar_name_prefers_payload_then_fms_then_fallback() -> None:
    fms = Reading("hauptwache", "vehicles/lf-10/fms", Kind.VEHICLE_FMS, "lf-10", FmsValue(2, "x", "LF 10/6"), True)
    assert _calendar(_hub_with(_reservation("lf-10", {"name": "Löschfahrzeug", "items": []}), fms)).name == (
        "Reservierungen Löschfahrzeug"
    )
    assert _calendar(_hub_with(_reservation("lf-10", {"name": None, "items": []}), fms)).name == (
        "Reservierungen LF 10/6"
    )
    assert _calendar(_hub_with(_reservation("lf-10", {"name": None, "items": []}))).name == "Reservierungen Lf 10"


def test_calendar_reads_items_from_object_payload() -> None:
    start = datetime(2999, 1, 1, 8, tzinfo=UTC)
    end = datetime(2999, 1, 1, 12, tzinfo=UTC)
    value = {"name": None, "items": [{"id": "r1", "start": start, "end": end}]}
    calendar = _calendar(_hub_with(_reservation("lf-10", value)))
    assert [(e.start, e.end) for e in calendar._events()] == [(start, end)]


def _flags(session_present: bool) -> Any:
    return SimpleNamespace(session_present=session_present)


def test_stale_session_replay_does_not_trigger_alarm_event(sent: list[tuple[Any, ...]]) -> None:
    hub = hub_module.ResqioHub(_hass(), "entry", _settings())
    client = MagicMock()
    hub._on_connect(client, None, _flags(True), _reason(0, failure=False), None)
    sent.clear()
    hub._handle_message("HomeAssistant/hauptwache/alarm/event", b"neu", False)
    assert not any(args and args[0] == hub_module.signal_alarm_event("entry") for args in sent)


def test_live_alarm_event_on_fresh_session_triggers(sent: list[tuple[Any, ...]]) -> None:
    hub = hub_module.ResqioHub(_hass(), "entry", _settings())
    hub._on_connect(MagicMock(), None, _flags(False), _reason(0, failure=False), None)
    sent.clear()
    hub._handle_message("HomeAssistant/hauptwache/alarm/event", b"neu", False)
    assert any(args and args[0] == hub_module.signal_alarm_event("entry") for args in sent)


def test_operation_client_is_persistent_and_probe_is_not() -> None:
    settings = _settings()
    persistent = hub_module._new_client(settings, "resqio-ha-x", persistent=True)
    probe = hub_module._new_client(settings, "resqio-ha-x-probe")
    assert persistent._clean_session is False
    assert probe._clean_session is True


def test_websocket_transport_sets_path() -> None:
    settings = build_settings(
        {
            "broker_host": "resqio.example.de",
            "broker_port": 443,
            "broker_tls": True,
            "broker_transport": "websockets",
            "ws_path": "/mqtt-ws",
            "username": "ha_test",
            "password": "geheim",
            "departments": [{"slug": "hauptwache", "name": "Hauptwache"}],
        }
    )
    client = hub_module._new_client(settings, "resqio-ha-x")
    assert client._transport == "websockets"
    assert client._websocket_path == "/mqtt-ws"
