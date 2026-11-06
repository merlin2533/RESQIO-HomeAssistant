"""Reine Parser-Logik fuer die RESQIO-Integration.

Dieses Modul darf NICHT von Home Assistant abhaengen: es wird von den Tests
direkt geladen, ohne das Paket `custom_components.resqio` zu importieren.
Alle Funktionen sind deterministisch und werfen fuer fremde oder kaputte
Eingaben keine Ausnahmen, sondern liefern `None`.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

DEFAULT_TOPIC_ROOT = "HomeAssistant"

# HA verwirft States mit mehr als 255 Zeichen.
MAX_STATE_LENGTH = 255

# Klartext der FMS-Status.
FMS_LABELS: dict[int, str] = {
    1: "Einsatzbereit über Funk",
    2: "Einsatzbereit auf Wache",
    3: "Einsatzübernahme / Anfahrt",
    4: "Ankunft Einsatzstelle",
    5: "Sprechwunsch",
    6: "Nicht einsatzbereit",
}

# Personal-Zusammenfassung (Datengruppe 7): nur Zahlen, keine Namen.
PERSONNEL_METRICS: tuple[str, ...] = ("accepted", "tentative", "declined", "pending", "present")

# Alarm-Ereignisse aus `<wehr>/alarm/event` (nicht retained).
EVENT_NEW = "neu"
EVENT_REINFORCED = "nachalarmiert"
EVENT_ENDED = "beendet"
ALARM_EVENT_TYPES: tuple[str, ...] = (EVENT_NEW, EVENT_REINFORCED, EVENT_ENDED)

# Obergrenzen fuer Listen-Topics (Kalender, News) und Payload-Groesse.
MAX_LIST_ITEMS = 20
MAX_PAYLOAD_BYTES = 8192

# Heartbeat: der Server meldet regelmaessig seinen Zeitstempel. Ohne frischen
# Heartbeat gilt die Bridge als nicht verfuegbar (kein LWT, siehe README).
HEARTBEAT_MAX_AGE_SECONDS = 120

# Transport zum Broker: klassisch TCP oder MQTT ueber WebSockets (Port 443 hinter einem Reverse-Proxy,
# fuer Netze, in denen 1883/8883 gesperrt sind).
TRANSPORT_TCP = "tcp"
TRANSPORT_WEBSOCKETS = "websockets"
TRANSPORTS: tuple[str, ...] = (TRANSPORT_TCP, TRANSPORT_WEBSOCKETS)
DEFAULT_WS_PATH = "/mqtt"

# Persistente MQTT-Session: nach einer Unterbrechung liefert der Broker verpasste QoS-1-Nachrichten nach.
# Laenger als diese Luecke (oder nach einem Neustart von Home Assistant) gelten nachgelieferte
# Alarm-Ereignisse als veraltet und loesen keine Automation mehr aus (Tor-Oeffnung Stunden spaeter).
REPLAY_MAX_GAP_SECONDS = 120.0
REPLAY_GUARD_WINDOW_SECONDS = 10.0

# Ab dieser Dauer ohne Verbindung erscheint ein Reparaturhinweis.
LONG_OUTAGE_SECONDS = 600

_WS_PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]{0,63}$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_ROOT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_CODE_RE = re.compile(r"^[A-Z0-9]{6,32}$")
_IDENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_USERNAME_RE = re.compile(r"^[^|\s/+#]{1,128}$")


class Kind(StrEnum):
    """Art eines eingehenden Topics. Bestimmt, welche Entitaeten entstehen."""

    AVAILABILITY = "availability"
    ALARM_STATE = "alarm_state"
    ALARM_ACTIVE = "alarm_active"
    ALARM_LOCATION = "alarm_location"
    ALARM_TEXT = "alarm_text"
    ALARM_EVENT = "alarm_event"
    ALARM_COORDINATES = "alarm_coordinates"
    ALARM_VEHICLE_COUNT = "alarm_vehicle_count"
    VEHICLE_FMS = "vehicle_fms"
    PERSONNEL = "personnel"
    MAINTENANCE_TOTAL = "maintenance_total"
    MAINTENANCE_CATEGORY = "maintenance_category"
    DEFECTS_TOTAL = "defects_total"
    DEFECTS_CATEGORY = "defects_category"
    DEFECTS_SEVERITY = "defects_severity"
    GAUGE = "gauge"
    EVENT_NEXT = "event_next"
    EVENT_UPCOMING = "event_upcoming"
    RESERVATIONS_ALL = "reservations_all"
    RESERVATIONS_VEHICLE = "reservations_vehicle"
    NEWS_LATEST = "news_latest"
    ROAD_CLOSURES = "road_closures"


class InvalidSettings(ValueError):
    """Eingaben oder Serverantwort sind unbrauchbar. `key` ist ein Fehlerschluessel."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


