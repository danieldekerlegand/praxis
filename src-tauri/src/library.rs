//! The seed library, served by the launcher that already exists.
//!
//! The shell does not reimplement browse/render: it starts `launcher/app.py` (FastAPI)
//! as a managed child process on a loopback port and points the webview at it —
//! `/api/library` for the model, `/render/<rel>` for a notebook. Badge logic therefore
//! stays in `nbstatus.py` alone.
//!
//! The Python side is not bundled yet (packaging is a later band), so the interpreter is
//! discovered at runtime: `$PRAXIS_PYTHON`, then the repo's `.venv`, then `python3`.
//!
//! The shell also decides *where the user's data lives*, in the one way only it can: it
//! passes Tauri's `app_data_dir()` down as `PRAXIS_APP_DIR` (see [`Launcher::use_app_data`]),
//! and `praxis/storage.py` puts subjects, tutorials and progress under it.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;

/// How long uvicorn gets to bind and answer /healthz before we call it failed.
const READY_TIMEOUT: Duration = Duration::from_secs(30);

const INSTALL_HINT: &str = "install the launch extra: pip install -e '.[launch]' \
                            (or: uv venv .venv && uv pip install --python .venv/bin/python \
                            -e '.[launch]')";

/// What the frontend needs to know to draw the library — or to explain why it can't.
#[derive(Clone, Serialize)]
pub struct LauncherStatus {
    /// `starting` · `ready` · `failed`
    pub state: String,
    /// Base URL of the launcher once ready, e.g. `http://127.0.0.1:53412`.
    pub url: Option<String>,
    /// Human-readable detail — the failure and its fix, or how it was started.
    pub detail: String,
}

impl LauncherStatus {
    fn starting() -> Self {
        Self { state: "starting".into(), url: None, detail: "starting the launcher…".into() }
    }
    fn failed(detail: impl Into<String>) -> Self {
        Self { state: "failed".into(), url: None, detail: detail.into() }
    }
}

/// Owns the launcher child process for the life of the app.
pub struct Launcher {
    status: Mutex<LauncherStatus>,
    child: Mutex<Option<Child>>,
    /// Tauri's `app_data_dir()`, handed to the Python side as `PRAXIS_APP_DIR`.
    ///
    /// Storage lives in `praxis/storage.py`, which computes this same per-OS path from
    /// the bundle identifier when nothing is set — so the launcher run by hand reads the
    /// data the app wrote. Passing it explicitly means the two can't drift if Tauri ever
    /// resolves it differently (a portable build, a sandbox).
    app_data: Mutex<Option<PathBuf>>,
}

impl Default for Launcher {
    fn default() -> Self {
        Self {
            status: Mutex::new(LauncherStatus::starting()),
            child: Mutex::new(None),
            app_data: Mutex::new(None),
        }
    }
}

impl Launcher {
    pub fn status(&self) -> LauncherStatus {
        self.status.lock().expect("launcher status poisoned").clone()
    }

    fn set(&self, status: LauncherStatus) {
        *self.status.lock().expect("launcher status poisoned") = status;
    }

    /// Tell the launcher where this app keeps user data. Call before `start`.
    ///
    /// Created here rather than in Python: Tauri owns the directory, and a user whose
    /// app-data dir can't be made should hear about it from the shell, not from the
    /// first subject they try to save.
    pub fn use_app_data(&self, dir: PathBuf) {
        if let Err(err) = std::fs::create_dir_all(&dir) {
            eprintln!("praxis: could not create {}: {err}", dir.display());
            return;
        }
        *self.app_data.lock().expect("launcher app_data poisoned") = Some(dir);
    }

