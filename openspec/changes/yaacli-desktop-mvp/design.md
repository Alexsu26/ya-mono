## Context

YAACLI currently combines a mature Python agent runtime with terminal presentation code. Its existing behavior includes configuration and model profiles, persistent sessions, structured `stream_agent` events, steering and cancellation, HITL approval, attachments, background work, and workspace tools. The desktop application must expose those behaviors without creating a second execution implementation or coupling local desktop use to the YA Claw HTTP service.

The repository already uses React, TypeScript, Vite, AG-UI-aligned event reduction, Radix UI primitives, virtualized lists, and resizable panels in `apps/ya-claw-web`. It also uses Python 3.11+, `uv`, Pydantic models, and some Rust workspace packages. The first distributable target is Apple Silicon macOS. The application must work without a separately installed Python toolchain and must respect macOS signing, notarization, Keychain, and updater constraints.

## Goals / Non-Goals

**Goals:**

- Deliver a native-feeling local workspace agent with session navigation, rich streaming presentation, run controls, approvals, and file-change review.
- Keep `ya-agent-sdk` and a shared YAACLI runtime as the only agent execution implementation used by both TUI and desktop adapters.
- Define a small, versioned, testable process boundary between Tauri and Python.
- Make failures diagnosable and recoverable without exposing secrets or corrupting committed session state.
- Produce a self-contained Apple Silicon application suitable for signing, notarization, and atomic updates.

**Non-Goals:**

- Replacing the YAACLI TUI or changing its public command-line behavior.
- Using YA Claw as a required local daemon or duplicating its multi-instance service architecture.
- Cloud synchronization, remote execution, team collaboration, plugin marketplace, multi-window operation, or Intel macOS support in the MVP.
- Building a general IDE, embedded source editor, or full terminal emulator.
- Migrating all existing package specifications into OpenSpec.

## Decisions

### 1. Add a dedicated Tauri application under `apps/yaacli-desktop`

The application will use Tauri v2 with a React, TypeScript, and Vite frontend. Rust owns native windows, menus, file dialogs, notifications, Keychain integration, updater integration, capability enforcement, and sidecar lifecycle. The webview owns presentation and user interaction.

This matches the existing frontend toolchain while keeping native privileges outside browser code. Electron was considered, but its larger runtime and broader Node surface do not provide enough benefit for this local bridge. A pure SwiftUI client was considered, but it would introduce a second UI language and prevent reuse of current React interaction code.

### 2. Extract a headless desktop adapter around shared YAACLI runtime behavior

Agent construction, configuration resolution, session persistence, input-part creation, event production, steering, cancellation, and approval state will live behind UI-independent Python interfaces. The existing TUI and the new desktop adapter will consume those interfaces through separate presentation adapters. Desktop code will not import Textual widgets or terminal renderers.

Extraction will be incremental: first establish characterization tests around existing behavior, then move only the minimum runtime ownership required by the desktop vertical slice. A full YAACLI rewrite was rejected because it creates unnecessary regression risk in working TUI behavior.

### 3. Use a supervised Python sidecar with JSON Lines over standard I/O

The Tauri host will launch an owned, bundled Python sidecar for the active workspace. Commands and events will use one JSON object per line on stdin/stdout; diagnostics will use stderr. Rust will expose narrow Tauri commands to the frontend and emit validated desktop events into the webview.

This avoids an unauthenticated localhost port, port discovery, firewall prompts, and browser-to-daemon authentication. Direct frontend-to-Python HTTP/SSE was rejected for those reasons. A Unix socket remains a future option if profiling shows stdio backpressure is insufficient.

The host will use bounded queues, maximum message sizes, one response per request ID, per-run event sequence numbers, and bounded restart attempts. It will not automatically retry non-idempotent run or approval commands after a crash.

### 4. Define a versioned desktop wire protocol independent of Python event classes

Python will define Pydantic request, response, error, handshake, and event envelopes. TypeScript will define matching Zod schemas and discriminated unions. Generated fixtures and contract tests will verify compatibility in both directions. Every envelope carries `protocol_version` and an envelope type; request-related messages carry `request_id`; run events carry `workspace_id`, `session_id`, `run_id`, and `sequence` where applicable.

The desktop protocol will project SDK events into stable product concepts instead of serializing arbitrary Pydantic AI or Python class layouts. AG-UI-aligned names may be reused where semantics match, but protocol compatibility will not depend on the YA Claw API.

### 5. Keep durable session truth in Python and transient presentation state in React