@dataclass(frozen=True, slots=True)
class FmsValue:
    fms: int
    label: str
    name: str | None


@dataclass(frozen=True, slots=True)
class Reading:
    """Ein dekodiertes Topic. `value is None` heisst: leer, ungueltig oder geloescht."""

    slug: str
    key: str
    kind: Kind
    ident: str
    value: Any
    retained: bool


# --------------------------------------------------------------------------- Topics


def split_topic(root: str, topic: str) -> tuple[str, tuple[str, ...]] | None:
    """Zerlegt `<root>/<slug>/<rest...>` in (slug, rest-Segmente)."""
    prefix = f"{root}/"
    if not topic.startswith(prefix):
        return None
    segments = topic[len(prefix) :].split("/")
    if len(segments) < 2 or not all(segments):
        return None
    slug = segments[0]
    if not _SLUG_RE.match(slug):
        return None
    return slug, tuple(segments[1:])


def classify_path(parts: tuple[str, ...]) -> tuple[Kind, str] | None:
    """Ordnet die Segmente nach dem Slug einer Art und einer Kennung zu."""
    match parts:
        case ("availability",):
            return Kind.AVAILABILITY, ""
        case ("alarm", "state"):
            return Kind.ALARM_STATE, ""
        case ("alarm", "active"):
            return Kind.ALARM_ACTIVE, ""
        case ("alarm", "location"):
            return Kind.ALARM_LOCATION, ""
        case ("alarm", "text"):
            return Kind.ALARM_TEXT, ""
        case ("alarm", "event"):
            return Kind.ALARM_EVENT, ""
        case ("alarm", "coordinates"):
            return Kind.ALARM_COORDINATES, ""
        case ("alarm", "vehicles", "count"):
            return Kind.ALARM_VEHICLE_COUNT, ""
        case ("vehicles", vehicle_id, "fms") if _IDENT_RE.match(vehicle_id):
            return Kind.VEHICLE_FMS, vehicle_id
        case ("personnel", metric) if metric in PERSONNEL_METRICS:
            return Kind.PERSONNEL, metric
        case ("maintenance", "open", "total"):
            return Kind.MAINTENANCE_TOTAL, ""
        case ("maintenance", "open", "by_category", category) if category:
            return Kind.MAINTENANCE_CATEGORY, category
        case ("defects", "open", "total"):
            return Kind.DEFECTS_TOTAL, ""
        case ("defects", "open", "by_category", category) if category:
            return Kind.DEFECTS_CATEGORY, category
        case ("defects", "open", "by_severity", severity) if severity:
            return Kind.DEFECTS_SEVERITY, severity
        case ("gauges", gauge) if gauge:
            return Kind.GAUGE, gauge
        case ("events", "next"):
            return Kind.EVENT_NEXT, ""
        case ("events", "upcoming"):
            return Kind.EVENT_UPCOMING, ""
        case ("reservations", "all"):
            return Kind.RESERVATIONS_ALL, ""
        case ("reservations", "vehicle", vehicle_id) if _IDENT_RE.match(vehicle_id):
            return Kind.RESERVATIONS_VEHICLE, vehicle_id
        case ("news", "latest"):
            return Kind.NEWS_LATEST, ""
        case ("roads", "closures"):
            return Kind.ROAD_CLOSURES, ""
        case _:
            return None


