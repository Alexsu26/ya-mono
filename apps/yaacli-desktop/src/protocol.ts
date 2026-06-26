import { z } from "zod";

export const PROTOCOL_VERSION = 1 as const;

const identifier = z.string().min(1).max(128);

export const inputPartSchema = z
  .object({
    type: z.enum(["text", "file", "image"]),
    text: z.string().nullable().optional(),
    path: z.string().nullable().optional(),
    media_type: z.string().nullable().optional(),
    name: z.string().nullable().optional(),
    data_base64: z.string().nullable().optional(),
  })
  .strict();

export type InputPart = z.infer<typeof inputPartSchema>;

export const workspaceInfoSchema = z
  .object({
    id: identifier,
    path: z.string(),
    name: z.string(),
    available: z.boolean().default(true),
    guidance_sources: z.array(z.string()).default([]),
    config_sources: z.array(z.string()).default([]),
    git_branch: z.string().nullable().optional(),
  })
  .strict();

export const sessionSummarySchema = z
  .object({
    id: identifier,
    name: z.string(),
    latest_user_prompt: z.string().default(""),
    updated_at: z.string().default(""),
    workspace_id: identifier,
    model: z.string().default(""),
    archived: z.boolean().default(false),
  })
  .strict();

export const runStatusSchema = z.enum([
  "idle",
  "running",
  "waiting_approval",
  "completed",
  "cancelled",
  "failed",
]);

export const sessionSnapshotSchema = z
  .object({
    session: sessionSummarySchema,
    transcript: z.array(z.record(z.string(), z.unknown())).default([]),
    run_status: runStatusSchema.default("idle"),
  })
  .strict();

export const approvalDecisionSchema = z.enum([
  "approve_once",
  "approve_session",
  "deny",
]);

export const approvalRequestSchema = z
  .object({
    id: identifier,
    workspace_id: identifier,
    session_id: identifier,
    run_id: identifier,
    tool_call_id: identifier,
    tool_name: z.string(),
    summary: z.string(),
    risk: z.string(),
    decisions: z.array(approvalDecisionSchema),
  })
  .strict();

export const fileChangeSchema = z
  .object({
    path: z.string(),
    change_type: z.enum(["added", "modified", "deleted", "renamed"]),
    old_path: z.string().nullable().optional(),
    diff: z.string().nullable().optional(),
    diff_available: z.boolean().default(false),
    binary: z.boolean().default(false),
  })
  .strict();

export const usageInfoSchema = z
  .object({
    input_tokens: z.number().int().nonnegative().default(0),
    output_tokens: z.number().int().nonnegative().default(0),
    total_tokens: z.number().int().nonnegative().default(0),
    context_window: z.number().int().positive().nullable().optional(),
    cost: z.number().nonnegative().nullable().optional(),
  })
  .strict();

export const protocolCapabilitiesSchema = z
  .object({
    commands: z.array(z.string()),
    events: z.array(z.string()),
    max_message_bytes: z.number().int().positive(),
    max_attachments: z.number().int().positive(),
    steering: z.boolean(),
    approvals: z.boolean(),
  })
  .strict();

export const handshakeEnvelopeSchema = z
  .object({
    protocol_version: z.literal(PROTOCOL_VERSION),
    type: z.literal("handshake"),
    runtime_version: z.string(),
    capabilities: protocolCapabilitiesSchema,
  })
  .strict();

export const requestEnvelopeSchema = z
  .object({
    protocol_version: z.literal(PROTOCOL_VERSION),
    type: z.literal("request"),
    request_id: identifier,
    command: identifier,
    payload: z.record(z.string(), z.unknown()),
  })
  .strict();

export const errorInfoSchema = z
  .object({
    code: z.string(),
    message: z.string(),
    retryable: z.boolean().default(false),
  })
  .strict();

export const responseEnvelopeSchema = z
  .object({
    protocol_version: z.literal(PROTOCOL_VERSION),
    type: z.literal("response"),
    request_id: identifier,
    ok: z.boolean(),
    payload: z.record(z.string(), z.unknown()).nullable().optional(),
    error: errorInfoSchema.nullable().optional(),
  })
  .strict();

export const eventEnvelopeSchema = z
  .object({
    protocol_version: z.literal(PROTOCOL_VERSION),
    type: z.literal("event"),
    event: identifier,
    payload: z.record(z.string(), z.unknown()),
    workspace_id: z.string().nullable().optional(),
    session_id: z.string().nullable().optional(),
    run_id: z.string().nullable().optional(),
    sequence: z.number().int().nonnegative().nullable().optional(),
  })
  .strict();

export const wireEnvelopeSchema = z.discriminatedUnion("type", [
  handshakeEnvelopeSchema,
  requestEnvelopeSchema,
  responseEnvelopeSchema,
  eventEnvelopeSchema,
]);

export type WorkspaceInfo = z.infer<typeof workspaceInfoSchema>;
export type SessionSummary = z.infer<typeof sessionSummarySchema>;
export type SessionSnapshot = z.infer<typeof sessionSnapshotSchema>;
export type ApprovalRequest = z.infer<typeof approvalRequestSchema>;
export type FileChange = z.infer<typeof fileChangeSchema>;
export type UsageInfo = z.infer<typeof usageInfoSchema>;
export type RequestEnvelope = z.infer<typeof requestEnvelopeSchema>;
export type ResponseEnvelope = z.infer<typeof responseEnvelopeSchema>;
export type EventEnvelope = z.infer<typeof eventEnvelopeSchema>;
export type WireEnvelope = z.infer<typeof wireEnvelopeSchema>;
