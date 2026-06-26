import { create } from "zustand";

import * as bridge from "./bridge";
import {
  appendUserBlock,
  initialConversationState,
  reduceProtocolEvent,
  type ConversationBlock,
  type ConversationState,
} from "./conversation";
import type {
  EventEnvelope,
  InputPart,
  SessionSnapshot,
  SessionSummary,
  WorkspaceInfo,
} from "./protocol";
import { desktopStorage } from "./storage";

type DesktopStore = {
  runtimeStatus: bridge.RuntimeState["status"];
  workspace: WorkspaceInfo | null;
  recentWorkspaces: WorkspaceInfo[];
  sessions: SessionSummary[];
  archivedSessions: SessionSummary[];
  selectedSession: SessionSnapshot | null;
  activeRunId: string | null;
  activeRunSessionId: string | null;
  pendingAttachments: InputPart[];
  config: bridge.DesktopConfig | null;
  conversation: ConversationState;
  conversationCache: Record<string, ConversationState>;
  error: string | null;
  initialize: () => Promise<() => void>;
  openWorkspace: () => Promise<void>;
  openRecentWorkspace: (path: string) => Promise<void>;
  removeRecentWorkspace: (path: string) => void;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  renameSelectedSession: (name: string) => Promise<void>;
  archiveSelectedSession: () => Promise<void>;
  restoreArchivedSession: (sessionId: string) => Promise<void>;
  refreshArchivedSessions: () => Promise<void>;
  sendPrompt: (text: string) => Promise<void>;
  chooseAttachments: () => Promise<void>;
  addAttachmentPaths: (paths: string[]) => void;
  addInlineAttachment: (part: InputPart) => void;
  removeAttachment: (index: number) => void;
  selectProfile: (name: string) => Promise<void>;
  setTheme: (theme: "light" | "dark") => Promise<void>;
  resolveApproval: (
    approval: import("./protocol").ApprovalRequest,
    decision: "approve_once" | "approve_session" | "deny",
    reason?: string,
  ) => Promise<void>;
  cancelRun: () => Promise<void>;
  handleEvent: (event: EventEnvelope) => void;
  clearError: () => void;
};

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function applyTheme(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
  desktopStorage.setItem("yaacli.desktop.theme", theme);
}

function cacheOutgoing(state: {
  selectedSession: SessionSnapshot | null;
  conversation: ConversationState;
  conversationCache: Record<string, ConversationState>;
}): Record<string, ConversationState> {
  const id = state.selectedSession?.session.id ?? null;
  if (!id) return { ...state.conversationCache };
  return { ...state.conversationCache, [id]: state.conversation };
}

function transcriptToBlocks(
  snapshot: SessionSnapshot,
  sessionId: string,
): ConversationBlock[] {
  const runId = `${sessionId}-history`;
  return snapshot.transcript
    .map((entry, index): ConversationBlock | null => {
      const id = `${sessionId}-history-${index}`;
      const kind = typeof entry.kind === "string" ? entry.kind : "";
      const text = typeof entry.text === "string" ? entry.text : "";
      if (kind === "user") return { id, type: "user", text };
      if (kind === "assistant") {
        return { id, type: "text", text, runId };
      }
      if (kind === "tool") {
        const tool =
          typeof entry.tool === "object" && entry.tool !== null
            ? (entry.tool as Record<string, unknown>)
            : {};
        return {
          id,
          type: "tool",
          runId,
          toolCallId: String(tool.tool_call_id ?? `history-tool-${index}`),
          name: String(tool.name ?? entry.label ?? "tool"),
          args: tool.args,
          result: tool.result,
          status: "completed",
        };
      }
      if (kind === "error") {
        return {
          id,
          type: "status",
          runId,
          status: "failed",
          message: text,
        };
      }
      // Unknown kinds are not rendered — avoids dumping internal entries as
      // assistant text.
      return null;
    })
    .filter((block): block is ConversationBlock => block !== null);
}

