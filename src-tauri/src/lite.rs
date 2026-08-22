//! The tutorial runtime: a JupyterLite site, served to the webview by the shell itself.
//!
//! `scripts/build-jupyterlite.sh` writes a static JupyterLab on a Pyodide kernel into
//! `src-tauri/resources/jupyterlite`, and a bundle carries it (`tauri.lite.conf.json`).
//! This module is the other half: it finds that directory, reads the manifest travelling
//! with it, and serves the tree over loopback so the webview can iframe a notebook.
//!
//! Two properties are the point, and both are why this is here rather than in
//! [`crate::library`]:
//!
//! - **It needs no Python.** The site is static and the kernel is the browser's, so
//!   reading and *running* a tutorial works in a bundle whose Python core is missing
//!   entirely — which is the whole first-run cost this deletes. Nothing in this file
//!   touches the launcher, and its failure mode is independent of it.
//! - **It serves content, never the gate.** What is on disk here has already had every
//!   graded region stripped by `praxis/lite.py`, and no answer key is staged; the gate's
//!   authority stays in the launcher, which the learner does not control
//!   (`docs/reference/gate-authority.md`). This is a read-only file server over one
//!   directory and holds no unlock logic of its own. It refuses an answer key by name
//!   as well ([`ANSWER_KEY`]) — the staging refusal is what keeps one out of the site,
//!   and this is what keeps a stray one unreachable if it ever got in.
//!
//! It is a few dozen lines of `std::net` rather than a dependency for the same reason
//! `library::healthy` writes its own `GET /healthz`: one read-only GET/HEAD server over
//! one directory is less code than wiring a crate for it.

use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Component, Path, PathBuf};
use std::sync::Mutex;

use serde::Serialize;

/// The site's directory name under Tauri's resource directory — what
/// `src-tauri/tauri.lite.conf.json` copies `src-tauri/resources/jupyterlite` in as.
const SITE_DIR: &str = "jupyterlite";

/// The manifest `praxis/lite.py` writes beside the site: the pins it was built from, and
/// every seed tutorial's verdict (`available` / `unavailable-in-browser`). It travels
/// *with* the site because the site is static — a shell with no Python core can still
/// draw a library from it.
const MANIFEST: &str = "praxis-lite.json";

/// Praxis's answer-key sidecar (`praxis::checks::checks_path`). `praxis/lite.py` stages
/// only `.ipynb`, so the site should contain none — this refuses one anyway, because
/// "there isn't one there" is a property of the last build and not of this server.
const ANSWER_KEY: &str = ".checks.json";

/// Point the shell at a site somewhere else. The same variable
/// `scripts/build-jupyterlite.sh` writes one with, so a site built to a scratch directory
/// can be run without staging it.
const SITE_ENV: &str = "PRAXIS_LITE_SITE";

/// Where a checkout's site lands, relative to the repo root — the dev path, for
/// `cargo run` and `make run`, which ship no resources.
const CHECKOUT_SITE: [&str; 3] = ["src-tauri", "resources", SITE_DIR];

/// What the frontend needs to open a tutorial in the browser — or to say why it can't.
#[derive(Clone, Serialize)]
pub struct LiteStatus {
    /// `ready` · `missing`
    pub state: String,
    /// Base URL of the site once served, e.g. `http://127.0.0.1:53413`.
    pub url: Option<String>,
    /// Human-readable detail — where the site came from, or how to build one.
    pub detail: String,
    /// `praxis-lite.json`: the pins, the counts, the domains and every tutorial's verdict.
    /// `None` when there is no site.
    pub manifest: Option<serde_json::Value>,
}

impl LiteStatus {
    fn missing(detail: impl Into<String>) -> Self {
        Self { state: "missing".into(), url: None, detail: detail.into(), manifest: None }
    }
}

/// Owns the site's file server for the life of the app.
pub struct Site {
    status: Mutex<LiteStatus>,
    /// Tauri's `resource_dir()` — see [`crate::library::Launcher::use_resources`], which
    /// is handed the same path for the same reason.
    resources: Mutex<Option<PathBuf>>,
}

