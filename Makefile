# Praxis — build/run entry points.
#
# The Python core (rubric · scaffolder · gate · launcher) is the product; `ui/` +
# `src-tauri/` are a shell around it. Everything here is a thin wrapper over the
# commands in README.md, docs/packaging.md and .chief/verify.sh — no build logic
# lives in this file that isn't already in one of those.
#
# Interpreter: a repo-local .venv if present, else python3. Override with PY=…
# (the same rule src-tauri/src/library.rs uses at runtime for PRAXIS_PYTHON).

PY      ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
UV      ?= uv
NPM     ?= npm
CARGO   ?= cargo
SUBJECT ?=
GOAL    ?=
NB      ?=
DOMAIN  ?=

.DEFAULT_GOAL := help
.PHONY: help venv install install-dev install-pip \
        run dev ui-dev launch lab web \
        build build-ui build-rust bundle bundle-app \
        test test-py verify check \
        doctor curriculum define scaffold construct docs tasklists ralph \
        clean clean-ui clean-rust distclean

## ---------------------------------------------------------------- help

help: ## Show this help
	@echo "Praxis — make targets"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Args:  SUBJECT=<slug>  NB=<path/to/topic.ipynb>  GOAL=\"what to learn\"  DOMAIN=<NN>"
	@echo "Using: PY=$(PY)"

## ---------------------------------------------------------------- setup

venv: ## Create .venv (uv)
	$(UV) venv .venv

install: venv ## Install the core + launch + dev extras into .venv (uv)
	$(UV) pip install --python .venv/bin/python -e '.[launch,dev]'

install-dev: install ## Alias for install

install-pip: ## Same install without uv, into the active environment
	$(PY) -m pip install -e '.[launch,dev]'

## ---------------------------------------------------------------- run

run: build-ui ## Open the desktop window (builds the frontend first — it is embedded at compile time)
	cd src-tauri && $(CARGO) run

dev: ## Desktop window with frontend HMR: needs `make ui-dev` (or npm run dev) in another terminal
	@echo "Start the Vite dev server first:  $(NPM) --prefix ui run dev"
	cd src-tauri && $(CARGO) run --no-default-features

ui-dev: ## Vite dev server on :1420 (pair with `make dev`)
	$(NPM) --prefix ui run dev

launch: ## Launcher API + its own HTML on :8000 (PRAXIS_HOST / PRAXIS_PORT)
	$(PY) -m launcher.app

lab: ## JupyterLab rooted at this repo, on :8888 — needed only to RUN notebook code
	$(PY) -c 'from launcher.app import launch_lab; launch_lab()'

web: build-ui ## Serve the built frontend statically (pair with `make launch`)
	$(NPM) --prefix ui run preview

## ---------------------------------------------------------------- build

build: build-ui build-rust ## Frontend then Rust — in that order, always

# Order-only: install deps once, not on every build. `make distclean` forces a reinstall.
ui/node_modules:
	$(NPM) --prefix ui ci

build-ui: | ui/node_modules ## tsc --noEmit && vite build -> ui/dist
	$(NPM) --prefix ui run build

build-rust: ## cargo build (embeds whatever is in ui/dist right now)
	cd src-tauri && $(CARGO) build

# tauri build runs beforeBuildCommand itself, so ui/dist cannot go stale here. It finds
# src-tauri/ by walking up from the CWD — hence repo root, not ui/ (docs/packaging.md).
bundle: | ui/node_modules ## Release desktop bundle (.app/.dmg, .msi/.exe, .deb/.AppImage)
	$(NPM) --prefix ui exec -- tauri build

bundle-app: | ui/node_modules ## macOS .app only, skipping the DMG step
	$(NPM) --prefix ui exec -- tauri build --bundles app

## ---------------------------------------------------------------- gates

test: test-py ## The Python gate (notebook core + launcher API)

test-py:
	$(PY) -m pytest -q tests/

verify: ## .chief/verify.sh — the path-scoped merge gate CI mirrors
	CHIEF_BASE_BRANCH=$${CHIEF_BASE_BRANCH:-main} ./.chief/verify.sh

check: test build ## Everything CI runs: pytest + frontend build + cargo build

## ---------------------------------------------------------------- the core

doctor: ## Print the resolved LLM route + timeout (spends no tokens)
	$(PY) -m praxis.llm

curriculum: ## List what is defined: seed domains + your subjects
	$(PY) curriculum.py

define: ## Define a subject from GOAL="..." (spends tokens)
	@test -n '$(GOAL)' || { echo 'usage: make define GOAL="I want to learn X"'; exit 2; }
	$(PY) -m praxis.curriculum_gen '$(GOAL)'

scaffold: ## Scaffold notebooks: SUBJECT=<slug>, or all (seed + subjects) with no arg
	$(PY) scaffold_notebooks.py $(if $(SUBJECT),--subject $(SUBJECT))

construct: ## Fill scaffolds to the rubric + write checks: SUBJECT=<slug> or NB=<path> (spends tokens)
	@test -n '$(SUBJECT)$(NB)' || { echo 'usage: make construct SUBJECT=<slug> | NB=<path.ipynb>'; exit 2; }
	$(PY) -m praxis.construct $(if $(SUBJECT),--subject $(SUBJECT)) $(NB)

docs: ## Regenerate CURRICULUM.md + indices with live badges
	$(PY) generate_docs.py

tasklists: ## Rebuild the ralph construction tasklists from the seed curriculum
	$(PY) ralph/generate_tasklists.py

ralph: ## Fill notebooks with an autonomous agent: DOMAIN=<NN> for one domain, else all
	./ralph/run.sh $(DOMAIN)

## ---------------------------------------------------------------- clean

clean: clean-ui ## Remove build output (keeps target/ and .venv)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache

clean-ui:
	rm -rf ui/dist ui/node_modules/.vite

clean-rust: ## cargo clean — drops the whole target/ dir
	cd src-tauri && $(CARGO) clean

distclean: clean clean-rust ## Also drop node_modules and .venv
	rm -rf ui/node_modules .venv
