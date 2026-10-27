//! Python backend lifecycle (PRD §8.5): spawn → health wait → ready event → restart once on crash → kill on exit.
//!
//! Dev builds run `backend/.venv/{bin,Scripts}/python -m app.main` directly (not `uv run`, whose child
//! python can be orphaned on Windows when uv is killed). Release builds run the PyInstaller sidecar
//! `binaries/ziko-backend-<target-triple>[.exe]`.
//! Each launch gets a random loopback port and a random bearer token; only this process and its
//! webviews know the token.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const HEALTH_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_RESTARTS: u32 = 1;

#[derive(Clone, Serialize, PartialEq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Starting,
    Ready,
    Down,
    Failed,
}

#[derive(Clone, Serialize)]
pub struct BackendInfo {
    pub base_url: String,
    pub ws_url: String,
    pub token: String,
    pub status: Status,
}

pub struct Backend {
    port: u16,
    token: String,
    status: Mutex<Status>,
    child: Mutex<Option<CommandChild>>,
    restarts: Mutex<u32>,
    shutting_down: Mutex<bool>,
}

impl Backend {
    pub fn new() -> Self {
        Self {
            port: free_port(),
            token: random_token(),
            status: Mutex::new(Status::Starting),
            child: Mutex::new(None),
            restarts: Mutex::new(0),
            shutting_down: Mutex::new(false),
        }
    }

    pub fn info(&self) -> BackendInfo {
        BackendInfo {
            base_url: format!("http://127.0.0.1:{}", self.port),
            ws_url: format!("ws://127.0.0.1:{}/ws/events?token={}", self.port, self.token),
            token: self.token.clone(),
            status: self.status.lock().unwrap().clone(),
        }
    }

    pub fn kill(&self) {
        *self.shutting_down.lock().unwrap() = true;
        if let Some(child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

fn set_status(app: &AppHandle, status: Status) {
    let backend = app.state::<Backend>();
    *backend.status.lock().unwrap() = status.clone();
    let _ = app.emit("backend://status", backend.info());
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn random_token() -> String {
    let mut buf = [0u8; 32];
    getrandom::fill(&mut buf).expect("OS RNG unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// `backend/` in the repo, resolved from this crate's manifest dir at compile time (dev only).
fn dev_backend_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../backend")
}

fn dev_python(dir: &PathBuf) -> Option<PathBuf> {
    let p = if cfg!(windows) {
        dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        dir.join(".venv").join("bin").join("python")
    };
    p.exists().then_some(p)
}

pub fn spawn(app: &AppHandle) {
    let backend = app.state::<Backend>();
    let envs = [
        ("ZIKO_PORT".to_string(), backend.port.to_string()),
        ("ZIKO_TOKEN".to_string(), backend.token.clone()),
        ("ZIKO_EXIT_ON_STDIN_EOF".to_string(), "1".to_string()),
        ("PYTHONUNBUFFERED".to_string(), "1".to_string()),
    ];

    let command = if cfg!(debug_assertions) {
        let dir = dev_backend_dir();
        match dev_python(&dir) {
            Some(py) => app.shell().command(py).args(["-m", "app.main"]).current_dir(&dir),
            None => {
                log::error!("backend venv missing at {:?} — run `uv sync` in backend/", dir);
                set_status(app, Status::Failed);
                return;
            }
        }
    } else {
        match app.shell().sidecar("ziko-backend") {
            Ok(c) => c,
            Err(e) => {
                log::error!("sidecar not bundled: {e}");
                set_status(app, Status::Failed);
                return;
            }
        }
    };

    let (mut rx, child) = match command.envs(envs).spawn() {
        Ok(v) => v,
        Err(e) => {
            log::error!("failed to spawn backend: {e}");
            set_status(app, Status::Failed);
            return;
        }
    };
    *backend.child.lock().unwrap() = Some(child);
    set_status(app, Status::Starting);

    // Health wait off the main thread (blocking TCP is fine here; ≤20 s, 250 ms cadence).
    let port = backend.port;
    let app_h = app.clone();
    std::thread::spawn(move || {
        let start = Instant::now();
        while start.elapsed() < HEALTH_TIMEOUT {
            if health_ok(port) {
                set_status(&app_h, Status::Ready);
                return;
            }
            if *app_h.state::<Backend>().status.lock().unwrap() == Status::Down {
                return; // died during startup; the event loop below handles restart
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        log::error!("backend did not become healthy within {:?}", HEALTH_TIMEOUT);
        set_status(&app_h, Status::Failed);
    });

    // Forward logs and watch for unexpected termination.
    let app_h = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    log::info!(target: "backend", "{}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Error(e) => log::error!(target: "backend", "{e}"),
                CommandEvent::Terminated(p) => {
                    let backend = app_h.state::<Backend>();
                    backend.child.lock().unwrap().take();
                    if *backend.shutting_down.lock().unwrap() {
                        return;
                    }
                    log::warn!("backend exited unexpectedly (code {:?})", p.code);
                    set_status(&app_h, Status::Down);
                    let mut restarts = backend.restarts.lock().unwrap();
                    if *restarts < MAX_RESTARTS {
                        *restarts += 1;
                        drop(restarts);
                        std::thread::sleep(Duration::from_millis(500));
                        spawn(&app_h);
                    } else {
                        set_status(&app_h, Status::Failed);
                    }
                    return;
                }
                _ => {}
            }
        }
    });
}

fn health_ok(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(300))
    else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_millis(800)));
    if s.write_all(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").is_err() {
        return false;
    }
    let mut buf = [0u8; 512];
    match s.read(&mut buf) {
        Ok(n) => {
            let head = String::from_utf8_lossy(&buf[..n]);
            head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")
        }
        Err(_) => false,
    }
}

#[tauri::command]
pub fn backend_info(backend: tauri::State<'_, Backend>) -> BackendInfo {
    backend.info()
}
