"""Tests fuer die reine Parser-Logik (ohne Home Assistant)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import resqio_parsing as p

ROOT = "HomeAssistant"


def j(obj: object) -> bytes:
    return json.dumps(obj).encode("utf-8")


# --------------------------------------------------------------------------- Topics


def test_split_topic_accepts_slug_and_rest() -> None:
    assert p.split_topic(ROOT, "HomeAssistant/hauptwache/alarm/state") == ("hauptwache", ("alarm", "state"))


@pytest.mark.parametrize(
    "topic",
    [
        "Other/hauptwache/alarm/state",
        "HomeAssistant/Haupt_Wache/alarm/state",
        "HomeAssistant/hauptwache",
        "HomeAssistant//alarm/state",
        "HomeAssistant/hauptwache/",
        "HomeAssistantX/hauptwache/alarm/state",
    ],
)
def test_split_topic_rejects_foreign_or_malformed(topic: str) -> None:
    assert p.split_topic(ROOT, topic) is None


@pytest.mark.parametrize(
    ("parts", "kind", "ident"),
    [
        (("availability",), p.Kind.AVAILABILITY, ""),
        (("alarm", "state"), p.Kind.ALARM_STATE, ""),
        (("alarm", "active"), p.Kind.ALARM_ACTIVE, ""),
        (("alarm", "location"), p.Kind.ALARM_LOCATION, ""),
        (("alarm", "text"), p.Kind.ALARM_TEXT, ""),
        (("alarm", "event"), p.Kind.ALARM_EVENT, ""),
        (("alarm", "coordinates"), p.Kind.ALARM_COORDINATES, ""),
        (("alarm", "vehicles", "count"), p.Kind.ALARM_VEHICLE_COUNT, ""),
        (("vehicles", "lf-10", "fms"), p.Kind.VEHICLE_FMS, "lf-10"),
        (("personnel", "accepted"), p.Kind.PERSONNEL, "accepted"),
        (("maintenance", "open", "total"), p.Kind.MAINTENANCE_TOTAL, ""),
        (("maintenance", "open", "by_category", "cat-42"), p.Kind.MAINTENANCE_CATEGORY, "cat-42"),
        (("defects", "open", "total"), p.Kind.DEFECTS_TOTAL, ""),
        (("defects", "open", "by_category", "cat-7"), p.Kind.DEFECTS_CATEGORY, "cat-7"),
        (("defects", "open", "by_severity", "kritisch"), p.Kind.DEFECTS_SEVERITY, "kritisch"),
        (("gauges", "eder"), p.Kind.GAUGE, "eder"),
        (("events", "next"), p.Kind.EVENT_NEXT, ""),
        (("events", "upcoming"), p.Kind.EVENT_UPCOMING, ""),
        (("reservations", "all"), p.Kind.RESERVATIONS_ALL, ""),
        (("reservations", "vehicle", "lf-10"), p.Kind.RESERVATIONS_VEHICLE, "lf-10"),
        (("news", "latest"), p.Kind.NEWS_LATEST, ""),
        (("roads", "closures"), p.Kind.ROAD_CLOSURES, ""),
    ],
)
def test_classify_known_topics(parts: tuple[str, ...], kind: p.Kind, ident: str) -> None:
    assert p.classify_path(parts) == (kind, ident)


@pytest.mark.parametrize(
    "parts",
    [
        ("discovery", "sensor", "x", "config"),  # Discovery wird nicht ausgewertet
        ("alarm", "personnel"),  # bewusst nicht konsumiert
        ("events", "ev-123"),  # kein Topic pro Veranstaltung mehr
        ("personnel", "name"),  # keine Namen
        ("vehicles", "fms"),
        ("reservations", "vehicle"),
    ],
)
def test_classify_ignores_unknown_or_forbidden(parts: tuple[str, ...]) -> None:
    assert p.classify_path(parts) is None


def test_decode_reading_passes_retained_and_key() -> None:
    reading = p.decode_reading(ROOT, "HomeAssistant/hauptwache/alarm/state", b"alarm", retained=True)
    assert reading is not None
    assert reading.slug == "hauptwache"
    assert reading.key == "alarm/state"
    assert reading.value is True
    assert reading.retained is True


def test_decode_reading_empty_payload_is_none_value() -> None:
    reading = p.decode_reading(ROOT, "HomeAssistant/hauptwache/alarm/state", b"", retained=True)
    assert reading is not None and reading.value is None


def test_decode_reading_invalid_utf8_is_none_value() -> None:
    reading = p.decode_reading(ROOT, "HomeAssistant/hauptwache/alarm/text", b"\xff\xfe", retained=True)
    assert reading is not None and reading.value is None


def test_decode_reading_oversize_payload_is_treated_as_empty() -> None:
    big = j([{"start": "2026-11-01T10:00:00+01:00", "end": "2026-11-01T11:00:00+01:00", "id": "x" * 9000}])
    assert len(big) > p.MAX_PAYLOAD_BYTES
    reading = p.decode_reading(ROOT, "HomeAssistant/hauptwache/reservations/all", big, retained=True)
    assert reading is not None and reading.value is None


def test_decode_reading_foreign_topic_returns_none() -> None:
    assert p.decode_reading(ROOT, "other/hauptwache/alarm/state", b"alarm", retained=True) is None


# --------------------------------------------------------------------------- Alarm


def test_alarm_state_words() -> None:
    assert p.parse_value(p.Kind.ALARM_STATE, "alarm") is True
    assert p.parse_value(p.Kind.ALARM_STATE, " idle ") is False
    assert p.parse_value(p.Kind.ALARM_STATE, "maybe") is None


@pytest.mark.parametrize(
    ("text", "expected"), [("neu", "neu"), ("Nachalarmiert", "nachalarmiert"), ("beendet", "beendet"), ("ende", None)]
)
def test_alarm_event_types(text: str, expected: str | None) -> None:
    assert p.parse_value(p.Kind.ALARM_EVENT, text) == expected


def test_alarm_active_parses_time_and_assumes_utc_for_naive() -> None:
    value = p.parse_alarm_active(
        json.dumps({"keyword": "F2 Brand", "category": "Brand", "alarm_time": "2026-11-01T10:12:00"})
    )
    assert value is not None
    assert value["keyword"] == "F2 Brand"
    assert value["alarm_time"] == datetime(2026, 11, 1, 10, 12, tzinfo=UTC)


def test_alarm_active_with_offset_and_z() -> None:
    value = p.parse_alarm_active(json.dumps({"alarm_time": "2026-11-01T10:12:00Z"}))
    assert value is not None and value["alarm_time"].utcoffset() == timedelta(0)


def test_alarm_active_rejects_non_object() -> None:
    assert p.parse_alarm_active("[1,2]") is None
    assert p.parse_alarm_active("kein json") is None


def test_coordinates_range_checked() -> None:
    assert p.parse_coordinates('{"lat": 48.5, "lon": 9.2}') == {"lat": 48.5, "lon": 9.2}
    assert p.parse_coordinates('{"lat": 91, "lon": 9}') is None
    assert p.parse_coordinates('{"lat": "48", "lon": 9}') is None
    assert p.parse_coordinates('{"lat": true, "lon": 9}') is None


# --------------------------------------------------------------------------- Zaehler, FMS


@pytest.mark.parametrize(
    ("text", "expected"), [("0", 0), ("12", 12), ("-1", None), ("1.5", None), ("", None), ("abc", None)]
)
def test_parse_count(text: str, expected: int | None) -> None:
    assert p.parse_count(text) == expected


def test_fms_plain_number_and_json_name() -> None:
    plain = p.parse_fms("3")
    assert plain is not None and plain.fms == 3 and plain.label == "Einsatzübernahme / Anfahrt" and plain.name is None
    named = p.parse_fms('{"fms": 4, "name": "LF 10"}')
    assert named is not None and named.label == "Ankunft Einsatzstelle" and named.name == "LF 10"


@pytest.mark.parametrize("text", ["0", "7", '{"fms": 9}', '{"fms": "x"}', "{kaputt"])
def test_fms_out_of_range_or_broken(text: str) -> None:
    assert p.parse_fms(text) is None


def test_fms_labels_match_resqio_definitions() -> None:
    assert p.FMS_LABELS == {
        1: "Einsatzbereit über Funk",
        2: "Einsatzbereit auf Wache",
        3: "Einsatzübernahme / Anfahrt",
        4: "Ankunft Einsatzstelle",
        5: "Sprechwunsch",
        6: "Nicht einsatzbereit",
    }


def test_named_count_for_categories_and_defects() -> None:
    assert p.parse_named_count('{"name": "Atemschutz", "count": 3}') == {"name": "Atemschutz", "count": 3}
    assert p.parse_named_count("5") == {"name": None, "count": 5}
    assert p.parse_named_count('{"name": "X", "count": -2}') is None


# --------------------------------------------------------------------------- Heartbeat, Pegel


def test_heartbeat_iso_and_json() -> None:
    assert p.parse_heartbeat("2026-11-01T10:00:00+00:00") == datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    assert p.parse_heartbeat('{"ts": "2026-11-01T10:00:00Z"}') is not None
    assert p.parse_heartbeat("online") is None
    assert p.parse_heartbeat('{"ts": 5}') is None


def test_gauge_null_value_is_unknown() -> None:
    assert p.parse_gauge('{"name": "Eder", "value": null, "unit": "m"}') is None
    gauge = p.parse_gauge('{"name": "Eder", "value": 1.42, "unit": "m", "measured_at": "2026-11-01T10:00:00+00:00"}')
    assert gauge is not None and gauge["value"] == 1.42 and gauge["unit"] == "m"


# --------------------------------------------------------------------------- Listen: Kalender, News, Sperren


def test_calendar_events_keep_only_whitelisted_fields() -> None:
    payload = [
        {
            "id": "ev-1",
            "title": "Dienstabend",
            "type": "uebung",
            "start": "2026-11-05T19:00:00+01:00",
            "end": "2026-11-05T21:00:00+01:00",
            "location": "Gerätehaus",
            "description": "geheim",
            "contact_phone": "0170",
            "registrations": 12,
        }
    ]
    items = p.parse_calendar_items(json.dumps(payload), reservation=False)
    assert items is not None and len(items) == 1
    item = items[0]
    assert set(item) == {"id", "title", "type", "start", "end", "location", "registrations"}
    assert item["registrations"] == 12
    assert "description" not in item and "contact_phone" not in item


def test_reservations_have_no_names_or_purpose() -> None:
    payload = [
        {
            "id": "res-1",
            "start": "2026-11-05T08:00:00+01:00",
            "end": "2026-11-05T12:00:00+01:00",
            "purpose": "Umzug",
            "person_name": "Max Muster",
            "destination": "Berlin",
            "notes": "x",
        }
    ]
    items = p.parse_calendar_items(json.dumps(payload), reservation=True)
    assert items is not None and set(items[0]) == {"id", "start", "end"}
    assert "Muster" not in json.dumps(items, default=str)


def test_calendar_drops_invalid_time_ranges() -> None:
    payload = [
        {"id": "a", "start": "2026-11-05T12:00:00+01:00", "end": "2026-11-05T08:00:00+01:00"},
        {"id": "b", "start": "kaputt", "end": "2026-11-05T08:00:00+01:00"},
        {"id": "c", "start": "2026-11-05T08:00:00+01:00"},
        "kein objekt",
        {"id": "d", "start": "2026-11-05T08:00:00+01:00", "end": "2026-11-05T09:00:00+01:00"},
    ]
    items = p.parse_calendar_items(json.dumps(payload), reservation=True)
    assert items is not None and [i["id"] for i in items] == ["d"]


def test_calendar_list_is_capped() -> None:
    payload = [
        {"id": str(n), "start": "2026-11-05T08:00:00+01:00", "end": "2026-11-05T09:00:00+01:00"} for n in range(50)
    ]
    items = p.parse_calendar_items(json.dumps(payload), reservation=True)
    assert items is not None and len(items) == p.MAX_LIST_ITEMS


def test_calendar_rejects_non_list() -> None:
    assert p.parse_calendar_items('{"a": 1}', reservation=False) is None
    assert p.parse_calendar_items("nope", reservation=False) is None


def test_news_only_headline_and_summary() -> None:
    payload = [
        {
            "id": "n1",
            "headline": "Übung verschoben",
            "summary": "Neuer Termin folgt.",
            "content": "Volltext",
            "author": "Max",
            "attachments": [],
        },
        {"id": "n2", "summary": "ohne Titel"},
    ]
    items = p.parse_news(json.dumps(payload))
    assert items is not None and len(items) == 1
    assert set(items[0]) == {"id", "title", "summary"}
    assert "Volltext" not in json.dumps(items)


def test_closures_drop_geometry() -> None:
    payload = [
        {
            "name": "B312 Ortsdurchfahrt",
            "reason": "Baustelle",
            "start": "2026-11-01T06:00:00+01:00",
            "end": "2026-11-03T18:00:00+01:00",
            "polygon": [[9.1, 48.1], [9.2, 48.2]],
        }
    ]
    items = p.parse_closures(json.dumps(payload))
    assert items is not None and set(items[0]) == {"name", "start", "end"}
    assert "Baustelle" not in str(items)


# --------------------------------------------------------------------------- Einstellungen


def valid_raw(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "broker_host": "resqio.example.de",
        "broker_port": 8883,
        "broker_tls": True,
        "username": "ha-gh-1",
        "password": "geheim",
        "topic_root": "HomeAssistant",
        "departments": [
            {"slug": "hauptwache", "name": "Hauptwache"},
            {"slug": "ortsteil-nord", "name": "Ortsteil Nord"},
        ],
        "ca_pem": None,
    }
    raw.update(overrides)
    return raw


def test_build_settings_and_topic_filters_are_per_department() -> None:
    settings = p.build_settings(valid_raw(), server_url="https://resqio.example.de")
    assert settings.topic_filters() == [
        "HomeAssistant/hauptwache/#",
        "HomeAssistant/ortsteil-nord/#",
    ]
    assert settings.department_name("ortsteil-nord") == "Ortsteil Nord"
    assert settings.department_name("unbekannt") == "unbekannt"


def test_no_wildcard_across_departments() -> None:
    settings = p.build_settings(valid_raw())
    for topic_filter in settings.topic_filters():
        assert topic_filter.count("#") == 1 and topic_filter.endswith("/#")
        assert "+" not in topic_filter


def test_password_not_in_repr() -> None:
    settings = p.build_settings(valid_raw())
    assert "geheim" not in repr(settings)


def test_entry_data_round_trip() -> None:
    settings = p.build_settings(valid_raw(), server_url="https://x.example", server_version="6.12.0")
    restored = p.ConnectionSettings.from_entry_data(settings.to_entry_data())
    assert restored == settings


@pytest.mark.parametrize(
    ("overrides", "key"),
    [
        ({"broker_host": "bad host"}, "invalid_host"),
        ({"broker_port": 0}, "invalid_port"),
        ({"broker_port": "abc"}, "invalid_port"),
        ({"username": "a|b"}, "invalid_username"),
        ({"username": ""}, "invalid_username"),
        ({"password": ""}, "invalid_response"),
        ({"topic_root": "Home/Assistant"}, "invalid_topic_root"),
        ({"topic_root": "Home#"}, "invalid_topic_root"),
        ({"departments": []}, "invalid_departments"),
        ({"departments": [{"slug": "Haupt Wache"}]}, "invalid_departments"),
        ({"departments": [{"slug": "a"}, {"slug": "a"}]}, "invalid_departments"),
        ({"departments": ["hauptwache"]}, "invalid_departments"),
        ({"ca_pem": "kein zertifikat"}, "invalid_response"),
    ],
)
def test_build_settings_rejects(overrides: dict[str, object], key: str) -> None:
    with pytest.raises(p.InvalidSettings) as err:
        p.build_settings(valid_raw(**overrides))
    assert err.value.key == key


def test_pairing_response_requires_object() -> None:
    with pytest.raises(p.InvalidSettings) as err:
        p.parse_pairing_response(["x"], "https://x.example")
    assert err.value.key == "invalid_response"


def test_pairing_response_default_topic_root() -> None:
    raw = valid_raw()
    raw.pop("topic_root")
    settings = p.parse_pairing_response(raw, "https://x.example")
    assert settings.topic_root == "HomeAssistant"


def test_manual_departments_text() -> None:
    departments = p.parse_departments_text(" hauptwache , ortsteil-nord ")
    assert [d.slug for d in departments] == ["hauptwache", "ortsteil-nord"]
    assert departments[0].name == "Hauptwache"
    for bad in ["", " , ", "Haupt Wache", "UPPER"]:
        with pytest.raises(p.InvalidSettings):
            p.parse_departments_text(bad)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("https://x.example/", "https://x.example"), (" http://10.0.0.5:8080/resqio ", "http://10.0.0.5:8080/resqio")],
)
def test_normalize_server_url(raw: str, expected: str) -> None:
    assert p.normalize_server_url(raw) == expected


@pytest.mark.parametrize("raw", ["ftp://x", "x.example", "https://"])
def test_normalize_server_url_rejects(raw: str) -> None:
    with pytest.raises(p.InvalidSettings):
        p.normalize_server_url(raw)


def test_normalize_pairing_code() -> None:
    assert p.normalize_pairing_code(" ab3d-7k9m ") == "AB3D7K9M"
    with pytest.raises(p.InvalidSettings):
        p.normalize_pairing_code("ab!")


def test_humanize_slug() -> None:
    assert p.humanize_slug("atemschutz-pruefung") == "Atemschutz pruefung"
    assert p.humanize_slug("") == ""


# --------------------------------------------------------------------------- Architektur


def test_parsing_module_has_no_homeassistant_import() -> None:
    source = (Path(p.__file__)).read_text(encoding="utf-8")
    assert "homeassistant" not in source


# --------------------------------------------------------------------------- Client-ID


def test_client_id_has_reserved_prefix_and_username() -> None:
    client_id = p.make_client_id("ha_0123456789ab")
    assert client_id.startswith("resqio-ha-ha_0123456789ab-")
    assert len(client_id) <= 128


def test_client_id_is_unique_per_connection() -> None:
    assert p.make_client_id("ha_0123456789ab") != p.make_client_id("ha_0123456789ab")


def test_probe_client_id_differs_from_operating_id() -> None:
    probe = p.make_client_id("ha_0123456789ab", "probe")
    assert probe.startswith(p.CLIENT_ID_PREFIX)
    assert "-probe-" in probe


# --------------------------------------------------------------------------- Reservierungen mit Namen, Tausch-Antwort


def test_reservations_accept_object_with_name_and_items() -> None:
    payload = {
        "name": "  LF 10  ",
        "items": [
            {"id": "r1", "start": "2026-11-05T08:00:00+01:00", "end": "2026-11-05T12:00:00+01:00", "purpose": "x"}
        ],
    }
    parsed = p.parse_reservations(json.dumps(payload))
    assert parsed is not None
    assert parsed["name"] == "LF 10"
    assert [set(item) for item in parsed["items"]] == [{"id", "start", "end"}]


def test_reservations_accept_plain_list_without_name() -> None:
    payload = [{"id": "r1", "start": "2026-11-05T08:00:00+01:00", "end": "2026-11-05T12:00:00+01:00"}]
    parsed = p.parse_reservations(json.dumps(payload))
    assert parsed is not None and parsed["name"] is None and len(parsed["items"]) == 1


@pytest.mark.parametrize("text", ["nope", "42", '{"name": "LF"}', '{"items": "x"}'])
def test_reservations_reject_broken_payloads(text: str) -> None:
    assert p.parse_reservations(text) is None


def test_reservation_topic_value_is_object_for_both_kinds() -> None:
    payload = {"name": "MTW", "items": []}
    for key in ("reservations/vehicle/mtw", "reservations/all"):
        reading = p.decode_reading(ROOT, f"{ROOT}/hauptwache/{key}", j(payload), retained=True)
        assert reading is not None and reading.value == {"name": "MTW", "items": []}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"tls_warning": True}, ""),
        ({"tls_warning": "Verbindung ist unverschlüsselt"}, "Verbindung ist unverschlüsselt"),
        ({"tls_warning": False}, None),
        ({"tls_warning": ""}, None),
        ({}, None),
        ([], None),
    ],
)
def test_parse_tls_warning(payload: object, expected: str | None) -> None:
    assert p.parse_tls_warning(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"success": True, "data": {"version": "6.12.3"}}, "6.12.3"),
        ({"success": True, "data": {"version": 7}}, "7"),
        ({"version": "6.12.3"}, None),  # alte Form: Version nur noch unter data
        ({"data": {"version": True}}, None),
        ({"data": {"version": ""}}, None),
        ({"data": []}, None),
        ("x", None),
    ],
)
def test_parse_server_version(payload: object, expected: str | None) -> None:
    assert p.parse_server_version(payload) == expected


@pytest.mark.parametrize(
    ("url", "insecure"),
    [
        ("http://resqio.example.de", True),
        ("https://resqio.example.de", False),
        ("http://192.168.1.5:3000", False),
        ("http://localhost:3000", False),
        ("http://resqio", False),
        ("http://8.8.8.8", True),
    ],
)
def test_is_insecure_remote_url(url: str, insecure: bool) -> None:
    assert p.is_insecure_remote_url(url) is insecure


def test_vehicle_ident_is_validated() -> None:
    assert p.classify_path(("vehicles", "bad id", "fms")) is None
    assert p.classify_path(("reservations", "vehicle", "x" * 65)) is None


# --------------------------------------------------------------------------- Transport, Session, Replay


def test_transport_defaults_to_tcp_and_roundtrips() -> None:
    settings = p.build_settings(valid_raw())
    assert settings.broker_transport == "tcp" and settings.ws_path == "/mqtt"
    data = settings.to_entry_data()
    assert data["broker_transport"] == "tcp" and data["ws_path"] == "/mqtt"
    assert p.ConnectionSettings.from_entry_data(data).broker_transport == "tcp"


def test_websocket_transport_is_accepted_from_pairing_payload() -> None:
    raw = {**valid_raw(), "broker_transport": "WebSockets", "ws_path": "/mqtt-ws"}
    settings = p.build_settings(raw)
    assert settings.broker_transport == "websockets" and settings.ws_path == "/mqtt-ws"


@pytest.mark.parametrize(
    "extra",
    [
        {"broker_transport": "udp"},
        {"broker_transport": "websockets", "ws_path": "mqtt"},
        {"broker_transport": "websockets", "ws_path": "/a/../b"},
        {"broker_transport": "websockets", "ws_path": "/a b"},
    ],
)
def test_invalid_transport_is_rejected(extra: dict[str, str]) -> None:
    with pytest.raises(p.InvalidSettings) as err:
        p.build_settings({**valid_raw(), **extra})
    assert err.value.key == "invalid_transport"


def test_session_client_id_is_stable_and_keeps_prefix() -> None:
    first = p.make_session_client_id("ha_test", "entry-1")
    assert first == p.make_session_client_id("ha_test", "entry-1")
    assert first != p.make_session_client_id("ha_test", "entry-2")
    assert first.startswith(p.CLIENT_ID_PREFIX + "ha_test-")
    assert len(first) < 65


def test_replay_guard_blocks_stale_replay_after_start_but_not_fresh_session() -> None:
    guard = p.ReplayGuard(max_gap=120, window=10)
    guard.on_connect(100.0, session_present=True)  # Start mit alter Session: Nachlieferung moeglich
    assert guard.accepts_live_event(105.0) is False
    assert guard.accepts_live_event(111.0) is True

    fresh = p.ReplayGuard()
    fresh.on_connect(100.0, session_present=False)
    assert fresh.accepts_live_event(100.0) is True


def test_replay_guard_allows_replay_after_short_gap_only() -> None:
    guard = p.ReplayGuard(max_gap=120, window=10)
    guard.on_connect(0.0, session_present=False)
    guard.on_disconnect(50.0)
    guard.on_connect(80.0, session_present=True)  # 30 s Luecke: verpasste Alarme duerfen nachkommen
    assert guard.accepts_live_event(80.0) is True
    guard.on_disconnect(200.0)
    guard.on_disconnect(210.0)  # zaehlt ab der ersten Trennung
    guard.on_connect(400.0, session_present=True)  # 200 s Luecke: veraltet
    assert guard.accepts_live_event(401.0) is False
    assert guard.accepts_live_event(411.0) is True
