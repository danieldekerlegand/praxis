#!/usr/bin/env python3
"""Praxis launcher — the FastAPI app the desktop shell is a window onto.

Left sidebar = the seed domains, plus the modules of any user-defined subject that has
notebooks. Each topic shows a completion badge (🔴/🟡/✅) and links to the live notebook
in JupyterLab and to a rendered read-only HTML view.

Serves the same library three ways off one view model (``build_model``):
    /             the standalone HTML browser
    /api/library  the same model as JSON — what the Tauri shell's browser reads
    /render/<rel> a read-only HTML render of one notebook (the shell iframes this)

Browsing is read-only. The writes are the three steps of building a subject — generate a
curriculum, scaffold it into notebooks, then construct those notebooks to the rubric —
which is why POST exists at all:
    GET  /api/subjects                  every persisted subject (curriculum.all_subjects)
    POST /api/subjects                  free-text goal -> AI-generated curriculum, persisted
    GET  /api/subjects/<slug>           one curriculum, for review before scaffolding
    POST /api/subjects/<slug>/scaffold  the reviewed curriculum -> 🔴 notebooks on disk
    POST /api/construct                 fill a topic / module / subject to the rubric
    GET  /api/construct[/<job_id>]      how that run is going, for the live badges

Construction is the one call that can't answer inside a request — it is a model call per
notebook — so it returns a job (launcher/jobs.py) the UI polls while 🔴 → 🟡 → ✅ moves.

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
    domain_by_dir,
    domain_path,
    load_subject,
    subjects_dir,
)
from launcher.jobs import JobRegistry, badge_for  # noqa: E402
from nbstatus import BADGE, notebook_status  # noqa: E402
from praxis.checks import needs_checks  # noqa: E402
from praxis.construct import topic_for_rel  # noqa: E402
from praxis.curriculum_gen import generate_and_save  # noqa: E402
from praxis.llm import LLMClient, LLMConfigError, LLMError  # noqa: E402
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


def library_path(rel: str) -> Optional[Path]:
    """The file a library `rel` names, or None if it escapes the library or is missing.

    Almost always `notebooks/<rel>`. A generated subject differs only when
    `PRAXIS_SUBJECTS_DIR` has moved the subject store out of the library — the same
    translation `domain_path()` does, so a relocated subject stays renderable.
    """
    rel = str(rel).strip("/")
    roots = [(NOTEBOOKS_DIR, rel)]
    if rel.startswith(f"{SUBJECTS_ROOT}/"):
        roots.insert(0, (subjects_dir(), rel[len(SUBJECTS_ROOT) + 1:]))
    for root, tail in roots:
        path = (root / tail).resolve()
        if root.resolve() in path.parents and path.is_file():
            return path
    return None


def _module_by_dir(dir_: str) -> tuple[Domain, object]:
    """A library directory -> the Domain it names, and the subject it belongs to."""
    for subject in all_subjects():
        for module in subject.modules:
            if module.dir == dir_:
                return module, subject
    domain = domain_by_dir(dir_)
    if domain is None:
        raise CurriculumError(f"no module {dir_!r} in the library")
    return domain, None


def _module_targets(domain: Domain, subject=None) -> list:
    """Every notebook of one module, as construction targets.

    A `filesystem` domain enumerates no topics — its notebooks only exist on disk — so
    they are resolved one path at a time instead.
    """
    if domain.source == "filesystem":
        return [topic_for_rel(row["rel"]) for row in _topics_for(domain)]
    return [(domain, topic, subject) for topic in domain.topics]


def construction_targets(payload: dict) -> tuple[str, str, str, list]:
    """Read a construct request: `rel` (one topic), `domain` (a module), or `subject`.

    Returns (kind, target, title, targets). Raises CurriculumError when the thing asked
    for isn't in the library, ValueError when nothing was asked for at all.
    """
    if rel := str(payload.get("rel") or "").strip():
        domain, topic, subject = topic_for_rel(rel)
        return "topic", rel, topic.title, [(domain, topic, subject)]
    if dir_ := str(payload.get("domain") or "").strip():
        domain, subject = _module_by_dir(dir_)
        return "module", dir_, domain.title, _module_targets(domain, subject)
    if slug := str(payload.get("subject") or "").strip():
        subject = load_subject(slug)
        return "subject", subject.slug, subject.title, [
            (module, topic, subject)
            for module in subject.modules for topic in module.topics
        ]
    raise ValueError("construct what? pass a rel, a domain or a subject")


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
    jobs = JobRegistry()  # per app: construction state lives with the process serving it
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

    @app.post("/api/construct", response_class=JSONResponse)
    def api_construct(payload: dict = Body(default={})):
        """Fill scaffolds to the rubric — one topic, one module, or a whole subject.

        The long write: one model call per notebook, so it answers 202 with a job and
        the caller polls `/api/construct/<id>` while the badges move. What lands on
        disk is decided by praxis/construct.py alone — a notebook that fails the grader
        is never written, and one that is already ✅ is skipped unless `force`.

        Reported apart like defining a subject: 400 nothing to build, 404 no such
        topic/module/subject, 409 a construction is already running, 503 nothing
        configured to call.
        """
        force = bool(payload.get("force"))
        try:
            kind, target, title, targets = construction_targets(payload)
        except ValueError as exc:
            code = 404 if isinstance(exc, CurriculumError) else 400
            return JSONResponse({"error": str(exc)}, status_code=code)
        if not targets:
            return JSONResponse({"error": f"nothing to construct in {target!r}"},
                                status_code=400)

        busy = jobs.running()
        if busy is not None:
            return JSONResponse(
                {"error": f"already constructing {busy.title!r}", "job": busy.to_dict()},
                status_code=409)

        # Resolve the key only if some notebook actually needs the model: re-running a
        # finished curriculum to confirm it is done must not demand one. A ✅ notebook
        # with no knowledge checks yet still needs it — the checks are the second half
        # of construction.
        client = None
        if force or any(badge_for(d, t) != "complete" or needs_checks(d, t)
                        for d, t, _ in targets):
            try:
                client = LLMClient()
            except LLMConfigError as exc:
                return JSONResponse({"error": str(exc)}, status_code=503)

        job = jobs.start(kind, target, title, targets, client=client, force=force)
        return JSONResponse(job.to_dict(), status_code=202)

    @app.get("/api/construct", response_class=JSONResponse)
    def api_construct_jobs():
        """Recent construction runs, newest first — how the shell re-attaches to one."""
        running = jobs.running()
        return {"running": running.id if running else None,
                "jobs": [j.to_dict() for j in jobs.recent()]}

    @app.get("/api/construct/{job_id}", response_class=JSONResponse)
    def api_construct_job(job_id: str):
        """One run: per-notebook phase and live badge. Polled while it is running."""
        job = jobs.get(job_id)
        if job is None:
            return JSONResponse({"error": f"no job {job_id!r}"}, status_code=404)
        return job.to_dict()

    @app.get("/render/{rel:path}", response_class=HTMLResponse)
    def render(rel: str):
        """Read-only HTML render of a notebook (no execution)."""
        path = library_path(rel)
        if path is None:
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
