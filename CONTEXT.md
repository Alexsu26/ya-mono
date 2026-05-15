# YA Mono Product Context

This context captures product language shared across the YA Mono workspace, especially the agent-facing CLI and session experience.

## Language

**Session**:
A resumable conversation workspace containing user prompts, assistant output, tool activity, and recovery state.
_Avoid_: chat log, transcript-only history

**Session name**:
The human-readable title used to identify a session in session lists and resume flows.
_Avoid_: filename, summary

**Latest user prompt**:
The most recent non-command user request in a session.
_Avoid_: last message

## Relationships

- A **Session** has at most one **Session name**.
- A **Session name** may be explicit, set by user rename, or automatic, derived from the first non-command user prompt.
- An explicit **Session name** set by rename takes precedence over automatic naming.
- A **Session** has zero or one **Latest user prompt**.

## Example Dialogue

> **Dev:** "If a user renames a **Session**, should the first prompt still auto-update the **Session name**?"
> **Domain expert:** "No. Rename is explicit user intent, so it takes precedence over automatic naming. The **Latest user prompt** should still update separately."

## Flagged Ambiguities

- "name" can mean an explicit rename or an automatically derived title. Resolved: **Session name** is the display title, and explicit rename has higher precedence than automatic naming.
