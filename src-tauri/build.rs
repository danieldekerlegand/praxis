use std::fs;
use std::path::Path;

/// `tauri::generate_context!` embeds `build.frontendDist` at compile time, but `ui/dist`
/// is generated, not committed — so a plain `cargo build` in a fresh checkout would fail
/// before the frontend has ever been built. Drop a placeholder in that case so the Rust
/// side compiles standalone; `npm run build` in `ui/` overwrites it with the real app.
const PLACEHOLDER: &str = "<!doctype html><meta charset=\"utf-8\"><title>Praxis</title>\
<body style=\"background:#0f1117;color:#e6e8ee;font:14px -apple-system,sans-serif;padding:40px\">\
<h1>Praxis</h1><p>Frontend not built. Run <code>npm run build</code> in <code>ui/</code>.</p>";

fn main() {
    let dist = Path::new("../ui/dist");
    if !dist.join("index.html").exists() {
        fs::create_dir_all(dist).expect("create ../ui/dist");
        fs::write(dist.join("index.html"), PLACEHOLDER).expect("write ../ui/dist/index.html");
        println!(
            "cargo:warning=ui/dist was empty — embedded a placeholder frontend. \
             Run `npm run build` in ui/ and rebuild for the real app."
        );
    }
    tauri_build::build()
}