def decode_reading(root: str, topic: str, payload: bytes, retained: bool) -> Reading | None:
    """Vollstaendige Auswertung einer MQTT-Nachricht. None = Topic gehoert nicht zu RESQIO."""
    split = split_topic(root, topic)
    if split is None:
        return None
    slug, parts = split
    classified = classify_path(parts)
    if classified is None:
        return None
    kind, ident = classified
    text = _decode_text(payload)
    if text is not None and len(payload) > MAX_PAYLOAD_BYTES:
        text = None  # zu gross: als leer behandeln, nie teilweise auswerten
    value = parse_value(kind, text) if text else None
    return Reading(
        slug=slug,
        key="/".join(parts),
        kind=kind,
        ident=ident,
        value=value,
        retained=retained,
    )


# --------------------------------------------------------------------------- Payloads


def parse_value(kind: Kind, text: str) -> Any:
    """Wertet den Nachrichtentext je nach Art aus. Ungueltig ergibt None."""
    match kind:
        case Kind.AVAILABILITY:
            return parse_heartbeat(text)
        case Kind.ALARM_STATE:
            return _parse_bool_word(text, "alarm", "idle")
        case Kind.ALARM_ACTIVE:
            return parse_alarm_active(text)
        case Kind.ALARM_LOCATION | Kind.ALARM_TEXT:
            return _clean_text(text)
        case Kind.ALARM_EVENT:
            word = text.strip().lower()
            return word if word in ALARM_EVENT_TYPES else None
        case Kind.ALARM_COORDINATES:
            return parse_coordinates(text)
        case Kind.ALARM_VEHICLE_COUNT | Kind.PERSONNEL | Kind.MAINTENANCE_TOTAL:
            return parse_count(text)
        case Kind.VEHICLE_FMS:
            return parse_fms(text)
        case Kind.MAINTENANCE_CATEGORY:
            return parse_named_count(text)
        case Kind.DEFECTS_TOTAL | Kind.DEFECTS_SEVERITY:
            return parse_count(text)
        case Kind.DEFECTS_CATEGORY:
            return parse_named_count(text)
        case Kind.GAUGE:
            return parse_gauge(text)
        case Kind.EVENT_NEXT:
            return parse_event(text)
        case Kind.EVENT_UPCOMING:
            return parse_calendar_items(text, reservation=False)
        case Kind.RESERVATIONS_ALL | Kind.RESERVATIONS_VEHICLE:
            return parse_reservations(text)
        case Kind.NEWS_LATEST:
            return parse_news(text)
        case Kind.ROAD_CLOSURES:
            return parse_closures(text)
    return None


