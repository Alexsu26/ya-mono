#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/apps/yaacli-desktop"
BUILD_DIR="$ROOT/build/yaacli-desktop-sidecar"
TARGET="aarch64-apple-darwin"
OUTPUT="$APP_DIR/src-tauri/binaries/yaacli-desktop-sidecar-$TARGET"
PYINSTALLER_VERSION="6.16.0"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "YAACLI Desktop sidecar builds require Apple Silicon macOS." >&2
  exit 1
fi

uv run python "$ROOT/scripts/generate-yaacli-desktop-version.py"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/dist" "$BUILD_DIR/work"

SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct)}" \
  uv run --project "$ROOT" --with "pyinstaller==$PYINSTALLER_VERSION" pyinstaller \
  --clean \
  --noconfirm \
  --distpath "$BUILD_DIR/dist" \
  --workpath "$BUILD_DIR/work" \
  "$APP_DIR/sidecar/yaacli-desktop-sidecar.spec"

install -m 755 "$BUILD_DIR/dist/yaacli-desktop-sidecar" "$OUTPUT"

if [[ -n "${APPLE_SIGNING_IDENTITY:-}" ]]; then
  codesign --force --options runtime --timestamp --sign "$APPLE_SIGNING_IDENTITY" "$OUTPUT"
  codesign --verify --strict --verbose=2 "$OUTPUT"
fi

SMOKE_WORKSPACE="$(mktemp -d)"
trap 'rm -rf "$SMOKE_WORKSPACE"' EXIT
HANDSHAKE="$(printf '%s\n' '{"protocol_version":1,"type":"request","request_id":"smoke-shutdown","command":"runtime.shutdown","payload":{}}' | env -i HOME="$SMOKE_WORKSPACE" PATH="/usr/bin:/bin" TMPDIR="$SMOKE_WORKSPACE" "$OUTPUT" --workspace "$SMOKE_WORKSPACE")"
printf '%s\n' "$HANDSHAKE" | grep -q '"type":"handshake"'
printf '%s\n' "$HANDSHAKE" | grep -q '"protocol_version":1'

echo "Built and smoke-tested $OUTPUT"
