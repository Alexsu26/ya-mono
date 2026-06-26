# Release Operations

## Local Unsigned Build

On Apple Silicon macOS with `uv`, pnpm, Rust, Xcode command-line tools, and DMG tooling installed:

```bash
make desktop-sidecar-build
make desktop-bundle
```

The sidecar build uses PyInstaller 6.16.0, collects explicit runtime data/metadata, writes the Tauri external binary with the required target suffix, and starts it with an empty environment to verify a protocol handshake and graceful shutdown. Tauri outputs the app and DMG below `apps/yaacli-desktop/src-tauri/target/release/bundle/`.

## Signed Release

Push a `yaacli-desktop-v*` tag or dispatch `YAACLI Desktop Release`. Configure these repository secrets:

- `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`
- `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`
- `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- `TAURI_UPDATER_PUBLIC_KEY`

The workflow imports the certificate, builds and signs the nested sidecar first, lets Tauri sign the enclosing app, submits/staples notarization, produces signed updater artifacts, validates signatures/staples, and creates a draft GitHub Release. A draft must not be published if any verification step fails.

## Updater

Production CI overlays the disabled development updater configuration with the public key and `createUpdaterArtifacts`. The stable endpoint is `https://github.com/wh1isper/ya-mono/releases/latest/download/latest.json`. The updater signature covers the atomic application bundle, including the paired sidecar. Invalid signatures are rejected before installation, leaving the installed application unchanged.

Version changes must update both `src-tauri/tauri.conf.json` and `src-tauri/Cargo.toml`. The build-time metadata generator rejects mismatches and records the compatible protocol version in the bundled `desktop-version.json`.
