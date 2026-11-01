"""Tests fuer die Release-Versionsberechnung (.github/scripts/next_version.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("next_version", ROOT / ".github" / "scripts" / "next_version.py")
assert _spec is not None and _spec.loader is not None
nv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv)


def test_no_tags_uses_manifest_version_as_first_release() -> None:
    assert nv.next_version([], "0.8.0") == "0.8.0"


def test_patch_is_incremented_from_highest_tag() -> None:
    assert nv.next_version(["v0.8.0", "v0.8.1", "v0.8.10", "v0.8.9"], "0.8.10") == "0.8.11"


def test_manual_higher_manifest_version_wins() -> None:
    assert nv.next_version(["v0.8.4"], "0.9.0") == "0.9.0"


def test_foreign_tags_are_ignored() -> None:
    assert nv.next_version(["latest", "v1", "release-2", "v0.8.2"], "0.8.2") == "0.8.3"


def test_invalid_manifest_version_raises() -> None:
    with pytest.raises(ValueError, match="Ungueltige"):
        nv.next_version([], "0.8")


def test_manifest_starts_clean_and_keys_are_sorted() -> None:
    manifest = json.loads((ROOT / "custom_components" / "resqio" / "manifest.json").read_text(encoding="utf-8"))
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
    # Einzige Abhaengigkeit: file_upload fuer den CA-Zertifikat-Upload im Config-Flow (kein MQTT-Add-on noetig).
    assert manifest["dependencies"] == ["file_upload"]
    assert manifest["integration_type"] == "hub"
    assert nv.next_version([], manifest["version"]) == manifest["version"]
