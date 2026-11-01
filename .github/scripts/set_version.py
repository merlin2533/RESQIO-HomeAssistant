"""Schreibt die Version in manifest.json und pyproject.toml (Schluesselreihenfolge bleibt erhalten)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    version = argv[1]
    manifest = Path("custom_components/resqio/manifest.json")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["version"] = version
    manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pyproject = Path("pyproject.toml")
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(re.sub(r'(?m)^version = ".*"$', f'version = "{version}"', text, count=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