impl Default for Site {
    fn default() -> Self {
        Self {
            status: Mutex::new(LiteStatus::missing(
                "no JupyterLite site yet — build one with scripts/build-jupyterlite.sh",
            )),
            resources: Mutex::new(None),
        }
    }
}

impl Site {
    pub fn status(&self) -> LiteStatus {
        self.status.lock().expect("lite status poisoned").clone()
    }

    /// Tell the site where this build keeps its resources. Call before `start`.
    pub fn use_resources(&self, dir: PathBuf) {
        *self.resources.lock().expect("lite resources poisoned") = Some(dir);
    }

    /// Find the site, read its manifest and serve it. Returns immediately — the accept
    /// loop runs on its own thread.
    ///
    /// A missing site is reported, never fatal: a build that shipped none still browses
    /// and constructs through the launcher, it just cannot run a notebook in the window.
    pub fn start(&self) {
        let resources = self.resources.lock().expect("lite resources poisoned").clone();
        let Some(root) = find_site(resources.as_deref()) else {
            self.set(LiteStatus::missing(
                "this build carries no JupyterLite site — build one with \
                 scripts/build-jupyterlite.sh (or set PRAXIS_LITE_SITE), then \
                 `make bundle` to ship it",
            ));
            return;
        };
        let manifest = match std::fs::read_to_string(root.join(MANIFEST))
            .ok()
            .and_then(|text| serde_json::from_str::<serde_json::Value>(&text).ok())
        {
            Some(manifest) => manifest,
            None => {
                self.set(LiteStatus::missing(format!(
                    "{} is unreadable — rebuild the site with scripts/build-jupyterlite.sh",
                    root.join(MANIFEST).display()
                )));
                return;
            }
        };
        match serve(root.clone()) {
            Ok(port) => self.set(LiteStatus {
                state: "ready".into(),
                url: Some(format!("http://127.0.0.1:{port}")),
                detail: root.display().to_string(),
                manifest: Some(manifest),
            }),
            Err(err) => self.set(LiteStatus::missing(format!(
                "could not serve {}: {err}",
                root.display()
            ))),
        }
    }

    fn set(&self, status: LiteStatus) {
        *self.status.lock().expect("lite status poisoned") = status;
    }
}

/// The site this build can serve: `$PRAXIS_LITE_SITE`, then the bundle's resources, then
/// a checkout's `src-tauri/resources/jupyterlite` above the binary or the cwd.
///
/// The same shape as [`crate::library::repo_root`]'s order and for the same reason: a
/// bundle carries its own and a dev build discovers the one `make build-lite` wrote.
fn find_site(resources: Option<&Path>) -> Option<PathBuf> {
    if let Some(explicit) = std::env::var_os(SITE_ENV) {
        let dir = PathBuf::from(explicit);
        if is_site(&dir) {
            return Some(dir);
        }
    }
    if let Some(dir) = resources.map(|dir| dir.join(SITE_DIR)).filter(|dir| is_site(dir)) {
        return Some(dir);
    }
    let seeds = [std::env::current_exe().ok(), std::env::current_dir().ok()];
    seeds
        .into_iter()
        .flatten()
        .flat_map(|seed| seed.ancestors().map(Path::to_path_buf).collect::<Vec<_>>())
        .map(|dir| CHECKOUT_SITE.iter().fold(dir, |dir, part| dir.join(part)))
        .find(|dir| is_site(dir))
}

/// A built site: JupyterLite's entry page, and the manifest Praxis staged beside it.
/// Both, because half of either is a half-finished build, not a site.
fn is_site(dir: &Path) -> bool {
    dir.join(MANIFEST).is_file() && dir.join("index.html").is_file()
}