def parse_count(text: str) -> int | None:
    """Ganze Zahl >= 0, sonst None."""
    try:
        number = int(text.strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def parse_fms(text: str) -> FmsValue | None:
    """Akzeptiert `3` oder `{"fms": 3, "name": "LF 10"}`."""
    raw = text.strip()
    name: str | None = None
    if raw.startswith("{"):
        data = _load_json_dict(raw)
        if data is None:
            return None
        name = _clean_text(str(data.get("name") or "")) or None
        number = _as_int(data.get("fms"))
    else:
        number = parse_count(raw)
    if number is None or number not in FMS_LABELS:
        return None
    return FmsValue(fms=number, label=FMS_LABELS[number], name=name)


def parse_alarm_active(text: str) -> dict[str, Any] | None:
    """`{"keyword", "category", "alarm_time"}`. alarm_time wird zu datetime."""
    data = _load_json_dict(text)
    if data is None:
        return None
    return {
        "keyword": _clean_text(str(data.get("keyword") or "")) or None,
        "category": _clean_text(str(data.get("category") or "")) or None,
        "alarm_time": parse_datetime(data.get("alarm_time")),
    }


def parse_coordinates(text: str) -> dict[str, float] | None:
    """`{"lat": 48.1, "lon": 9.2}` mit Bereichspruefung."""
    data = _load_json_dict(text)
    if data is None:
        return None
    lat, lon = _as_float(data.get("lat")), _as_float(data.get("lon"))
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return {"lat": lat, "lon": lon}


def parse_named_count(text: str) -> dict[str, Any] | None:
    """Wartungskategorie: plain `3` oder `{"name": "Atemschutz", "count": 3}`."""
    raw = text.strip()
    if raw.startswith("{"):
        data = _load_json_dict(raw)
        if data is None:
            return None
        count = _as_int(data.get("count"))
        name = _clean_text(str(data.get("name") or "")) or None
    else:
        count = parse_count(raw)
        name = None
    if count is None or count < 0:
        return None
    return {"name": name, "count": count}


def parse_event(text: str) -> dict[str, Any] | None:
    """Naechste Veranstaltung als Objekt (ohne Beschreibung)."""
    data = _load_json_dict(text)
    if data is None:
        return None
    return _sanitize_event(data)


def parse_calendar_items(text: str, *, reservation: bool) -> list[dict[str, Any]] | None:
    """Listen-Topic (Veranstaltungen oder Reservierungen). Hoechstens MAX_LIST_ITEMS Eintraege.

    Reservierungen werden auf id/start/end reduziert: keine Namen, kein Zweck.
    Eintraege ohne gueltigen Zeitraum fallen weg. Bei Reservierungen darf die Liste auch in einem
    Objekt `{"name": ..., "items": [...]}` stehen.
    """
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if reservation and isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list):
        return None
    items: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        start = parse_datetime(raw.get("start"))
        end = parse_datetime(raw.get("end"))
        if start is None or end is None or end <= start:
            continue
        if reservation:
            items.append({"id": _short(raw.get("id"), 64), "start": start, "end": end})
        else:
            event = _sanitize_event(raw)
            event["start"], event["end"] = start, end
            items.append(event)
        if len(items) >= MAX_LIST_ITEMS:
            break
    return items


def parse_reservations(text: str) -> dict[str, Any] | None:
    """Reservierungen als `{"name": str | None, "items": [...]}`.

    Akzeptiert die Liste (bisheriges Format) oder ein Objekt `{"name": ..., "items": [...]}`.
    Der Name ist optional und nur ein Anzeigename des Fahrzeugs.
    """
    items = parse_calendar_items(text, reservation=True)
    if items is None:
        return None
    name: str | None = None
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict):
        name = _short(_clean_text(str(data.get("name") or "")), 100)
    return {"name": name, "items": items}


def parse_news(text: str) -> list[dict[str, Any]] | None:
    """News: nur Titel (`headline`) und Kurztext (`summary`). Nie Volltext, Autor, Anhaenge."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    items = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        title = _short(raw.get("headline"), 200)
        if not title:
            continue
        items.append({"id": _short(raw.get("id"), 64), "title": title, "summary": _short(raw.get("summary"), 300)})
        if len(items) >= MAX_LIST_ITEMS:
            break
    return items


def parse_heartbeat(text: str) -> datetime | None:
    """Zeitstempel des Heartbeats: ISO-Text oder `{"ts": "..."}`."""
    raw = text.strip()
    if raw.startswith("{"):
        data = _load_json_dict(raw)
        raw = str(data.get("ts") or "") if data else ""
    return parse_datetime(raw)


def parse_gauge(text: str) -> dict[str, Any] | None:
    """Pegel: `{"name", "value", "unit", "measured_at"}`. value null = unbekannt."""
    data = _load_json_dict(text)
    if data is None:
        return None
    value = _as_float(data.get("value"))
    if value is None:
        return None
    return {
        "name": _short(data.get("name"), 100),
        "value": value,
        "unit": _short(data.get("unit"), 16),
        "measured_at": parse_datetime(data.get("measured_at")),
    }


def parse_closures(text: str) -> list[dict[str, Any]] | None:
    """Aktive Strassensperrungen: nur Name und Zeitraum (keine Geometrie, kein Freitext)."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    items = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        items.append(
            {
                "name": _short(raw.get("name"), 200),
                "start": parse_datetime(raw.get("start")),
                "end": parse_datetime(raw.get("end")),
            }
        )
        if len(items) >= MAX_LIST_ITEMS:
            break
    return items


