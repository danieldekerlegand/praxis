"""Read-only health checks for the shipped notebook seed library.

The audit deliberately composes the rubric's existing checks.  It does not edit
notebooks, and an inability to reach the network is reported as ``unchecked``
rather than being mistaken for a live resource.

CLI::

    python -m praxis.audit notebooks --json
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NOTEBOOKS = ROOT / "notebooks"
DEFAULT_TIMEOUT = 10.0

from praxis.rubric import (  # noqa: E402
    URL_RE,
    _resources_text,
    code_syntax_failures,
    construction_failures,
    gate_failures,
    notebook_text,
)


def _resource_urls(nb: dict) -> list[str]:
    """Return the https URLs in the notebook's Resources section."""
    return [url for url in URL_RE.findall(_resources_text(nb)) if url.startswith("https://")]


def _check_url(
    url: str,
    *,
    timeout: float,
    opener: Callable[..., Any] | None = None,
) -> dict[str, str]:
    """Make one bounded request and classify its measured result."""
    request = urllib.request.Request(url, method="HEAD")
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            if status is not None and status >= 400:
                return {"url": url, "status": "dead", "detail": f"HTTP {status}"}
            return {"url": url, "status": "live", "detail": f"HTTP {status or 200}"}
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": "dead", "detail": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        # DNS failures, refused connections, and timeouts say nothing about the
        # URL's liveness when the audit host has no network access.
        return {"url": url, "status": "unchecked", "detail": str(exc) or exc.__class__.__name__}
    except Exception as exc:  # an injected/test transport may use its own failure type
        return {"url": url, "status": "unchecked", "detail": str(exc) or exc.__class__.__name__}


def audit_notebook(
    path: Path,
    *,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Audit one notebook without changing it."""
    relative = path.relative_to(root).as_posix()
    try:
        nb = json.loads(path.read_text())
    except Exception as exc:
        return {
            "notebook": relative,
            "status": "rotted",
            "findings": [f"notebook could not be read: {exc}"],
            "urls": [],
        }

    urls = [_check_url(url, timeout=timeout, opener=opener) for url in _resource_urls(nb)]
    findings = list(gate_failures(nb))
    # construction_failures is the shipped composite grader.  Pulling its
    # syntax sentences here ensures audit output stays identical to construction.
    construction = construction_failures(nb)
    for failure in code_syntax_failures(nb):
        if failure not in findings:
            findings.append(failure)
    for result in urls:
        if result["status"] == "dead":
            findings.append(f"Resources URL {result['url']} is dead ({result['detail']})")
    return {
        "notebook": relative,
        "status": "rotted" if findings else "healthy",
        "urls": urls,
        "gate_failures": list(gate_failures(nb)),
        "construction_failures": construction,
        "findings": findings,
        "chars": len(notebook_text(nb)),
    }


def audit_notebooks(
    root: str | Path = DEFAULT_NOTEBOOKS,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Audit every ``*.ipynb`` below *root* and return a JSON-ready report."""
    root = Path(root)
    reports = [
        audit_notebook(path, root=root, timeout=timeout, opener=opener)
        for path in sorted(root.rglob("*.ipynb"))
    ]
    rotted = [report for report in reports if report.get("status") == "rotted"]
    return {
        "root": str(root),
        "notebooks": len(reports),
        "rotted": len(rotted),
        "reports": reports,
    }


# A concise alias for callers that describe the operation as a seed audit.
audit_seeds = audit_notebooks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit seed notebooks without rewriting them")
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_NOTEBOOKS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    args = parser.parse_args(argv)
    report = audit_notebooks(args.root, timeout=args.timeout)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"audited {report['notebooks']} notebooks; {report['rotted']} rotted")
        for item in report["reports"]:
            if item["status"] == "rotted":
                print(f"{item['notebook']}: {'; '.join(item['findings'])}")
    return 1 if report["rotted"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
