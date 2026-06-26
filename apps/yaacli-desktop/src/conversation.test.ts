import { describe, expect, test } from 'vitest'

import { initialConversationState, reduceProtocolEvent } from './conversation'
import type { EventEnvelope } from './protocol'

function event(
  name: string,
  sequence: number,
  payload: Record<string, unknown>,
): EventEnvelope {
  return {
    protocol_version: 1,
    type: 'event',
    event: name,
    payload,
    run_id: 'run-1',
    sequence,
  }
}

describe('conversation reducer', () => {
  test('joins ordered text deltas and ignores duplicates', () => {
    const first = reduceProtocolEvent(
      initialConversationState,
      event('text.delta', 0, { delta: 'Hello' }),
    )
    const second = reduceProtocolEvent(
      first,
      event('text.delta', 1, { delta: ' world' }),
    )
    const duplicate = reduceProtocolEvent(
      second,
      event('text.delta', 1, { delta: ' world' }),
    )

    expect(second.blocks[0]).toMatchObject({ text: 'Hello world' })
    expect(duplicate).toBe(second)
  })

  test('records a warning for an event gap', () => {
    const first = reduceProtocolEvent(
      initialConversationState,
      event('run.started', 0, {}),
    )
    const next = reduceProtocolEvent(first, event('text.delta', 3, { delta: 'late' }))

    expect(next.warnings).toHaveLength(1)
  })

  test('completes the matching tool block', () => {
    const started = reduceProtocolEvent(
      initialConversationState,
      event('tool.started', 0, {
        tool_call_id: 'tool-1',
        tool_name: 'read_file',
        args: { path: 'README.md' },
      }),
    )
    const completed = reduceProtocolEvent(
      started,
      event('tool.completed', 1, { tool_call_id: 'tool-1', result: 'done' }),
    )

    expect(completed.blocks[0]).toMatchObject({ status: 'completed', result: 'done' })
  })

  test('records and resolves a scoped approval block', () => {
    const requested = reduceProtocolEvent(
      initialConversationState,
      event('approval.requested', 0, {
        id: 'approval-1',
        workspace_id: 'workspace-1',
        session_id: 'session-1',
        run_id: 'run-1',
        tool_call_id: 'tool-1',
        tool_name: 'shell',
        summary: '{"command":"pwd"}',
        risk: 'runtime_review',
        decisions: ['approve_once', 'approve_session', 'deny'],
      }),
    )
    const resolved = reduceProtocolEvent(
      requested,
      event('approval.resolved', 1, {
        approval_id: 'approval-1',
        decision: 'deny',
      }),
    )

    expect(resolved.blocks[0]).toMatchObject({ status: 'resolved', decision: 'deny' })
  })
})
