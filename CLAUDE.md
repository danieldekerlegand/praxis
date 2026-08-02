# Praxis — notes for coding agents

Praxis constructs interactive, gated notebook tutorials for any subject. The Python core
(rubric · scaffolder · gate · launcher · seed notebooks) is the product; `src-tauri/` +
`ui/` are a shell around it. Extend that core — don't reimplement it in Rust or TS.

## Build order and the two ways a Tauri window goes blank

1. `ui/dist` is embedded at **compile** time. Always `npm run build` in `ui/` before
   `cargo build`. `src-tauri/build.rs` writes a placeholder `index.html` when `ui/dist`
   is missing, so a green `cargo build` does not prove the real UI is inside.
2. Embedding only happens with the `custom-protocol` feature (default-on in
   `src-tauri/Cargo.toml`). Without it Tauri loads `build.devUrl` (:1420) and the window
   is **blank white with no error** unless a Vite dev server is running. Use
   `cargo run --no-default-features` + `npm run dev` when you want HMR.

A window that opens with the right title proves nothing about the page. To check the page
actually ran, look for a call reaching the backend (e.g. a request in the launcher's
access log) or screenshot the window by its CGWindow id — `screencapture -l<id>` returns
only the frame for an occluded window, so raise it first (`AXRaise` via System Events).

## The library path

`launcher/app.py` owns browse/render for both UIs: `build_model()` → `/` (its own HTML)
and `/api/library` (JSON for the shell), `/render/<rel>` for a read-only notebook. Badge
logic lives in `nbstatus.py` only. `src-tauri/src/library.rs` starts that app on a free
loopback port; the webview fetches it directly, so cross-origin access is gated by
`SHELL_ORIGIN_RE` in `launcher/app.py` — extend that regex, don't widen it to `*`.

The two stylesheets `launcher/static/app.css` and `ui/src/app.css` share `:root` tokens on
purpose. Keep them in sync.

## Curricula: seed and generated

`curriculum.py` is one model for both. A user-defined subject's **modules are `Domain`s**
(`Module = Domain`), so the scaffolder, the launcher and the gate need no branch for them —
give a new consumer `Domain`/`Topic` and it works on either. Only `Domain.source` differs:
`manifest` (every topic has a notebook) · `filesystem` (scan the dir) · `subject` (topics
are enumerated, but only the scaffolded ones exist yet).

`Domain.dir` is always relative to the notebooks root — that string is the `rel` in
`/api/library` and `/render/<rel>`. Resolve it to a path with `domain_path(domain)`, never
by hand: a generated subject resolves under `subjects_dir()`, which `PRAXIS_SUBJECTS_DIR`
relocates so tests don't write into `notebooks/`.

The AI never writes files directly. `praxis/curriculum_gen.py` asks for JSON, and
`subject_from_dict()` normalizes it — lenient about what the model omits (slugs, dirs,
flags), strict about what would break the scaffolder. Extend that validation rather than
trusting a payload downstream. Generated content is gitignored (`notebooks/subjects/`).

Scaffolding is the second, separate write: `scaffold_domain()` / `scaffold_subject()` in
`scaffold_notebooks.py`, reached from `POST /api/subjects/<slug>/scaffold`. Keep it
**idempotent — an existing notebook is skipped, never rewritten** — because a curriculum
gets re-scaffolded after an author has already filled part of it. Anything generated per
notebook that depends on where the file sits (the rubric backlink, for one) must be
computed from `Domain.dir`'s depth: a seed domain is one level under `notebooks/`, a
subject's module is three.

## Gates

`python3 -m pytest -q tests/` (notebook core + launcher API), `npm run build` in `ui/`,
`cargo build` in `src-tauri/`. `.chief/verify.sh` runs them path-scoped. The launcher tests
skip themselves without the launch extra: `uv pip install --python .venv/bin/python -e '.[launch]'`.