/// Bind a loopback port and serve `root` read-only until the process exits.
fn serve(root: PathBuf) -> std::io::Result<u16> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    std::thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            let root = root.clone();
            // Thread per connection: JupyterLab opens dozens of asset requests at once,
            // and a serial loop would deadlock the page waiting on itself.
            std::thread::spawn(move || {
                let _ = respond(stream, &root);
            });
        }
    });
    Ok(port)
}

/// One request. Everything is `Connection: close`, so there is no keep-alive state.
fn respond(mut stream: TcpStream, root: &Path) -> std::io::Result<()> {
    let (method, target) = match request_head(&stream) {
        Some(head) => head,
        None => return send(&mut stream, 400, "text/plain", b"bad request", true),
    };
    if method != "GET" && method != "HEAD" {
        return send(&mut stream, 405, "text/plain", b"method not allowed", true);
    }
    let body = method == "GET";
    match resolve(root, &target) {
        Resolved::Found(path) => match std::fs::read(&path) {
            Ok(bytes) => send(&mut stream, 200, mime_for(&path), &bytes, body),
            Err(_) => send(&mut stream, 404, "text/plain", b"not found", body),
        },
        Resolved::Missing => send(&mut stream, 404, "text/plain", b"not found", body),
        Resolved::Refused => send(&mut stream, 403, "text/plain", b"forbidden", body),
    }
}