export const useDesktopStore = create<DesktopStore>((set, get) => ({
  runtimeStatus: "unavailable",
  workspace: null,
  recentWorkspaces: [],
  sessions: [],
  archivedSessions: [],
  selectedSession: null,
  activeRunId: null,
  activeRunSessionId: null,
  pendingAttachments: [],
  config: null,
  conversation: initialConversationState,
  conversationCache: {},
  error: null,

  initialize: async () => {
    const persistedTheme = desktopStorage.getItem("yaacli.desktop.theme");
    if (persistedTheme === "light" || persistedTheme === "dark") {
      document.documentElement.dataset.theme = persistedTheme;
    }
    let recentWorkspaces: WorkspaceInfo[] = [];
    const persisted = desktopStorage.getItem("yaacli.desktop.recentWorkspaces");
    if (persisted) {
      try {
        recentWorkspaces = JSON.parse(persisted) as WorkspaceInfo[];
        set({ recentWorkspaces });
      } catch {
        desktopStorage.removeItem("yaacli.desktop.recentWorkspaces");
      }
    }
    const [unlistenEvents, unlistenState, unlistenDrop] = await Promise.all([
      bridge.subscribeProtocolEvents((event) => get().handleEvent(event)),
      bridge.subscribeRuntimeState((state) =>
        set({ runtimeStatus: state.status }),
      ),
      bridge.subscribeDroppedPaths((paths) => get().addAttachmentPaths(paths)),
    ]);
    const lastWorkspace = desktopStorage.getItem(
      "yaacli.desktop.lastWorkspace",
    );
    if (
      lastWorkspace &&
      recentWorkspaces.some((item) => item.path === lastWorkspace)
    ) {
      await get().openRecentWorkspace(lastWorkspace);
      // A vanished last workspace shouldn't pester the user on every launch.
      if (get().error) {
        set({ error: null });
        desktopStorage.removeItem("yaacli.desktop.lastWorkspace");
      }
    }
    return () => {
      unlistenEvents();
      unlistenState();
      unlistenDrop();
    };
  },

  openWorkspace: async () => {
    try {
      const path = await bridge.chooseWorkspace();
      if (!path) return;
      set({ runtimeStatus: "starting", error: null });
      await get().openRecentWorkspace(path);
    } catch (error) {
      set({ error: message(error), runtimeStatus: "unavailable" });
    }
  },

  openRecentWorkspace: async (path) => {
    try {
      const current = get();
      if (current.workspace?.path !== path && current.activeRunId) {
        set({ error: "Cancel the active run before switching workspaces." });
        return;
      }
      set({ runtimeStatus: "starting", error: null });
      if (current.workspace?.path !== path && current.workspace) {
        await bridge.stopRuntime();
      }
      const workspace = await bridge.openWorkspace(path);
      const [sessions, config] = await Promise.all([
        bridge.listSessions(),
        bridge.getConfig(),
      ]);
      const recentWorkspaces = [
        workspace,
        ...get().recentWorkspaces.filter(
          (item) => item.path !== workspace.path,
        ),
      ].slice(0, 12);
      desktopStorage.setItem(
        "yaacli.desktop.recentWorkspaces",
        JSON.stringify(recentWorkspaces),
      );
      set({
        workspace,
        recentWorkspaces,
        sessions,
        selectedSession: null,
        activeRunId: null,
        activeRunSessionId: null,
        pendingAttachments: [],
        conversation: initialConversationState,
        conversationCache: {},
        runtimeStatus: "ready",
        config,
      });
      desktopStorage.setItem("yaacli.desktop.lastWorkspace", workspace.path);
      if (config.theme) applyTheme(config.theme);
      void get().refreshArchivedSessions();
    } catch (error) {
      set((state) => ({
        error: message(error),
        runtimeStatus: "unavailable",
        recentWorkspaces: state.recentWorkspaces.map((item) =>
          item.path === path ? { ...item, available: false } : item,
        ),
      }));
    }
  },

  removeRecentWorkspace: (path) => {
    const recentWorkspaces = get().recentWorkspaces.filter(
      (item) => item.path !== path,
    );
    desktopStorage.setItem(
      "yaacli.desktop.recentWorkspaces",
      JSON.stringify(recentWorkspaces),
    );
    set({ recentWorkspaces });
  },

  createSession: async () => {
    try {
      const current = get();
      const conversationCache = cacheOutgoing(current);
      const selectedSession = await bridge.createSession();
      const sessions = await bridge.listSessions();
      set({
        selectedSession,
        sessions,
        conversationCache,
        pendingAttachments: [],
        conversation: initialConversationState,
        error: null,
      });
    } catch (error) {
      set({ error: message(error) });
    }
  },

  selectSession: async (sessionId) => {
    try {
      const current = get();
      const currentId = current.selectedSession?.session.id ?? null;
      // Preserve the outgoing session's live conversation (including any
      // in-flight stream) so switching back restores it instead of the stale
      // persisted transcript.
      const conversationCache = currentId
        ? { ...current.conversationCache, [currentId]: current.conversation }
        : { ...current.conversationCache };
      const selectedSession = await bridge.loadSession(sessionId);
      const cached = conversationCache[sessionId];
      const conversation = cached ?? {
        ...initialConversationState,
        blocks: transcriptToBlocks(selectedSession, sessionId),
      };
      // The live `conversation` field now owns this session's state.
      if (cached) delete conversationCache[sessionId];
      set({
        selectedSession,
        conversation,
        conversationCache,
        pendingAttachments: [],
        error: null,
      });
    } catch (error) {
      set({ error: message(error) });
    }
  },

  renameSelectedSession: async (name) => {
    const selected = get().selectedSession;
    if (!selected || !name.trim()) return;
    try {
      const session = await bridge.renameSession(
        selected.session.id,
        name.trim(),
      );
      const sessions = await bridge.listSessions();
      set({ selectedSession: { ...selected, session }, sessions, error: null });
    } catch (error) {
      set({ error: message(error) });
    }
  },

  archiveSelectedSession: async () => {
    const selected = get().selectedSession;
    if (!selected || get().activeRunId) return;
    try {
      await bridge.archiveSession(selected.session.id);
      const sessions = await bridge.listSessions();
      set((state) => {
        const conversationCache = { ...state.conversationCache };
        delete conversationCache[selected.session.id];
        return {
          sessions,
          selectedSession: null,
          pendingAttachments: [],
          conversation: initialConversationState,
          conversationCache,
          error: null,
        };
      });
      void get().refreshArchivedSessions();
    } catch (error) {
      set({ error: message(error) });
    }
  },

  refreshArchivedSessions: async () => {
    try {
      set({ archivedSessions: await bridge.listArchivedSessions() });
    } catch (error) {
      set({ error: message(error) });
    }
  },

  restoreArchivedSession: async (sessionId) => {
    if (get().activeRunId) return;
    try {
      const current = get();
      const conversationCache = cacheOutgoing(current);
      const selectedSession = await bridge.restoreSession(sessionId);
      const [sessions, archivedSessions] = await Promise.all([
        bridge.listSessions(),
        bridge.listArchivedSessions(),
      ]);
      const blocks = transcriptToBlocks(selectedSession, sessionId);
      set({
        selectedSession,
        sessions,
        archivedSessions,
        conversationCache,
        pendingAttachments: [],
        conversation: { ...initialConversationState, blocks },
        error: null,
      });
    } catch (error) {
      set({ error: message(error) });
    }
  },

  sendPrompt: async (text) => {
    const {
      selectedSession,
      activeRunId,
      activeRunSessionId,
      pendingAttachments,
    } = get();
    const prompt = text.trim();
    if (!selectedSession || (!prompt && pendingAttachments.length === 0))
      return;
    // The runtime allows a single active run at a time. Steering only targets
    // the active run, so if it belongs to another session we block rather than
    // inject into the wrong conversation.
    if (activeRunId && activeRunSessionId !== selectedSession.session.id) {
      set({
        error:
          "A run is active in another session. Cancel it before starting a new one.",
      });
      return;
    }
    const displayText =
      prompt ||
      pendingAttachments
        .map((part) => `[Attachment: ${part.name ?? part.path}]`)
        .join("\n");
    const previousConversation = get().conversation;
    set((state) => ({
      conversation: appendUserBlock(
        state.conversation,
        `user-${Date.now()}`,
        displayText,
      ),
      error: null,
    }));
    try {
      if (activeRunId) {
        if (pendingAttachments.length > 0) {
          throw new Error("Attachments cannot be added to steering input");
        }
        await bridge.steerRun(activeRunId, prompt);
        return;
      }
      const runId = await bridge.startRun(selectedSession.session.id, [
        ...(prompt ? [{ type: "text" as const, text: prompt }] : []),
        ...pendingAttachments,
      ]);
      set({
        activeRunId: runId,
        activeRunSessionId: selectedSession.session.id,
        pendingAttachments: [],
      });
    } catch (error) {
      // Roll back the optimistic user message so the conversation does not
      // show a prompt that never produced a run.
      set({ error: message(error), conversation: previousConversation });
    }
  },

  chooseAttachments: async () => {
    try {
      get().addAttachmentPaths(await bridge.chooseAttachmentPaths());
    } catch (error) {
      set({ error: message(error) });
    }
  },

  addAttachmentPaths: (paths) => {
    set((state) => ({
      pendingAttachments: [
        ...state.pendingAttachments,
        ...paths.map(bridge.inputPartFromPath),
      ].slice(0, 32),
    }));
  },

  addInlineAttachment: (part) => {
    set((state) => ({
      pendingAttachments: [...state.pendingAttachments, part].slice(0, 32),
    }));
  },

  removeAttachment: (index) => {
    set((state) => ({
      pendingAttachments: state.pendingAttachments.filter(
        (_item, itemIndex) => itemIndex !== index,
      ),
    }));
  },

  selectProfile: async (name) => {
    try {
      set({
        config: await bridge.updateConfig({ active_profile: name }),
        error: null,
      });
    } catch (error) {
      set({ error: message(error) });
    }
  },

  setTheme: async (theme) => {
    try {
      const config = await bridge.updateConfig({ theme });
      applyTheme(theme);
      set({ config, error: null });
    } catch (error) {
      set({ error: message(error) });
    }
  },

  resolveApproval: async (approval, decision, reason) => {
    try {
      await bridge.resolveApproval(approval, decision, reason);
    } catch (error) {
      set({ error: message(error) });
    }
  },

  cancelRun: async () => {
    const runId = get().activeRunId;
    if (!runId) return;
    try {
      await bridge.cancelRun(runId);
    } catch (error) {
      set({ error: message(error) });
    }
  },

  handleEvent: (event) => {
    const terminal = ["run.completed", "run.cancelled", "run.failed"].includes(
      event.event,
    );
    if (terminal) {
      const title =
        event.event === "run.completed"
          ? "YAACLI run completed"
          : "YAACLI run stopped";
      void bridge.notifyRun(title, event.event.replace("run.", ""));
      // A finished run may have auto-renamed its session (last user prompt);
      // refresh the sidebar, but only if the user hasn't since switched to a
      // different workspace.
      const workspacePath = get().workspace?.path;
      void bridge
        .listSessions()
        .then((sessions) => {
          if (get().workspace?.path === workspacePath) set({ sessions });
        })
        .catch(() => undefined);
    }
    set((state) => {
      const clearRun = terminal
        ? {
            activeRunId: null as string | null,
            activeRunSessionId: null as string | null,
          }
        : {};
      const selectedId = state.selectedSession?.session.id ?? null;
      const targetId = event.session_id ?? null;
      // Events for a session that is not currently visible update that
      // session's cached conversation so switching back shows its live state
      // instead of the stale persisted transcript.
      if (targetId && targetId !== selectedId) {
        const cached = state.conversationCache[targetId];
        if (!cached) return clearRun;
        return {
          conversationCache: {
            ...state.conversationCache,
            [targetId]: reduceProtocolEvent(cached, event),
          },
          ...clearRun,
        };
      }
      return {
        conversation: reduceProtocolEvent(state.conversation, event),
        ...clearRun,
      };
    });
  },

  clearError: () => set({ error: null }),
}));
