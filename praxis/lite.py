"""JupyterLite delivery — the released library, staged for an in-browser kernel.

The friction this deletes is measured from the README: before a learner sees a single
tutorial they install Python, install the launch extra, register a kernel and run two
processes in two terminals. JupyterLite runs a full JupyterLab on a Pyodide kernel in
the browser, so the *runtime* for notebook content needs none of that.

This module is the **staging** half of that adoption, and it is deliberately not a
second product: it selects, strips and triages, and hands the result to JupyterLite's
own `jupyter lite build` (`scripts/build-jupyterlite.sh`). Three rules do the work, and
each is the repo's existing discipline pointed at an untrusted browser:

- **What crosses is what `checks.learner_check()` already permits, and less.** A
  JupyterLite site is a static directory the learner controls entirely, so the gate's
  authority cannot live there — `browser_notebook()` therefore removes *every* graded
  region (Praxis's own check cells, nbgrader's graded/locked/solution cells and their
  companion `-tests` cells) and no sidecar answer key is ever copied. What is delivered
  is the tutorial body: the eight rubric sections and their runnable code.
- **Nothing that would leak is written.** `leak_failures()` re-inspects the artifact
  *after* stripping and `stage_contents()` raises on any failure, so a notebook that
  still carries a reference solution or a hidden test stops the build instead of
  reaching the browser — the constructor's "content that fails the grader is never
  written", one level out.
- **Not-measured rather than silently-zero.** Pyodide cannot provide `torch`, and a
  tutorial served into a kernel that will die at its first import is worse than one
  honestly reported as unavailable. `requirements()` resolves each notebook's imports
  against a pinned Pyodide package index and `stage_contents()` stages only what
  resolves; the rest is recorded in the manifest as `unavailable-in-browser`, naming
  the modules that made it so.

The Pyodide index is **vendored** (`praxis/data/pyodide-packages.json`) rather than
fetched at build time, for the same reason the JupyterLite versions are pinned here: a
build that reaches the network for its own definition of "available" is not
reproducible. `python3 -m praxis.lite index` regenerates it from the pinned release.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from curriculum import DOMAINS, Domain, domain_path

ROOT = Path(__file__).resolve().parent.parent

# --- the pins ---------------------------------------------------------------
#
# One JupyterLite release, named here and nowhere else. `scripts/build-jupyterlite.sh`
# reads these through `python3 -m praxis.lite pins`, so the build and the tests cannot
# disagree about which release was adopted.
JUPYTERLITE_CORE = "0.8.3"
JUPYTERLITE_PYODIDE_KERNEL = "0.8.5"
# jupyterlite-core's contents addon refuses custom content without it ("jupyter-server is
# not installed. You cannot add custom content to jupyterlite."). It is a build-time
# dependency of the site, not a runtime one: the built site is static.
JUPYTER_SERVER = "2.14.2"

#: Where `scripts/build-jupyterlite.sh` writes the site. Untracked, like the embedded
#: Python runtime beside it (`src-tauri/resources/` is gitignored wholesale).
SITE_DIR = ROOT / "src-tauri" / "resources" / "jupyterlite"

#: The manifest the shell reads to know what is runnable in the browser and what is not.
MANIFEST_NAME = "praxis-lite.json"

#: The vendored Pyodide package index — see `index_document()` for its shape.
INDEX_PATH = Path(__file__).resolve().parent / "data" / "pyodide-packages.json"

AVAILABLE = "available"
UNAVAILABLE = "unavailable-in-browser"

#: nbgrader's region markers. A released notebook has none; finding one in an artifact
#: bound for the browser means the authored source was staged by mistake.
LEAK_MARKERS = (
    "### BEGIN SOLUTION",
    "### END SOLUTION",
    "### BEGIN HIDDEN TESTS",
    "### END HIDDEN TESTS",
)


class LiteError(RuntimeError):
    """A tutorial could not be staged for the browser. Nothing is written."""


# --- the pinned Pyodide package index ---------------------------------------


_INDEX: dict | None = None


def index_document() -> dict:
    """The vendored index: `{pyodide, python, source, imports: {…}, stdlib: [...]}`.

    `imports` maps an importable top-level name to the Pyodide package that provides it
    (`PIL` -> `Pillow`), which is exactly `pyodide-lock.json`'s own `imports` field —
    resolved from the release the pinned kernel loads, never guessed from a package name.
    """
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = json.loads(INDEX_PATH.read_text())
        except OSError as err:
            raise LiteError(f"the pinned Pyodide index is missing: {INDEX_PATH} ({err})") from err
    return _INDEX


def pyodide_imports() -> dict[str, str]:
    return dict(index_document().get("imports", {}))


def pyodide_stdlib() -> set[str]:
    return set(index_document().get("stdlib", ()))


# --- what a tutorial needs --------------------------------------------------


@dataclass(frozen=True)
class Requirements:
    """What one notebook imports, split by whether Pyodide can provide it."""

    modules: tuple[str, ...] = ()      # every non-stdlib top-level import
    packages: tuple[str, ...] = ()     # the Pyodide packages that resolve them
    missing: tuple[str, ...] = ()      # the modules nothing in Pyodide provides

    @property
    def available(self) -> bool:
        return not self.missing

    @property
    def status(self) -> str:
        return AVAILABLE if self.available else UNAVAILABLE


def notebook_imports(nb: dict) -> list[str]:
    """Top-level module names imported by the notebook's code cells.

    A cell that does not parse contributes nothing rather than failing the notebook:
    tutorials legitimately show broken or elided code, and `rubric.construction_failures`
    is where compilability is enforced.
    """
    names: set[str] = set()
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return sorted(names)


def requirements(nb: dict) -> Requirements:
    """Resolve a notebook's imports against the pinned Pyodide package index."""
    provides, stdlib = pyodide_imports(), pyodide_stdlib()
    modules = [name for name in notebook_imports(nb) if name not in stdlib]
    packages = sorted({provides[name] for name in modules if name in provides})
    missing = tuple(name for name in modules if name not in provides)
    return Requirements(tuple(modules), tuple(packages), missing)


