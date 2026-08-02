//! The Praxis desktop/web shell.
//!
//! This crate is only the shell: it opens a window over the frontend in `ui/` and runs
//! the Python launcher behind it (see [`library`]) so the seed notebook library browses
//! in-app. The notebook-construction core (rubric, scaffolder, gate) stays in Python at
//! the repo root and is wired in by later bands.

use std::sync::Arc;

use serde::Serialize;
use tauri::{Manager, State};

mod library;

use library::{Launcher, LauncherStatus};

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

pub fn run() {
    let launcher = Arc::new(Launcher::default());

    tauri::Builder::default()
        .manage(launcher.clone())
        .invoke_handler(tauri::generate_handler![app_info, launcher_status])
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
