import { beforeEach, describe, expect, test, vi } from "vitest";

import * as bridge from "./bridge";
import { initialConversationState } from "./conversation";
import { useDesktopStore } from "./desktopStore";
import type { EventEnvelope, SessionSummary, WorkspaceInfo } from "./protocol";
import { desktopStorage } from "./storage";

vi.mock("./bridge", () => ({
  subscribeProtocolEvents: vi.fn(async () => () => undefined),
  subscribeRuntimeState: vi.fn(async () => () => undefined),
  subscribeDroppedPaths: vi.fn(async () => () => undefined),
  openWorkspace: vi.fn(),
  stopRuntime: vi.fn(),
  getConfig: vi.fn(async () => ({
    configured: true,
    active_profile: "default",
    profiles: {
      default: { label: "Default", model: "test:model", description: "" },
    },
    sources: [],
    theme: "dark",
  })),
  updateConfig: vi.fn(),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  loadSession: vi.fn(),
  renameSession: vi.fn(),
  archiveSession: vi.fn(),
  listArchivedSessions: vi.fn(async () => []),
  restoreSession: vi.fn(),
  startRun: vi.fn(),
  cancelRun: vi.fn(),
  steerRun: vi.fn(),
  chooseAttachmentPaths: vi.fn(),
  inputPartFromPath: vi.fn((path: string) => ({
    type: "file",
    path,
    name: path.split("/").at(-1),
  })),
  resolveApproval: vi.fn(),
  notifyRun: vi.fn(),
}));

const firstWorkspace: WorkspaceInfo = {
  id: "workspace-first",
  name: "first",
  path: "/tmp/first",
  available: true,
  guidance_sources: [],
  config_sources: [],
};

const secondWorkspace: WorkspaceInfo = {
  ...firstWorkspace,
  id: "workspace-second",
  name: "second",
  path: "/tmp/second",
};

const firstSession: SessionSummary = {
  id: "session-first",
  name: "First session",
  latest_user_prompt: "",
  updated_at: "",
  workspace_id: firstWorkspace.id,
  model: "",
  archived: false,
};

