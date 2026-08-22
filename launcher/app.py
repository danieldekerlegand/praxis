#!/usr/bin/env python3
"""Praxis launcher — the FastAPI app the desktop shell is a window onto.

Left sidebar = the seed domains, plus the modules of any user-defined subject that has
notebooks. Each topic shows a completion badge (🔴/🟡/✅) and links to the live notebook
in JupyterLab and to a rendered read-only HTML view.

Serves the same library three ways off one view model (``build_model``):
    /             the standalone HTML browser
    /api/library  the same model as JSON — what the Tauri shell's browser reads,
                  gated coverage (`praxis/coverage.py`) folded onto it
    /render/<rel> a read-only render of one notebook, graded regions stripped

Browsing is read-only. The writes are the three steps of building a subject — generate a
curriculum, scaffold it into notebooks, then construct those notebooks to the rubric —
which is why POST exists at all:
    GET  /api/subjects                  every persisted subject (curriculum.all_subjects)
    POST /api/subjects                  free-text goal -> AI-generated curriculum, persisted
    GET  /api/subjects/<slug>           one curriculum, for review before scaffolding
    POST /api/subjects/<slug>/scaffold  the reviewed curriculum -> 🔴 notebooks on disk
    POST /api/construct                 fill a topic / module / subject to the rubric
    GET  /api/construct[/<job_id>]      how that run is going, for the live badges

Learning is the other write, and the one the whole thing is for:
    GET  /api/study/<rel>               a notebook's gate: sections, locked, passed
    POST /api/study/<rel>               grade one answer and move the gate (423 if locked)

A job description is the one document the user brings, and it needs no model at all:
    GET  /api/jd                        every imported posting, as summaries (no text)
    GET  /api/jd/<id>                   one posting, canonical plain text included
    POST /api/jd                        {text, title} -> normalize a pasted posting
    POST /api/jd/upload?filename=       the file's raw bytes -> parse, normalize, persist

Everything those writes land on lives wherever `praxis/storage.py` says, and which disk
that is is itself something the user sets:
    GET  /api/storage                   the active backend, its root, and whether it's there
    POST /api/storage                   {kind, options} -> switch backend (400 with why not)
    POST /api/storage/sync              push/pull a mirrored backend (503 if offline)

Every other write is refused with 503 while the active backend is unwritable — one
middleware, so an unplugged drive can't be silently recreated on the internal disk.

Construction is the one call that can't answer inside a request — it is a model call per
notebook — so it returns a job (launcher/jobs.py) the UI polls while 🔴 → 🟡 → ✅ moves.

Run the two pieces (separate terminals):
    praxis-lab        # JupyterLab rooted at the repo, on :8888 (no token)
    praxis-launch     # this app, on :8000

The desktop shell starts this process itself (see src-tauri/src/library.rs) on a
free port, so it needs no separate terminal there.
"""

import json
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
from nbstatus import BADGE, status_from_dict  # noqa: E402
from praxis.checks import (  # noqa: E402
    CheckError,
    checks_path,
    grade,
    graded_cells,
    learner_answer,
    load_checks,
    needs_checks,
)
from praxis.construct import topic_for_rel  # noqa: E402
from praxis.lite import browser_notebook  # noqa: E402
from praxis.coverage import coverage_report  # noqa: E402
from praxis.curriculum_gen import generate_and_save  # noqa: E402
from praxis.llm import LLMClient, LLMConfigError, LLMError  # noqa: E402
from praxis import jd, storage  # noqa: E402
from praxis import gap, jd_extract, suggest, suggestion_review  # noqa: E402
from praxis.progress import (  # noqa: E402
    DEFAULT_LEARNER,
    gate_for,
    learner_id,
    load_progress,
    module_gates,
    record_outcome,
    section_gates,
    topic_outcomes,
    topic_progress,
)
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


