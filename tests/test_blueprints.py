"""Prueft die Blueprints: YAML laedt, alle !input-Verweise existieren, Templates sind gueltiges Jinja."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")
jinja2 = pytest.importorskip("jinja2")

BLUEPRINT_DIR = Path(__file__).resolve().parents[1] / "blueprints" / "automation" / "resqio"
FILES = sorted(BLUEPRINT_DIR.glob("*.yaml"))


class _Input:
    def __init__(self, name: str) -> None:
        self.name = name


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!input", lambda loader, node: _Input(loader.construct_scalar(node)))


def _walk(node: Any):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _load(path: Path) -> dict[str, Any]:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)


def test_expected_blueprints_exist() -> None:
    names = {path.name for path in FILES}
    assert {"geraetehaus_tor_pro_fahrzeug.yaml", "licht_ueber_knx_bei_alarm.yaml"} <= names


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_blueprint_is_consistent(path: Path) -> None:
    data = _load(path)
    blueprint = data["blueprint"]
    assert blueprint["domain"] == "automation"
    assert blueprint["name"].startswith("RESQIO")
    inputs = set(blueprint["input"])
    for definition in blueprint["input"].values():
        assert "selector" in definition

    used = {
        node.name for node in _walk({k: v for k, v in data.items() if k != "blueprint"}) if isinstance(node, _Input)
    }
    assert used, "kein !input verwendet"
    assert used <= inputs, f"unbekannte Eingaben: {used - inputs}"
    assert inputs <= used, f"ungenutzte Eingaben: {inputs - used}"

    env = jinja2.Environment()
    for node in _walk(data):
        if isinstance(node, str) and ("{{" in node or "{%" in node):
            env.parse(node)


def test_vehicle_gate_blueprint_triggers_and_service() -> None:
    data = _load(BLUEPRINT_DIR / "geraetehaus_tor_pro_fahrzeug.yaml")
    assert {t["id"] for t in data["trigger"]} == {"fahrzeug", "alarm"}
    services = [node["action"] for node in _walk(data["action"]) if isinstance(node, dict) and "action" in node]
    assert services == ["cover.open_cover"]
    options = {o["value"] for o in data["blueprint"]["input"]["ausloeser"]["selector"]["select"]["options"]}
    assert options == {"fahrzeug_im_einsatz", "alarm_aktiv"}


def test_knx_blueprint_uses_only_standard_services() -> None:
    data = _load(BLUEPRINT_DIR / "licht_ueber_knx_bei_alarm.yaml")
    services = {node["action"] for node in _walk(data["action"]) if isinstance(node, dict) and "action" in node}
    assert services == {"light.turn_on", "light.turn_off", "knx.send"}


def test_knx_address_template_splits_and_trims() -> None:
    data = _load(BLUEPRINT_DIR / "licht_ueber_knx_bei_alarm.yaml")
    template = jinja2.Environment().from_string(data["variables"]["adressen"])
    assert template.render(adressen_text=" 1/0/1, 1/0/2 ,,") == "['1/0/1', '1/0/2']"
    assert template.render(adressen_text="") == "[]"


def _alarm_notification_filter() -> Any:
    data = _load(BLUEPRINT_DIR / "alarm_benachrichtigung.yaml")
    condition = data["condition"][1]["value_template"]
    return jinja2.Environment().from_string(condition)


@pytest.mark.parametrize(
    ("filter_text", "keyword", "expected"),
    [
        ("", "B3 Wohnungsbrand", "True"),
        ("b3, thl", "B3 Wohnungsbrand", "True"),
        ("B3, THL", "thl klein", "True"),
        ("b3", "THL klein", "False"),
        (" , ", "irgendwas", "True"),
    ],
)
def test_alarm_notification_keyword_filter(filter_text: str, keyword: str, expected: str) -> None:
    template = _alarm_notification_filter()
    rendered = template.render(
        stichwort_filter=filter_text,
        stichwort_sensor="sensor.x",
        states=lambda _entity: keyword,
    )
    assert rendered.strip() == expected


def test_alarm_notification_blueprint_triggers_on_event_entity() -> None:
    data = _load(BLUEPRINT_DIR / "alarm_benachrichtigung.yaml")
    assert data["trigger"][0]["trigger"] == "state"
    defaults = data["blueprint"]["input"]["ereignisarten"]["default"]
    assert defaults == ["neu"]