describe("desktop workspace state", () => {
  beforeEach(() => {
    desktopStorage.clear();
    vi.clearAllMocks();
    useDesktopStore.setState({
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
    });
  });

  test("switching workspace clears session and conversation state", async () => {
    vi.mocked(bridge.openWorkspace)
      .mockResolvedValueOnce(firstWorkspace)
      .mockResolvedValueOnce(secondWorkspace);
    vi.mocked(bridge.listSessions)
      .mockResolvedValueOnce([firstSession])
      .mockResolvedValueOnce([]);

    await useDesktopStore.getState().openRecentWorkspace(firstWorkspace.path);
    useDesktopStore.setState({
      selectedSession: {
        session: firstSession,
        transcript: [],
        run_status: "idle",
      },
      conversation: {
        ...initialConversationState,
        blocks: [{ id: "user-1", type: "user", text: "hello" }],
      },
    });
    await useDesktopStore.getState().openRecentWorkspace(secondWorkspace.path);

    const state = useDesktopStore.getState();
    expect(state.workspace?.id).toBe(secondWorkspace.id);
    expect(state.sessions).toEqual([]);
    expect(state.selectedSession).toBeNull();
    expect(state.conversation.blocks).toEqual([]);
    expect(bridge.stopRuntime).toHaveBeenCalledOnce();
  });

  test("active run must be cancelled before switching workspace", async () => {
    useDesktopStore.setState({
      workspace: firstWorkspace,
      activeRunId: "run-1",
    });

    await useDesktopStore.getState().openRecentWorkspace(secondWorkspace.path);

    expect(bridge.stopRuntime).not.toHaveBeenCalled();
    expect(bridge.openWorkspace).not.toHaveBeenCalled();
    expect(useDesktopStore.getState().error).toBe(
      "Cancel the active run before switching workspaces.",
    );
  });

  test("unavailable recent workspace is retained and marked", async () => {
    useDesktopStore.setState({ recentWorkspaces: [firstWorkspace] });
    vi.mocked(bridge.openWorkspace).mockRejectedValue(new Error("missing"));

    await useDesktopStore.getState().openRecentWorkspace(firstWorkspace.path);

    expect(useDesktopStore.getState().recentWorkspaces[0].available).toBe(
      false,
    );
    expect(useDesktopStore.getState().error).toBe("missing");
  });

  test("creating a session selects it and resets the conversation", async () => {
    const created = {
      session: firstSession,
      transcript: [],
      run_status: "idle" as const,
    };
    vi.mocked(bridge.createSession).mockResolvedValue(created);
    vi.mocked(bridge.listSessions).mockResolvedValue([firstSession]);
    useDesktopStore.setState({
      workspace: firstWorkspace,
      conversation: {
        ...initialConversationState,
        blocks: [{ id: "old", type: "user", text: "old conversation" }],
      },
    });

    await useDesktopStore.getState().createSession();

    expect(useDesktopStore.getState().selectedSession).toEqual(created);
    expect(useDesktopStore.getState().conversation.blocks).toEqual([]);
    expect(useDesktopStore.getState().sessions).toEqual([firstSession]);
  });

  test("selecting a session maps transcript kinds into typed blocks", async () => {
    vi.mocked(bridge.loadSession).mockResolvedValue({
      session: firstSession,
      run_status: "completed" as const,
      transcript: [
        { kind: "user", text: "list the files" },
        { kind: "assistant", text: "Here is the plan." },
        {
          kind: "tool",
          text: "",
          tool: {
            name: "list_files",
            tool_call_id: "tc-1",
            args: { path: "apps/yaacli-desktop" },
            result: '[{"name":"README.md"}]',
          },
        },
        { kind: "error", text: "boom" },
        { kind: "system", text: "should be dropped" },
      ],
    });

    await useDesktopStore.getState().selectSession("session-first");

    const blocks = useDesktopStore.getState().conversation.blocks;
    // Unknown kinds ("system") are dropped, not rendered as assistant text.
    expect(blocks).toHaveLength(4);
    expect(blocks[0]).toMatchObject({ type: "user", text: "list the files" });
    expect(blocks[1]).toMatchObject({
      type: "text",
      text: "Here is the plan.",
    });
    expect(blocks[2]).toMatchObject({
      type: "tool",
      name: "list_files",
      args: { path: "apps/yaacli-desktop" },
      result: '[{"name":"README.md"}]',
      status: "completed",
    });
    expect(blocks[3]).toMatchObject({
      type: "status",
      status: "failed",
      message: "boom",
    });
  });

  test("steering is delivered to the active run without starting another run", async () => {
    useDesktopStore.setState({
      selectedSession: {
        session: firstSession,
        transcript: [],
        run_status: "running",
      },
      activeRunId: "run-1",
      activeRunSessionId: firstSession.id,
    });

    await useDesktopStore.getState().sendPrompt("adjust the plan");

    expect(bridge.steerRun).toHaveBeenCalledWith("run-1", "adjust the plan");
    expect(bridge.startRun).not.toHaveBeenCalled();
  });

  test("switching away mid-stream preserves the session's live conversation", async () => {
    const streamSession: SessionSummary = {
      ...firstSession,
      id: "session-stream",
      name: "stream",
    };
    const otherSession: SessionSummary = {
      ...firstSession,
      id: "session-other",
      name: "other",
    };
    useDesktopStore.setState({
      workspace: firstWorkspace,
      selectedSession: {
        session: streamSession,
        transcript: [],
        run_status: "running",
      },
      activeRunId: "run-1",
      activeRunSessionId: streamSession.id,
      conversation: {
        ...initialConversationState,
        blocks: [{ id: "user-1", type: "user", text: "hello" }],
      },
    });
    // While the run streams into session-stream, a delta arrives for it while
    // the user is viewing another session: it must update the cached state, not
    // the visible conversation.
    vi.mocked(bridge.loadSession).mockResolvedValue({
      session: otherSession,
      transcript: [],
      run_status: "idle" as const,
    });
    await useDesktopStore.getState().selectSession(otherSession.id);

    useDesktopStore.getState().handleEvent({
      protocol_version: 1,
      type: "event",
      event: "text.delta",
      payload: { delta: "world" },
      run_id: "run-1",
      session_id: streamSession.id,
      sequence: 1,
    } satisfies EventEnvelope);

    // Visible conversation belongs to the other session (empty — no pollution
    // from the stream session's delta).
    expect(useDesktopStore.getState().conversation.blocks).toEqual([]);
    // The streamed session's cached state kept its user block AND captured the
    // delta that arrived while another session was viewed.
    const cached =
      useDesktopStore.getState().conversationCache[streamSession.id];
    expect(cached.blocks[0]).toMatchObject({
      type: "user",
      text: "hello",
    });
    expect(cached.blocks.at(-1)).toMatchObject({
      type: "text",
      text: "world",
    });
  });

  test("dropped paths become ordered pending attachments", () => {
    useDesktopStore.getState().addAttachmentPaths(["/tmp/a.txt", "/tmp/b.txt"]);

    expect(
      useDesktopStore.getState().pendingAttachments.map((item) => item.name),
    ).toEqual(["a.txt", "b.txt"]);
  });
});