def _read(path: Path) -> tuple[str, Optional[dict]]:
    """(badge status, the parsed notebook) in one read.

    `notebook_status()` parses the file to decide the badge and then throws it away.
    `_gated()` needs the same dict again — the graded cells are what says a notebook
    carries its gate — and reading 245 notebooks twice per library request is the whole
    cost of the tracker, so read once and hand the dict on.
    """
    try:
        nb = json.loads(path.read_text())
    except Exception:            # unreadable / invalid JSON — same verdict as nbstatus
        return "error", None
    return status_from_dict(nb)[0], nb


def _topics_for(domain: Domain, progress: Optional[dict] = None) -> list:
    """Uniform topic view models for a domain, from manifest or filesystem.

    Each row also carries the learner's gate for that notebook (`gated`, `graded`,
    `locked`, `passed`, `checks`) — one model, so the library list, the study view and
    the coverage tracker can't disagree about what is open. A domain whose notebooks
    have no checks beside them comes back exactly as it did before there was a gate:
    nothing gated, nothing locked.
    """
    base = domain_path(domain)
    rows, files, notebooks = [], {}, {}
    if domain.source in ("filesystem", "subject"):
        # Only what exists: a subject's curriculum may run ahead of its scaffolds.
        titles = {t.slug: t for t in domain.topics}
        paths = sorted(base.glob("*.ipynb") if domain.source == "subject"
                       else base.rglob("*.ipynb"))
        for p in paths:
            status, notebook = _read(p)
            topic = titles.get(p.stem)
            rel = f"{domain.dir}/{p.relative_to(base).as_posix()}"
            files[rel] = p
            notebooks[rel] = notebook
            rows.append({
                "title": topic.title if topic else p.stem.replace("-", " ").title(),
                "rel": rel,
                "status": status,
                "recommended": bool(topic and topic.recommended),
                "note": (topic.note if topic else
                         (p.parent.name if p.parent != base else "")),
            })
    else:
        for t in domain.topics:
            p = base / f"{t.slug}.ipynb"
            status, notebook = _read(p) if p.exists() else ("error", None)
            rel = p.relative_to(NOTEBOOKS_DIR).as_posix()
            files[rel] = p
            notebooks[rel] = notebook
            rows.append({
                "title": t.title,
                "rel": rel,
                "status": status,
                "recommended": t.recommended,
                "note": t.note,
            })
    return _gated(rows, files, progress, notebooks)


def _gated(
    rows: list, files: dict, progress: Optional[dict],
    notebooks: Optional[dict] = None,
) -> list:
    """Fold this learner's progression state into a domain's topic rows, in order.

    `gated` is the *behavioural* half — this learner meets questions here, which is
    what locks the next topic — and comes from the answer key beside the notebook.
    `graded` is the *shipped* half: the nbgrader graded cells really on disk, which is
    what `praxis/backfill.py` calls gated and what `praxis/coverage.py` counts. A
    notebook with a key but no cells is a half-migrated gate and is reported as one
    rather than as coverage nobody has.
    """
    if progress is None:
        progress = load_progress()
    notebooks = notebooks or {}
    docs = {rel: load_checks(checks_path(p)) for rel, p in files.items()}
    gates = module_gates([r["rel"] for r in rows], docs, progress)
    titles = {r["rel"]: r["title"] for r in rows}
    for row in rows:
        gate = dict(gates[row["rel"]])
        gate["blockedBy"] = titles.get(gate["blockedBy"], "")
        notebook = notebooks.get(row["rel"])
        gate["graded"] = bool(notebook and graded_cells(notebook))
        row.update(gate)
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


def build_model(learner: str = DEFAULT_LEARNER) -> dict:
    """Everything the templates need; recomputed per request so badges stay live.

    The learner's progress is read once here and threaded down, so a library request is
    still one pass over the notebooks rather than one per topic.
    """
    progress = load_progress(learner)
    domains = []
    counts = {"scaffold": 0, "partial": 0, "complete": 0, "error": 0}
    for d in _library_domains():
        topics = _topics_for(d, progress=progress)
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
            "gated": sum(1 for r in topics if r["gated"]),
            "passed": sum(1 for r in topics if r["gated"] and r["complete"]),
        })
    total = sum(d["n"] for d in domains)
    # Gated coverage, off these very rows: how much of the library actually gates, per
    # domain first. Folded in here rather than served from a second endpoint because a
    # second endpoint would be a second `build_model()` pass over the same notebooks —
    # and `praxis.coverage` counts the view model, so it has to be counted where the
    # view model is built. `covered` is each domain's fraction on the row the sidebar
    # already renders; `coverage` is the whole report, breadth included.
    coverage = coverage_report(domains)
    for domain, row in zip(domains, coverage["domains"]):
        domain["covered"] = row["gated"]
    return {
        "domains": domains,
        "counts": counts,
        "coverage": coverage,
        "total": total,
        "badge": BADGE,
        "lab_base": LAB_BASE,
        "learner": learner_id(learner),
        "pct": round(100 * counts["complete"] / total) if total else 0,
    }


