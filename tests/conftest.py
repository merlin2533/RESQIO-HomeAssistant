"""Laedt parsing.py direkt aus dem Dateipfad.

Das Paket `custom_components.resqio` wuerde beim Import Home Assistant laden. Die reine
Parser-Logik braucht das nicht; deshalb wird nur die Datei geladen.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PARSING_PATH = Path(__file__).resolve().parents[1] / "custom_components" / "resqio" / "parsing.py"

_spec = importlib.util.spec_from_file_location("resqio_parsing", PARSING_PATH)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["resqio_parsing"] = _module
_spec.loader.exec_module(_module)
