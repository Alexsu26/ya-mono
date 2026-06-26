import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open } from "@tauri-apps/plugin-dialog";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";

import {
  eventEnvelopeSchema,
  sessionSnapshotSchema,
  sessionSummarySchema,
  workspaceInfoSchema,
  type EventEnvelope,
  type ApprovalRequest,
  type InputPart,
  type SessionSnapshot,
  type SessionSummary,
  type WorkspaceInfo,
} from "./protocol";

export type RuntimeState = {
  status: "starting" | "ready" | "unavailable" | "stopping";
  workspace: string | null;
};

export type DesktopConfig = {
  configured: boolean;
  active_profile: string | null;
  profiles: Record<
    string,
    { label: string; model: string; description: string }
  >;
  sources: string[];
  theme: "light" | "dark";
};

export type CredentialState = { provider: string; present: boolean };

function requireTauri() {
  if (!isTauri())
    throw new Error("This action requires the YAACLI Desktop app");
}

export async function chooseWorkspace(): Promise<string | null> {
  requireTauri();
  const selected = await open({ directory: true, multiple: false });
  return typeof selected === "string" ? selected : null;
}

export async function chooseAttachmentPaths(): Promise<string[]> {
  requireTauri();
  const selected = await open({ multiple: true, directory: false });
  if (Array.isArray(selected)) return selected;
  return typeof selected === "string" ? [selected] : [];
}

export async function subscribeDroppedPaths(
  callback: (paths: string[]) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) return () => undefined;
  return getCurrentWebview().onDragDropEvent((event) => {
    if (event.payload.type === "drop") callback(event.payload.paths);
  });
}

export function inputPartFromPath(path: string): InputPart {
  const name = path.split("/").at(-1) || path;
  const extension = name.split(".").at(-1)?.toLowerCase();
  const imageTypes: Record<string, string> = {
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    gif: "image/gif",
    webp: "image/webp",
  };
  const mediaType = extension ? imageTypes[extension] : undefined;
  return {
    type: mediaType ? "image" : "file",
    path,
    name,
    media_type: mediaType ?? "application/octet-stream",
  };
}

export async function inputPartFromClipboardFile(
  file: File,
): Promise<InputPart> {
  if (file.size > 20 * 1024 * 1024) {
    throw new Error(`${file.name || "Clipboard image"} exceeds 20 MiB`);
  }
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result)));
    reader.addEventListener("error", () =>
      reject(reader.error ?? new Error("Could not read clipboard image")),
    );
    reader.readAsDataURL(file);
  });
  const comma = dataUrl.indexOf(",");
  if (comma < 0) throw new Error("Clipboard image could not be encoded");
  return {
    type: "image",
    name: file.name || "clipboard-image.png",
    media_type: file.type || "image/png",
    data_base64: dataUrl.slice(comma + 1),
  };
}

export async function startRuntime(workspace: string): Promise<RuntimeState> {
  requireTauri();
  return invoke<RuntimeState>("runtime_start", { workspace });
}

export async function stopRuntime(): Promise<void> {
  requireTauri();
  await invoke("runtime_stop");
}

export async function getRuntimeState(): Promise<RuntimeState> {
  requireTauri();
  return invoke<RuntimeState>("runtime_state");
}

export async function request(
  command: string,
  payload: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  requireTauri();
  return invoke<Record<string, unknown>>("runtime_request", {
    command,
    payload,
  });
}

export async function openWorkspace(path: string): Promise<WorkspaceInfo> {
  await startRuntime(path);
  return workspaceInfoSchema.parse(await request("workspace.open", { path }));
}

export async function listSessions(): Promise<SessionSummary[]> {
  const payload = await request("session.list");
  return sessionSummarySchema.array().parse(payload.sessions);
}

export async function listArchivedSessions(): Promise<SessionSummary[]> {
  const payload = await request("session.list_archived");
  return sessionSummarySchema.array().parse(payload.sessions);
}

export async function createSession(name = ""): Promise<SessionSnapshot> {
  return sessionSnapshotSchema.parse(await request("session.create", { name }));
}

export async function loadSession(sessionId: string): Promise<SessionSnapshot> {
  return sessionSnapshotSchema.parse(
    await request("session.load", { session_id: sessionId }),
  );
}

export async function renameSession(
  sessionId: string,
  name: string,
): Promise<SessionSummary> {
  return sessionSummarySchema.parse(
    await request("session.rename", { session_id: sessionId, name }),
  );
}

export async function archiveSession(sessionId: string): Promise<void> {
  await request("session.archive", { session_id: sessionId });
}

export async function restoreSession(
  sessionId: string,
): Promise<SessionSnapshot> {
  return sessionSnapshotSchema.parse(
    await request("session.restore", { session_id: sessionId }),
  );
}

export async function startRun(
  sessionId: string,
  inputParts: InputPart[],
): Promise<string> {
  const payload = await request("run.start", {
    session_id: sessionId,
    input_parts: inputParts,
  });
  if (typeof payload.run_id !== "string")
    throw new Error("Runtime did not return a run ID");
  return payload.run_id;
}

export async function cancelRun(runId: string): Promise<void> {
  await request("run.cancel", { run_id: runId });
}

export async function steerRun(runId: string, text: string): Promise<void> {
  await request("run.steer", { run_id: runId, text });
}

export async function resolveApproval(
  approval: ApprovalRequest,
  decision: "approve_once" | "approve_session" | "deny",
  reason?: string,
): Promise<void> {
  await request("approval.resolve", {
    approval_id: approval.id,
    workspace_id: approval.workspace_id,
    session_id: approval.session_id,
    run_id: approval.run_id,
    decision,
    reason,
  });
}

export async function getConfig(): Promise<DesktopConfig> {
  return (await request("config.get")) as DesktopConfig;
}

export async function updateConfig(update: {
  active_profile?: string;
  theme?: "light" | "dark";
}): Promise<DesktopConfig> {
  return (await request("config.update", update)) as DesktopConfig;
}

export async function credentialStatus(
  provider: string,
): Promise<CredentialState> {
  requireTauri();
  return invoke<CredentialState>("credential_status", { provider });
}

export async function setCredential(
  provider: string,
  secret: string,
): Promise<CredentialState> {
  requireTauri();
  return invoke<CredentialState>("credential_set", { provider, secret });
}

export async function deleteCredential(
  provider: string,
): Promise<CredentialState> {
  requireTauri();
  return invoke<CredentialState>("credential_delete", { provider });
}

export async function notifyRun(title: string, body: string): Promise<void> {
  if (!isTauri()) return;
  let allowed = await isPermissionGranted();
  if (!allowed) allowed = (await requestPermission()) === "granted";
  if (allowed) sendNotification({ title, body });
}

export async function subscribeProtocolEvents(
  callback: (event: EventEnvelope) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) return () => undefined;
  return listen("desktop://protocol-event", ({ payload }) => {
    const parsed = eventEnvelopeSchema.safeParse(payload);
    if (parsed.success) callback(parsed.data);
    else console.warn("Rejected invalid sidecar event", parsed.error);
  });
}

export async function subscribeRuntimeState(
  callback: (state: RuntimeState) => void,
): Promise<UnlistenFn> {
  if (!isTauri()) return () => undefined;
  return listen<RuntimeState>("desktop://runtime-state", ({ payload }) =>
    callback(payload),
  );
}
