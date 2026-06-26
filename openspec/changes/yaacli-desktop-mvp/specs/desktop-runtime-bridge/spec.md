## ADDED Requirements

### Requirement: Supervise a workspace runtime

The Tauri host SHALL start at most one bundled Python runtime process for the active workspace context, observe its lifecycle, and terminate owned processes during application shutdown.

#### Scenario: Workspace runtime starts successfully

- **WHEN** the user opens a workspace and no compatible runtime is active for it
- **THEN** the host starts the bundled sidecar with that workspace as explicit context and waits for a successful handshake before enabling run commands

#### Scenario: Sidecar exits unexpectedly

- **WHEN** the owned runtime process exits during an active desktop session
- **THEN** the host marks the runtime unavailable, preserves committed UI state, reports the failure, and offers a bounded restart action

### Requirement: Negotiate protocol compatibility

The host and runtime MUST exchange protocol versions and supported capabilities before session or run commands are accepted.

#### Scenario: Protocol versions are compatible

- **WHEN** the sidecar handshake advertises a supported protocol version
- **THEN** the host records the negotiated version and enables only mutually supported commands and events

#### Scenario: Protocol versions are incompatible

- **WHEN** no compatible protocol version exists
- **THEN** the application blocks runtime operations and reports an application installation mismatch rather than attempting partial execution

### Requirement: Exchange typed commands and ordered events

The bridge SHALL use typed request, response, error, and event envelopes with correlation identifiers, session and run identifiers where applicable, and monotonically increasing event sequence numbers per run.

#### Scenario: Command completes

- **WHEN** the host sends a valid command with a unique request identifier
- **THEN** the runtime returns exactly one correlated success or error response while related streaming events remain independently ordered

#### Scenario: Duplicate or out-of-order event arrives

- **WHEN** the host receives a duplicate sequence number or a sequence lower than the last applied event for a run
- **THEN** the frontend does not apply the event twice and records a diagnosable protocol warning

### Requirement: Separate protocol and diagnostics

The sidecar MUST reserve standard output for framed protocol messages and MUST write human-readable diagnostics to standard error without including secrets.

#### Scenario: Runtime logs during streaming

- **WHEN** the runtime emits diagnostics while a run is producing events
- **THEN** the host captures the diagnostics separately and protocol parsing continues without corruption

### Requirement: Bound bridge resources

The bridge SHALL apply configurable limits to message size, pending command count, attachment metadata, and restart attempts.

#### Scenario: Protocol message exceeds a limit

- **WHEN** either endpoint receives a message larger than the negotiated maximum
- **THEN** it rejects the message with a typed bridge error and does not allocate unbounded additional memory