def parse_datetime(value: Any) -> datetime | None:
    """ISO-8601. Ohne Zeitzone wird UTC angenommen (Annahme, siehe README)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def humanize_slug(slug: str) -> str:
    """Anzeigename aus einem Slug, z. B. `atemschutz-pruefung` -> `Atemschutz pruefung`."""
    words = slug.replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else slug


# --------------------------------------------------------------------------- Einstellungen


@dataclass(frozen=True, slots=True)
class Department:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class ConnectionSettings:
    broker_host: str
    broker_port: int
    broker_tls: bool
    username: str
    password: str = field(repr=False)
    topic_root: str
    departments: tuple[Department, ...]
    ca_pem: str | None = field(default=None, repr=False)
    server_url: str | None = None
    server_version: str | None = None
    broker_transport: str = TRANSPORT_TCP
    ws_path: str = DEFAULT_WS_PATH

    def topic_filters(self) -> list[str]:
        """Eine Subscription je Wehr. Nie `<root>/#` oder Wildcards ueber Wehrgrenzen."""
        return [f"{self.topic_root}/{dept.slug}/#" for dept in self.departments]

    def department_name(self, slug: str) -> str:
        for dept in self.departments:
            if dept.slug == slug:
                return dept.name
        return slug

    def to_entry_data(self) -> dict[str, Any]:
        return {
            "broker_host": self.broker_host,
            "broker_port": self.broker_port,
            "broker_tls": self.broker_tls,
            "username": self.username,
            "password": self.password,
            "topic_root": self.topic_root,
            "ca_pem": self.ca_pem,
            "departments": [{"slug": d.slug, "name": d.name} for d in self.departments],
            "server_url": self.server_url,
            "server_version": self.server_version,
            "broker_transport": self.broker_transport,
            "ws_path": self.ws_path,
        }

    @classmethod
    def from_entry_data(cls, data: Mapping[str, Any]) -> ConnectionSettings:
        return build_settings(
            data,
            server_url=data.get("server_url"),
            server_version=data.get("server_version"),
        )


def build_settings(
    raw: Mapping[str, Any],
    *,
    server_url: str | None = None,
    server_version: str | None = None,
) -> ConnectionSettings:
    """Gemeinsamer Validierungspfad fuer Kopplung, manuelle Eingabe und gespeicherte Daten."""
    host = str(raw.get("broker_host") or "").strip()
    if not host or any(ch.isspace() for ch in host) or "/" in host:
        raise InvalidSettings("invalid_host")

    port = _as_int(raw.get("broker_port"))
    if port is None or not 1 <= port <= 65535:
        raise InvalidSettings("invalid_port")

    username = str(raw.get("username") or "")
    if not _USERNAME_RE.match(username):
        raise InvalidSettings("invalid_username")

    password = str(raw.get("password") or "")
    if not password:
        raise InvalidSettings("invalid_response")

    root = str(raw.get("topic_root") or DEFAULT_TOPIC_ROOT).strip()
    if not _ROOT_RE.match(root):
        raise InvalidSettings("invalid_topic_root")

    departments = tuple(_parse_department(item) for item in raw.get("departments") or [])
    if not departments:
        raise InvalidSettings("invalid_departments")
    if len({d.slug for d in departments}) != len(departments):
        raise InvalidSettings("invalid_departments")

    ca_pem = str(raw.get("ca_pem") or "").strip() or None
    if ca_pem is not None and "BEGIN CERTIFICATE" not in ca_pem:
        raise InvalidSettings("invalid_response")

    transport = str(raw.get("broker_transport") or TRANSPORT_TCP).strip().lower()
    if transport not in TRANSPORTS:
        raise InvalidSettings("invalid_transport")
    ws_path = str(raw.get("ws_path") or DEFAULT_WS_PATH).strip()
    if not _WS_PATH_RE.match(ws_path) or ".." in ws_path:
        raise InvalidSettings("invalid_transport")

    return ConnectionSettings(
        broker_host=host,
        broker_port=port,
        broker_tls=bool(raw.get("broker_tls", False)),
        username=username,
        password=password,
        topic_root=root,
        departments=departments,
        ca_pem=ca_pem,
        server_url=server_url,
        server_version=server_version,
        broker_transport=transport,
        ws_path=ws_path,
    )


def parse_pairing_response(payload: Any, server_url: str) -> ConnectionSettings:
    """Antwort von `POST {url}/api/ha-bridge/pairing/exchange`."""
    if not isinstance(payload, dict):
        raise InvalidSettings("invalid_response")
    return build_settings(payload, server_url=server_url)


def parse_tls_warning(payload: Any) -> str | None:
    """Hinweis des Servers auf eine unverschluesselte Verbindung (`tls_warning`).

    Liefert None ohne Warnung, sonst den Hinweistext (leer, wenn der Server nur `true` meldet).
    """
    if not isinstance(payload, dict):
        return None
    warning = payload.get("tls_warning")
    if warning is True:
        return ""
    if isinstance(warning, str) and warning.strip():
        return _short(_clean_text(warning), 300) or ""
    return None


def parse_server_version(payload: Any) -> str | None:
    """Version aus der Antwort `{"success": true, "data": {"version": "..."}}`. Fail-open: sonst None."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    version = data.get("version") if isinstance(data, dict) else None
    if isinstance(version, bool) or not isinstance(version, (str, int)):
        return None
    return str(version).strip()[:32] or None


