# Architecture and Protocol

YAACLI Desktop has three trust and ownership layers:

1. React renders workspace, session, conversation, approval, file review, and settings state.
2. The Tauri Rust host owns native dialogs, notifications, menus, Keychain access, updates, and process supervision.
3. The bundled Python sidecar owns YAACLI configuration, agent runtime creation, sessions, runs, approvals, and transcript persistence.

React cannot spawn processes or read arbitrary files. It invokes a narrow Tauri command set. Rust starts one workspace-scoped sidecar and exchanges newline-delimited JSON on private stdin/stdout pipes. Sidecar stderr is diagnostic-only and is redacted before logging.

## Protocol Versioning

Every envelope carries `protocol_version`. Requests and responses correlate through `request_id`; events carry workspace/session/run scope and a monotonically increasing run sequence. Python models are defined in `packages/yaacli/yaacli/desktop/protocol.py`, TypeScript validators in `apps/yaacli-desktop/src/protocol.ts`, and shared fixtures in `packages/yaacli/tests/fixtures/desktop_protocol/`.

Change rules:

- Additive optional fields may retain the current protocol version.
- Removing, renaming, or changing the meaning of a field requires a protocol version increment.
- Rust must reject an unsupported handshake before accepting commands.
- Python, TypeScript, Rust, golden fixtures, and `desktop-version.json` must change together.

`scripts/generate-yaacli-desktop-version.py` verifies Cargo and Tauri app versions match and generates app/sidecar/protocol compatibility metadata before packaging.

## Runtime Continuity

The desktop adapter calls the same `open_runtime_stream` boundary as the terminal interfaces. Workspace switching stops the prior runtime before opening another. Restored sessions rebuild the UI from persisted snapshot/events and do not rerun the model. Approvals and steering are validated against workspace, session, run, and approval identifiers.
