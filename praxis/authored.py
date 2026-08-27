#!/usr/bin/env python3
"""Author-in-the-loop gating: drive the shipped backfill with no model behind it.

`praxis/backfill.py` selects the ✅-but-ungated topics of a domain and hands them to
`construct_each` → `generate_checks`, which asks a model for JSON and then *grades* it.
The grading half is the product; only the asking half needs an API key. This module
supplies the asking half **from disk**, so an author — a person, or an agent with no
provider configured — writes the JSON themselves and it lands through exactly the
shipped path: `checks_from_reply` normalizes it, `checkset_failures(verify_code=True)`
runs each `code` check's reference solution against its own `test` in a subprocess and
applies `gateaudit`'s four triviality rules, `publish_graded_cells` annotates the
notebook and `nbgrader validate`s a staging copy, and a draft that fails any of it is
**not written**. The bar an authored gate clears is the bar a model's gate clears,
because it is the same code.

It invents no gating rule and no second write path. `generate_checks` reads exactly two
things off its client — `complete(prompt, system=…)` and `config.model` — so

    backfill_domain(domain, client=AuthoredClient(root), attempts=1)

is the whole integration, and every property of an unattended run (skip-if-✅,
skip-if-gated, one failed topic not stranding the rest) is inherited rather than
restated.

**The drafts.** One per topic, beside its notebook as `<slug>.checks.draft.json`,
holding the reply the model would have returned — `{"checks": [...]}`, the schema in
`checks.CHECK_SCHEMA`. A draft is the author's working copy and is deliberately *not*
tracked: the accepted `<slug>.checks.json` is the durable artifact, and a committed
draft would be a second copy of the same questions with nothing keeping the two in
sync. A draft with no gate beside it means the grader rejected it — read the failure
sentences, edit the draft, run again.

**The one coupling.** A client is handed a prompt, not a topic, so the draft has to be
looked up from the prompt's own text. `build_prompt` quotes the topic title in a
`<topic>` tag and that tag is all this module reads; `tests/test_authored.py` pins the
round trip, so a change to the prompt's shape fails a test instead of silently
selecting the wrong draft.

Run it with one attempt: a repair prompt handed back to a file gets the same file, so
retrying costs subprocess time and changes nothing. The failure sentences are the
author's repair loop, exactly as they are the model's.

CLI::

    python3 -m praxis.authored prompts 01-symbolic-ai-logic   what the runner would ask
    python3 -m praxis.authored status  01-symbolic-ai-logic   draft/gate state per topic
    python3 -m praxis.authored run     01-symbolic-ai-logic   grade the drafts, write gates
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import curriculum  # noqa: E402
from curriculum import CurriculumError, Domain, Subject, Topic, topic_path  # noqa: E402
from praxis.backfill import backfill_domain, backfill_targets, is_gated  # noqa: E402
from praxis.checks import build_prompt, checks_path  # noqa: E402
from praxis.construct import ConstructionResult  # noqa: E402
from praxis.llm import LLMError  # noqa: E402

DRAFT_SUFFIX = ".checks.draft.json"

# The one thing read back out of `build_prompt`'s output — see the module docstring.
TOPIC_TAG = re.compile(r"<topic>\s*(.*?)\s*</topic>", re.DOTALL)

DEFAULT_AUTHOR = "hand-authored"


def draft_path(notebook: str | Path) -> Path:
    """`<slug>.checks.draft.json` beside a notebook — `checks_path`'s working copy."""
    path = Path(notebook)
    return path.with_name(path.stem + DRAFT_SUFFIX)


def topic_draft_path(domain: Domain, topic: Topic) -> Path:
    return draft_path(topic_path(domain, topic))