def parse_departments_text(text: str) -> tuple[Department, ...]:
    """Manuelle Eingabe: kommagetrennte Slugs. Der Name ist vorlaeufig der Slug."""
    slugs = [part.strip() for part in text.split(",") if part.strip()]
    if not slugs or any(not _SLUG_RE.match(slug) for slug in slugs):
        raise InvalidSettings("invalid_departments")
    return tuple(Department(slug=slug, name=humanize_slug(slug)) for slug in slugs)


def normalize_server_url(url: str) -> str:
    """Nur http(s) mit Host. Abschliessende Schraegstriche werden entfernt."""
    cleaned = url.strip().rstrip("/")
    parts = urlsplit(cleaned)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidSettings("invalid_url")
    return cleaned


def is_insecure_remote_url(url: str) -> bool:
    """True bei `http://` an einen Host ausserhalb von Loopback und privaten Netzen."""
    parts = urlsplit(url)
    if parts.scheme != "http":
        return False
    host = parts.hostname or ""
    if host == "localhost" or host.endswith((".local", ".lan", ".home.arpa")) or ("." not in host and ":" not in host):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local)


CLIENT_ID_PREFIX = "resqio-ha-"


def make_client_id(username: str, purpose: str = "") -> str:
    """Client-ID `resqio-ha-<benutzer>[-probe]-<zufall>`.

    Der RESQIO-Broker uebernimmt eine bereits verbundene Client-ID und trennt den alten Client. Er
    akzeptiert Zugaenge mit Benutzernamen `ha_...` deshalb NUR mit dem Praefix `resqio-ha-`, und
    sperrt dieses Praefix fuer alle anderen Benutzer. Der Zufallsteil verhindert, dass zwei
    Verbindungen desselben Zugangs (z. B. Pruefung und Betrieb) einander verdraengen.
    """
    middle = f"{purpose}-" if purpose else ""
    return f"{CLIENT_ID_PREFIX}{username}-{middle}{secrets.token_hex(4)}"