# --- what may cross into the browser ----------------------------------------


def _graded(cell: dict) -> bool:
    """Is this cell part of a gate? Praxis's own namespace, or nbgrader's flags.

    Both halves are needed: `checks.graded_cells()` finds what `annotate_notebook`
    wrote, while the companion autograder-tests cell nbgrader releases beside a code
    check carries only nbgrader metadata — and its assertions are the answer.
    """
    metadata = cell.get("metadata", {})
    if metadata.get("praxis", {}).get("extension") == "checks":
        return True
    nbgrader = metadata.get("nbgrader", {})
    return any(bool(nbgrader.get(flag)) for flag in ("grade", "solution", "locked", "task"))


def browser_notebook(nb: dict) -> dict:
    """A copy of *nb* carrying only what an untrusted browser may hold.

    Every graded region is removed, not filtered: a locked section serves no checks at
    all, and a static file cannot enforce that. The gate is answered in the trusted
    process (`GET|POST /api/study/<rel>`), so the delivered notebook is the tutorial
    body — which is the part JupyterLite exists to run.
    """
    out = copy.deepcopy(nb)
    out["cells"] = [cell for cell in out.get("cells", []) if not _graded(cell)]
    metadata = out.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("praxis", None)
    return out


def leak_failures(nb: dict, where: str = "notebook") -> list[str]:
    """What would leak if *nb* were served. Empty == safe to hand to the browser.

    Run on the artifact after stripping rather than on the source, so it measures what
    is actually written; `stage_contents()` refuses on any sentence here.
    """
    failures: list[str] = []
    for index, cell in enumerate(nb.get("cells", []), 1):
        metadata = cell.get("metadata", {})
        praxis = metadata.get("praxis", {})
        if praxis.get("extension") == "checks":
            grade_id = praxis.get("grade_id") or f"cell {index}"
            failures.append(f"{where}: carries the Praxis check cell {grade_id}")
        nbgrader = metadata.get("nbgrader", {})
        flags = [flag for flag in ("grade", "solution", "locked", "task") if nbgrader.get(flag)]
        if flags:
            grade_id = nbgrader.get("grade_id") or f"cell {index}"
            failures.append(f"{where}: carries the graded cell {grade_id} ({', '.join(flags)})")
        source = "".join(cell.get("source", []))
        for marker in LEAK_MARKERS:
            if marker in source:
                failures.append(f"{where}: cell {index} still contains a `{marker}` region")
    if isinstance(nb.get("metadata"), dict) and "praxis" in nb["metadata"]:
        failures.append(f"{where}: carries a Praxis answer key in its notebook metadata")
    return failures


