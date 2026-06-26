import {
  Activity,
  Archive,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  Copy,
  Files,
  FolderOpen,
  GitBranch,
  PanelRight,
  MessageSquarePlus,
  Paperclip,
  Pencil,
  RotateCcw,
  Search,
  Send,
  Settings2,
  Sparkles,
  Square,
  TerminalSquare,
  Wrench,
  X,
} from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { convertFileSrc } from "@tauri-apps/api/core";
import {
  useEffect,
  useLayoutEffect,
  useCallback,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type FormEvent,
  type ReactNode,
} from "react";

import ReactMarkdown from "react-markdown";

import {
  markdownComponents,
  markdownRehypePlugins,
  markdownRemarkPlugins,
} from "./markdown";
import type { ConversationBlock } from "./conversation";
import type { SessionSummary } from "./protocol";
import {
  credentialStatus,
  deleteCredential,
  inputPartFromClipboardFile,
  setCredential,
} from "./bridge";
import { useDesktopStore } from "./desktopStore";
import { desktopStorage } from "./storage";

const SESSION_GROUPS = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "week", label: "Previous 7 days" },
  { key: "older", label: "Older" },
] as const;

type SessionGroupKey = (typeof SESSION_GROUPS)[number]["key"];

const RUNTIME_LABEL: Record<string, string> = {
  ready: "Ready",
  starting: "Starting",
  stopping: "Stopping",
  unavailable: "Offline",
};

function sessionBucket(updatedAt: string): SessionGroupKey {
  if (!updatedAt) return "older";
  const ts = Date.parse(updatedAt);
  if (Number.isNaN(ts)) return "older";
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const day = 86400000;
  if (ts >= startOfToday) return "today";
  if (ts >= startOfToday - day) return "yesterday";
  if (ts >= startOfToday - 7 * day) return "week";
  return "older";
}

function relativeTime(updatedAt: string): string {
  if (!updatedAt) return "";
  const ts = Date.parse(updatedAt);
  if (Number.isNaN(ts)) return "";
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(ts).toLocaleDateString();
}

function groupedSessions(
  sessions: SessionSummary[],
  query: string,
): Array<{ key: SessionGroupKey; label: string; sessions: SessionSummary[] }> {
  const q = query.trim().toLowerCase();
  const filtered = q
    ? sessions.filter((session) => {
        const haystack =
          `${session.name} ${session.latest_user_prompt}`.toLowerCase();
        return haystack.includes(q);
      })
    : sessions;
  const buckets: Record<SessionGroupKey, SessionSummary[]> = {
    today: [],
    yesterday: [],
    week: [],
    older: [],
  };
  for (const session of filtered) {
    buckets[sessionBucket(session.updated_at)].push(session);
  }
  return SESSION_GROUPS.map((group) => ({
    ...group,
    sessions: buckets[group.key],
  })).filter((group) => group.sessions.length > 0);
}

