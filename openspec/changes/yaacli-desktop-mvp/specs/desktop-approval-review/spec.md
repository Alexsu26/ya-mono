## ADDED Requirements

### Requirement: Block execution pending approval

The desktop runtime MUST pause an approval-gated operation until the user submits an explicit decision or the run is cancelled.

#### Scenario: Approval is requested

- **WHEN** the runtime emits a human-in-the-loop approval request
- **THEN** the application presents a blocking approval surface containing the requesting tool, action summary, risk context, and available decisions

#### Scenario: Application loses connection during approval

- **WHEN** the bridge disconnects while an approval is pending
- **THEN** the operation remains unapproved and the UI does not infer an allow decision

### Requirement: Apply scoped approval decisions

The application SHALL support the decision scopes advertised by the runtime and MUST send the decision only for the matching approval, session, and run.

#### Scenario: User approves once

- **WHEN** the user selects the one-time allow decision
- **THEN** only the matching pending operation resumes and the decision is recorded in the conversation timeline

#### Scenario: User denies an operation

- **WHEN** the user denies a pending operation
- **THEN** the runtime receives the denial, the operation does not execute, and the agent can continue or terminate according to runtime behavior

### Requirement: Review file changes

The application SHALL present workspace file changes as additions, modifications, deletions, and renames with a readable diff when content is available.

#### Scenario: Agent changes a text file

- **WHEN** the runtime reports a text-file modification
- **THEN** the context panel shows the path, change type, and before/after diff associated with the originating run

#### Scenario: Changed content is binary or unavailable

- **WHEN** a normal text diff cannot be produced
- **THEN** the application shows metadata and an explicit unavailable-diff state instead of fabricated content

### Requirement: Protect sensitive values

Approval details, diagnostics, and file review MUST redact configured secrets and MUST NOT persist bearer tokens, provider keys, or keychain values in desktop event history.

#### Scenario: Tool input contains a known secret

- **WHEN** approval or tool metadata includes a value registered as sensitive
- **THEN** the rendered and persisted representation replaces the sensitive value with a redaction marker
