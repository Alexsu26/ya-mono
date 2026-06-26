"""Generate aligned YAACLI Desktop release compatibility metadata."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = ROOT / "apps" / "yaacli-desktop" / "src-tauri"


def main() -> None:
    tauri_config = json.loads((TAURI_DIR / "tauri.conf.json").read_text())
    cargo_config = tomllib.loads((TAURI_DIR / "Cargo.toml").read_text())
    app_version = str(tauri_config["version"])
    cargo_version = str(cargo_config["package"]["version"])
    if cargo_version != app_version:
        raise SystemExit(f"desktop version mismatch: Tauri {app_version}, Cargo {cargo_version}")

    protocol_source = (ROOT / "packages" / "yaacli" / "yaacli" / "desktop" / "protocol.py").read_text()
    match = re.search(r"^PROTOCOL_VERSION = (\d+)$", protocol_source, re.MULTILINE)
    if match is None:
        raise SystemExit("desktop protocol version constant was not found")
    protocol_version = int(match.group(1))
    metadata = {
        "appVersion": app_version,
        "sidecarVersion": app_version,
        "protocolVersion": protocol_version,
        "protocolCompatibility": str(protocol_version),
    }
    (TAURI_DIR / "desktop-version.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