# --- staging the library ----------------------------------------------------


@dataclass
class Tutorial:
    """One library notebook's verdict: where it came from, and whether it can run."""

    rel: str
    status: str
    packages: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    domain: str = ""
    title: str = ""

    def to_dict(self) -> dict:
        return {
            "rel": self.rel,
            "domain": self.domain,
            "title": self.title,
            "status": self.status,
            "packages": list(self.packages),
            "missing": list(self.missing),
        }


@dataclass
class StagingReport:
    """What one staging run selected, and what it honestly declined to serve."""

    tutorials: list[Tutorial] = field(default_factory=list)

    @property
    def available(self) -> list[Tutorial]:
        return [t for t in self.tutorials if t.status == AVAILABLE]

    @property
    def unavailable(self) -> list[Tutorial]:
        return [t for t in self.tutorials if t.status == UNAVAILABLE]

    def manifest(self) -> dict:
        """The document the shell reads. Pins included: a site is one build's output."""
        return {
            "jupyterlite": JUPYTERLITE_CORE,
            "pyodideKernel": JUPYTERLITE_PYODIDE_KERNEL,
            "pyodide": index_document().get("pyodide", ""),
            "counts": {
                "total": len(self.tutorials),
                AVAILABLE: len(self.available),
                UNAVAILABLE: len(self.unavailable),
            },
            "domains": domain_rows(t.domain for t in self.tutorials),
            "tutorials": [t.to_dict() for t in sorted(self.tutorials, key=lambda t: t.rel)],
        }

    def summary(self) -> str:
        return (f"lite: {len(self.available)} runnable in the browser, "
                f"{len(self.unavailable)} unavailable-in-browser, "
                f"{len(self.tutorials)} seed notebooks")


@dataclass(frozen=True)
class Source:
    """One library notebook as the shell names it: its `rel`, its file, and its label."""

    rel: str
    path: Path
    domain: str = ""
    title: str = ""


def domain_label(domain: Domain | str) -> str:
    """The sidebar label `launcher.app._short` gives this domain (or bare directory).

    Restated here rather than imported because the site is built with the *build*
    interpreter (`.lite-venv`), and `launcher/app.py` needs FastAPI — this module has no
    dependency beyond the standard library and `curriculum.py` on purpose. A test pins
    the two against each other.
    """
    dir = domain if isinstance(domain, str) else domain.dir
    leaf = dir.rsplit("/", 1)[-1]
    head, _, rest = leaf.partition("-")
    return (rest if head.isdigit() and rest else leaf).replace("-", " ").title()


def topic_title(domain: Domain, stem: str) -> str:
    """The title the launcher shows for `<stem>.ipynb` in this domain — its topic's, or
    the file stem made human. Same rule as `launcher.app._topics_for`, same reason as
    `domain_label`."""
    for topic in domain.topics:
        if topic.slug == stem:
            return topic.title
    return stem.replace("-", " ").title()


