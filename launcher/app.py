#!/usr/bin/env python3
"""Praxis launcher — a read-only FastAPI app.

Left sidebar = the 11 domains. Each topic shows a completion badge (🔴/🟡/✅) and
links to the live notebook in JupyterLab and to a rendered read-only HTML view.

Serves the same library three ways off one view model (``build_model``):
    /             the standalone HTML browser
    /api/library  the same model as JSON — what the Tauri shell's browser reads
    /render/<rel> a read-only HTML render of one notebook (the shell iframes this)

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

from curriculum import DOMAINS, NOTEBOOKS_DIR, Domain  # noqa: E402
from nbstatus import BADGE, notebook_status  # noqa: E402

LAB_PORT = int(os.environ.get("PRAXIS_LAB_PORT", "8888"))
LAB_BASE = os.environ.get("PRAXIS_LAB_URL", f"http://localhost:{LAB_PORT}")


def _short(domain: Domain) -> str:
    return domain.dir.split("-", 1)[1].replace("-", " ").title()


def _topics_for(domain: Domain) -> list:
    """Uniform topic view models for a domain, from manifest or filesystem."""
    base = NOTEBOOKS_DIR / domain.dir
    rows = []
    if domain.source == "filesystem":
        for p in sorted(base.rglob("*.ipynb")):
            status, _ = notebook_status(p)
            rows.append({
                "title": p.stem.replace("-", " ").title(),
                "rel": p.relative_to(NOTEBOOKS_DIR).as_posix(),
                "status": status,
                "recommended": False,
                "note": p.parent.name if p.parent != base else "",
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
    for d in DOMAINS:
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
    from fastapi import FastAPI, Request
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
        allow_methods=["GET"],
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
