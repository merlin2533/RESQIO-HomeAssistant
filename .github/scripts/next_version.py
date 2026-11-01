"""Berechnet die naechste Release-Version (Patch-Stufe hochzaehlen).

Basis ist das hoechste vorhandene Tag `vX.Y.Z`. Gibt es noch keins, wird die Version aus dem
Manifest selbst als erstes Release verwendet. Hat jemand das Manifest von Hand auf eine hoehere
Version gesetzt (z. B. 0.9.0), gilt diese unveraendert.

Aufruf: python next_version.py <manifest.json>   (Tags kommen aus `git tag`)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

Version = tuple[int, int, int]


def _parse(text: str, pattern: re.Pattern[str]) -> Version | None:
    match = pattern.match(text.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def next_version(tags: list[str], manifest_version: str) -> str:
    manifest = _parse(manifest_version, _VERSION_RE)
    if manifest is None:
        raise ValueError(f"Ungueltige Manifest-Version: {manifest_version!r}")
    found = [v for tag in tags if (v := _parse(tag, _TAG_RE)) is not None]
    if not found:
        chosen = manifest
    else:
        highest = max(found)
        chosen = manifest if manifest > highest else (highest[0], highest[1], highest[2] + 1)
    return ".".join(str(part) for part in chosen)


def main(argv: list[str]) -> int:
    manifest_path = argv[1]
    with open(manifest_path, encoding="utf-8") as handle:
        manifest_version = json.load(handle)["version"]
    tags = subprocess.run(["git", "tag", "--list"], check=True, capture_output=True, text=True).stdout.split()  # noqa: S607
    print(next_version(tags, manifest_version))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
