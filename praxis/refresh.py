"""Repo-maintenance refreshes for the shipped notebook seed library.

Refreshing a seed is deliberately separate from the in-app notebook paths.  A
normal invocation produces a finding for a maintainer; only an explicit
``force=True`` call for an audited, rotted notebook delegates to the shipped
constructor.  The constructor grades its candidate before writing it, so a
failed regeneration leaves the existing file untouched.

CLI::

    python -m praxis.refresh notebooks/02-ai-ml-tooling/pytorch.ipynb
    python -m praxis.refresh --force notebooks/02-ai-ml-tooling/pytorch.ipynb
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from praxis.audit import audit_notebook
from praxis.construct import ConstructionResult, construct_path

FLAGGED_FOR_HUMAN = "FLAGGED-FOR-HUMAN"
FORCE_REGENERATE = "FORCE-REGENERATE"


@dataclass(frozen=True)
class RefreshResult:
    """The auditable decision made for one seed notebook."""

    notebook: str
    outcome: str
    audit: dict[str, Any]
    construction: ConstructionResult | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == FORCE_REGENERATE and self.construction is not None and self.construction.ok

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "notebook": self.notebook,
            "outcome": self.outcome,
            "audit": self.audit,
        }
        if self.construction is not None:
            result["construction"] = {
                "status": self.construction.status,
                "detail": self.construction.detail,
                "failures": list(self.construction.failures),
            }
        return result


def refresh_notebook(
    path: str | Path,
    *,
    force: bool = False,
    root: str | Path | None = None,
    timeout: float = 10.0,
    opener: Callable[..., Any] | None = None,
    **construct_kwargs: Any,
) -> RefreshResult:
    """Audit *path* and optionally explicitly regenerate that one rotted seed.

    ``force`` is intentionally a keyword-only opt-in.  A healthy/complete seed
    is never a regeneration target, even when the caller passes ``force=True``.
    ``construct_path`` remains the sole writer and its pre-write grader is the
    final write barrier.
    """
    path = Path(path)
    root = Path(root) if root is not None else _root_for(path)
    audit = audit_notebook(path, root=root, timeout=timeout, opener=opener)
    if audit.get("status") != "rotted":
        return RefreshResult(path.relative_to(root).as_posix(), FLAGGED_FOR_HUMAN, audit)
    if not force:
        return RefreshResult(path.relative_to(root).as_posix(), FLAGGED_FOR_HUMAN, audit)

    construction = construct_path(path, force=True, **construct_kwargs)
    return RefreshResult(
        path.relative_to(root).as_posix(), FORCE_REGENERATE, audit, construction
    )


def _root_for(path: Path) -> Path:
    """Use the seed root for the packaged library, or the fixture's parent root."""
    parts = path.resolve().parts
    if "notebooks" in parts:
        return Path(*parts[: parts.index("notebooks") + 1])
    return path.resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review or explicitly refresh one seed notebook")
    parser.add_argument("path", type=Path)
    parser.add_argument("--force", action="store_true", help="opt in to regeneration after audit")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="emit the machine-readable decision")
    args = parser.parse_args(argv)
    result = refresh_notebook(args.path, force=args.force, timeout=args.timeout)
    if args.json:
        json.dump(result.as_dict(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"{result.outcome}: {result.notebook}")
        if result.audit.get("findings"):
            print("; ".join(result.audit["findings"]))
        if result.construction is not None:
            print(result.construction.summary())
    return 0 if result.outcome == FLAGGED_FOR_HUMAN or result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