def make_session_client_id(username: str, entry_id: str) -> str:
    """Stabile Client-ID fuer die persistente Session des Betriebs.

    Gleiche Eintrags-ID ergibt dieselbe Client-ID, damit der Broker die Session (Abonnements und
    verpasste QoS-1-Nachrichten) wiederfindet. Prefix und Benutzername wie bei `make_client_id`.
    """
    digest = hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:8]
    return f"{CLIENT_ID_PREFIX}{username}-s{digest}"


class ReplayGuard:
    """Entscheidet, ob eine nicht retained Alarmmeldung als live gelten darf.

    Mit persistenter Session stellt der Broker Nachrichten nach, die waehrend einer Unterbrechung
    ankamen. Kurze Luecken sind erwuenscht (der Alarm wurde sonst verpasst). Nach einem Neustart
    oder einer langen Unterbrechung wuerde dieselbe Nachlieferung einen Alarm von gestern als
    neuen Alarm ausloesen. Dann werden Alarm-Ereignisse im Zeitfenster nach dem Verbinden verworfen.
    Zeiten sind monotone Sekunden.
    """

    def __init__(
        self,
        max_gap: float = REPLAY_MAX_GAP_SECONDS,
        window: float = REPLAY_GUARD_WINDOW_SECONDS,
    ) -> None:
        self._max_gap = max_gap
        self._window = window
        self._last_disconnect: float | None = None
        self._ever_connected = False
        self._blocked_until = 0.0

    def on_connect(self, now: float, *, session_present: bool) -> None:
        if not session_present:
            # Frische Session: es gibt nichts nachzuliefern.
            self._blocked_until = 0.0
        else:
            gap = None if not self._ever_connected or self._last_disconnect is None else now - self._last_disconnect
            self._blocked_until = now + self._window if gap is None or gap > self._max_gap else 0.0
        self._ever_connected = True
        self._last_disconnect = None

    def on_disconnect(self, now: float) -> None:
        if self._last_disconnect is None:
            self._last_disconnect = now

    def accepts_live_event(self, now: float) -> bool:
        return now >= self._blocked_until


def normalize_pairing_code(code: str) -> str:
    """Leerzeichen und Trennstriche weg, Grossschreibung. Ungueltig -> InvalidSettings."""
    normalized = re.sub(r"[\s-]", "", code).upper()
    if not _CODE_RE.match(normalized):
        raise InvalidSettings("invalid_code")
    return normalized


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


# --------------------------------------------------------------------------- intern


def _parse_department(item: Any) -> Department:
    if not isinstance(item, dict):
        raise InvalidSettings("invalid_departments")
    slug = str(item.get("slug") or "").strip()
    if not _SLUG_RE.match(slug):
        raise InvalidSettings("invalid_departments")
    name = _clean_text(str(item.get("name") or "")) or humanize_slug(slug)
    return Department(slug=slug, name=name[:100])


def _decode_text(payload: bytes) -> str | None:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _clean_text(text: str) -> str:
    return text.strip()


def _sanitize_event(data: dict[str, Any]) -> dict[str, Any]:
    registrations = _as_int(data.get("registrations"))
    return {
        "id": _short(data.get("id"), 64),
        "title": _short(data.get("title"), 200),
        "type": _short(data.get("type"), 64),
        "start": parse_datetime(data.get("start")),
        "end": parse_datetime(data.get("end")),
        "location": _short(data.get("location"), 200),
        "registrations": registrations if registrations is not None and registrations >= 0 else None,
    }


def _short(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = _clean_text(str(value))[:limit]
    return text or None


def _parse_bool_word(text: str, true_word: str, false_word: str) -> bool | None:
    word = text.strip().lower()
    if word == true_word:
        return True
    if word == false_word:
        return False
    return None


def _load_json_dict(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return parse_count(value) if value.strip().lstrip("-").isdigit() else None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
