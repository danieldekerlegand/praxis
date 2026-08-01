# Project context for Chief agents — Praxis

**Praxis** (this repo, formerly `ai-tutor`) is a desktop/web app that **constructs interactive,
gated notebook tutorials for any subject**. A user defines a subject; AI agents build the
tutorials to a rubric; the tutorials gate progression behind knowledge checks that exercise the
learner's understanding.

## Build on the existing core — do not greenfield

This repo already ships the reusable machinery. Extend it; don't replace it.

- `docs/notebook-rubric.md` — the **definition of a complete tutorial** (8 sections, runnable vs
  conceptual). The construction agents fill notebooks *to this rubric*; it is also the shape of the
  gated tutorial.
- `scaffold_notebooks.py` + `curriculum.py` — the scaffolder. Generalize these from the 10 built-in
  domains to **any user-defined subject**, don't rewrite from scratch.
- `nbstatus.py` + `tests/test_notebooks.py` — the completion **gate** (🔴 scaffold · 🟡 partial · ✅
  complete). This becomes both the author-side "is it built?" check and the learner-side gate.
- `launcher/` — the FastAPI browse/launch/render UI. The Tauri shell wraps this (sidecar or port).
- `notebooks/` — 221 real notebooks across 10 domains. Keep them as the **seed library / examples**.

## Architecture

- **Tauri** desktop/web app: Rust backend in `src-tauri/`, TS/React frontend in `ui/`.
- The notebook-construction + gating core stays **Python** (reuses the scaffolder/rubric/gate).
- **LLM access is BYO-key** (provider + key from config/env: OpenAI / Anthropic / local), with an
  **optional** `AGORA_BASE_URL` to route through agora's provider-router. Never hardcode or commit a
  key. This is a standalone product — no hard dependency on the rest of the ecosystem.

## Quality checks (how to verify a story)
- Rust: `cd src-tauri && cargo build` (and `cargo test` where there are tests).
- Frontend: `cd ui && npm run build` (+ `npm test` where present).
- Notebook core / gate: `python3 -m pytest -q tests/`.
- `.chief/verify.sh` runs these path-scoped and blocks a merge on any red one. Only mark a story
  done when the checks relevant to what you changed are green.

## Anti-fabrication
A tutorial is "complete" only when `nbstatus.py` reports ✅ **and** `tests/test_notebooks.py` passes
for it — never flip a status or a story's `passes` on an unfilled notebook or a UI that doesn't
actually build and run. Resources must be **real URLs**, not placeholders.

## Conventions
- Branch per tasklist: `chief/NN-slug` off `main`. Keep `main` clean.
- Commit message ends with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- One story per iteration; keep the gate green.