/// `(method, target)` from the request line, with the headers read and dropped.
fn request_head(stream: &TcpStream) -> Option<(String, String)> {
    let mut reader = BufReader::new(stream.try_clone().ok()?);
    let mut line = String::new();
    reader.read_line(&mut line).ok()?;
    let mut parts = line.split_whitespace();
    let method = parts.next()?.to_string();
    let target = parts.next()?.to_string();
    // Drain the headers so the client's write completes before we answer; the body of a
    // GET/HEAD is not ours to read.
    loop {
        let mut header = String::new();
        match reader.read_line(&mut header) {
            Ok(0) => break,
            Ok(_) if header.trim().is_empty() => break,
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    Some((method, target))
}

/// What a request target names.
#[derive(Debug, PartialEq, Eq)]
enum Resolved {
    /// A file inside the site.
    Found(PathBuf),
    /// Nothing is there. Distinct from [`Resolved::Refused`] so a missing asset reads as
    /// 404 in the browser's network panel rather than as a security refusal.
    Missing,
    /// It named something outside the site.
    Refused,
}

/// The file a request target names.
///
/// Refuses `..` rather than normalizing it, and re-checks the *canonical* path against
/// the site root — a symlink inside a JupyterLab asset tree is the way a normalizing
/// server still serves `/etc/passwd`. With `..` refused up front, a path that does not
/// exist cannot be outside the root, so "missing" and "refused" stay separable.
///
/// An [`ANSWER_KEY`] target is refused before anything is looked up, so the refusal does
/// not depend on whether one happens to be on disk.
fn resolve(root: &Path, target: &str) -> Resolved {
    let path = target.split(['?', '#']).next().unwrap_or_default();
    let decoded = percent_decode(path);
    if decoded.ends_with(ANSWER_KEY) {
        return Resolved::Refused;
    }
    let Ok(base) = root.canonicalize() else {
        return Resolved::Refused;
    };
    let mut file = base.clone();
    for segment in decoded.split('/') {
        if segment.is_empty() || segment == "." {
            continue;
        }
        if segment == ".." || segment.contains('\0') {
            return Resolved::Refused;
        }
        let candidate = Path::new(segment);
        // A single normal component and nothing else — no drive letters, no roots.
        if candidate.components().count() != 1
            || !matches!(candidate.components().next(), Some(Component::Normal(_)))
        {
            return Resolved::Refused;
        }
        file.push(segment);
    }
    if file.is_dir() {
        file.push("index.html");
    }
    match file.canonicalize() {
        Ok(real) if real.starts_with(&base) => Resolved::Found(real),
        Ok(_) => Resolved::Refused,
        Err(_) => Resolved::Missing,
    }
}

/// `%20` and friends. Malformed escapes are left as written rather than guessed at.
fn percent_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).ok();
            if let Some(byte) = hex.and_then(|hex| u8::from_str_radix(hex, 16).ok()) {
                out.push(byte);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Content types for what a JupyterLite site is made of. A type the browser refuses is a
/// blank page with no error, so `.wasm`, `.mjs` and `.json` matter more than the rest.
fn mime_for(path: &Path) -> &'static str {
    match path.extension().and_then(|ext| ext.to_str()).unwrap_or_default() {
        "html" | "htm" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        // A notebook is JSON, and JupyterLite fetches both the same way.
        "json" | "ipynb" | "map" => "application/json; charset=utf-8",
        "wasm" => "application/wasm",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        "ttf" => "font/ttf",
        "txt" | "md" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

fn send(
    stream: &mut TcpStream,
    status: u16,
    content_type: &str,
    body: &[u8],
    with_body: bool,
) -> std::io::Result<()> {
    let reason = match status {
        200 => "OK",
        400 => "Bad Request",
        403 => "Forbidden",
        404 => "Not Found",
        _ => "Method Not Allowed",
    };
    let head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\n\
         Content-Length: {}\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(head.as_bytes())?;
    if with_body {
        stream.write_all(body)?;
    }
    stream.flush()
}

#[cfg(test)]
mod tests {
    //! Discovery and the path rule. The second is the one worth a test: this server has
    //! one directory to serve and no authority of its own, so the only way it can be
    //! wrong is by serving something outside that directory.

    use std::io::Read;

    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("praxis-lite-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch dir");
        dir
    }

    fn write(path: &Path, body: &str) {
        std::fs::create_dir_all(path.parent().expect("parent")).expect("mkdir");
        std::fs::write(path, body).expect("write");
    }

    /// A directory shaped like a built site.
    fn site_at(dir: &Path) -> PathBuf {
        write(&dir.join("index.html"), "<!doctype html>");
        write(&dir.join(MANIFEST), r#"{"counts":{"total":0}}"#);
        write(&dir.join("files").join("01-domain").join("topic.ipynb"), "{}");
        dir.to_path_buf()
    }

    #[test]
    fn a_site_is_jupyterlite_and_the_manifest_or_it_is_not_a_site() {
        let dir = scratch("halves");
        assert!(!is_site(&dir), "an empty directory is not a site");
        write(&dir.join("index.html"), "<!doctype html>");
        assert!(!is_site(&dir), "JupyterLab with no manifest is a half-finished build");
        write(&dir.join(MANIFEST), "{}");
        assert!(is_site(&dir));
    }

    #[test]
    fn a_bundles_own_site_is_preferred_to_none_and_a_build_without_one_finds_nothing() {
        let resources = scratch("resources");
        assert!(
            find_site(Some(&resources)).is_none()
                || std::env::var_os(SITE_ENV).is_some()
                || find_site(None).is_some(),
            "a build with no site anywhere reports none"
        );
        site_at(&resources.join(SITE_DIR));
        assert_eq!(find_site(Some(&resources)), Some(resources.join(SITE_DIR)));
    }

    #[test]
    fn nothing_outside_the_site_is_reachable() {
        let dir = scratch("traversal");
        let root = site_at(&dir.join("site"));
        write(&dir.join("secret.txt"), "the answer key");

        // The site's own files resolve, `/` is its index, and a query string is not part
        // of the path — JupyterLite opens a notebook as `lab/index.html?path=…`.
        let index = Resolved::Found(root.join("index.html").canonicalize().unwrap());
        assert_eq!(resolve(&root, "/"), index);
        assert_eq!(resolve(&root, "/index.html?path=01-domain/topic.ipynb"), index);
        assert!(matches!(resolve(&root, "/files/01-domain/topic.ipynb"), Resolved::Found(_)));

        // Everything that leaves the directory, however it is spelled.
        for target in ["/../secret.txt", "/files/../../secret.txt", "/%2e%2e/secret.txt"] {
            assert_eq!(resolve(&root, target), Resolved::Refused, "{target} escaped the site");
        }
        // ...including through a symlink planted inside it, which is why the canonical
        // path is re-checked rather than the joined one.
        #[cfg(unix)]
        {
            let link = root.join("out");
            std::os::unix::fs::symlink(dir.join("secret.txt"), &link).expect("symlink");
            assert_eq!(resolve(&root, "/out"), Resolved::Refused, "a symlink out is not served");
        }

        // An asset that simply is not there is missing, not refused: with `..` already
        // refused, a path that does not exist cannot be outside the site.
        assert_eq!(resolve(&root, "/nothing-here.js"), Resolved::Missing);
    }

    #[test]
    fn an_answer_key_is_refused_whether_or_not_one_is_on_disk() {
        // `praxis/lite.py` stages only `.ipynb`, so a built site holds no key at all.
        // That is a property of the last build; this is a property of the server.
        let dir = scratch("answer-key");
        let root = site_at(&dir.join("site"));
        let planted = root.join("files").join("01-domain").join("topic.checks.json");
        write(&planted, r#"{"checks": [{"answer": 0, "test": "assert True"}]}"#);
        assert!(planted.is_file(), "the key really is there to be served");

        for target in [
            "/files/01-domain/topic.checks.json",
            "/files/01-domain/topic.checks.json?download=1",
            "/files/01-domain/topic%2Echecks%2Ejson",
        ] {
            assert_eq!(resolve(&root, target), Resolved::Refused, "{target} served a key");
        }
        // The notebook beside it is still content, and still served.
        assert!(matches!(resolve(&root, "/files/01-domain/topic.ipynb"), Resolved::Found(_)));
    }

    #[test]
    fn percent_escapes_decode_and_a_malformed_one_is_left_alone() {
        assert_eq!(percent_decode("/a%20b/c.ipynb"), "/a b/c.ipynb");
        assert_eq!(percent_decode("/a%2Fb"), "/a/b");
        assert_eq!(percent_decode("/100%"), "/100%");
        assert_eq!(percent_decode("/%zz"), "/%zz");
    }

    #[test]
    fn the_types_a_blank_page_depends_on_are_named() {
        assert_eq!(mime_for(Path::new("a/index.html")), "text/html; charset=utf-8");
        assert_eq!(mime_for(Path::new("a/main.js")), "text/javascript; charset=utf-8");
        assert_eq!(mime_for(Path::new("a/kernel.wasm")), "application/wasm");
        assert_eq!(mime_for(Path::new("a/topic.ipynb")), "application/json; charset=utf-8");
        assert_eq!(mime_for(Path::new("a/font.woff2")), "font/woff2");
    }

    #[test]
    fn the_site_is_served_over_loopback_and_a_traversal_is_refused() {
        let dir = scratch("serve");
        let root = site_at(&dir.join("site"));
        write(&dir.join("secret.txt"), "the answer key");
        let port = serve(root).expect("bind a loopback port");

        let get = |target: &str| -> String {
            let mut sock = TcpStream::connect(("127.0.0.1", port)).expect("connect");
            sock.write_all(
                format!("GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
                    .as_bytes(),
            )
            .expect("write");
            let mut reply = String::new();
            sock.read_to_string(&mut reply).expect("read");
            reply
        };

        let index = get("/");
        assert!(index.starts_with("HTTP/1.1 200 OK"), "{index}");
        assert!(index.contains("text/html"), "{index}");
        assert!(index.ends_with("<!doctype html>"), "{index}");

        let notebook = get("/files/01-domain/topic.ipynb");
        assert!(notebook.starts_with("HTTP/1.1 200 OK"), "{notebook}");
        assert!(notebook.contains("application/json"), "{notebook}");

        assert!(get("/../secret.txt").starts_with("HTTP/1.1 403"));
        assert!(get("/nothing-here.js").starts_with("HTTP/1.1 404"));
    }
}
