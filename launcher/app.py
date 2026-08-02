#!/usr/bin/env python3
"""Praxis launcher — the FastAPI app the desktop shell is a window onto.

Left sidebar = the seed domains, plus the modules of any user-defined subject that has
notebooks. Each topic shows a completion badge (🔴/🟡/✅) and links to the live notebook
in JupyterLab and to a rendered read-only HTML view.

Serves the same library three ways off one view model (``build_model``):
    /             the standalone HTML browser
    /api/library  the same model as JSON — what the Tauri shell's browser reads
    /render/<rel> a read-only HTML render of one notebook (the shell iframes this)

Browsing is read-only. The writes are the two steps of defining a subject — generate a
curriculum, then scaffold it into notebooks — which is why POST exists at all:
    GET  /api/subjects                  every persisted subject (curriculum.all_subjects)
    POST /api/subjects                  free-text goal -> AI-generated curriculum, persisted
    GET  /api/subjects/<slug>           one curriculum, for review before scaffolding
    POST /api/subjects/<slug>/scaffold  the reviewed curriculum -> 🔴 notebooks on disk

Run the two pieces (separate terminals):
    praxis-lab        # JupyterLab rooted at the repo, on :8888 (no token)
    praxis-launch     # this app, on :8000

The desktop shell starts this process itself (see src-tauri/src/library.rs) on a
free port, so it needs no separate terminal there.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from curriculum import (  # noqa: E402
    DOMAINS,
    NOTEBOOKS_DIR,
    SUBJECTS_ROOT,
    CurriculumError,
    Domain,
    all_subjects,
    domain_path,
    load_subject,
)
from nbstatus import BADGE, notebook_status  # noqa: E402
from praxis.curriculum_gen import generate_and_save  # noqa: E402
from praxis.llm import LLMConfigError, LLMError  # noqa: E402
from scaffold_notebooks import scaffold_subject  # noqa: E402

LAB_PORT = int(os.environ.get("PRAXIS_LAB_PORT", "8888"))
LAB_BASE = os.environ.get("PRAXIS_LAB_URL", f"http://localhost:{LAB_PORT}")


def _short(domain: Domain) -> str:
    """Sidebar label: the last path segment, minus any `NN-` ordering prefix."""
    leaf = domain.dir.rsplit("/", 1)[-1]
    head, _, rest = leaf.partition("-")
    return (rest if head.isdigit() and rest else leaf).replace("-", " ").title()


def _library_domains() -> list[Domain]:
    """The seed domains, then every generated-subject module that has notebooks.

    A subject's modules only appear once they are scaffolded, so defining a subject
    doesn't put empty groups in the sidebar — and every notebook on disk belongs to
    exactly one listed domain, which is what keeps the counts honest.
    """
    domains = list(DOMAINS)
    for subject in all_subjects():
        domains += [m for m in subject.modules if any(domain_path(m).glob("*.ipynb"))]
    return domains


def _topics_for(domain: Domain) -> list:
    """Uniform topic view models for a domain, from manifest or filesystem."""
    base = domain_path(domain)
    rows = []
    if domain.source in ("filesystem", "subject"):
        # Only what exists: a subject's curriculum may run ahead of its scaffolds.
        titles = {t.slug: t for t in domain.topics}
        paths = sorted(base.glob("*.ipynb") if domain.source == "subject"
                       else base.rglob("*.ipynb"))
        for p in paths:
            status, _ = notebook_status(p)
            topic = titles.get(p.stem)
            rows.append({
                "title": topic.title if topic else p.stem.replace("-", " ").title(),
                "rel": f"{domain.dir}/{p.relative_to(base).as_posix()}",
                "status": status,
                "recommended": bool(topic and topic.recommended),
                "note": (topic.note if topic else
                         (p.parent.name if p.parent != base else "")),
            })
    else:
        for t in domain.topics:
            p = base / f"{t.slug}.ipynb"
            status, _ = notebook_status(p) if p.exists() else ("error", {})
            rows.append({
                "title": t.title,
                "rel": p.relative_to(NOTEBOOKS_DIR).as_posix(),
                "status": status,
                "recommended": t.recommended,
                "note": t.note,
            })
    return rows


def build_model() -> dict:
    """Everything the templates need; recomputed per request so badges stay live."""
    domains = []
    counts = {"scaffold": 0, "partial": 0, "complete": 0, "error": 0}
    for d in _library_domains():
        topics = _topics_for(d)
        for r in topics:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        domains.append({
            "dir": d.dir,
            "name": _short(d),
            "title": d.title,
            "blurb": d.blurb,
            "topics": topics,
            "n": len(topics),
            "done": sum(1 for r in topics if r["status"] == "complete"),
        })
    total = sum(d["n"] for d in domains)
    return {
        "domains": domains,
        "counts": counts,
        "total": total,
        "badge": BADGE,
        "lab_base": LAB_BASE,
        "pct": round(100 * counts["complete"] / total) if total else 0,
    }


# FastAPI imported at module level (guarded) so route type hints resolve in this
# module's globals. The launch extra installs it; absent, create_app() explains.
try:
    from fastapi import Body, FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    _FASTAPI_ERR = None
except Exception as exc:  # pragma: no cover
    _FASTAPI_ERR = exc

# The shell's webview fetches /api/library cross-origin. Allow exactly the origins a
# local shell can have — the Tauri webview (tauri://localhost on macOS/Linux,
# http://tauri.localhost on Windows) and the vite dev server — and nothing else, so a
# random page in a browser can't read the library off this loopback port.
SHELL_ORIGIN_RE = (
    r"^(tauri://localhost"
    r"|https?://tauri\.localhost"
    r"|https?://localhost(:\d+)?"
    r"|https?://127\.0\.0\.1(:\d+)?)$"
)


def _exit_with_parent(parent_pid: int, interval: float = 2.0) -> threading.Thread:
    """Stop this process once `parent_pid` is gone. Returns the watchdog thread.

    The desktop shell kills the launcher when it exits cleanly, but a hard kill or a
    crash never runs that cleanup — without this, an orphaned uvicorn keeps holding its
    port. On POSIX an orphan is reparented (getppid() becomes 1), which is the signal.
    """
    def watch() -> None:
        while os.getppid() == parent_pid:
            time.sleep(interval)
        os._exit(0)  # a server thread is mid-request; don't unwind, just go

    thread = threading.Thread(target=watch, daemon=True, name="praxis-parent-watch")
    thread.start()
    return thread


def create_app():
    if _FASTAPI_ERR is not None:  # pragma: no cover
        raise RuntimeError(
            "FastAPI not installed — run: pip install -e '.[launch]'"
        ) from _FASTAPI_ERR

    parent = os.environ.get("PRAXIS_PARENT_PID")
    if parent and parent.isdigit():
        _exit_with_parent(int(parent))

    here = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(here / "templates"))
    app = FastAPI(title="Praxis launcher")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=SHELL_ORIGIN_RE,
        # POST is only for defining a subject; everything else is a read.
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=str(here / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, domain: Optional[str] = None):
        model = build_model()
        active = next((d for d in model["domains"] if d["dir"] == domain),
                      model["domains"][0])
        return templates.TemplateResponse(
            request, "index.html", {"active": active, **model})

    @app.get("/api/library", response_class=JSONResponse)
    def api_library():
        """The whole library as JSON — domains, topics, live badges, counts.

        Same view model the HTML browser renders, so the shell's browser and this
        app can never disagree about a badge. Recomputed per request.
        """
        return build_model()

    @app.get("/api/subjects", response_class=JSONResponse)
    def api_subjects():
        """Every user-defined subject, newest first — the review list in the shell."""
        return {"subjects": [s.to_dict() for s in all_subjects()]}

    @app.get("/api/subjects/{slug}", response_class=JSONResponse)
    def api_subject(slug: str):
        """One persisted curriculum: modules -> topics, for review before scaffolding."""
        try:
            return load_subject(slug).to_dict()
        except CurriculumError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.post("/api/subjects", response_class=JSONResponse)
    def api_define_subject(payload: dict = Body(...)):
        """Free-text goal -> AI-generated curriculum, persisted for review.

        The only write in this app. It spends tokens against the user's own key
        (praxis/llm.py), so the failure modes are reported apart: 400 the goal is
        empty, 503 nothing is configured to call, 502 the provider failed, 422 the
        model answered with something that isn't a usable curriculum.
        """
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            return JSONResponse({"error": "a subject needs a goal"}, status_code=400)
        try:
            subject = generate_and_save(
                goal,
                slug=str(payload.get("slug") or ""),
                modules=payload.get("modules", 5),
                topics_per_module=payload.get("topics_per_module", 6),
            )
        except LLMConfigError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        except LLMError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        except CurriculumError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(subject.to_dict(), status_code=201)

    @app.post("/api/subjects/{slug}/scaffold", response_class=JSONResponse)
    def api_scaffold_subject(slug: str):
        """Turn a reviewed curriculum into rubric-shaped notebooks on disk.

        Spends no tokens — the scaffolds are blank, an author fills them later. Safe to
        repeat: a topic that already has a notebook is skipped, never rewritten, so this
        only ever fills the gaps in a partly-built subject.
        """
        try:
            subject = load_subject(slug)
        except CurriculumError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        try:
            created, skipped = scaffold_subject(subject)
        except OSError as exc:
            return JSONResponse({"error": f"could not write notebooks: {exc}"},
                                status_code=500)
        return {
            "slug": subject.slug,
            "created": created,
            "skipped": skipped,
            "n_topics": subject.n_topics,
            "dir": f"{SUBJECTS_ROOT}/{subject.slug}",
        }

    @app.get("/render/{rel:path}", response_class=HTMLResponse)
    def render(rel: str):
        """Read-only HTML render of a notebook (no execution)."""
        path = (NOTEBOOKS_DIR / rel).resolve()
        if NOTEBOOKS_DIR not in path.parents or not path.exists():
            return HTMLResponse("not found", status_code=404)
        try:
            import nbformat
            from nbconvert import HTMLExporter
            nb = nbformat.read(str(path), as_version=4)
            body, _ = HTMLExporter(template_name="classic").from_notebook_node(nb)
            return HTMLResponse(body)
        except Exception as exc:  # nbconvert optional
            return HTMLResponse(
                "<p>Install the launch extra to render: "
                "<code>pip install -e '.[launch]'</code></p>"
                f"<pre>{exc}</pre>", status_code=200)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        return "ok"

    return app


# Importable ASGI app for `uvicorn launcher.app:app`.
app = create_app() if _FASTAPI_ERR is None else None


def main() -> None:
    """Console script: praxis-launch."""
    import uvicorn
    host = os.environ.get("PRAXIS_HOST", "127.0.0.1")
    port = int(os.environ.get("PRAXIS_PORT", "8000"))
    print(f"Praxis launcher -> http://{host}:{port}  (notebooks open in {LAB_BASE})")
    uvicorn.run("launcher.app:app", host=host, port=port, reload=False)


def launch_lab() -> None:
    """Console script: praxis-lab — JupyterLab rooted at the repo."""
    cmd = [
        sys.executable, "-m", "jupyterlab",
        f"--port={LAB_PORT}",
        f"--ServerApp.root_dir={ROOT}",
        "--IdentityProvider.token=",
        "--no-browser",
    ]
    print("starting JupyterLab:", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=str(ROOT), check=True)
    except FileNotFoundError:
        sys.exit("JupyterLab not installed — run: pip install -e '.[launch]'")


if __name__ == "__main__":
    main()
