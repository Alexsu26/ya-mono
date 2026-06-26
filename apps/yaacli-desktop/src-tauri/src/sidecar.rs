use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::{
    collections::HashMap,
    fs::OpenOptions,
    io::Write,
    process::Stdio,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, Command},
    sync::{oneshot, Mutex},
    time::timeout,
};

const PROTOCOL_VERSION: u64 = 1;
const DESKTOP_APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const MAX_MESSAGE_BYTES: usize = 1024 * 1024;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(20);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_START_ATTEMPTS: u32 = 3;
const START_ATTEMPT_WINDOW: Duration = Duration::from_secs(60);
const WATCHDOG_INTERVAL: Duration = Duration::from_secs(30);
const WATCHDOG_PING_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_LOG_BYTES: u64 = 2 * 1024 * 1024;

type PendingRequests = Arc<Mutex<HashMap<String, oneshot::Sender<Result<Value, String>>>>>;

#[derive(Clone, Default)]
pub struct SidecarManager {
    inner: Arc<Mutex<SidecarInner>>,
    next_request_id: Arc<AtomicU64>,
    active_run: Arc<AtomicBool>,
    exiting: Arc<AtomicBool>,
}

#[derive(Default)]
struct SidecarInner {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    pending: PendingRequests,
    status: RuntimeStatus,
    workspace: Option<String>,
    start_attempts: u32,
    attempt_window_started: Option<Instant>,
    watchdog: Option<tauri::async_runtime::JoinHandle<()>>,
}

#[derive(Clone, Default, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeStatus {
    Starting,
    Ready,
    #[default]
    Unavailable,
    Stopping,
}

#[derive(Clone, Serialize)]
pub struct RuntimeState {
    status: RuntimeStatus,
    workspace: Option<String>,
}

#[derive(Debug, Deserialize)]
struct Handshake {
    protocol_version: u64,
    #[serde(rename = "type")]
    envelope_type: String,
}

impl SidecarManager {
    pub async fn start(&self, app: AppHandle, workspace: String) -> Result<RuntimeState, String> {
        let mut inner = self.inner.lock().await;
        if inner.child.is_some() {
            if inner.workspace.as_deref() == Some(workspace.as_str()) {
                return Ok(RuntimeState {
                    status: inner.status.clone(),
                    workspace: inner.workspace.clone(),
                });
            }
            return Err("stop the active workspace runtime before switching workspaces".into());
        }
        self.record_start_attempt(&mut inner)?;
        self.exiting.store(false, Ordering::Relaxed);
        inner.status = RuntimeStatus::Starting;

        let mut command = sidecar_command(&app, &workspace)?;
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|error| format!("failed to start YAACLI sidecar: {error}"))?;

        let stdin = child.stdin.take().ok_or("sidecar stdin is unavailable")?;
        let stdout = child.stdout.take().ok_or("sidecar stdout is unavailable")?;
        let stderr = child.stderr.take().ok_or("sidecar stderr is unavailable")?;
        let (handshake_tx, handshake_rx) = oneshot::channel();
        let pending = inner.pending.clone();
        let manager = self.clone();
        let reader_app = app.clone();
        tauri::async_runtime::spawn(async move {
            read_stdout(reader_app, manager, pending, stdout, handshake_tx).await;
        });
        let stderr_app = app.clone();
        tauri::async_runtime::spawn(async move {
            read_stderr(stderr_app, stderr).await;
        });

        inner.child = Some(child);
        inner.stdin = Some(stdin);
        inner.workspace = Some(workspace);
        drop(inner);

