"""Konstanten der RESQIO-Integration (Home-Assistant-seitig)."""

from __future__ import annotations

DOMAIN = "resqio"
MANUFACTURER = "RESQIO"
MODEL = "Feuerwehr-Zugang"

DEFAULT_BROKER_PORT = 1883
DEFAULT_BROKER_PORT_TLS = 8883

# Schluessel in den Config-Entry-Daten (siehe ConnectionSettings.to_entry_data)
CONF_URL = "url"
CONF_CODE = "code"
CONF_CA_PEM = "ca_pem"
CONF_TOPIC_ROOT = "topic_root"
CONF_DEPARTMENTS = "departments"

# Kopplungs- und Statusendpunkte des RESQIO-Servers
PAIRING_EXCHANGE_PATH = "/api/ha-bridge/pairing/exchange"
DISCOVER_PATH = "/api/ha-bridge/discover"
CAPABILITIES_PATH = "/api/system/capabilities"

# Dispatcher-Signale je Config-Entry
SIGNAL_NEW_TOPIC_PREFIX = f"{DOMAIN}_new_topic_"
SIGNAL_UPDATE_PREFIX = f"{DOMAIN}_update_"
SIGNAL_ALARM_EVENT_PREFIX = f"{DOMAIN}_alarm_event_"


def signal_new_topic(entry_id: str) -> str:
    return f"{SIGNAL_NEW_TOPIC_PREFIX}{entry_id}"


def signal_update(entry_id: str) -> str:
    return f"{SIGNAL_UPDATE_PREFIX}{entry_id}"


def signal_alarm_event(entry_id: str) -> str:
    return f"{SIGNAL_ALARM_EVENT_PREFIX}{entry_id}"
