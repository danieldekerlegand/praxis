"""Promote recommended topics into the shipped seed library.

Promotion is a repository-maintenance operation.  It delegates notebook construction
and knowledge-check generation to the existing pipeline, and only edits the gap
analysis after both artifacts pass their shipped graders.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import curriculum
from curriculum import DOMAINS, Domain, Topic, topic_path
from nbstatus import status_from_dict
from praxis.checks import checkset_failures, load_checks, checks_path
from praxis.gateaudit import body_text
from praxis.construct import ConstructionResult, construct_topic
from praxis.rubric import gate_failures

GAP_ANALYSIS = Path(__file__).resolve().parent.parent / "docs/explanation/gap-analysis.md"


@dataclass(frozen=True)
class PromotionResult:
    """The graded outcome of promoting one recommended topic."""

    slug: str
    title: str
    promoted: bool
    construction: ConstructionResult | None = None
    failures: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.promoted

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "promoted": self.promoted,
            "failures": list(self.failures),
            "construction": self.construction.summary() if self.construction else None,
        }


def domain_numbering_failures(
    *, root: str | Path | None = None,
    domains: list[Domain] | None = None,
) -> list[str]:
    """Return policy violations for the numbered seed domains.

    Domain 06 is intentionally absent.  The check compares the manifest and the
    top-level directories, while allowing the legacy domain's nested notebooks.
    """
    root = Path(root) if root is not None else curriculum.NOTEBOOKS_DIR
    manifest = list(domains if domains is not None else curriculum.DOMAINS)
    manifest_dirs = [d.dir for d in manifest if d.source != "subject"]
    failures: list[str] = []
    if any(d.startswith("06-") for d in manifest_dirs):
        failures.append("domain 06 is reserved and must not be reused")
    numbers = [int(match.group(1)) for d in manifest_dirs
               if (match := re.match(r"^(\d{2})-", d))]
    if len(numbers) != len(set(numbers)):
        failures.append("domain numbers must be unique")
    required = set(range(1, 16)) - {6}
    if numbers and max(numbers) >= 16:
        required.update(range(16, max(numbers) + 1))
    if set(numbers) != required:
        failures.append("DOMAINS must contain 01-05, 07-15, and contiguous appended domains")
    disk_dirs = {p.name for p in root.iterdir() if p.is_dir()} if root.is_dir() else set()
    if set(manifest_dirs) != {d for d in disk_dirs if re.match(r"^\d{2}-", d)}:
        failures.append("on-disk numbered domain directories must match DOMAINS")
    return failures


def _read_notebook(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _record_in_gap_analysis(domain: Domain, topic: Topic, path: str | Path = GAP_ANALYSIS) -> None:
    """Move one exact recommended bullet from §2 into its §1 coverage heading."""
    doc_path = Path(path)
    text = doc_path.read_text()
    backlog = f"- **{topic.title}**"
    if backlog not in text:
        # A prior successful promotion is idempotent; anything else is a malformed
        # analysis and must not be silently claimed as promoted.
        coverage = f"- ✅ {topic.title}"
        if coverage in text:
            return
        raise ValueError(f"recommended topic is not in gap-analysis §2: {topic.title}")
    text = text.replace(backlog, f"- ✅ {topic.title}", 1)
    heading = f"### {domain.title}"
    match = re.search(rf"(?m)^{re.escape(heading)}\n", text)
    if not match:
        raise ValueError(f"no coverage section for domain: {domain.title}")
    doc_path.write_text(text[: match.end()] + f"\n- ✅ {topic.title}\n" + text[match.end():])


def promote_topic(
    domain: Domain,
    topic: Topic,
    *,
    gap_path: str | Path = GAP_ANALYSIS,
    **construct_kwargs: Any,
) -> PromotionResult:
    """Construct and gate one recommended topic, then record its promotion.

    The documentation write is last.  A non-complete notebook or absent/invalid
    checkset can never move an item out of the backlog.
    """
    if not topic.recommended:
        return PromotionResult(topic.slug, topic.title, False, failures=("topic is not recommended",))
    result = construct_topic(domain, topic, checks=True, **construct_kwargs)
    failures = list(result.failures)
    if not result.ok:
        failures.append(f"construction did not pass: {result.status}")
    if not result.checks_ok:
        failures.extend(result.checks.failures if result.checks else ("knowledge checks are absent",))
    path = topic_path(domain, topic)
    notebook = _read_notebook(path)
    if notebook is None:
        failures.append(f"notebook is missing or unreadable: {path}")
    else:
        status, _ = status_from_dict(notebook)
        failures.extend(gate_failures(notebook))
        if status != "complete":
            failures.append("notebook does not have the ✅ complete status")
    check_path = checks_path(path)
    checkset = load_checks(check_path)
    if checkset is None:
        failures.append(f"knowledge checks are absent: {check_path}")
    else:
        failures.extend(checkset_failures(
            checkset, verify_code=True,
            notebook=body_text(notebook) if notebook else "",
        ))
    if failures:
        return PromotionResult(topic.slug, topic.title, False, result, tuple(dict.fromkeys(failures)))
    try:
        _record_in_gap_analysis(domain, topic, gap_path)
    except (OSError, ValueError) as exc:
        return PromotionResult(topic.slug, topic.title, False, result, (str(exc),))
    return PromotionResult(topic.slug, topic.title, True, result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote one recommended seed topic")
    parser.add_argument("domain", help="domain directory, for example 02-ai-ml-tooling")
    parser.add_argument("slug", help="recommended topic slug")
    parser.add_argument("--gap", type=Path, default=GAP_ANALYSIS)
    args = parser.parse_args(argv)
    domain = next((d for d in DOMAINS if d.dir == args.domain), None)
    topic = next((t for t in domain.topics if t.slug == args.slug), None) if domain else None
    if domain is None or topic is None:
        print("unknown domain or topic", file=sys.stderr)
        return 2
    result = promote_topic(domain, topic, gap_path=args.gap)
    print(json.dumps(result.as_dict(), indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