def load_draft(path: str | Path) -> dict | None:
    """The reply an author wrote, or None when there is no readable draft there."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def topic_title_in(prompt: str) -> str:
    """The topic `build_prompt` was called for, read back off its own text."""
    found = TOPIC_TAG.search(prompt or "")
    return found.group(1).strip() if found else ""


@dataclass(frozen=True)
class _AuthorConfig:
    """The one field `generate_checks` reads off `client.config`."""

    model: str = DEFAULT_AUTHOR


class AuthoredClient:
    """An `LLMClient`-shaped stand-in that serves replies an author wrote to disk.

    Built from a domain (its drafts are found beside its notebooks) or from an explicit
    title → reply mapping, which is what the tests use. A prompt naming a topic with no
    draft raises `LLMError`, so the runner reports that topic failed and carries on with
    the rest — the same way it treats a provider that refused one call.
    """

    def __init__(
        self,
        drafts: dict[str, dict] | None = None,
        *,
        model: str = DEFAULT_AUTHOR,
    ) -> None:
        self.config = _AuthorConfig(model=model)
        self.last_route: dict | None = None
        self.drafts = dict(drafts or {})
        self.asked: list[str] = []

    @classmethod
    def for_domain(
        cls,
        domain: Domain,
        *,
        subject: Subject | None = None,
        model: str = DEFAULT_AUTHOR,
    ) -> AuthoredClient:
        drafts: dict[str, dict] = {}
        for dom, topic, _ in backfill_targets(domain, subject=subject):
            draft = load_draft(topic_draft_path(dom, topic))
            if draft is not None:
                drafts[topic.title] = draft
        return cls(drafts, model=model)

    def complete(self, prompt: str, system: str | None = None) -> str:
        title = topic_title_in(prompt)
        self.asked.append(title)
        draft = self.drafts.get(title)
        if draft is None:
            raise LLMError(
                f"no authored draft for {title!r} — write the checks to "
                f"{DRAFT_SUFFIX!r} beside its notebook "
                "(python3 -m praxis.authored prompts <DOMAIN> prints what to answer)"
            )
        return json.dumps(draft)


def run_domain(
    domain: Domain,
    *,
    subject: Subject | None = None,
    limit: int | None = None,
    model: str = DEFAULT_AUTHOR,
) -> list[ConstructionResult]:
    """`backfill_domain` with the author's drafts standing in for the model.

    One attempt, deliberately: `_repair_prompt` handed back to a file gets the same
    file, so a second attempt re-runs every subprocess and reaches the same verdict.
    """
    return backfill_domain(
        domain,
        subject=subject,
        limit=limit,
        client=AuthoredClient.for_domain(domain, subject=subject, model=model),
        attempts=1,
        checks=True,
    )


# --- CLI --------------------------------------------------------------------


def _domain_for(name: str) -> Domain:
    domain = curriculum.domain_by_dir(name)
    if domain is None:
        raise CurriculumError(
            f"no seed domain '{name}' — its id is the directory under notebooks/, "
            f"e.g. {curriculum.DOMAINS[0].dir}"
        )
    return domain


def _prompts(domain: Domain, targets, out: Path | None) -> int:
    for dom, topic, subject in targets:
        nb = json.loads(topic_path(dom, topic).read_text())
        prompt = build_prompt(dom, topic, nb, subject=subject)
        if out is None:
            print(f"\n{'=' * 78}\n{topic.slug}\n{'=' * 78}\n{prompt}")
        else:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{topic.slug}.prompt.txt").write_text(prompt)
    if out is not None:
        print(f"{len(targets)} prompts written to {out}")
    return 0


def _status(domain: Domain, subject: Subject | None) -> int:
    rows = backfill_targets(domain, subject=subject)
    for dom, topic, _ in rows:
        draft = topic_draft_path(dom, topic)
        gate = checks_path(topic_path(dom, topic))
        mark = "✅" if is_gated(dom, topic) else ("draft" if draft.is_file() else "—")
        print(f"  {mark:<6} {topic.slug:<34} "
              f"draft={'yes' if draft.is_file() else 'no':<3} "
              f"gate={'yes' if gate.is_file() else 'no'}")
    print(f"\n{len(rows)} ungated ✅ topics in {domain.dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the gating backfill from authored drafts instead of a model"
    )
    parser.add_argument("command", choices=("prompts", "status", "run"))
    parser.add_argument("domain", metavar="DIR", help="a seed domain directory")
    parser.add_argument("--limit", type=int, default=None, help="cap the topics touched")
    parser.add_argument("--out", type=Path, default=None,
                        help="write prompts to this directory instead of stdout")
    parser.add_argument("--by", default=DEFAULT_AUTHOR,
                        help=f"what to record as 'generated_by' (default {DEFAULT_AUTHOR})")
    args = parser.parse_args(argv)

    try:
        domain = _domain_for(args.domain)
    except CurriculumError as exc:
        print(f"praxis.authored: {exc}", file=sys.stderr)
        return 2

    targets = backfill_targets(domain)
    if args.limit is not None:
        targets = targets[: max(0, args.limit)]

    if args.command == "prompts":
        return _prompts(domain, targets, args.out)
    if args.command == "status":
        return _status(domain, None)

    started = time.monotonic()
    results = run_domain(domain, limit=args.limit, model=args.by)
    failed = 0
    for result in results:
        print(result.summary())
        if not result.checks_ok:
            for failure in result.checks.failures or (result.checks.detail,):
                print(f"    - checks: {failure}", file=sys.stderr)
            failed += 1
    elapsed = time.monotonic() - started
    print(f"\n{len(results) - failed} of {len(results)} topics gated "
          f"in {elapsed:.1f}s ({elapsed / max(1, len(results)):.1f}s per notebook)")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
