//! The seed library, served by the launcher that already exists.
//!
//! The shell does not reimplement browse/render: it starts `launcher/app.py` (FastAPI)
//! as a managed child process on a loopback port and points the webview at it —
//! `/api/library` for the model, `/render/<rel>` for a notebook. Badge logic therefore
//! stays in `nbstatus.py` alone.
//!
//! The Python side is discovered at runtime, and a release bundle can carry it: a bundled
//! runtime under `<resources>/praxis-runtime` (an interpreter with the launch extra, plus
//! a copy of the core) is preferred, and everything that worked before it existed still
//! works behind it — `$PRAXIS_ROOT` / the walk-up for the core, `$PRAXIS_PYTHON`, then the
//! repo's `.venv`, then `python3` for the interpreter. A build with no embedded runtime
//! (every dev build, `cargo run`) takes exactly the path it took before.
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

/// The bundled runtime, relative to Tauri's resource directory: `python/` (a relocatable
/// interpreter carrying the launch extra) beside `core/` (the same `curriculum.py` +
/// `launcher/` + `notebooks/` a checkout has). Written by `scripts/embed-python.sh` and
/// copied in by `src-tauri/tauri.embedded.conf.json`; absent from an ordinary build.
const RUNTIME_DIR: &str = "praxis-runtime";

/// Set this to any non-empty value to ignore an embedded runtime and take the discovery
/// path a build without one takes. The escape hatch for a bundle whose runtime is broken:
/// otherwise the embedded interpreter wins over `PRAXIS_PYTHON`, so there would be none.
const NO_EMBED: &str = "PRAXIS_NO_EMBED";

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
    /// Tauri's `resource_dir()`, where a bundle's embedded runtime lives (see
    /// [`RUNTIME_DIR`]). Only the shell can ask Tauri for it, so — like `app_data` — it is
    /// resolved in `run()` and handed down rather than guessed from the binary's path,
    /// which differs per platform and per bundle format.
    resources: Mutex<Option<PathBuf>>,
}

