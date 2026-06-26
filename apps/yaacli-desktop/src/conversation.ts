import type { ApprovalRequest, EventEnvelope, FileChange } from './protocol'

export type ConversationBlock =
  | { id: string; type: 'user'; text: string }
  | { id: string; type: 'text' | 'thinking'; text: string; runId: string }
  | {
      id: string
      type: 'tool'
      runId: string
      toolCallId: string
      name: string
      args: unknown
      result?: unknown
      status: 'running' | 'completed'
    }
  | { id: string; type: 'status'; runId: string; status: string; message?: string }
  | {
      id: string
      type: 'approval'
      runId: string
      approval: ApprovalRequest
      status: 'pending' | 'resolved'
      decision?: string
    }

export type ConversationState = {
  blocks: ConversationBlock[]
  tasks: Array<Record<string, unknown>>
  fileChanges: FileChange[]
  usage: Record<string, unknown> | null
  lastSequenceByRun: Record<string, number>
  warnings: string[]
}

export const initialConversationState: ConversationState = {
  blocks: [],
  tasks: [],
  fileChanges: [],
  usage: null,
  lastSequenceByRun: {},
  warnings: [],
}

export function appendUserBlock(
  state: ConversationState,
  id: string,
  text: string,
): ConversationState {
  return { ...state, blocks: [...state.blocks, { id, type: 'user', text }] }
}

export function reduceProtocolEvent(
  state: ConversationState,
  event: EventEnvelope,
): ConversationState {
  const runId = event.run_id ?? 'runtime'
  if (event.sequence != null) {
    const last = state.lastSequenceByRun[runId]
    if (last != null && event.sequence <= last) return state
    const warnings =
      last != null && event.sequence > last + 1
        ? [...state.warnings, `Event gap for ${runId}: expected ${last + 1}, received ${event.sequence}`]
        : state.warnings
    state = {
      ...state,
      lastSequenceByRun: {
        ...state.lastSequenceByRun,
        [runId]: event.sequence,
      },
      warnings,
    }
  }

  if (event.event === 'text.delta' || event.event === 'thinking.delta') {
    const type = event.event === 'text.delta' ? 'text' : 'thinking'
    const delta = typeof event.payload.delta === 'string' ? event.payload.delta : ''
    const last = state.blocks.at(-1)
    if (last?.type === type && last.runId === runId) {
      return {
        ...state,
        blocks: [
          ...state.blocks.slice(0, -1),
          { ...last, text: last.text + delta },
        ],
      }
    }
    return {
      ...state,
      blocks: [
        ...state.blocks,
        { id: `${runId}-${event.sequence}-${type}`, type, text: delta, runId },
      ],
    }
  }

  if (event.event === 'tool.started') {
    const toolCallId = String(event.payload.tool_call_id ?? '')
    return {
      ...state,
      blocks: [
        ...state.blocks,
        {
          id: `${runId}-tool-${toolCallId}`,
          type: 'tool',
          runId,
          toolCallId,
          name: String(event.payload.tool_name ?? 'tool'),
          args: event.payload.args,
          status: 'running',
        },
      ],
    }
  }

  if (event.event === 'tool.completed') {
    const toolCallId = String(event.payload.tool_call_id ?? '')
    return {
      ...state,
      blocks: state.blocks.map((block) =>
        block.type === 'tool' && block.toolCallId === toolCallId
          ? { ...block, result: event.payload.result, status: 'completed' }
          : block,
      ),
    }
  }

  if (event.event === 'task.updated') {
    return {
      ...state,
      tasks: Array.isArray(event.payload.tasks)
        ? (event.payload.tasks as Array<Record<string, unknown>>)
        : [],
    }
  }

  if (event.event === 'file.changed') {
    return {
      ...state,
      fileChanges: [...state.fileChanges, event.payload as FileChange],
    }
  }

  if (event.event === 'usage.updated') return { ...state, usage: event.payload }

  if (event.event === 'approval.requested') {
    return {
      ...state,
      blocks: [
        ...state.blocks,
        {
          id: String(event.payload.id),
          type: 'approval',
          runId,
          approval: event.payload as ApprovalRequest,
          status: 'pending',
        },
      ],
    }
  }

  if (event.event === 'approval.resolved') {
    return {
      ...state,
      blocks: state.blocks.map((block) =>
        block.type === 'approval' && block.id === event.payload.approval_id
          ? {
              ...block,
              status: 'resolved',
              decision: String(event.payload.decision ?? ''),
            }
          : block,
      ),
    }
  }

  if (event.event.startsWith('run.')) {
    const status = event.event.slice(4)
    return {
      ...state,
      blocks: [
        ...state.blocks,
        {
          id: `${runId}-${event.sequence}-${status}`,
          type: 'status',
          runId,
          status,
          message:
            typeof event.payload.error === 'object' && event.payload.error
              ? String((event.payload.error as Record<string, unknown>).message ?? '')
              : undefined,
        },
      ],
    }
  }

  return state
}
