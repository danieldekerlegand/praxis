//! The Praxis desktop/web shell.
//!
//! This crate is only the shell: it opens a window over the frontend in `ui/` and runs
//! the Python launcher behind it (see [`library`]) so the seed notebook library browses
//! in-app. The notebook-construction core (rubric, scaffolder, gate) stays in Python at
//! the repo root and is wired in by later bands.

use std::sync::Arc;

use serde::Serialize;
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;

mod library;
mod lite;

use library::{Launcher, LauncherStatus};
use lite::{LiteStatus, Site};

/// What the frontend shows in its footer — enough to prove the backend is live.
#[derive(Serialize)]
pub struct AppInfo {
    name: String,
    version: String,
    tauri: bool,
}

#[tauri::command]
fn app_info() -> AppInfo {
    AppInfo {
        name: "Praxis".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        tauri: true,
    }
}

/// Where the library lives right now — the frontend polls this until it is ready.
#[tauri::command]
fn launcher_status(launcher: State<'_, Arc<Launcher>>) -> LauncherStatus {
    launcher.status()
}

/// Where the in-browser tutorial runtime is being served from — or why there is none.
///
/// Deliberately independent of [`launcher_status`]: the JupyterLite site is static and
/// its kernel is the browser's, so reading and running a tutorial works in a bundle whose
/// Python core is missing. The frontend polls both and shows what each one can do.
#[tauri::command]
fn lite_status(site: State<'_, Arc<Site>>) -> LiteStatus {
    site.status()
}

/// A native folder picker, for pointing storage at a drive. `None` if the user cancelled.
///
/// The only part of choosing a storage backend the webview cannot do itself: the rest of
/// the settings view is an ordinary form posted to the launcher, and `praxis/storage.py`
/// is what decides whether the chosen path is usable. This hands back a string and makes
/// no judgement about it — a picker that also validated would be a second opinion about
/// where data may live, and there is deliberately only one.
///
/// Async, and the wait happens on a blocking thread: on macOS the dialog itself has to
/// run on the main thread (the plugin arranges that), so this must not be holding it.
#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    let (tx, rx) = std::sync::mpsc::channel();
    app.dialog()
        .file()
        .set_title("Where should Praxis keep your work?")
        .pick_folder(move |picked| {
            let _ = tx.send(picked);
        });
    tauri::async_runtime::spawn_blocking(move || rx.recv().ok().flatten())
        .await
        .ok()
        .flatten()
        .and_then(|path| path.into_path().ok())
        .map(|path| path.to_string_lossy().into_owned())
}

pub fn run() {
    let launcher = Arc::new(Launcher::default());
    let site = Arc::new(Site::default());

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(launcher.clone())
        .manage(site.clone())
        .invoke_handler(tauri::generate_handler![
            app_info,
            launcher_status,
            lite_status,
            pick_folder
        ])
        .setup(|app| {
            let launcher = app.state::<Arc<Launcher>>().inner().clone();
            // Where the user's subjects, tutorials and progress live. Only the shell can
            // ask Tauri for this, so it is resolved here and handed to the Python side;
            // praxis/storage.py owns everything below it.
            match app.path().app_data_dir() {
                Ok(dir) => launcher.use_app_data(dir),
                Err(err) => eprintln!("praxis: no app-data directory ({err}) — \
                                       storage falls back to the per-OS default"),
            }
            // Where a release bundle keeps the embedded Python runtime it may have
            // shipped. Same reason as above: only the shell can ask Tauri where its
            // resources landed, and that answer differs per platform and bundle format.
            // Tauri refuses to answer for a binary under a symlinked path, which a
            // relocated .app can easily be, so fall back to the bundle's own layout
            // rather than lose the runtime it shipped (`library::bundle_resources`).
            match app.path().resource_dir().ok().or_else(library::bundle_resources) {
                Some(dir) => {
                    launcher.use_resources(dir.clone());
                    app.state::<Arc<Site>>().use_resources(dir);
                }
                None => eprintln!("praxis: no resource directory — neither an embedded \
                                   Python runtime nor the JupyterLite site can be used"),
            }
            // The learner's runtime, and the first thing to come up: it is static files
            // and a loopback port, so it is ready in milliseconds and does not depend on
            // the Python core resolving at all.
            let site = app.state::<Arc<Site>>().inner().clone();
            site.start();
            eprintln!("praxis: jupyterlite {}", match site.status().url {
                Some(url) => url,
                None => site.status().detail,
            });
            // Off the main thread: starting uvicorn takes a second or two and the window
            // should be up (showing "starting the launcher…") the whole time.
            std::thread::spawn(move || launcher.start());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Praxis")
        .run(move |_app, event| {
            if let tauri::RunEvent::Exit = event {
                launcher.shutdown();
            }
        });
}