impl Default for Launcher {
    fn default() -> Self {
        Self {
            status: Mutex::new(LauncherStatus::starting()),
            child: Mutex::new(None),
            app_data: Mutex::new(None),
            resources: Mutex::new(None),
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

    /// Tell the launcher where this build keeps its resources. Call before `start`.
    ///
    /// A bundle built with the embed carries the whole Python side under
    /// `<dir>/praxis-runtime`; an ordinary build carries none, and this changes nothing.
    pub fn use_resources(&self, dir: PathBuf) {
        *self.resources.lock().expect("launcher resources poisoned") = Some(dir);
    }

    /// The embedded runtime this build shipped, if any.
    fn embedded(&self) -> Option<Embedded> {
        if std::env::var_os(NO_EMBED).is_some_and(|value| !value.is_empty()) {
            return None;
        }
        let resources = self.resources.lock().expect("launcher resources poisoned").clone()?;
        embedded_runtime(&resources)
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
        let embedded = self.embedded();
        let root = match repo_root(embedded.as_ref()) {
            Some(root) => root,
            None => {
                self.set(LauncherStatus::failed(
                    "could not find the Praxis repo (no curriculum.py + launcher/app.py \
                     above this binary) — set PRAXIS_ROOT",
                ));
                return;
            }
        };
        let python = python_bin(embedded.as_ref(), &root);

        // A broken embedded runtime has a different fix from a checkout missing the extra,
        // and the user of a shipped .app cannot act on the second one.
        let install_hint = if embedded.is_some() {
            "the bundle's embedded runtime is incomplete — rebuild it with \
             scripts/embed-python.sh, or set PRAXIS_NO_EMBED=1 to fall back to an \
             interpreter on this machine"
        } else {
            INSTALL_HINT
        };

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
                    "{} has no FastAPI/uvicorn/jinja2 — {install_hint}",
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
                    detail: format!(
                        "{}{} · {}",
                        if embedded.is_some() { "embedded runtime: " } else { "" },
                        python.display(),
                        root.display()
                    ),
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

/// The two halves of a bundled runtime, once both have been found on disk.
#[derive(Clone, Debug, PartialEq, Eq)]
struct Embedded {
    /// A copy of the Python core — the same shape `is_root` looks for in a checkout.
    core: PathBuf,
    /// The interpreter beside it, which is the one carrying the launch extra.
    python: PathBuf,
}

/// The embedded runtime under a resource directory, or `None` — which is every build that
/// did not ship one, and also a half-copied one: both halves must be there, because
/// running a bundle's core on a checkout's interpreter (or the reverse) is the shape of
/// failure this is meant to remove.
fn embedded_runtime(resources: &Path) -> Option<Embedded> {
    let runtime = resources.join(RUNTIME_DIR);
    let core = runtime.join("core");
    if !is_root(&core) {
        return None;
    }
    // python-build-standalone's layout, which is what scripts/embed-python.sh unpacks.
    ["bin/python3", "bin/python", "python.exe", "Scripts/python.exe"]
        .into_iter()
        .map(|rel| runtime.join("python").join(rel))
        .find(|candidate| candidate.is_file())
        .map(|python| Embedded { core, python })
}

/// The bundle's resource directory worked out from the binary, for when Tauri will not
/// answer — `None` when this is not a macOS .app.
///
/// `app.path().resource_dir()` reads `current_exe()` through tauri-utils' `StartingBinary`,
/// which on macOS **refuses any path with a symlinked ancestor** (it guards a relaunch
/// against a hijacked path). An .app under a symlinked directory therefore gets no resource
/// directory at all — `/tmp`, a link to `/private/tmp`, is the easy one to hit — and a
/// bundle that shipped a runtime silently loses it, falling back to a checkout that a
/// relocated app has no reason to have.
///
/// Locating our own read-only resources is not the operation that guard protects, so this
/// reads the bundle layout instead: the binary of a macOS .app sits in `Contents/MacOS`,
/// beside `Contents/Resources`. The name check is what keeps it from inventing a resource
/// directory anywhere else — every other build still resolves through Tauri alone.
fn resources_from_exe(exe: &Path) -> Option<PathBuf> {
    let macos_dir = exe.parent()?;
    if macos_dir.file_name()? != "MacOS" {
        return None;
    }
    let resources = macos_dir.parent()?.join("Resources");
    resources.is_dir().then_some(resources)
}

/// [`resources_from_exe`] for this process — what the shell passes to [`Launcher::use_resources`]
/// when `app.path().resource_dir()` comes back with an error.
pub fn bundle_resources() -> Option<PathBuf> {
    resources_from_exe(&std::env::current_exe().ok()?)
}

/// A directory holding the Python core. The one predicate, used for a checkout and for an
/// embedded copy alike — they are the same tree.
fn is_root(dir: &Path) -> bool {
    dir.join("curriculum.py").is_file()
        && dir.join("launcher").join("app.py").is_file()
        && dir.join("notebooks").is_dir()
}

/// The repo root: the directory holding the Python core. The embedded copy if this build
/// shipped one, else `PRAXIS_ROOT`, else the first such directory found by walking up from
/// the binary and from the cwd — so this still works from `cargo run` and from a bundled
/// .app beside a checkout, which is the only thing that worked before the embed existed.
fn repo_root(embedded: Option<&Embedded>) -> Option<PathBuf> {
    if let Some(embedded) = embedded {
        return Some(embedded.core.clone());
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

/// The embedded interpreter, else `$PRAXIS_PYTHON`, else the repo's `.venv`, else whatever
/// `python3` resolves to.
///
/// The embedded one goes first because it is the only interpreter that is *known* to carry
/// the launch extra — a shipped app that quietly borrowed a user's `python3` is the failure
/// this order exists to prevent. It also only exists in a build that shipped it, so every
/// other build reads this exactly as it did before; `PRAXIS_NO_EMBED` is the way back.
fn python_bin(embedded: Option<&Embedded>, root: &Path) -> PathBuf {
    pick_python(embedded, std::env::var("PRAXIS_PYTHON").ok().as_deref(), root)
}

/// `python_bin` with the environment passed in, so the order can be tested without it.
fn pick_python(embedded: Option<&Embedded>, explicit: Option<&str>, root: &Path) -> PathBuf {
    if let Some(embedded) = embedded {
        return embedded.python.clone();
    }
    if let Some(explicit) = explicit.filter(|value| !value.is_empty()) {
        return PathBuf::from(explicit);
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

#[cfg(test)]
mod tests {
    //! The discovery ORDER, which is the whole change an embedded runtime makes. The two
    //! `..._bin` functions read the environment, so the order itself lives in `pick_python`
    //! / `embedded_runtime`, which take what they need — a test here cannot be raced by a
    //! sibling test setting `PRAXIS_PYTHON`.

    use super::*;

    /// A scratch directory, named for the test so two of them never collide.
    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("praxis-discovery-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch dir");
        dir
    }

    fn touch(path: &Path) {
        std::fs::create_dir_all(path.parent().expect("parent")).expect("mkdir");
        std::fs::write(path, b"").expect("write");
    }

    /// The shape `is_root` looks for — a checkout's, and an embedded copy's.
    fn core_at(dir: &Path) -> PathBuf {
        touch(&dir.join("curriculum.py"));
        touch(&dir.join("launcher").join("app.py"));
        std::fs::create_dir_all(dir.join("notebooks")).expect("notebooks");
        dir.to_path_buf()
    }

    /// A resource directory carrying a complete embedded runtime.
    fn runtime_at(resources: &Path) -> PathBuf {
        let runtime = resources.join(RUNTIME_DIR);
        core_at(&runtime.join("core"));
        let python = runtime.join("python").join("bin").join("python3");
        touch(&python);
        python
    }

    #[test]
    fn an_embedded_runtime_is_both_halves_or_nothing() {
        let resources = scratch("halves");
        assert_eq!(embedded_runtime(&resources), None, "an ordinary build ships neither");

        core_at(&resources.join(RUNTIME_DIR).join("core"));
        assert_eq!(embedded_runtime(&resources), None, "a core with no interpreter is not a runtime");

        let python = runtime_at(&resources);
        let found = embedded_runtime(&resources).expect("both halves are there");
        assert_eq!(found.python, python);
        assert!(is_root(&found.core));
    }

    #[test]
    fn the_embedded_interpreter_is_preferred_over_every_fallback() {
        let resources = scratch("preferred");
        let python = runtime_at(&resources);
        let embedded = embedded_runtime(&resources).expect("runtime");

        // A checkout with its own .venv, and PRAXIS_PYTHON set on top of it: the bundle
        // still runs the interpreter it shipped, which is the one with the launch extra.
        let root = scratch("preferred-root");
        touch(&root.join(".venv").join("bin").join("python"));
        assert_eq!(pick_python(Some(&embedded), Some("/usr/bin/python3.9"), &root), python);
    }

    #[test]
    fn without_an_embedded_runtime_the_order_is_what_it_always_was() {
        let root = scratch("fallbacks");

        // 3rd: nothing to find at all.
        assert_eq!(
            pick_python(None, None, &root),
            PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
        );

        // 2nd: the checkout's venv.
        let venv = root.join(".venv").join(if cfg!(windows) { "Scripts/python.exe" } else { "bin/python" });
        touch(&venv);
        assert_eq!(pick_python(None, None, &root), venv);
        assert_eq!(pick_python(None, Some(""), &root), venv, "an empty override is not an override");

        // 1st: PRAXIS_PYTHON.
        assert_eq!(pick_python(None, Some("/opt/py/bin/python"), &root), PathBuf::from("/opt/py/bin/python"));
    }

    #[test]
    fn a_bundles_resources_are_found_from_its_binary_when_tauri_will_not_say() {
        // The .app layout, which is the only one this may answer for: Tauri gives up on a
        // binary under a symlinked path, and a relocated bundle would lose its runtime.
        let app = scratch("bundle").join("Praxis.app");
        let exe = app.join("Contents").join("MacOS").join("praxis");
        touch(&exe);
        let resources = app.join("Contents").join("Resources");
        runtime_at(&resources);

        assert_eq!(resources_from_exe(&exe), Some(resources.clone()));
        assert!(embedded_runtime(&resources_from_exe(&exe).unwrap()).is_some());

        // Not a bundle: no Contents/MacOS, or no Resources beside it. Both read as "no
        // resource directory", exactly as they did before this fallback existed.
        let loose = scratch("bundle-loose").join("praxis");
        touch(&loose);
        assert_eq!(resources_from_exe(&loose), None);
        let bare = scratch("bundle-bare").join("Contents").join("MacOS").join("praxis");
        touch(&bare);
        assert_eq!(resources_from_exe(&bare), None);
    }

    #[test]
    fn the_embedded_core_is_the_root_of_a_bundle_that_shipped_one() {
        let resources = scratch("root");
        runtime_at(&resources);
        let embedded = embedded_runtime(&resources).expect("runtime");

        // No walk-up, no PRAXIS_ROOT: a relocated .app finds its own copy of the core.
        assert_eq!(repo_root(Some(&embedded)), Some(embedded.core.clone()));
        assert!(is_root(&embedded.core));
    }
}