        match timeout(HANDSHAKE_TIMEOUT, handshake_rx).await {
            Ok(Ok(Ok(()))) => {
                let mut inner = self.inner.lock().await;
                inner.status = RuntimeStatus::Ready;
                if let Some(handle) = inner.watchdog.take() {
                    handle.abort();
                }
                inner.watchdog = Some(tauri::async_runtime::spawn(watchdog_loop(
                    app.clone(),
                    self.clone(),
                )));
                let state = RuntimeState {
                    status: inner.status.clone(),
                    workspace: inner.workspace.clone(),
                };
                let _ = app.emit("desktop://runtime-state", &state);
                Ok(state)
            }
            Ok(Ok(Err(error))) => {
                self.stop().await.ok();
                Err(error)
            }
            Ok(Err(_)) => {
                self.stop().await.ok();
                Err("sidecar exited before protocol handshake".into())
            }
            Err(_) => {
                self.stop().await.ok();
                Err("timed out waiting for sidecar protocol handshake".into())
            }
        }
    }

    pub async fn request(&self, command: String, payload: Value) -> Result<Value, String> {
        let request_id = format!(
            "desktop-{}",
            self.next_request_id.fetch_add(1, Ordering::Relaxed)
        );
        let (tx, rx) = oneshot::channel();
        let pending = {
            let mut inner = self.inner.lock().await;
            if !matches!(inner.status, RuntimeStatus::Ready) {
                return Err("YAACLI sidecar is not ready".into());
            }
            if inner.pending.lock().await.len() >= 64 {
                return Err("too many pending sidecar requests".into());
            }
            inner.pending.lock().await.insert(request_id.clone(), tx);
            let message = json!({
                "protocol_version": PROTOCOL_VERSION,
                "type": "request",
                "request_id": request_id,
                "command": command,
                "payload": payload,
            });
            let bytes = serde_json::to_vec(&message).map_err(|error| error.to_string())?;
            if bytes.len() > MAX_MESSAGE_BYTES {
                inner.pending.lock().await.remove(&request_id);
                return Err("sidecar request exceeds the message size limit".into());
            }
            let stdin = inner.stdin.as_mut().ok_or("sidecar stdin is unavailable")?;
            stdin
                .write_all(&bytes)
                .await
                .map_err(|error| format!("failed to write sidecar request: {error}"))?;
            stdin
                .write_all(b"\n")
                .await
                .map_err(|error| format!("failed to finish sidecar request: {error}"))?;
            stdin.flush().await.map_err(|error| error.to_string())?;
            inner.pending.clone()
        };

        match timeout(Duration::from_secs(30), rx).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err("sidecar response channel closed".into()),
            Err(_) => {
                pending.lock().await.remove(&request_id);
                Err("timed out waiting for sidecar response".into())
            }
        }
    }

    pub async fn stop(&self) -> Result<(), String> {
        let (mut child, mut stdin, pending) = {
            let mut inner = self.inner.lock().await;
            inner.status = RuntimeStatus::Stopping;
            if let Some(handle) = inner.watchdog.take() {
                handle.abort();
            }
            (
                inner.child.take(),
                inner.stdin.take(),
                inner.pending.clone(),
            )
        };
        if let Some(mut writer) = stdin.take() {
            let shutdown = json!({
                "protocol_version": PROTOCOL_VERSION,
                "type": "request",
                "request_id": "desktop-shutdown",
                "command": "runtime.shutdown",
                "payload": {},
            });
            if let Ok(mut bytes) = serde_json::to_vec(&shutdown) {
                bytes.push(b'\n');
                let _ = writer.write_all(&bytes).await;
                let _ = writer.flush().await;
            }
        }
        if let Some(mut process) = child.take() {
            if timeout(SHUTDOWN_TIMEOUT, process.wait()).await.is_err() {
                process.kill().await.map_err(|error| error.to_string())?;
            }
        }
        fail_pending(&pending, "sidecar stopped").await;
        let mut inner = self.inner.lock().await;
        inner.status = RuntimeStatus::Unavailable;
        inner.workspace = None;
        Ok(())
    }

    pub async fn state(&self) -> RuntimeState {
        let inner = self.inner.lock().await;
        RuntimeState {
            status: inner.status.clone(),
            workspace: inner.workspace.clone(),
        }
    }

    pub fn has_active_run(&self) -> bool {
        self.active_run.load(Ordering::Relaxed)
    }

    fn record_start_attempt(&self, inner: &mut SidecarInner) -> Result<(), String> {
        let now = Instant::now();
        if inner
            .attempt_window_started
            .is_none_or(|started| now.duration_since(started) >= START_ATTEMPT_WINDOW)
        {
            inner.attempt_window_started = Some(now);
            inner.start_attempts = 0;
        }
        if inner.start_attempts >= MAX_START_ATTEMPTS {
            return Err("sidecar restart limit reached; retry after one minute".into());
        }
        inner.start_attempts += 1;
        Ok(())
    }

    async fn mark_unavailable(&self) {
        let pending = {
            let mut inner = self.inner.lock().await;
            if let Some(handle) = inner.watchdog.take() {
                handle.abort();
            }
            // Drop the child so kill_on_drop terminates the process even if the
            // reader task has not yet observed stdout EOF.
            inner.child = None;
            inner.stdin = None;
            inner.status = RuntimeStatus::Unavailable;
            inner.pending.clone()
        };
        // Defensive: any path that marks the runtime unavailable also unblocks
        // pending requests instead of letting them wait for the 30s timeout.
        fail_pending(&pending, "sidecar unavailable").await;
    }

    /// First caller wins; subsequent callers (e.g. the re-issued exit after the
    /// graceful shutdown task runs) get `false` and let the app exit proceed.
    pub fn begin_shutdown(&self) -> bool {
        !self.exiting.swap(true, Ordering::Relaxed)
    }

    /// Force the runtime into the unavailable state: fail pending requests,
    /// kill the child, and emit the new state to the webview. Idempotent and a
    /// no-op while a legitimate stop is already in progress.
    async fn crash(&self, app: &AppHandle, reason: &str) {
        {
            let inner = self.inner.lock().await;
            if matches!(
                inner.status,
                RuntimeStatus::Unavailable | RuntimeStatus::Stopping
            ) {
                return;
            }
        }
        eprintln!("YAACLI sidecar watchdog: {reason}");
        self.mark_unavailable().await;
        self.active_run.store(false, Ordering::Relaxed);
        let state = self.state().await;
        let _ = app.emit("desktop://runtime-state", state);
    }
}