def study_model(rel: str, learner: str = DEFAULT_LEARNER) -> dict:
    """One notebook as a learner meets it: the gate, and how far through it they are.

    Raises CurriculumError when `rel` names nothing in the library. Everything else is
    read off disk per request — the unlock state is *derived* from the recorded
    outcomes every time it is asked for, never stored, so it cannot be set by hand.
    """
    domain, topic, _ = topic_for_rel(rel)
    progress = load_progress(learner)
    row = next((r for r in _topics_for(domain, progress=progress) if r["rel"] == rel), None)
    path = library_path(rel)
    doc = load_checks(checks_path(path)) if path else None
    outcomes = topic_outcomes(progress, rel)

    locked = bool(row and row["locked"])
    sections = [g.to_dict(outcomes) for g in section_gates(doc, outcomes)]
    summary = topic_progress(doc, outcomes)
    if locked:
        # An earlier topic in this module is unfinished: the whole notebook is closed,
        # questions included.
        for section in sections:
            section.update(locked=True, checks=[])
        summary["unlocked"], summary["next"] = [], ""
    return {
        "rel": rel,
        "title": topic.title,
        "domain": domain.dir,
        "learner": learner_id(learner),
        "status": row["status"] if row else "error",
        "locked": locked,
        "blockedBy": row["blockedBy"] if row else "",
        "sections": sections,
        **summary,
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

    @app.middleware("http")
    async def refuse_writes_with_nowhere_to_write(request: Request, call_next):
        """One place that stops a write when the storage backend has gone away.

        A drive gets unplugged mid-session; `mkdir(parents=True)` would cheerfully rebuild
        `/Volumes/Backup/Praxis` on the internal disk and the user would go on filling a
        decoy their drive never sees. So every write is checked, here rather than in four
        endpoints that can each forget to — and `/api/storage` itself is exempt, because
        pointing Praxis somewhere else is precisely the fix.

        The check is `writable()`, not `available()`: it is local and cheap, and a cloud
        backend with the network down is still perfectly writable (its root is a mirror),
        so going offline must not stop a learner answering a question.

        Registered *before* the CORS middleware so it ends up inside it — a 503 the
        webview can't read because it lacks the CORS headers is not a clear error.
        """
        if request.method != "GET" and not request.url.path.startswith("/api/storage"):
            ok, why = storage.active_backend().writable()
            if not ok:
                return JSONResponse(
                    {"error": f"storage is unavailable — {why}"}, status_code=503)
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=SHELL_ORIGIN_RE,
        # POST is only for defining a subject; everything else is a read.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
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
        """The whole library as JSON — domains, topics, live badges, counts, coverage.

        Same view model the HTML browser renders, so the shell's browser and this
        app can never disagree about a badge. Recomputed per request, which is what
        makes the `coverage` block a live tracker: a backfill batch's new gates are
        in the next response, off the rows already being built rather than a rescan.
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

    @app.get("/api/study/{rel:path}", response_class=JSONResponse)
    def api_study(rel: str, learner: str = DEFAULT_LEARNER):
        """One notebook's gate for one learner: sections, locked state, what they passed.

        A locked section hands back its size and nothing else — no questions, and never
        an answer key (praxis.checks.learner_check). The unlock state is derived from
        the recorded outcomes on every request, so there is no stored flag to forge.
        """
        try:
            return study_model(rel, learner)
        except CurriculumError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

    @app.post("/api/study/{rel:path}", response_class=JSONResponse)
    def api_study_answer(rel: str, learner: str = DEFAULT_LEARNER,
                         payload: dict = Body(default={})):
        """Grade one answer, record it, and hand back the gate it just moved.

        This is the gate: a check in a locked section — or in a notebook locked behind
        an earlier topic — is refused **423** without being graded, so progression
        cannot be skipped by posting ahead. Grading is praxis.checks.grade() alone;
        nothing here decides a pass, and neither does the client — the body is read
        through praxis.checks.learner_answer(), so a submission carrying its own
        verdict is refused **400** instead of being believed. `choice` and `code` are
        auto-graded here, in this process, so only a `short` answer needs a key (503
        when there is none, 502 if the provider fails).
        """
        try:
            study = study_model(rel, learner)
        except CurriculumError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        path = library_path(rel)
        doc = load_checks(checks_path(path)) if path else None
        if not doc:
            return JSONResponse(
                {"error": f"{rel!r} has no knowledge checks yet"}, status_code=404)

        try:
            check_id, submitted = learner_answer(payload)
        except CheckError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        check = next((c for c in doc.get("checks", [])
                      if isinstance(c, dict) and str(c.get("id")) == check_id), None)
        if check is None:
            return JSONResponse({"error": f"no check {check_id!r} in {rel!r}"},
                                status_code=404)

        outcomes = topic_outcomes(load_progress(learner), rel)
        gate = gate_for(doc, outcomes, check_id)
        if study["locked"]:
            return JSONResponse(
                {"error": f"finish {study['blockedBy'] or 'the earlier topic'} first",
                 "state": study}, status_code=423)
        if gate is None or gate.locked:
            return JSONResponse(
                {"error": f"'{check.get('section')}' is locked — pass the checks before "
                          "it to unlock it", "state": study}, status_code=423)

        client = None
        if check.get("kind") == "short":
            try:
                client = LLMClient()
            except LLMConfigError as exc:
                return JSONResponse({"error": str(exc)}, status_code=503)
        try:
            outcome = grade(check, submitted, client=client)
        except LLMError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        except CheckError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        record_outcome(learner, rel, outcome)
        return {"outcome": outcome.to_dict(), "state": study_model(rel, learner)}

    @app.get("/api/jd", response_class=JSONResponse)
    def api_jds():
        """Every imported job description, newest first — summaries, never the text.

        `praxis.jd.list_jds` drops `text` on purpose: a list view renders titles and word
        counts, and a dozen postings' full text is megabytes the shell would never show.
        """
        return {"jds": jd.list_jds()}

    @app.post("/api/jd", response_class=JSONResponse)
    def api_import_jd(payload: dict = Body(...)):
        """A pasted posting -> one canonical plain-text document, persisted.

        The read path with no model in it: `praxis/jd.py` imports nothing from
        `praxis/llm.py`, so this works with no key configured — BYO-key starts a band
        later, at extraction. Everything `jd` refuses (an empty paste, a posting too
        short to be one) is a 400 carrying the sentence to show the user; nothing that
        failed to parse is written.

        The id is the title's slug plus a digest of the normalized text, so re-posting
        the same posting rewrites one document instead of piling up copies.
        """
        try:
            doc = jd.ingest_text(
                str(payload.get("text") or ""),
                title=str(payload.get("title") or ""),
            )
        except jd.JDError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(doc, status_code=201)

    @app.post("/api/jd/upload", response_class=JSONResponse)
    async def api_upload_jd(request: Request, filename: str = "", title: str = ""):
        """An uploaded .txt/.md/.pdf/.docx -> the same canonical document.

        The file arrives as the **raw request body** with its name in the query string,
        not as multipart — which is a `fetch(url, {body: file})` on the shell's side and
        saves the launcher a `python-multipart` dependency for a form with one field.
        The same stdlib-over-a-dependency call `praxis/jd.py` itself makes for .docx and
        .pdf.

        `jd` decides what is readable: an unsupported extension, bytes that are not text
        and a scan with no extractable text are each a 400 naming the file and what to do
        instead. It also enforces its own 8MB ceiling, so the size error is the
        file-shaped one rather than a truncated body.
        """
        data = await request.body()
        try:
            doc = jd.ingest_upload(filename, data, title=title)
        except jd.JDError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(doc, status_code=201)

    @app.get("/api/jd/{jd_id}", response_class=JSONResponse)
    def api_jd(jd_id: str):
        """One imported posting, canonical text and all — what a later band reads."""
        if jd_id != Path(jd_id).name or jd_id.startswith("."):
            return JSONResponse({"error": "not a job description id"}, status_code=404)
        doc = jd.load_jd(jd_id)
        if doc is None:
            return JSONResponse(
                {"error": f"no imported job description '{jd_id}'"}, status_code=404)
        return doc

    def _jd_suggestion_id(jd_id: str) -> Optional[dict]:
        if jd_id != Path(jd_id).name or jd_id.startswith("."):
            return None
        return jd.load_jd(jd_id)

    def _review(jd_id: str, payload: Optional[dict] = None) -> dict:
        """Load persisted review state, constructing it from the shipped funnel once."""
        stored = suggestion_review.load(jd_id)
        if stored is not None:
            return stored
        doc = _jd_suggestion_id(jd_id)
        if doc is None:
            raise jd.JDError(f"no imported job description '{jd_id}'")
        source = (payload or {}).get("analysis") or (payload or {}).get("requirements")
        extracted = source if source else jd_extract.extract_requirements(doc)
        analysis = gap.analyze(extracted)
        review = suggest.suggest(analysis)
        return suggestion_review.save(jd_id, review)

    def _suggestions_response(jd_id: str, payload: Optional[dict] = None):
        try:
            return suggestion_review.public(_review(jd_id, payload))
        except jd.JDError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except (LLMConfigError, LLMError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        except (gap.GapError, suggest.SuggestError, jd_extract.JDExtractError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

    @app.get("/api/jd/{jd_id}/suggestions", response_class=JSONResponse)
    def api_suggestions(jd_id: str):
        return _suggestions_response(jd_id)

    @app.post("/api/jd/{jd_id}/suggestions", response_class=JSONResponse)
    def api_build_suggestions(jd_id: str, payload: dict = Body(default={} )):
        # A supplied analysis is useful to callers that already ran bands 75/76; absent
        # one, this is the normal model-backed extraction -> gap -> suggestion funnel.
        return _suggestions_response(jd_id, payload)

    def _mutate_suggestion(jd_id: str, suggestion_id: str, action: str, payload: dict):
        try:
            review = _review(jd_id)
        except jd.JDError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        rows = review.get("suggestions", [])
        row = next((item for item in rows if item.get("id") == suggestion_id), None)
        if row is None:
            return JSONResponse({"error": f"no suggestion '{suggestion_id}'"}, status_code=404)
        if action == "edit":
            goal = str(payload.get("goal") or "").strip()
            if not goal:
                return JSONResponse({"error": "a suggestion needs a goal"}, status_code=400)
            row["goal"] = goal
        elif action == "drop":
            rows.remove(row)
            review.setdefault("dropped", []).append({**row, "reason": "user"})
        elif action == "accept":
            goal = str(row.get("goal") or "").strip()
            try:
                subject = generate_and_save(goal)
            except LLMConfigError as exc:
                return JSONResponse({"error": str(exc)}, status_code=503)
            except (LLMError, CurriculumError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=422)
            rows.remove(row)
            review.setdefault("accepted", []).append({"id": suggestion_id, "slug": subject.slug})
            suggestion_review.save(jd_id, review)
            return JSONResponse({"slug": subject.slug, "suggestion": row}, status_code=201)
        suggestion_review.save(jd_id, review)
        return suggestion_review.public(review)

    @app.put("/api/jd/{jd_id}/suggestions/{suggestion_id}", response_class=JSONResponse)
    def api_edit_suggestion(jd_id: str, suggestion_id: str, payload: dict = Body(default={} )):
        return _mutate_suggestion(jd_id, suggestion_id, "edit", payload)

    @app.patch("/api/jd/{jd_id}/suggestions/{suggestion_id}", response_class=JSONResponse)
    def api_patch_suggestion(jd_id: str, suggestion_id: str, payload: dict = Body(default={} )):
        return _mutate_suggestion(jd_id, suggestion_id, "edit", payload)

    @app.delete("/api/jd/{jd_id}/suggestions/{suggestion_id}", response_class=JSONResponse)
    def api_drop_suggestion(jd_id: str, suggestion_id: str):
        return _mutate_suggestion(jd_id, suggestion_id, "drop", {})

    @app.post("/api/jd/{jd_id}/suggestions/{suggestion_id}/accept", response_class=JSONResponse)
    def api_accept_suggestion(jd_id: str, suggestion_id: str):
        return _mutate_suggestion(jd_id, suggestion_id, "accept", {})

    @app.post("/api/jd/{jd_id}/suggestions/{suggestion_id}", response_class=JSONResponse)
    def api_mutate_suggestion(jd_id: str, suggestion_id: str,
                               payload: dict = Body(default={} )):
        """Action-shaped companion for clients that use one mutation verb."""
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"edit", "drop", "accept"}:
            return JSONResponse({"error": "action must be edit, drop or accept"}, status_code=400)
        return _mutate_suggestion(jd_id, suggestion_id, action, payload)

    @app.get("/api/storage", response_class=JSONResponse)
    def api_storage():
        """Where this app is keeping the user's subjects and progress, right now.

        Read-only, and computed per request — a backend that has gone away (an unplugged
        drive) reports `available: false` with the reason rather than 500ing. Credentials
        in a backend's options never cross this boundary (`Backend.public_options`), which
        is also why `backends[].fields` reports a stored secret as `set: true` and never
        by value.
        """
        return storage.describe()

    @app.post("/api/storage", response_class=JSONResponse)
    def api_select_storage(payload: dict = Body(...)):
        """Move the user's work to another backend: `{kind, options}`.

        Exempt from the write guard above — this is the endpoint that *fixes* an
        unavailable backend. `select_backend` resolves, checks and creates before it
        stores the choice, so a wrong path or an unreachable bucket comes back as a 400
        with the reason and the previous selection is still in force. Nothing is copied
        between backends: switching changes where Praxis looks, and the old root keeps
        everything that was in it.
        """
        kind = str(payload.get("kind") or "").strip()
        options = payload.get("options")
        if not isinstance(options, dict):
            options = {}
        try:
            storage.select_backend(kind, options)
        except storage.StorageError as exc:
            return JSONResponse({"error": str(exc), "storage": storage.describe()},
                                status_code=400)
        return storage.describe()

    @app.post("/api/storage/sync", response_class=JSONResponse)
    def api_sync_storage():
        """Reconcile the active backend with wherever its real copy lives.

        Only the cloud backend has one — for the others this answers `synced: false` and
        says why there is nothing to do, rather than erroring. A sync that could not reach
        the bucket is a 503 with the reason: reporting a sync that did not happen is the
        one thing it must never do.
        """
        try:
            return storage.sync_active()
        except storage.StorageError as exc:
            return JSONResponse({"error": str(exc), "storage": storage.describe()},
                                status_code=503)

    @app.get("/render/{rel:path}", response_class=HTMLResponse)
    def render(rel: str):
        """Read-only HTML render of a notebook (no execution).

        A rendered page is HTML in a browser the learner can read with devtools, so it
        is the same untrusted surface the JupyterLite site is and gets the same filter:
        `praxis.lite.browser_notebook()` drops every graded region — Praxis's check
        cells and nbgrader's companion autograder-tests cell, whose assertions *are*
        the answer — before nbconvert ever sees the notebook. The questions are served
        by `/api/study/<rel>`, which knows what this learner has unlocked; a static
        render cannot. See docs/reference/gate-authority.md.
        """
        path = library_path(rel)
        if path is None:
            return HTMLResponse("not found", status_code=404)
        try:
            import nbformat
            from nbconvert import HTMLExporter
            nb = nbformat.from_dict(
                browser_notebook(nbformat.read(str(path), as_version=4)))
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