def domain_rows(dirs) -> list[dict]:
    """`{dir, name, title, blurb}` for each named domain, in library order.

    The manifest carries these so a shell with no Python core can still draw a library:
    the site is static, so what the browser can be told about it has to travel with it.
    """
    known = {domain.dir: domain for domain in DOMAINS}
    order = list(known)
    wanted = {d for d in dirs if d}
    rows = []
    for dir in sorted(wanted, key=lambda d: (order.index(d) if d in known else len(order), d)):
        domain = known.get(dir)
        rows.append({
            "dir": dir,
            "name": domain_label(domain or dir),
            "title": domain.title if domain else dir,
            "blurb": domain.blurb if domain else "",
        })
    return rows


def library_index(domains: list[Domain] | None = None) -> list[Source]:
    """Every notebook of the seed library, in library order, with its label.

    `rel` is the same string `/api/library` and `/render/<rel>` use, so a manifest entry
    names the topic the shell already knows. Generated subjects are excluded on purpose:
    they are the user's data, live outside the repo (`docs/reference/storage.md`), and a
    site is a build artifact of this checkout.
    """
    sources: list[Source] = []
    for domain in domains if domains is not None else DOMAINS:
        base = domain_path(domain)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.ipynb")):
            if ".ipynb_checkpoints" in path.parts:
                continue
            rel = f"{domain.dir}/{path.relative_to(base).as_posix()}"
            sources.append(Source(rel, path, domain.dir, topic_title(domain, path.stem)))
    return sources


def library_sources(domains: list[Domain] | None = None) -> list[tuple[str, Path]]:
    """[`library_index`] as the `(rel, path)` pairs `stage_contents` takes."""
    return [(source.rel, source.path) for source in library_index(domains)]


def _as_sources(sources) -> list[Source]:
    """Accept either shape: `Source`s, or the bare `(rel, path)` pairs a caller stages."""
    return [s if isinstance(s, Source) else Source(s[0], Path(s[1])) for s in sources]


def stage_contents(
    dest: str | Path,
    sources: list[Source] | list[tuple[str, Path]] | None = None,
) -> StagingReport:
    """Write the browser-safe contents tree JupyterLite will build, and report it.

    Only `.ipynb` files are ever written — the answer key lives beside a notebook as
    `<slug>.checks.json` and copying a directory would carry it — and only tutorials
    whose imports Pyodide can resolve are staged at all. Raises `LiteError` rather than
    writing a notebook that still leaks.
    """
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    report = StagingReport()
    for source in (library_index() if sources is None else _as_sources(sources)):
        rel = source.rel
        try:
            nb = json.loads(source.path.read_text())
        except (OSError, ValueError) as err:
            raise LiteError(f"{rel}: could not be read as a notebook ({err})") from err
        needs = requirements(nb)
        report.tutorials.append(Tutorial(rel, needs.status, needs.packages, needs.missing,
                                         source.domain, source.title))
        if not needs.available:
            continue
        released = browser_notebook(nb)
        failures = leak_failures(released, rel)
        if failures:
            raise LiteError("; ".join(failures))
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(released, indent=1) + "\n")
    return report


def write_manifest(report: StagingReport, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.manifest(), indent=2) + "\n")
    return path


# --- regenerating the pinned index ------------------------------------------


def pyodide_lock_url(version: str) -> str:
    return f"https://cdn.jsdelivr.net/pyodide/{version}/full/pyodide-lock.json"


def build_index(lock: dict, *, version: str) -> dict:
    """The vendored index, derived from one `pyodide-lock.json`.

    `source` is where that lock is *published* for the pinned release, not the byte
    stream this call happened to read: a local copy is a copy of the same file, and the
    vendored index should say what a reader can go and check.

    The stdlib half is this interpreter's, recorded with its version: Pyodide's CPython
    and the one running the build are the same minor line by construction of the pin, and
    a triage that resolved stdlib names differently between them would be worse than one
    that says which interpreter answered.
    """
    imports: dict[str, str] = {}
    for key, meta in sorted(lock.get("packages", {}).items()):
        name = meta.get("name", key)
        for module in meta.get("imports") or []:
            imports.setdefault(module, name)
    return {
        "pyodide": version,
        "python": lock.get("info", {}).get("python", ""),
        "source": pyodide_lock_url(version),
        "stdlib_from": f"CPython {'.'.join(str(p) for p in sys.version_info[:3])}",
        "imports": dict(sorted(imports.items())),
        "stdlib": sorted(sys.stdlib_module_names),
    }


