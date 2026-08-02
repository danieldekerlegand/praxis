//! The Praxis desktop/web shell.
//!
//! This crate is only the shell: it opens a window over the frontend in `ui/`. The
//! notebook-construction core (rubric, scaffolder, gate) stays in Python at the repo
//! root and is wired in by later bands.

use serde::Serialize;

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

pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![app_info])
        .run(tauri::generate_context!())
        .expect("error while running Praxis");
}