export function App() {
  const [contextOpen, setContextOpen] = useState(
    () => desktopStorage.getItem("yaacli.desktop.contextOpen") === "true",
  );
  const [sessionQuery, setSessionQuery] = useState("");
  const [prompt, setPrompt] = useState("");
  const [settingsVisible, setSettingsVisible] = useState(false);
  const [archiveConfirm, setArchiveConfirm] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [focusToken, setFocusToken] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);
  const runtimeStatus = useDesktopStore((state) => state.runtimeStatus);
  const workspace = useDesktopStore((state) => state.workspace);
  const recentWorkspaces = useDesktopStore((state) => state.recentWorkspaces);
  const sessions = useDesktopStore((state) => state.sessions);
  const archivedSessions = useDesktopStore((state) => state.archivedSessions);
  const selectedSession = useDesktopStore((state) => state.selectedSession);
  const activeRunId = useDesktopStore((state) => state.activeRunId);
  const activeRunSessionId = useDesktopStore(
    (state) => state.activeRunSessionId,
  );
  const pendingAttachments = useDesktopStore(
    (state) => state.pendingAttachments,
  );
  const config = useDesktopStore((state) => state.config);
  const conversation = useDesktopStore((state) => state.conversation);
  const error = useDesktopStore((state) => state.error);
  const initialize = useDesktopStore((state) => state.initialize);
  const openWorkspace = useDesktopStore((state) => state.openWorkspace);
  const openRecentWorkspace = useDesktopStore(
    (state) => state.openRecentWorkspace,
  );
  const removeRecentWorkspace = useDesktopStore(
    (state) => state.removeRecentWorkspace,
  );
  const createSession = useDesktopStore((state) => state.createSession);
  const selectSession = useDesktopStore((state) => state.selectSession);
  const renameSelectedSession = useDesktopStore(
    (state) => state.renameSelectedSession,
  );
  const archiveSelectedSession = useDesktopStore(
    (state) => state.archiveSelectedSession,
  );
  const restoreArchivedSession = useDesktopStore(
    (state) => state.restoreArchivedSession,
  );
  const sendPrompt = useDesktopStore((state) => state.sendPrompt);
  const chooseAttachments = useDesktopStore((state) => state.chooseAttachments);
  const addInlineAttachment = useDesktopStore(
    (state) => state.addInlineAttachment,
  );
  const removeAttachment = useDesktopStore((state) => state.removeAttachment);
  const selectProfile = useDesktopStore((state) => state.selectProfile);
  const setTheme = useDesktopStore((state) => state.setTheme);
  const cancelRun = useDesktopStore((state) => state.cancelRun);
  const clearError = useDesktopStore((state) => state.clearError);

  useEffect(() => {
    let cleanup: () => void = () => undefined;
    void initialize().then((unsubscribe) => {
      cleanup = unsubscribe;
    });
    return () => cleanup();
  }, [initialize]);

  const toggleContext = useCallback(() => {
    setContextOpen((open) => {
      const next = !open;
      desktopStorage.setItem("yaacli.desktop.contextOpen", String(next));
      return next;
    });
  }, []);

  const startNewSession = useCallback(() => {
    setPrompt("");
    setFocusToken((token) => token + 1);
    void createSession();
  }, [createSession]);

  useEffect(() => {
    const shortcuts = (event: KeyboardEvent) => {
      if (event.metaKey && event.key.toLowerCase() === "o") {
        event.preventDefault();
        void openWorkspace();
      } else if (event.metaKey && event.key.toLowerCase() === "n") {
        event.preventDefault();
        if (workspace) startNewSession();
      } else if (event.metaKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      } else if (event.key === "Escape") {
        if (archiveConfirm) {
          setArchiveConfirm(false);
        } else if (contextOpen) {
          setContextOpen(false);
          desktopStorage.setItem("yaacli.desktop.contextOpen", "false");
        } else if (activeRunId) {
          event.preventDefault();
          void cancelRun();
        }
      }
    };
    window.addEventListener("keydown", shortcuts);
    return () => window.removeEventListener("keydown", shortcuts);
  }, [
    activeRunId,
    archiveConfirm,
    cancelRun,
    contextOpen,
    openWorkspace,
    startNewSession,
    workspace,
  ]);

  const contextBadge =
    conversation.tasks.length + conversation.fileChanges.length;

  // A run that belongs to a different session than the one being viewed must not
  // drive this view's streaming cursor or composer state.
  const runInSelectedSession =
    Boolean(activeRunId) && activeRunSessionId === selectedSession?.session.id;

  const groups = groupedSessions(sessions, sessionQuery);

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Workspaces and sessions">
        <div className="traffic-light-space" />
        <div className="brand">
          <span className="brand-mark">
            <TerminalSquare size={15} />
          </span>
          <span className="brand-name">YAACLI</span>
        </div>

        <button
          className="workspace-switcher"
          onClick={() => void openWorkspace()}
          type="button"
        >
          <span className="workspace-mark">
            <FolderOpen size={14} />
          </span>
          <span className="workspace-copy">
            <strong>{workspace?.name ?? "Open workspace"}</strong>
            <span>{workspace?.path ?? "Choose a local project directory"}</span>
          </span>
          <ChevronDown size={14} aria-hidden="true" />
        </button>

        <button
          className="primary-action"
          disabled={!workspace || runtimeStatus !== "ready"}
          onClick={startNewSession}
          type="button"
        >
          <MessageSquarePlus size={15} /> New session
        </button>

        <label className="search-box">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">Search sessions</span>
          <input
            onChange={(event) => setSessionQuery(event.target.value)}
            placeholder="Search sessions"
            ref={searchRef}
            value={sessionQuery}
          />
          <kbd>⌘K</kbd>
        </label>

        <div className="session-scroll">
          {groups.map((group) => (
            <section className="session-group" key={group.key}>
              <p className="session-group-label">{group.label}</p>
              <ul className="session-list">
                {group.sessions.map((session) => (
                  <li key={session.id}>
                    <button
                      className={
                        selectedSession?.session.id === session.id
                          ? "session-row active"
                          : "session-row"
                      }
                      onClick={() => void selectSession(session.id)}
                      type="button"
                    >
                      <span className="session-title">
                        {session.name ||
                          session.latest_user_prompt ||
                          "New session"}
                      </span>
                      <span className="session-sub">
                        {session.latest_user_prompt
                          ? relativeTime(session.updated_at)
                          : (session.updated_at &&
                              relativeTime(session.updated_at)) ||
                            "Empty"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {workspace && groups.length === 0 && (
            <p className="empty-copy">
              {sessionQuery ? "No matching sessions." : "No sessions yet."}
            </p>
          )}
        </div>

        {workspace && archivedSessions.length > 0 && (
          <section
            className="session-group archived-group"
            aria-label="Archived sessions"
          >
            <button
              aria-expanded={showArchived}
              className="session-group-label toggle"
              onClick={() => setShowArchived((open) => !open)}
              type="button"
            >
              <ChevronDown
                className={showArchived ? "expanded" : ""}
                size={12}
              />
              Archived <span>{archivedSessions.length}</span>
            </button>
            {showArchived && (
              <ul className="session-list">
                {archivedSessions.map((session) => (
                  <li className="archived-row" key={session.id}>
                    <span className="session-title">
                      {session.name ||
                        session.latest_user_prompt ||
                        "New session"}
                    </span>
                    <button
                      aria-label={`Restore ${session.name || "session"}`}
                      className="icon-button restore-button"
                      disabled={Boolean(activeRunId)}
                      onClick={() => void restoreArchivedSession(session.id)}
                      title="Restore session"
                      type="button"
                    >
                      <RotateCcw size={12} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {recentWorkspaces.length > 0 && (
          <nav className="workspace-list" aria-label="Recent workspaces">
            <p className="session-group-label">Workspaces</p>
            {recentWorkspaces.map((item) => (
              <div className="workspace-row" key={item.path}>
                <button
                  className={item.available ? "" : "unavailable"}
                  onClick={() => void openRecentWorkspace(item.path)}
                  title={item.path}
                  type="button"
                >
                  <FolderOpen size={13} /> <span>{item.name}</span>
                </button>
                <button
                  aria-label={`Remove ${item.name} from recent workspaces`}
                  onClick={() => removeRecentWorkspace(item.path)}
                  type="button"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
          </nav>
        )}

        <div className="sidebar-footer">
          <button onClick={() => void openWorkspace()} type="button">
            <FolderOpen size={15} /> Open workspace
          </button>
          <button onClick={() => setSettingsVisible(true)} type="button">
            <Settings2 size={15} /> Settings
          </button>
        </div>
      </aside>

      <section className="conversation">
        <header className="topbar">
          <div className="topbar-title">
            <div className="eyebrow">
              <GitBranch size={12} />{" "}
              {workspace?.git_branch ?? workspace?.name ?? "No workspace"}
            </div>
            {selectedSession ? (
              <SessionTitle
                name={selectedSession.session.name || "New session"}
                onCommit={(name) => void renameSelectedSession(name)}
              />
            ) : (
              <h1>YAACLI Desktop</h1>
            )}
          </div>
          <div className="topbar-actions">
            <span className={`runtime-indicator ${runtimeStatus}`}>
              <span /> {RUNTIME_LABEL[runtimeStatus] ?? runtimeStatus}
            </span>
            <label className="model-select">
              <Sparkles size={13} />
              <span className="sr-only">Model profile</span>
              <select
                disabled={!config || Boolean(activeRunId)}
                onChange={(event) => void selectProfile(event.target.value)}
                value={config?.active_profile ?? ""}
              >
                {!config?.active_profile && (
                  <option value="">Model profile</option>
                )}
                {Object.entries(config?.profiles ?? {}).map(
                  ([name, profile]) => (
                    <option key={name} value={name}>
                      {profile.label}
                    </option>
                  ),
                )}
              </select>
            </label>
            {selectedSession && (
              <button
                aria-label="Archive session"
                className="icon-button"
                disabled={Boolean(activeRunId)}
                onClick={() => setArchiveConfirm(true)}
                type="button"
              >
                <Archive size={15} />
              </button>
            )}
            <button
              aria-expanded={contextOpen}
              aria-label={
                contextOpen ? "Close run context" : "Open run context"
              }
              className={
                contextOpen
                  ? "icon-button context-toggle active"
                  : "icon-button context-toggle"
              }
              onClick={toggleContext}
              type="button"
            >
              <PanelRight size={16} />
              {!contextOpen && contextBadge > 0 && (
                <span className="badge">{contextBadge}</span>
              )}
            </button>
          </div>
        </header>

        <ConversationTimeline
          runActive={runInSelectedSession}
          blocks={conversation.blocks}
          empty={
            !workspace ? (
              <Welcome onOpen={() => void openWorkspace()} />
            ) : !selectedSession ? (
              <EmptySession onCreate={startNewSession} />
            ) : null
          }
        />

        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <button
              aria-label="Dismiss error"
              onClick={clearError}
              type="button"
            >
              <X size={14} />
            </button>
          </div>
        )}

        <Composer
          busy={runInSelectedSession}
          addInlineAttachment={addInlineAttachment}
          attachments={pendingAttachments}
          chooseAttachments={chooseAttachments}
          focusToken={focusToken}
          onCancel={() => void cancelRun()}
          onRemoveAttachment={removeAttachment}
          onSubmit={(value) => {
            void sendPrompt(value);
            setPrompt("");
          }}
          onPromptChange={setPrompt}
          prompt={prompt}
          runtimeReady={runtimeStatus === "ready"}
          selectedSession={selectedSession}
        />
      </section>

      <div
        aria-hidden={!contextOpen}
        className={contextOpen ? "context-backdrop open" : "context-backdrop"}
        onClick={toggleContext}
      />
      <aside
        aria-hidden={!contextOpen}
        aria-label="Run context"
        className={contextOpen ? "context-drawer open" : "context-drawer"}
        inert={!contextOpen}
      >
        <header className="context-header">
          <div>
            <Activity size={15} /> Run context
          </div>
          <span className={`status-pill ${activeRunId ? "" : "idle"}`}>
            <span /> {activeRunId ? "Running" : "Idle"}
          </span>
        </header>
        <div className="context-body">
          <section className="context-section">
            <h2>
              Plan <span>{conversation.tasks.length}</span>
            </h2>
            {conversation.tasks.length > 0 ? (
              <ol className="task-list">
                {conversation.tasks.map((task, index) => {
                  const status = String(task.status ?? "");
                  return (
                    <li
                      className={status === "completed" ? "completed" : ""}
                      key={String(task.id ?? index)}
                    >
                      {status === "completed" ? (
                        <CheckCircle2 size={14} />
                      ) : (
                        <CircleDashed size={14} />
                      )}
                      {String(
                        task.subject ?? task.description ?? `Task ${index + 1}`,
                      )}
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="empty-copy">Tasks appear while the agent works.</p>
            )}
          </section>

          <section className="context-section">
            <h2>
              Guidance <span>{workspace?.guidance_sources.length ?? 0}</span>
            </h2>
            {workspace?.guidance_sources.map((source) => (
              <div className="activity-row" key={source}>
                <Files size={14} />
                <span>
                  <strong>{source.split("/").at(-1)}</strong>
                  <small>{source}</small>
                </span>
              </div>
            ))}
            {workspace && workspace.guidance_sources.length === 0 && (
              <p className="empty-copy">No project guidance discovered.</p>
            )}
          </section>

          <section className="context-section">
            <h2>
              Changes <span>{conversation.fileChanges.length}</span>
            </h2>
            {conversation.fileChanges.map((change, index) => (
              <details className="change-row" key={`${change.path}-${index}`}>
                <summary>
                  <Files size={14} />
                  <span>
                    <strong>{change.path}</strong>
                    <small>{change.change_type}</small>
                  </span>
                </summary>
                {change.diff_available && change.diff ? (
                  <pre>{change.diff}</pre>
                ) : (
                  <p>
                    {change.binary
                      ? "Binary content cannot be previewed."
                      : "No text diff available."}
                  </p>
                )}
              </details>
            ))}
            {conversation.fileChanges.length === 0 && (
              <p className="empty-copy">File changes appear here.</p>
            )}
          </section>

          <section className="context-section">
            <h2>Context</h2>
            <div className="usage-copy">
              <span>
                <strong>
                  {Number(
                    conversation.usage?.total_tokens ?? 0,
                  ).toLocaleString()}
                </strong>{" "}
                tokens
              </span>
              <span>
                {conversation.warnings.length
                  ? `${conversation.warnings.length} warnings`
                  : "synced"}
              </span>
            </div>
            <div className="usage-track">
              <span />
            </div>
          </section>
        </div>
      </aside>

      {settingsVisible && (
        <SettingsPanel
          config={config}
          onClose={() => setSettingsVisible(false)}
          onTheme={(theme) => void setTheme(theme)}
        />
      )}

      {archiveConfirm && selectedSession && (
        <ConfirmDialog
          body="The session moves to the Archived list and can be restored later. Any active run must be cancelled first."
          confirmLabel="Archive"
          destructive
          onCancel={() => setArchiveConfirm(false)}
          onConfirm={() => {
            setArchiveConfirm(false);
            void archiveSelectedSession();
          }}
          title="Archive this session?"
        />
      )}
    </main>
  );
}

function SessionTitle({
  name,
  onCommit,
}: {
  name: string;
  onCommit: (name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);

  const begin = () => {
    setDraft(name);
    setEditing(true);
  };

  const commit = () => {
    const trimmed = draft.trim();
    setEditing(false);
    if (trimmed && trimmed !== name) onCommit(trimmed);
  };

  if (editing) {
    return (
      <input
        aria-label="Session name"
        autoFocus
        className="session-title-input"
        onBlur={commit}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            setDraft(name);
            setEditing(false);
          }
        }}
        value={draft}
      />
    );
  }

  return (
    <div className="session-title">
      <h1 onClick={begin} title="Click to rename">
        {name}
      </h1>
      <button
        aria-label="Rename session"
        className="icon-button"
        onClick={begin}
        type="button"
      >
        <Pencil size={13} />
      </button>
    </div>
  );
}

type ConfirmDialogProps = {
  title: string;
  body: string;
  confirmLabel: string;
  destructive?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
};

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  destructive,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <div className="settings-backdrop" onClick={onCancel} role="presentation">
      <section
        aria-label={title}
        aria-modal="true"
        className="settings-panel confirm-panel"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header>
          <div>
            <strong>{title}</strong>
          </div>
          <button aria-label="Cancel" onClick={onCancel} type="button">
            <X size={15} />
          </button>
        </header>
        <div className="settings-body">
          <p className="confirm-body">{body}</p>
          <div className="settings-actions">
            <button onClick={onCancel} type="button">
              Cancel
            </button>
            <button
              className={destructive ? "danger" : ""}
              onClick={onConfirm}
              type="button"
            >
              {confirmLabel}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

type ComposerProps = {
  busy: boolean;
  addInlineAttachment: (part: import("./protocol").InputPart) => void;
  attachments: import("./protocol").InputPart[];
  chooseAttachments: () => Promise<void>;
  focusToken: number;
  onCancel: () => void;
  onRemoveAttachment: (index: number) => void;
  onSubmit: (value: string) => void;
  onPromptChange: (value: string) => void;
  prompt: string;
  runtimeReady: boolean;
  selectedSession: import("./protocol").SessionSnapshot | null;
};

function Composer({
  busy,
  addInlineAttachment,
  attachments,
  chooseAttachments,
  focusToken,
  onCancel,
  onRemoveAttachment,
  onSubmit,
  onPromptChange,
  prompt,
  runtimeReady,
  selectedSession,
}: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const max = Math.max(120, Math.round(window.innerHeight * 0.38));
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
  }, [prompt]);

  // Focus when a NEW session is created, not on every session selection —
  // browsing the sidebar must not yank focus away from the list.
  useEffect(() => {
    if (focusToken > 0) ref.current?.focus();
  }, [focusToken]);

  const paste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const images = Array.from(event.clipboardData.files).filter((file) =>
      file.type.startsWith("image/"),
    );
    if (images.length === 0) return;
    event.preventDefault();
    for (const image of images) {
      void inputPartFromClipboardFile(image)
        .then(addInlineAttachment)
        .catch((failure: unknown) => console.warn(failure));
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!prompt.trim() && attachments.length === 0) return;
    onSubmit(prompt);
  };

  const disabled = !selectedSession;

  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={submit}>
        <textarea
          aria-label="Message"
          disabled={disabled}
          onChange={(event) => onPromptChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && event.metaKey) submit(event);
          }}
          onPaste={paste}
          placeholder={
            selectedSession
              ? busy
                ? "Steer the active run…"
                : "Ask YAACLI to work in this workspace…"
              : "Open a workspace and create a session"
          }
          ref={ref}
          rows={2}
          value={prompt}
        />
        {attachments.length > 0 && (
          <div className="attachment-list">
            {attachments.map((attachment, index) => {
              const src = attachmentSrc(attachment);
              return (
                <span
                  className={`attachment-chip${src ? " with-thumb" : ""}`}
                  key={`${attachment.name}-${index}`}
                >
                  {src ? (
                    <img
                      alt={attachment.name ?? "attachment"}
                      className="attachment-thumb"
                      src={src}
                    />
                  ) : (
                    <Paperclip size={11} />
                  )}
                  <span className="attachment-name">
                    {attachment.name ?? attachment.path ?? "Attachment"}
                  </span>
                  <button
                    aria-label={`Remove ${attachment.name ?? "attachment"}`}
                    onClick={() => onRemoveAttachment(index)}
                    type="button"
                  >
                    <X size={11} />
                  </button>
                </span>
              );
            })}
          </div>
        )}
        <div className="composer-actions">
          <button
            aria-label="Attach files"
            className="icon-button"
            disabled={disabled || busy}
            onClick={() => void chooseAttachments()}
            type="button"
          >
            <Paperclip size={16} />
          </button>
          <span className="composer-hint">
            <kbd>⌘↵</kbd> {busy ? "to steer · Esc to cancel" : "to send"}
          </span>
          {busy ? (
            <button
              aria-label="Cancel run"
              className="send-button cancel-button"
              disabled={!runtimeReady}
              onClick={onCancel}
              type="button"
            >
              <Square size={13} />
            </button>
          ) : (
            <button
              aria-label="Send message"
              className="send-button"
              disabled={
                disabled || (!prompt.trim() && attachments.length === 0)
              }
              type="submit"
            >
              <Send size={16} />
            </button>
          )}
        </div>
      </form>
      <p className="disclaimer">
        YAACLI can modify files and run commands. Review approvals and diffs.
      </p>
    </div>
  );
}

function ConversationTimeline({
  runActive,
  blocks,
  empty,
}: {
  runActive: boolean;
  blocks: ConversationBlock[];
  empty: ReactNode;
}) {
  const parentRef = useRef<HTMLDivElement>(null);
  // Tracks whether the user is parked at the bottom. Scrolling up pauses
  // auto-follow so streaming output does not yank them back down.
  const stickRef = useRef(true);
  // TanStack Virtual intentionally returns mutable measurement callbacks.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: blocks.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const type = blocks[index]?.type;
      return type === "tool" ? 38 : type === "thinking" ? 34 : 140;
    },
    overscan: 6,
  });

  const onScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickRef.current = distance < 80;
  }, []);

  useEffect(() => {
    if (blocks.length === 0) return;
    const last = blocks[blocks.length - 1];
    // A freshly sent user message always snaps back to the latest content.
    if (last.type === "user") stickRef.current = true;
    if (stickRef.current) {
      virtualizer.scrollToIndex(blocks.length - 1, { align: "end" });
    }
  }, [blocks, virtualizer]);

  return (
    <div className="transcript" onScroll={onScroll} ref={parentRef}>
      {blocks.length === 0 ? (
        empty
      ) : (
        <div
          className="virtual-transcript"
          style={{ height: virtualizer.getTotalSize() }}
        >
          {virtualizer.getVirtualItems().map((row) => {
            const block = blocks[row.index];
            const streaming =
              runActive &&
              row.index === blocks.length - 1 &&
              block.type === "text";
            return (
              <div
                className="virtual-message"
                data-index={row.index}
                key={block.id}
                ref={virtualizer.measureElement}
                style={{ transform: `translateY(${row.start}px)` }}
              >
                <ConversationItem block={block} streaming={streaming} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ConversationItem({
  block,
  streaming,
}: {
  block: ConversationBlock;
  streaming: boolean;
}) {
  const runtimeStatus = useDesktopStore((state) => state.runtimeStatus);
  const resolveApproval = useDesktopStore((state) => state.resolveApproval);
  if (block.type === "user") {
    return (
      <article className="message user-message">
        <div className="message-meta">You</div>
        <div className="message-body">{block.text}</div>
      </article>
    );
  }
  if (block.type === "thinking") {
    return <ThinkingBlock id={block.id} text={block.text} />;
  }
  if (block.type === "tool") {
    return <ToolCall block={block} />;
  }
  if (block.type === "status") {
    if (block.status === "started" || block.status === "phase") return null;
    return (
      <div className={`run-status ${block.status}`}>
        {block.status}
        {block.message ? `: ${block.message}` : ""}
      </div>
    );
  }
  if (block.type === "approval") {
    return (
      <div className="approval-card">
        <Wrench size={16} />
        <div>
          <strong>Approval required: {block.approval.tool_name}</strong>
          <p>{block.approval.summary}</p>
          {block.status === "pending" ? (
            <div className="approval-actions">
              <button
                disabled={runtimeStatus !== "ready"}
                onClick={() =>
                  void resolveApproval(block.approval, "approve_once")
                }
                type="button"
              >
                Allow once
              </button>
              <button
                disabled={runtimeStatus !== "ready"}
                onClick={() =>
                  void resolveApproval(block.approval, "approve_session")
                }
                type="button"
              >
                Allow for session
              </button>
              <button
                className="deny"
                disabled={runtimeStatus !== "ready"}
                onClick={() => {
                  const reason = window.prompt(
                    "Reason for denying this operation (optional)",
                  );
                  void resolveApproval(
                    block.approval,
                    "deny",
                    reason ?? undefined,
                  );
                }}
                type="button"
              >
                Deny
              </button>
            </div>
          ) : (
            <small>Resolved: {block.decision}</small>
          )}
        </div>
      </div>
    );
  }
  return <AssistantMessage block={block} streaming={streaming} />;
}

type TextBlock = Extract<ConversationBlock, { text: string; runId: string }>;

function AssistantMessage({
  block,
  streaming,
}: {
  block: TextBlock;
  streaming: boolean;
}) {
  const [copied, setCopied] = useState(false);
  // Re-parse markdown at most ~5x/s while streaming, instead of on every token.
  // Keeps the output formatted (headings, code, lists) while staying O(n) over
  // the stream. The latest text is read from a ref so the interval does not need
  // to re-arm on each token.
  const [rendered, setRendered] = useState(block.text);
  const textRef = useRef(block.text);
  useEffect(() => {
    textRef.current = block.text;
  }, [block.text]);
  useEffect(() => {
    if (!streaming) return;
    const id = window.setInterval(() => setRendered(textRef.current), 200);
    return () => window.clearInterval(id);
  }, [streaming]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(block.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — ignore */
    }
  };

  const source = streaming ? rendered : block.text;

  return (
    <article className="message assistant-message">
      <span className="agent-avatar">
        <Bot size={16} />
      </span>
      <div className="message-body">
        <div className="message-meta">
          <span>YAACLI</span>
          <button
            aria-label="Copy message"
            className={`copy-message${copied ? " copied" : ""}`}
            onClick={copy}
            type="button"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <ReactMarkdown
          components={markdownComponents}
          rehypePlugins={markdownRehypePlugins}
          remarkPlugins={markdownRemarkPlugins}
        >
          {source}
        </ReactMarkdown>
        {streaming && <span className="streaming-cursor" aria-hidden="true" />}
      </div>
    </article>
  );
}

type ToolBlock = Extract<ConversationBlock, { type: "tool" }>;

export function ToolCall({ block }: { block: ToolBlock }) {
  const [open, setOpen] = useState(false);
  const done = block.status === "completed";
  const summary = useMemo(() => summarizeArgs(block.args), [block.args]);
  const argsText = useMemo(() => formatValue(block.args), [block.args]);
  const resultText = useMemo(() => formatValue(block.result), [block.result]);
  const hasDetail = Boolean(argsText || resultText);

  return (
    <div className={`tool-call${open ? " open" : ""}`}>
      <button
        aria-expanded={open}
        className="tool-call-header"
        disabled={!hasDetail}
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span className={`tool-call-state ${block.status}`}>
          {done ? <CheckCircle2 size={13} /> : <CircleDashed size={13} />}
        </span>
        <TerminalSquare size={13} />
        <span className="tool-call-name">{block.name}</span>
        {summary && <span className="tool-call-summary">{summary}</span>}
        {hasDetail && (
          <ChevronDown
            className={`tool-call-chevron${open ? " open" : ""}`}
            size={13}
          />
        )}
      </button>
      {open && hasDetail && (
        <div className="tool-call-body">
          {argsText && (
            <div className="tool-call-section">
              <span className="tool-call-label">args</span>
              <pre className="tool-call-pre">{argsText}</pre>
            </div>
          )}
          {resultText && (
            <div className="tool-call-section">
              <span className="tool-call-label">result</span>
              <pre className="tool-call-pre">{resultText}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function summarizeArgs(args: unknown): string {
  if (args == null) return "";
  if (typeof args === "string") return truncateOneline(args, 64);
  if (typeof args === "object") {
    const obj = args as Record<string, unknown>;
    const preferred =
      obj.path ??
      obj.command ??
      obj.query ??
      obj.pattern ??
      obj.file_name ??
      obj.url;
    if (typeof preferred === "string" && preferred)
      return truncateOneline(preferred, 64);
    const entries = Object.entries(obj)
      .filter(([, value]) => value != null && value !== "")
      .slice(0, 2)
      .map(([key, value]) => `${key}: ${truncateOneline(String(value), 24)}`);
    return entries.join("  ·  ");
  }
  return "";
}

function formatValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function truncateOneline(value: string, limit: number): string {
  const oneLine = value.replace(/\s+/g, " ").trim();
  return oneLine.length > limit ? `${oneLine.slice(0, limit - 1)}…` : oneLine;
}

function attachmentSrc(part: import("./protocol").InputPart): string | null {
  if (part.type !== "image") return null;
  if (part.data_base64) {
    return `data:${part.media_type ?? "image/png"};base64,${part.data_base64}`;
  }
  if (part.path) return convertFileSrc(part.path);
  return null;
}

export function ThinkingBlock({ id, text }: { id: string; text: string }) {
  const [expanded, setExpanded] = useState(false);
  const contentId = `${id}-content`;
  return (
    <section className="thinking-block">
      <button
        aria-controls={contentId}
        aria-expanded={expanded}
        className="thinking-row"
        onClick={() => setExpanded((current) => !current)}
        type="button"
      >
        <CircleDashed size={13} /> Thinking
        <ChevronDown className={expanded ? "expanded" : ""} size={13} />
      </button>
      {expanded && (
        <div className="thinking-content" id={contentId}>
          <ReactMarkdown
            components={markdownComponents}
            rehypePlugins={markdownRehypePlugins}
            remarkPlugins={markdownRemarkPlugins}
          >
            {text}
          </ReactMarkdown>
        </div>
      )}
    </section>
  );
}

function Welcome({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="welcome-state">
      <div className="welcome-mark">
        <TerminalSquare size={22} />
      </div>
      <h2>Work with YAACLI on your Mac</h2>
      <p>
        Open a local project to start a workspace-scoped agent session. YAACLI
        runs in a bundled sidecar — your code never leaves the machine.
      </p>
      <button className="primary-action" onClick={onOpen} type="button">
        <FolderOpen size={15} /> Open workspace
      </button>
    </div>
  );
}

function EmptySession({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="welcome-state compact">
      <div className="welcome-mark">
        <MessageSquarePlus size={22} />
      </div>
      <h2>No session selected</h2>
      <p>Create a session or pick one from the sidebar.</p>
      <button className="primary-action" onClick={onCreate} type="button">
        <MessageSquarePlus size={15} /> New session
      </button>
    </div>
  );
}

function SettingsPanel({
  config,
  onClose,
  onTheme,
}: {
  config: import("./bridge").DesktopConfig | null;
  onClose: () => void;
  onTheme: (theme: "light" | "dark") => void;
}) {
  const [provider, setProvider] = useState("openai");
  const [secret, setSecret] = useState("");
  const [present, setPresent] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    void credentialStatus(provider)
      .then((result) => setPresent(result.present))
      .catch(() => setPresent(false));
  }, [provider]);

  return (
    <div className="settings-backdrop" role="presentation">
      <section
        aria-label="Settings"
        aria-modal="true"
        className="settings-panel"
        role="dialog"
      >
        <header>
          <div>
            <Settings2 size={16} />
            <strong>Settings</strong>
          </div>
          <button aria-label="Close settings" onClick={onClose} type="button">
            <X size={15} />
          </button>
        </header>
        <div className="settings-body">
          <label>
            Appearance
            <select
              onChange={(event) =>
                onTheme(event.target.value as "light" | "dark")
              }
              value={config?.theme ?? "dark"}
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
            </select>
          </label>
          <div className="credential-form">
            <h3>Provider credential</h3>
            <p>
              Secrets are stored in macOS Keychain and never returned to the
              webview.
            </p>
            <label>
              Provider
              <select
                onChange={(event) => setProvider(event.target.value)}
                value={provider}
              >
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="deepseek">DeepSeek</option>
                <option value="zai">Z.ai</option>
                <option value="gemini">Gemini</option>
              </select>
            </label>
            <label>
              API key
              <input
                onChange={(event) => setSecret(event.target.value)}
                placeholder={present ? "Credential stored" : "Enter credential"}
                type="password"
                value={secret}
              />
            </label>
            <div className="settings-actions">
              <button
                disabled={!secret}
                onClick={() => {
                  void setCredential(provider, secret)
                    .then((result) => {
                      setPresent(result.present);
                      setSecret("");
                      setStatus("Stored. Reopen the workspace to apply it.");
                    })
                    .catch((error: unknown) => setStatus(String(error)));
                }}
                type="button"
              >
                Save to Keychain
              </button>
              <button
                disabled={!present}
                onClick={() => {
                  void deleteCredential(provider)
                    .then(() => {
                      setPresent(false);
                      setStatus("Credential removed.");
                    })
                    .catch((error: unknown) => setStatus(String(error)));
                }}
                type="button"
              >
                Delete
              </button>
            </div>
            {status && <p role="status">{status}</p>}
          </div>
        </div>
      </section>
    </div>
  );
}