def refresh_index(
    version: str, path: str | Path = INDEX_PATH, lock_file: str | Path | None = None,
) -> Path:
    """Rewrite the vendored index from the pinned Pyodide release.

    Fetches `pyodide-lock.json` from the CDN unless *lock_file* names a copy already on
    disk — the same escape hatch every other network step here has, and what makes
    regenerating the index possible on a machine whose Python has no CA bundle.
    """
    if lock_file:
        lock = json.loads(Path(lock_file).read_text())
    else:
        from urllib.request import urlopen

        with urlopen(pyodide_lock_url(version), timeout=120) as reply:  # noqa: S310
            lock = json.loads(reply.read().decode("utf-8"))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_index(lock, version=version), indent=1) + "\n")
    return path


# --- CLI --------------------------------------------------------------------


def _plan_lines() -> list[str]:
    document = index_document()
    report = StagingReport()
    for source in library_index():
        try:
            nb = json.loads(source.path.read_text())
        except (OSError, ValueError):
            continue
        needs = requirements(nb)
        report.tutorials.append(Tutorial(source.rel, needs.status, needs.packages,
                                         needs.missing, source.domain, source.title))
    return [
        f"lite: jupyterlite-core=={JUPYTERLITE_CORE} "
        f"jupyterlite-pyodide-kernel=={JUPYTERLITE_PYODIDE_KERNEL} "
        f"jupyter-server=={JUPYTER_SERVER}",
        f"lite: pyodide {document.get('pyodide', '?')} (python {document.get('python', '?')}), "
        f"{len(document.get('imports', {}))} importable names",
        f"lite: site {SITE_DIR.relative_to(ROOT) if SITE_DIR.is_relative_to(ROOT) else SITE_DIR}",
        report.summary(),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m praxis.lite",
        description="Stage the released seed library for a JupyterLite site.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan", help="print the pins and the triage; write nothing")
    sub.add_parser("pins", help="print the pinned build dependencies, one per line")
    stage = sub.add_parser("stage", help="write the browser-safe contents tree")
    stage.add_argument("dest", help="the contents directory `jupyter lite build` will read")
    stage.add_argument("--manifest", default="", help="where to write praxis-lite.json")
    refresh = sub.add_parser("index", help="regenerate the vendored Pyodide index (network)")
    refresh.add_argument("--pyodide", default="", help="the Pyodide release, e.g. v314.0.5")
    refresh.add_argument("--lock", default="", help="a pyodide-lock.json already on disk")
    args = parser.parse_args(argv)

    if args.command in (None, "plan"):
        for line in _plan_lines():
            print(line)
        return 0
    if args.command == "pins":
        print(f"jupyterlite-core=={JUPYTERLITE_CORE}")
        print(f"jupyterlite-pyodide-kernel=={JUPYTERLITE_PYODIDE_KERNEL}")
        print(f"jupyter-server=={JUPYTER_SERVER}")
        return 0
    if args.command == "stage":
        try:
            report = stage_contents(args.dest)
        except LiteError as err:
            print(f"lite: {err}", file=sys.stderr)
            return 2
        manifest = args.manifest or str(Path(args.dest).parent / MANIFEST_NAME)
        write_manifest(report, manifest)
        print(report.summary())
        print(f"lite: contents {args.dest}")
        print(f"lite: manifest {manifest}")
        return 0
    if args.command == "index":
        version = args.pyodide or index_document().get("pyodide", "")
        if not version:
            print("lite: --pyodide is required when no index is vendored yet", file=sys.stderr)
            return 2
        print(f"lite: wrote {refresh_index(version, lock_file=args.lock or None)}")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
