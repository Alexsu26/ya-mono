## 1. Product and Repository Foundations

- [x] 1.1 Resolve and document the public app name, bundle identifier, minimum macOS version, updater release host/channel, and close-window behavior listed in the design open questions
- [x] 1.2 Create `apps/yaacli-desktop/` as a pnpm workspace member with React, TypeScript, Vite, Tauri v2, lint, format, unit-test, and build scripts
- [x] 1.3 Add repository Makefile targets and CI setup for desktop frontend checks, Rust checks, and development launch without changing existing YAACLI commands
- [x] 1.4 Add the initial adaptive three-pane application shell and design tokens with accessible light/dark system theme behavior

## 2. Shared YAACLI Runtime Boundary

- [x] 2.1 Add characterization tests for current YAACLI session creation/restoration, structured input parts, streamed events, cancellation, steering, and approval behavior
- [x] 2.2 Define UI-independent Python interfaces for runtime creation, session operations, run lifecycle, steering, cancellation, and approval resolution
- [x] 2.3 Refactor the existing TUI to consume the shared interfaces while keeping its commands, persistence formats, and test suite behavior unchanged
- [x] 2.4 Add a `yaacli` desktop-sidecar entry point that accepts explicit workspace context and does not import terminal or Textual presentation modules

## 3. Versioned Desktop Protocol

- [x] 3.1 Define Pydantic handshake, request, response, error, and event envelopes with protocol version, correlation IDs, scoped identifiers, and per-run sequence numbers
- [x] 3.2 Define typed workspace, session, run, input-part, approval, file-change, usage, and runtime-health payloads without serializing SDK implementation classes directly
- [x] 3.3 Implement JSON Lines stdin/stdout transport with protocol-only stdout, redacted stderr diagnostics, message-size limits, bounded pending requests, and graceful shutdown
- [x] 3.4 Add matching TypeScript discriminated unions and Zod validators in the desktop app
- [x] 3.5 Add shared golden fixtures and cross-language contract tests covering valid messages, malformed input, incompatible versions, duplicate events, and out-of-order events

## 4. Tauri Sidecar Supervision and Vertical Slice

- [x] 4.1 Configure development sidecar discovery and minimal Tauri capabilities for process launch, file selection, events, and application lifecycle
- [x] 4.2 Implement Rust sidecar start, handshake, stdin command dispatch, stdout event parsing, stderr capture, graceful termination, and bounded restart behavior
- [x] 4.3 Expose narrow typed Tauri commands and events to React without granting direct shell access to the webview
- [x] 4.4 Implement the first end-to-end slice: select workspace, start runtime, create session, submit text, render text deltas, cancel the run, and display terminal state
- [x] 4.5 Add Rust and frontend integration tests for startup failure, incompatible protocol, unexpected exit, cancellation, and restart reconciliation

## 5. Workspaces and Sessions

- [x] 5.1 Implement canonical workspace selection, recent-workspace persistence, unavailable-path handling, switching, and removal
- [x] 5.2 Surface active project configuration and workspace guidance sources without exposing secret values
- [x] 5.3 Implement session create, list, select, rename, archive, and restore commands and UI states scoped to the active workspace
- [x] 5.4 Rebuild a restored conversation from the runtime snapshot and committed event history without rerunning the agent
- [x] 5.5 Add tests proving workspace switching isolates session lists, working directories, drafts, attachments, and active runtime state

## 6. Agent Conversation and Run Controls

- [x] 6.1 Implement the multiline composer with ordered text/file/image input parts, drag-and-drop, file selection, clipboard image paste, validation, and removal
- [x] 6.2 Implement the sequence-aware conversation reducer for text, thinking, tools, tasks, usage, file changes, errors, and terminal run events
- [x] 6.3 Render virtualized conversation blocks with Markdown/code presentation, collapsible thinking, structured tool cards, and stable completed content
- [x] 6.4 Implement cancel and steering controls with runtime-advertised availability, acknowledgment state, and run-scoped delivery
- [x] 6.5 Implement the optional context pane for tasks, tool detail, background activity, file changes, and usage plus persistent non-sensitive layout preferences
- [x] 6.6 Add reducer and component tests for interleaved streams, replay plus live-event deduplication, long histories, attachment errors, and run controls

## 7. Approval and File-Change Review

- [x] 7.1 Project runtime HITL events into scoped desktop approval requests containing tool identity, action summary, risk context, and advertised decisions
- [x] 7.2 Implement a blocking accessible approval surface that fails closed on disconnect, rejects stale identities, and records resolved decisions in the timeline
- [x] 7.3 Implement additions, modifications, deletions, renames, text diffs, and explicit binary/unavailable diff states in the context pane
- [x] 7.4 Add secret-redaction tests covering approval content, tool metadata, diagnostics, persisted events, and file review
- [x] 7.5 Add end-to-end tests for allow-once, denial, cancellation while pending, sidecar loss while pending, and mismatched approval identifiers

## 8. Settings, Credentials, and Desktop Integration

- [x] 8.1 Implement model/profile selection and non-secret YAACLI configuration editing through typed runtime commands
- [x] 8.2 Implement macOS Keychain-backed provider credential create, update, presence check, and delete commands with no plaintext return path to React
- [x] 8.3 Add native menus, keyboard shortcuts, file-open dialogs, completion/failure notifications, and the selected close-window/run-lifecycle policy
- [x] 8.4 Review and test Tauri capability allowlists so the webview can invoke only required desktop commands

## 9. Apple Silicon Packaging and Updates

- [x] 9.1 Add a reproducible PyInstaller arm64 sidecar build with explicit hooks/data collection and a clean-environment smoke test
- [x] 9.2 Embed the sidecar through Tauri `externalBin` and generate aligned app, sidecar, and protocol compatibility version metadata
- [x] 9.3 Produce an unsigned local arm64 application bundle and DMG that runs on a supported Mac without Python, Homebrew, Node.js, or `uv`
- [x] 9.4 Add CI signing, nested-binary signing order, notarization, stapling, and failure gates using repository secrets
- [ ] 9.5 Configure signed updater metadata and verify atomic app-plus-sidecar update, invalid-signature rejection, and rollback to the unchanged installed version

## 10. Verification and Documentation

- [x] 10.1 Add focused Python, TypeScript, Rust, protocol-contract, and desktop integration suites to repository `make lint`, `make check`, and `make test` coverage
- [ ] 10.2 Run the existing YAACLI TUI and SDK tests and resolve regressions introduced by the shared runtime extraction
- [ ] 10.3 Verify the MVP acceptance flow on a clean Apple Silicon Mac: install, open workspace, create and restore session, stream a run, steer/cancel, approve/deny, review a diff, restart, and update
- [x] 10.4 Document desktop development, architecture, protocol versioning, sidecar packaging, signing/notarization, updater operation, security boundaries, and known MVP limitations
- [x] 10.5 Update root and package READMEs, workspace metadata, lockfiles, CI/release workflows, and relevant existing specifications to match the shipped desktop behavior