fn sidecar_command(app: &AppHandle, workspace: &str) -> Result<Command, String> {
    #[cfg(debug_assertions)]
    {
        let workspace_root = app
            .path()
            .resource_dir()
            .ok()
            .and_then(find_workspace_root)
            .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../.."));
        let binary = workspace_root
            .join(".venv")
            .join("bin")
            .join("yaacli-desktop-sidecar");
        if !binary.is_file() {
            return Err(format!(
                "development sidecar is missing at {}; run `make desktop-install`",
                binary.display()
            ));
        }
        let mut command = Command::new(binary);
        command
            .arg("--workspace")
            .arg(workspace)
            .current_dir(workspace_root);
        command.env("YAACLI_DESKTOP_APP_VERSION", DESKTOP_APP_VERSION);
        crate::credentials::inject_provider_environment(&mut command);
        Ok(command)
    }
    #[cfg(not(debug_assertions))]
    {
        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?;
        let binary = resource_dir
            .parent()
            .ok_or("application resource directory has no bundle parent")?
            .join("MacOS")
            .join("yaacli-desktop-sidecar");
        let mut command = Command::new(binary);
        command.arg("--workspace").arg(workspace);
        command.env("YAACLI_DESKTOP_APP_VERSION", DESKTOP_APP_VERSION);
        crate::credentials::inject_provider_environment(&mut command);
        Ok(command)
    }
}

#[cfg(debug_assertions)]
fn find_workspace_root(resource_dir: PathBuf) -> Option<PathBuf> {
    resource_dir
        .ancestors()
        .find(|path| path.join("pyproject.toml").is_file())
        .map(PathBuf::from)
}

