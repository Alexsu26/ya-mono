## ADDED Requirements

### Requirement: Open a local workspace

The desktop application SHALL let the user select an existing local directory and SHALL treat its canonical path as the workspace identity.

#### Scenario: User opens a valid directory

- **WHEN** the user selects a readable local directory
- **THEN** the application opens the workspace and displays its associated sessions

#### Scenario: Previously opened workspace is unavailable

- **WHEN** a recent workspace path no longer exists or is not readable
- **THEN** the application keeps the recent entry, marks it unavailable, and offers removal or reselection without starting a runtime in that path

### Requirement: Load workspace guidance

The desktop runtime SHALL load project-level YAACLI configuration and workspace guidance through the same precedence and safety rules used by the shared YAACLI runtime.

#### Scenario: Workspace contains guidance

- **WHEN** a run starts in a workspace containing supported guidance and project configuration files
- **THEN** the runtime applies them and the UI identifies which workspace guidance sources are active

### Requirement: Manage workspace sessions

The application SHALL let the user create, list, select, rename, archive, and restore sessions within the active workspace.

#### Scenario: User creates a session

- **WHEN** the user starts a new conversation in an open workspace
- **THEN** the runtime creates a distinct session and the application selects it

#### Scenario: User restores a session

- **WHEN** the user selects a previously persisted session
- **THEN** the application restores its committed conversation history, active profile, and latest known run state

#### Scenario: User archives a session

- **WHEN** the user confirms archiving a session with no active run
- **THEN** the session is removed from the default list without deleting its workspace files or unrelated sessions

### Requirement: Isolate workspace state

The system MUST NOT use a session from one canonical workspace path as the active session of another workspace.

#### Scenario: User switches workspaces

- **WHEN** the user changes from one workspace to another
- **THEN** the session list, active session, runtime working directory, and attachments switch to the selected workspace before another run can start
