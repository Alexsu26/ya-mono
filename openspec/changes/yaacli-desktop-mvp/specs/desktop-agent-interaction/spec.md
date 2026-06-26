## ADDED Requirements

### Requirement: Compose multimodal input

The application SHALL accept multiline text, local file attachments, and pasted or selected images and SHALL preserve their order as structured input parts.

#### Scenario: User submits text and attachments

- **WHEN** the user submits a prompt containing text and supported attachments
- **THEN** the runtime receives ordered input parts and the conversation displays the submitted parts

#### Scenario: Attachment cannot be read

- **WHEN** a selected attachment is unavailable, unsupported, or exceeds the configured limit
- **THEN** the application identifies the rejected attachment and does not start the run until the invalid input is removed

### Requirement: Render structured streaming activity

The application SHALL render ordered agent text, thinking, tool activity, task updates, usage updates, file changes, and terminal run state without exposing raw protocol messages as the primary interface.

#### Scenario: Run emits interleaved events

- **WHEN** a run emits ordered events from multiple supported event types
- **THEN** the conversation and context panel reduce them deterministically into stable blocks without duplicating completed content

#### Scenario: Thinking visibility changes

- **WHEN** the user expands or collapses a thinking block
- **THEN** the visibility changes without altering the run or persisted event order

### Requirement: Control an active run

The user SHALL be able to cancel an active run and send steering input when the runtime reports that steering is available.

#### Scenario: User cancels an active run

- **WHEN** the user confirms cancellation while a run is active
- **THEN** the runtime requests cancellation, reports the terminal run state, and keeps committed conversation content available

#### Scenario: User steers an active run

- **WHEN** the user submits steering input during a steerable run
- **THEN** the input is acknowledged, displayed as pending or accepted, and delivered to that run only

### Requirement: Expose current execution context

The application SHALL show the active workspace, session, model profile, run phase, token usage when available, and whether there are pending approvals or background tasks.

#### Scenario: Execution context changes

- **WHEN** the runtime reports a profile, phase, usage, approval, or task-state change
- **THEN** the corresponding desktop status updates without requiring a page reload

### Requirement: Recover conversation presentation

The application SHALL rebuild the same committed conversation timeline after restart from persisted session data and compacted events.

#### Scenario: Application restarts after a completed run

- **WHEN** the application reopens a session whose latest run completed before shutdown
- **THEN** it renders the committed inputs, outputs, tool summaries, and terminal state without rerunning the agent