async fn read_stdout(
    app: AppHandle,
    manager: SidecarManager,
    pending: PendingRequests,
    stdout: tokio::process::ChildStdout,
    handshake_tx: oneshot::Sender<Result<(), String>>,
) {
    let mut reader = BufReader::new(stdout);
    let mut buffer = Vec::new();
    let mut handshake_tx = Some(handshake_tx);
    loop {
        buffer.clear();
        match reader.read_until(b'\n', &mut buffer).await {
            Ok(0) => break,
            Ok(_) if buffer.len() > MAX_MESSAGE_BYTES => {
                if let Some(sender) = handshake_tx.take() {
                    let _ = sender.send(Err("sidecar handshake exceeds message limit".into()));
                }
                break;
            }
            Ok(_) => {}
            Err(error) => {
                eprintln!("YAACLI sidecar stdout error: {error}");
                break;
            }
        }
        let value: Value = match serde_json::from_slice(&buffer) {
            Ok(value) => value,
            Err(error) => {
                eprintln!("YAACLI sidecar emitted invalid protocol JSON: {error}");
                continue;
            }
        };
        match value.get("type").and_then(Value::as_str) {
            Some("handshake") => {
                let result = validate_handshake(value);
                if let Some(sender) = handshake_tx.take() {
                    let _ = sender.send(result);
                }
            }
            Some("response") => {
                if let Some(request_id) = value.get("request_id").and_then(Value::as_str) {
                    if let Some(sender) = pending.lock().await.remove(request_id) {
                        let result = if value.get("ok").and_then(Value::as_bool) == Some(true) {
                            Ok(value.get("payload").cloned().unwrap_or_else(|| json!({})))
                        } else {
                            Err(value
                                .pointer("/error/message")
                                .and_then(Value::as_str)
                                .unwrap_or("sidecar command failed")
                                .to_string())
                        };
                        let _ = sender.send(result);
                    }
                }
            }
            Some("event") => {
                if let Some(event) = value.get("event").and_then(Value::as_str) {
                    if event == "run.started" {
                        manager.active_run.store(true, Ordering::Relaxed);
                    } else if matches!(event, "run.completed" | "run.cancelled" | "run.failed") {
                        manager.active_run.store(false, Ordering::Relaxed);
                    }
                }
                let _ = app.emit("desktop://protocol-event", value);
            }
            _ => eprintln!("YAACLI sidecar emitted an unknown protocol envelope"),
        }
    }
    if let Some(sender) = handshake_tx.take() {
        let _ = sender.send(Err("sidecar exited before handshake".into()));
    }
    fail_pending(&pending, "sidecar exited").await;
    manager.mark_unavailable().await;
    manager.active_run.store(false, Ordering::Relaxed);
    let state = manager.state().await;
    let _ = app.emit("desktop://runtime-state", state);
}

async fn read_stderr(app: AppHandle, stderr: tokio::process::ChildStderr) {
    let log = SidecarLog::new(&app);
    let mut lines = BufReader::new(stderr).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        let redacted = redact_diagnostic(&line);
        if let Some(log) = log.as_ref() {
            log.append(&redacted);
        }
        eprintln!("YAACLI sidecar: {}", redacted);
    }
}

/// Append-only sidecar stderr sink with a single rolling backup, so long-lived
/// runs do not grow an unbounded log. Diagnostics are redacted before logging.
struct SidecarLog {
    path: PathBuf,
}

impl SidecarLog {
    fn new(app: &AppHandle) -> Option<SidecarLog> {
        let dir = app.path().app_log_dir().ok()?;
        std::fs::create_dir_all(&dir).ok()?;
        Some(SidecarLog {
            path: dir.join("yaacli-sidecar.log"),
        })
    }

    fn append(&self, line: &str) {
        let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
        else {
            return;
        };
        let _ = writeln!(file, "{}", line);
        if let Ok(meta) = file.metadata() {
            if meta.len() > MAX_LOG_BYTES {
                let rotated = {
                    let mut name = self.path.as_os_str().to_owned();
                    name.push(".1");
                    PathBuf::from(name)
                };
                let _ = std::fs::rename(&self.path, &rotated);
            }
        }
    }
}

