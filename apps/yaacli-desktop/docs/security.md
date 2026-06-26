# Security Boundaries

The WebView receives no shell or general filesystem capability. Tauri capabilities allow only the native dialog and notification operations required by the UI; application commands are explicitly registered in Rust.

Provider credentials are stored in macOS Keychain under the desktop bundle identity. React may create, replace, query presence, or delete a credential, but Rust never returns plaintext. Known provider credentials are injected only into the child sidecar environment. Non-secret model/profile and theme preferences are persisted separately per workspace.

The sidecar protocol enforces a one-megabyte message limit, bounded pending requests, handshake timeout, bounded restart attempts, scoped approval identities, and fail-closed behavior when the process disconnects. Attachments are size-limited before decoding. Protocol stdout must contain JSONL only; sensitive diagnostic patterns are redacted from stderr and approval/file projections.

Release builds preserve the boundary by signing the PyInstaller sidecar before the enclosing application. Tauri then signs the outer bundle, notarizes it, staples the ticket, and signs updater artifacts. The release workflow fails before publication when any required credential, signature, notarization, staple, or updater artifact is missing.

Known MVP constraints include a single supervised runtime, no hardened multi-user isolation inside one macOS account, and no protection against an already-compromised host account. Workspace tools retain the same authority and approval policy as YAACLI TUI.
