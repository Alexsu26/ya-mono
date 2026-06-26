## Why

YAACLI already provides a capable local agent runtime, but its terminal-only interface limits discoverability, rich file interaction, approval review, and session navigation for everyday macOS use. A focused desktop MVP can preserve the existing Python runtime while adding a native-feeling workspace UI and a distributable application without turning YAACLI into a second runtime implementation.

## What Changes

- Add an Apple Silicon macOS desktop application built with Tauri, React, and TypeScript.
- Add a headless YAACLI desktop runtime that reuses `ya-agent-sdk` execution, configuration, sessions, streaming events, steering, cancellation, and HITL behavior.
- Add a versioned local bridge between the Tauri host and the Python runtime, with typed commands, streamed events, lifecycle management, and failure recovery.
- Add a three-pane workspace experience for projects and sessions, conversation and composition, and contextual task/tool/file-change details.
- Add desktop approval dialogs and file-change review so users can understand and authorize sensitive operations before execution.
- Add local session restoration, model/profile selection, attachments, image paste, and workspace guidance discovery.
- Add an Apple Silicon development and release pipeline that bundles the Python sidecar and produces a signed, notarizable, update-ready macOS application artifact.
- Keep the existing TUI supported on the shared runtime; the MVP does not replace YA Claw, add cloud sync, or introduce team collaboration.

## Capabilities

### New Capabilities

- `desktop-workspaces-sessions`: Open local workspaces and create, browse, restore, rename, and archive desktop conversation sessions.
- `desktop-agent-interaction`: Compose prompts and attachments, observe structured streaming agent activity, steer or cancel runs, and inspect task and usage state.
- `desktop-runtime-bridge`: Start and supervise a bundled Python runtime and exchange versioned commands, responses, and ordered events through the Tauri host.
- `desktop-approval-review`: Present human-in-the-loop approval requests and file changes with sufficient context for an informed decision.
- `desktop-macos-distribution`: Build and package the Apple Silicon desktop application and Python sidecar for signed, notarizable, update-ready distribution.

### Modified Capabilities

None. The repo-local OpenSpec baseline has no existing capabilities, and existing package specifications remain authoritative for their current surfaces.

## Impact

- Adds a new frontend workspace member under `apps/yaacli-desktop/` with React, TypeScript, Vite, and Tauri dependencies.
- Adds a desktop/headless runtime boundary under `packages/yaacli/yaacli/` while preserving the current TUI entry points and behavior.
- Introduces a shared wire protocol represented by Pydantic models in Python and validated TypeScript schemas in the desktop app.
- Extends workspace metadata, lockfiles, Makefile targets, CI/release workflows, documentation, and macOS signing/update configuration.
- Requires a reproducible Apple Silicon Python sidecar build and explicit separation between protocol stdout and diagnostic stderr.
- Reuses existing AG-UI-aligned event concepts and selected presentation utilities where their contracts fit, without coupling the desktop app to the YA Claw service.