    /// Kill the child. Called on app exit; safe to call twice.
    pub fn shutdown(&self) {
        if let Some(mut child) = self.child.lock().expect("launcher child poisoned").take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    /// True once the child has exited on its own (i.e. startup failed).
    fn child_died(&self) -> bool {
        let mut guard = self.child.lock().expect("launcher child poisoned");
        match guard.as_mut() {
            Some(child) => matches!(child.try_wait(), Ok(Some(_))),
            None => false,
        }
    }

    /// Start the launcher and block until it answers /healthz. Run this off the main
    /// thread — it takes a second or two (uvicorn import time).
    pub fn start(&self) {
        let root = match repo_root() {
            Some(root) => root,
            None => {
                self.set(LauncherStatus::failed(
                    "could not find the Praxis repo (no curriculum.py + launcher/app.py \
                     above this binary) — set PRAXIS_ROOT",
                ));
                return;
            }
        };
        let python = python_bin(&root);

        // Preflight the imports separately: a missing dependency is by far the likeliest
        // failure, and it reads much better than "the server never came up".
        match Command::new(&python)
            .args(["-c", "import fastapi, uvicorn, jinja2"])
            .current_dir(&root)
            .output()
        {
            Ok(out) if out.status.success() => {}
            Ok(_) => {
                self.set(LauncherStatus::failed(format!(
                    "{} has no FastAPI/uvicorn/jinja2 — {INSTALL_HINT}",
                    python.display()
                )));
                return;
            }
            Err(err) => {
                self.set(LauncherStatus::failed(format!(
                    "cannot run {}: {err} — set PRAXIS_PYTHON to a Python 3.10+ interpreter",
                    python.display()
                )));
                return;
            }
        }

        let port = match free_port() {
            Some(port) => port,
            None => {
                self.set(LauncherStatus::failed("no free loopback port"));
                return;
            }
        };

        let mut command = Command::new(&python);
        command
            .args([
                "-m",
                "uvicorn",
                "launcher.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                &port.to_string(),
                "--log-level",
                "warning",
            ])
            .current_dir(&root)
            .env("PYTHONPATH", &root)
            // Belt and braces: `shutdown` kills the child on a clean exit, and this makes
            // it stop itself if the shell is hard-killed instead.
            .env("PRAXIS_PARENT_PID", std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        if let Some(dir) = self.app_data.lock().expect("launcher app_data poisoned").clone() {
            command.env("PRAXIS_APP_DIR", dir);
        }
        let spawned = command.spawn();

        match spawned {
            Ok(child) => *self.child.lock().expect("launcher child poisoned") = Some(child),
            Err(err) => {
                self.set(LauncherStatus::failed(format!("could not start uvicorn: {err}")));
                return;
            }
        }

        let deadline = Instant::now() + READY_TIMEOUT;
        while Instant::now() < deadline {
            if healthy(port) {
                self.set(LauncherStatus {
                    state: "ready".into(),
                    url: Some(format!("http://127.0.0.1:{port}")),
                    detail: format!("{} · {}", python.display(), root.display()),
                });
                return;
            }
            if self.child_died() {
                self.set(LauncherStatus::failed(format!(
                    "the launcher exited during startup — run it by hand to see why: \
                     cd {} && {} -m uvicorn launcher.app:app",
                    root.display(),
                    python.display()
                )));
                return;
            }
            std::thread::sleep(Duration::from_millis(200));
        }
        self.shutdown();
        self.set(LauncherStatus::failed("the launcher did not answer /healthz in 30s"));
    }
}

/// The repo root: the directory holding the Python core. Walk up from the binary and
/// from the cwd, so this works both from `cargo run` and from a bundled .app beside a
/// checkout. `PRAXIS_ROOT` overrides.
fn repo_root() -> Option<PathBuf> {
    fn is_root(dir: &Path) -> bool {
        dir.join("curriculum.py").is_file()
            && dir.join("launcher").join("app.py").is_file()
            && dir.join("notebooks").is_dir()
    }

    if let Ok(explicit) = std::env::var("PRAXIS_ROOT") {
        let dir = PathBuf::from(explicit);
        if is_root(&dir) {
            return Some(dir);
        }
    }
    let seeds = [std::env::current_exe().ok(), std::env::current_dir().ok()];
    seeds
        .into_iter()
        .flatten()
        .flat_map(|seed| seed.ancestors().map(Path::to_path_buf).collect::<Vec<_>>())
        .find(|dir| is_root(dir))
}

/// `$PRAXIS_PYTHON`, else the repo's `.venv`, else whatever `python3` resolves to.
fn python_bin(root: &Path) -> PathBuf {
    if let Ok(explicit) = std::env::var("PRAXIS_PYTHON") {
        if !explicit.is_empty() {
            return PathBuf::from(explicit);
        }
    }
    for rel in ["bin/python", "Scripts/python.exe"] {
        let candidate = root.join(".venv").join(rel);
        if candidate.is_file() {
            return candidate;
        }
    }
    PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
}

/// An ephemeral port the OS just handed out. Racy in principle (we drop the listener so
/// uvicorn can bind it), which is why a failure to bind surfaces as `child_died`.
fn free_port() -> Option<u16> {
    TcpListener::bind(("127.0.0.1", 0)).ok()?.local_addr().ok().map(|addr| addr.port())
}

/// One `GET /healthz` over a raw socket — the shell needs no HTTP client for this.
fn healthy(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut sock) = TcpStream::connect_timeout(&addr, Duration::from_millis(500)) else {
        return false;
    };
    let _ = sock.set_read_timeout(Some(Duration::from_secs(2)));
    if sock
        .write_all(b"GET /healthz HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    if sock.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.") && response.contains(" 200 ") && response.ends_with("ok")
}
