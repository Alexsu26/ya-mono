# Transcript-First TUI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the yaacli v2 TUI into a modern transcript-first agent timeline with consistent visual tokens, stable block structure, and CJK-safe rendering.

**Architecture:** Keep the existing Textual/Rich stack and RichLog pipeline. Add semantic design tokens and small rendering helpers, then update block renderers and chrome widgets so user, assistant, tool, error, and system output share one visual grammar.

**Tech Stack:** Python 3.11, Textual, Rich, pytest, pytest-asyncio.

______________________________________________________________________

### Task 1: Visual Contract Tests

**Files:**

- Modify: `packages/yaacli/tests/test_console.py`

- Modify: `packages/yaacli/tests/test_textual_app.py`

- [ ] Add tests for transcript-first user, assistant, tool, error, and system output.

- [ ] Add tests for CJK-safe truncation and table/list layout.

- [ ] Run the targeted tests and confirm they fail before implementation.

### Task 2: Design Tokens And Helpers

**Files:**

- Modify: `packages/yaacli/yaacli/console/theme.py`

- Modify: `packages/yaacli/yaacli/console/glyphs.py`

- Create: `packages/yaacli/yaacli/console/design.py`

- [ ] Define semantic color/style tokens for surfaces, text, borders, accents, states, headings, and code.

- [ ] Add helpers for transcript headers, rail-prefixed body lines, CJK-safe truncation, and compact metadata.

- [ ] Run visual contract tests for helper behavior.

### Task 3: Transcript Blocks

**Files:**

- Modify: `packages/yaacli/yaacli/console/blocks/user_prompt.py`

- Modify: `packages/yaacli/yaacli/console/blocks/model_text.py`

- Modify: `packages/yaacli/yaacli/console/blocks/tool_call.py`

- Modify: `packages/yaacli/yaacli/console/blocks/error.py`

- Modify: `packages/yaacli/yaacli/console/blocks/system.py`

- Modify: `packages/yaacli/yaacli/console/blocks/thinking.py`

- Modify: `packages/yaacli/yaacli/console/blocks/edit.py`

- [ ] Render user and assistant as stable transcript turns.

- [ ] Render tool calls as compact timeline child events, with details still available in ctrl+o view.

- [ ] Render errors and system output with the same rail/label/meta grammar.

- [ ] Preserve existing summarization, clipping, and export behavior.

### Task 4: Chrome And Tables

**Files:**

- Modify: `packages/yaacli/yaacli/console/header.py`

- Modify: `packages/yaacli/yaacli/console/widgets.py`

- Modify: `packages/yaacli/yaacli/console/textual_app.py`

- [ ] Collapse header into a modern one-line workspace strip.

- [ ] Make status text explicit: ready, thinking, waiting for tool result, running tool, streaming response.

- [ ] Make session/search/tool tables use CJK-safe compact columns and consistent dim metadata.

### Task 5: Verification

**Commands:**

- `uv run --with ruff ruff check packages/yaacli/yaacli/console packages/yaacli/tests/test_console.py packages/yaacli/tests/test_textual_app.py`
- `uv run --package yaacli --with pytest --with pytest-asyncio pytest packages/yaacli/tests/test_console.py packages/yaacli/tests/test_textual_app.py -q`
- `uv run --package yaacli --with pytest --with pytest-asyncio --with pytest-xdist --with inline-snapshot pytest packages/yaacli/tests -q --inline-snapshot=disable`
- `YAACLI_TUI=v2 uv run --package yaacli xunocli` with `/sessions`, `/help`, `/export`, `/resume latest`, and visual inspection through PTY.
