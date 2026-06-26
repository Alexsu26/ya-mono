# YAACLI Desktop Adapter

YAACLI Desktop is a presentation adapter over the shared YAACLI execution path. It must not fork agent semantics from the TUI.

The Python desktop package exposes a versioned JSONL sidecar protocol for workspace/session/run lifecycle, structured input parts, streamed events, steering, cancellation, approval resolution, configuration, and health. Tauri owns native integration and process supervision. React owns presentation only.

Desktop sessions continue to use YAACLI project/global configuration and transcript persistence. Workspace identifiers are canonical paths hashed into opaque IDs. Session, run, approval, and file-change payloads are protocol projections rather than serialized SDK classes.

Credentials are not YAACLI config values in the desktop product. Provider secrets remain in macOS Keychain and enter only the sidecar child environment. The WebView cannot retrieve them or invoke a shell.

Protocol compatibility and release packaging are specified in `apps/yaacli-desktop/docs/`. Any shared runtime change must preserve existing TUI behavior and pass both CLI and desktop suites.