/// Periodically ping the sidecar so a process that is alive but unresponsive
/// (stuck event loop, deadlock) is detected and failed fast instead of making
/// every pending request wait for its 30s timeout.
async fn watchdog_loop(app: AppHandle, manager: SidecarManager) {
    loop {
        tokio::time::sleep(WATCHDOG_INTERVAL).await;
        let should_run = {
            let inner = manager.inner.lock().await;
            matches!(inner.status, RuntimeStatus::Ready) && inner.child.is_some()
        };
        if !should_run {
            break;
        }
        let ping = manager.request("runtime.health".into(), json!({}));
        let healthy = matches!(
            timeout(WATCHDOG_PING_TIMEOUT, ping).await,
            Ok(Ok(_))
        );
        if !healthy {
            manager
                .crash(&app, "sidecar health check failed")
                .await;
            break;
        }
    }
}

fn redact_diagnostic(line: &str) -> String {
    let lower = line.to_ascii_lowercase();
    if lower.contains("authorization") || lower.contains("api_key") || lower.contains("api key") {
        return "[REDACTED DIAGNOSTIC]".into();
    }
    line.to_string()
}

fn validate_handshake(value: Value) -> Result<(), String> {
    let handshake =
        serde_json::from_value::<Handshake>(value).map_err(|error| error.to_string())?;
    if handshake.envelope_type != "handshake" {
        return Err("invalid sidecar handshake type".into());
    }
    if handshake.protocol_version != PROTOCOL_VERSION {
        return Err(format!(
            "incompatible sidecar protocol {}; expected {}",
            handshake.protocol_version, PROTOCOL_VERSION
        ));
    }
    Ok(())
}

async fn fail_pending(pending: &PendingRequests, message: &str) {
    for (_, sender) in pending.lock().await.drain() {
        let _ = sender.send(Err(message.to_string()));
    }
}

#[tauri::command]
pub async fn runtime_start(
    app: AppHandle,
    manager: tauri::State<'_, SidecarManager>,
    workspace: String,
) -> Result<RuntimeState, String> {
    manager.start(app, workspace).await
}

#[tauri::command]
pub async fn runtime_request(
    manager: tauri::State<'_, SidecarManager>,
    command: String,
    payload: Value,
) -> Result<Value, String> {
    manager.request(command, payload).await
}

#[tauri::command]
pub async fn runtime_stop(manager: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    manager.stop().await
}

#[tauri::command]
pub async fn runtime_state(
    manager: tauri::State<'_, SidecarManager>,
) -> Result<RuntimeState, String> {
    Ok(manager.state().await)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_sensitive_diagnostic_lines() {
        assert_eq!(
            redact_diagnostic("Authorization: Bearer abc"),
            "[REDACTED DIAGNOSTIC]"
        );
        assert_eq!(redact_diagnostic("runtime ready"), "runtime ready");
    }

    #[test]
    fn runtime_status_serializes_for_frontend() {
        assert_eq!(serde_json::to_value(RuntimeStatus::Ready).unwrap(), "ready");
    }

    #[test]
    fn rejects_incompatible_handshake() {
        let result = validate_handshake(json!({
            "protocol_version": 2,
            "type": "handshake"
        }));

        assert!(result
            .unwrap_err()
            .contains("incompatible sidecar protocol"));
    }

    #[test]
    fn bounds_restart_attempts() {
        let manager = SidecarManager::default();
        let mut inner = SidecarInner::default();

        assert!(manager.record_start_attempt(&mut inner).is_ok());
        assert!(manager.record_start_attempt(&mut inner).is_ok());
        assert!(manager.record_start_attempt(&mut inner).is_ok());
        assert!(manager.record_start_attempt(&mut inner).is_err());
    }

    #[tokio::test]
    async fn unavailable_state_is_used_after_process_exit() {
        let manager = SidecarManager::default();
        {
            let mut inner = manager.inner.lock().await;
            inner.status = RuntimeStatus::Ready;
            inner.workspace = Some("/tmp/workspace".into());
        }

        manager.mark_unavailable().await;

        assert!(matches!(
            manager.state().await.status,
            RuntimeStatus::Unavailable
        ));
    }
}