The Python runtime remains authoritative for configuration, session metadata, message history, committed run results, and approval/run lifecycle. React stores only active selection, panel layout, composer drafts, optimistic command state, and a reduced view of received events. On reconnect or application restart, the frontend rebuilds from a runtime snapshot plus subsequent sequenced events.

Zustand and a pure event reducer will manage presentation state. TanStack Virtual will render long conversations. Existing `ya-claw-web` reducer and component ideas will be reused only after separating them from YA Claw-specific API shapes; shared packages will be introduced only when actual reuse removes duplication.

### 6. Use an adaptive three-pane desktop layout

The left pane contains recent workspaces and their sessions. The center pane contains the conversation, structured stream blocks, and composer. The optional right pane contains tasks, tool details, file changes, background activity, and usage. Approval requests use a focused modal or sheet and remain represented in the conversation timeline after resolution.

The layout will remain usable with the context pane hidden and will persist non-sensitive UI preferences. Raw event JSON may be available in a developer diagnostic view but is not the primary experience.

### 7. Treat approvals and credentials as native security boundaries

Approval commands will include matching approval, workspace, session, and run identifiers. Missing connection, stale identity, or unknown scope fails closed. The UI will render the exact operation summary and supported scopes received from the runtime and will not invent broader approval options.

Provider credentials will be stored in macOS Keychain through Rust commands. Tauri capabilities will allowlist required native commands and sidecar execution. Protocol logs, crash reports, stored events, and approval history will pass through secret redaction before persistence or display.

### 8. Bundle the sidecar and application as one release unit

The initial sidecar build will use PyInstaller to produce an arm64 executable containing YAACLI and its Python dependencies. Tauri `externalBin` configuration will embed the executable. The Tauri application version, sidecar application version, and protocol compatibility range will be generated from the same release metadata.

Release CI will build on macOS arm64, execute sidecar smoke tests and protocol contract tests, build the Tauri bundle, sign nested binaries in the required order, notarize and staple the application/DMG, and generate signed updater metadata. A release is not public when signing, notarization, or update signature generation fails.

Nuitka and a managed Python framework bundle were considered. PyInstaller is selected for the MVP because it minimizes custom launcher work; the build remains replaceable behind the sidecar artifact contract.

## Risks / Trade-offs

- **Python packaging misses dynamic imports or data files** -> Maintain explicit collection hooks and run a clean-machine sidecar smoke suite against provider, skill, tool, and attachment discovery.
- **TUI behavior changes during runtime extraction** -> Add characterization tests first and keep TUI adapters consuming the same typed runtime interfaces.
- **High-frequency stream events overload stdio or the webview** -> Bound queues, batch compatible deltas in Rust or React, virtualize history, and retain sequence-aware replay.
- **Sidecar crash leaves ambiguous operation state** -> Persist only runtime-confirmed state, fail pending approvals closed, avoid automatic replay of non-idempotent commands, and reconcile through a runtime snapshot after restart.
- **Protocol schemas drift between Python and TypeScript** -> Version envelopes, share golden fixtures, and require cross-language contract tests in CI.
- **Tauri permissions become broader than intended** -> Keep a small command surface, maintain explicit capability files, and add permission review to release verification.
- **Signing and notarization hide failures until late** -> Establish an unsigned local bundle early, then add signed CI artifacts before feature completion rather than at the end.
- **Reusing YA Claw web code couples products accidentally** -> Reuse isolated visual/reducer utilities only; do not import YA Claw API clients, routes, or server assumptions.

## Migration Plan

1. Add protocol models, fixtures, and a minimal headless runtime command without changing the default `yaacli` entry point.
2. Add the Tauri app and prove the launch/handshake/prompt/text-stream/cancel vertical slice in development.
3. Move shared session and run coordination behind UI-independent interfaces while running the existing TUI test suite after each extraction.
4. Add session restoration, structured events, approvals, file review, attachments, and profile selection behind desktop feature boundaries.
5. Add self-contained sidecar packaging, then unsigned application bundles, then signed/notarized release and updater workflows.
6. Keep desktop distribution opt-in until contract, TUI regression, clean-machine, and release checks pass. Rollback consists of withdrawing the desktop artifact; existing YAACLI installation and TUI data remain usable because their entry point and durable formats are not replaced.

## Open Questions

- Which public product name and macOS bundle identifier should be used for signing and Keychain access groups?
- Which release host and channel should publish signed updater metadata and application downloads?
- Should the first public build require macOS 13 or a newer minimum based on the selected Tauri/WebKit feature set?
- Should a closed main window terminate active runs in the MVP, or should the application remain active in the menu bar until runs complete?
