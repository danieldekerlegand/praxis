#!/usr/bin/env python3
"""Knowledge checks — the questions a learner must pass to unlock the next section.

Praxis writes a tutorial in three passes: define (praxis/curriculum_gen.py), scaffold
(scaffold_notebooks.py), construct (praxis/construct.py). This is the fourth, and it is
what makes a tutorial *gated* rather than merely finished: for a notebook that already
passes the rubric, ask the model for the checks that prove a learner understood each
section, and store them beside the notebook as `<slug>.checks.json`.

Beside the notebook, not inside it, on purpose: the answer key must not be sitting in a
cell the learner is reading, the seed library's notebooks can gain checks without being
rewritten (and without moving off `gate_failures`), and the file is a self-describing
document anything can validate on its own.

Three kinds, all gradable without a human in the loop:

  choice  multiple choice — the option the learner picked, against the answer key
  code    write code that satisfies an assertion — the learner's code and the check's
          `test` are run together in a subprocess; a non-zero exit is a fail
  short   a written answer — graded by the configured model, with the learner's answer
          recorded verbatim on the outcome

The anti-fabrication rules mirror the constructor's, because the same failure mode is
available here (a check that looks like a check and asserts nothing):

  - **A set that fails `checkset_failures()` is never written.** In particular a `code`
    check must carry a reference `solution` that really does pass its own `test` — and
    that is verified by *running* it, not by reading it.
  - **An existing, valid set is skipped, not rewritten** (`force=True` overrides), so
    regenerating across a curriculum is idempotent and a batch is resumable.

Reached from `praxis.construct.construct_topic`, so filling a curriculum writes the
checks alongside the notebooks; `--no-checks` on that CLI turns it off.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curriculum import Domain, Subject, Topic, topic_path  # noqa: E402
from nbstatus import status_from_dict  # noqa: E402
from praxis.curriculum_gen import extract_json  # noqa: E402
from praxis.llm import LLMClient, LLMError  # noqa: E402
from praxis.rubric import RUBRIC_SECTIONS, notebook_text  # noqa: E402

CHECKS_VERSION = 1
CHECKS_SUFFIX = ".checks.json"

DEFAULT_ATTEMPTS = 3

# The rubric's sections, minus the two that teach nothing a learner can be tested on.
# Derived from RUBRIC_SECTIONS rather than retyped, so adding a section to the rubric
# adds it here too.
UNGATED_SECTIONS = ("Setup", "Resources")
GATED_SECTIONS = tuple(s for s in RUBRIC_SECTIONS if s not in UNGATED_SECTIONS)

KINDS = ("choice", "code", "short")

# What the model calls them when it isn't reading carefully.
KIND_ALIASES = {
    "choice": "choice", "multiple-choice": "choice", "multiple_choice": "choice",
    "multiplechoice": "choice", "mcq": "choice", "select": "choice",
    "code": "code", "coding": "code", "exercise": "code", "assertion": "code",
    "code-assertion": "code",
    "short": "short", "short-answer": "short", "short_answer": "short",
    "shortanswer": "short", "free-response": "short", "open": "short",
    "written": "short", "explain": "short",
}

MIN_OPTIONS = 3          # two options is a coin flip, not a check
MIN_PROMPT_CHARS = 25
MIN_EXPECTED_CHARS = 40  # a short-answer key too vague to grade against
CODE_TIMEOUT = 30        # a runaway reference solution must not hang a construction job

# How much of the notebook the model is shown when writing its checks.
NOTEBOOK_EXCERPT = 24000

SYSTEM_PROMPT = (
    "You are a demanding but fair examiner. You write knowledge checks that a learner "
    "can only pass by understanding the material — never by pattern-matching the "
    "wording of the text, and never by general knowledge they walked in with. Every "
    "answer key you give is one you have checked. You answer with JSON only."
)

SHORT_GRADER_SYSTEM_PROMPT = (
    "You grade a learner's written answer against a marking key. You reward "
    "understanding, not vocabulary: an answer in the learner's own words that covers "
    "the key points passes, and a fluent answer that misses or misstates them does "
    "not. You answer with JSON only."
)

CHECK_SCHEMA = """{
  "checks": [
    {"section": "1. What & Why", "kind": "choice",
     "prompt": "...", "options": ["...", "...", "..."], "answer": 0,
     "explanation": "why that option is right and the others are not"},
    {"section": "3. Key Concepts", "kind": "short",
     "prompt": "...", "expected": "the points a correct answer must make",
     "explanation": "..."},
    {"section": "5. Worked Examples", "kind": "code",
     "prompt": "...", "starter": "# your code here",
     "solution": "def add(a, b):\\n    return a + b",
     "test": "assert add(2, 3) == 5", "explanation": "..."}
  ]
}"""


class CheckError(RuntimeError):
    """A knowledge-check payload could not be read."""


# --- where a set lives ------------------------------------------------------


def checks_path(notebook: str | Path) -> Path:
    """The checks file for a notebook path: `<dir>/<slug>.checks.json`."""
    notebook = Path(notebook)
    return notebook.with_name(notebook.stem + CHECKS_SUFFIX)


def topic_checks_path(domain: Domain, topic: Topic) -> Path:
    return checks_path(topic_path(domain, topic))


def load_checks(path: str | Path) -> dict | None:
    """The stored set, or None when there isn't one (or it isn't readable JSON)."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_checks(path: str | Path, doc: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def checks_for_topic(domain: Domain, topic: Topic) -> dict | None:
    return load_checks(topic_checks_path(domain, topic))


def needs_checks(domain: Domain, topic: Topic) -> bool:
    """True when this topic has no usable set — i.e. generating one needs the model."""
    doc = checks_for_topic(domain, topic)
    return doc is None or bool(checkset_failures(doc, verify_code=False))


# --- normalizing what the model sent ---------------------------------------


def _key(text: object) -> str:
    """A heading squashed to letters and digits, so `## 1. What & Why` == `what and why`."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower().replace("&", "and"))


def canonical_section(value: object) -> str:
    """Map whatever the model called a section onto one of GATED_SECTIONS ("" if none)."""
    key = _key(value)
    if not key:
        return ""
    for section in GATED_SECTIONS:
        if _key(section) in key:
            return section
    return ""


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_check(raw: dict, index: int, *, slug: str) -> dict | None:
    """One check in canonical shape, or None when there is nothing there to keep.

    Lenient about what the model names things, strict about what would make a check
    ungradable — that part is `check_failures`, so every complaint is a sentence the
    repair prompt can hand back.
    """
    prompt = _text(raw.get("prompt") or raw.get("question"))
    if not prompt:
        return None
    kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
    check = {
        "id": f"{slug}-{index:02d}",
        "section": canonical_section(raw.get("section") or raw.get("heading")),
        "kind": KIND_ALIASES.get(kind, kind),
        "prompt": prompt,
        "explanation": _text(raw.get("explanation") or raw.get("rationale")),
    }
    if check["kind"] == "choice":
        options = raw.get("options") or raw.get("choices") or []
        check["options"] = [_text(o) for o in options] if isinstance(options, list) else []
        check["answer"] = _answer_index(raw.get("answer"), check["options"])
    elif check["kind"] == "code":
        check["starter"] = _text(raw.get("starter") or raw.get("stub"))
        check["solution"] = _text(raw.get("solution") or raw.get("reference"))
        check["test"] = _text(raw.get("test") or raw.get("assertions"))
    elif check["kind"] == "short":
        check["expected"] = _text(raw.get("expected") or raw.get("key") or raw.get("answer"))
    return check


def _answer_index(value: object, options: list[str]) -> int:
    """The answer key as an index. Accepts an index, a letter, or the option's text."""
    if isinstance(value, bool):
        return -1
    if isinstance(value, int):
        return value
    text = _text(value)
    if not text:
        return -1
    if text.isdigit():
        return int(text)
    if len(text) == 1 and text.upper().isalpha():
        return ord(text.upper()) - ord("A")
    for i, option in enumerate(options):
        if option.strip().lower() == text.lower():
            return i
    return -1


def checks_from_reply(data: dict, topic: Topic) -> list[dict]:
    """Normalize the model's check list. Raises only when there is nothing usable."""
    raw = data.get("checks")
    if not isinstance(raw, list) or not raw:
        raise CheckError("the model returned no checks")
    checks: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CheckError(f"check {len(checks) + 1} is not an object")
        check = normalize_check(item, len(checks) + 1, slug=topic.slug)
        if check is not None:
            checks.append(check)
    if not checks:
        raise CheckError("every check the model returned was empty")
    return checks


def build_checkset(
    domain: Domain, topic: Topic, checks: list[dict], *, model: str = ""
) -> dict:
    """Assemble the stored document — the whole of the defined format."""
    return {
        "version": CHECKS_VERSION,
        "slug": topic.slug,
        "title": topic.title,
        "domain": domain.dir,
        "runnable": topic.runnable,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_by": model,
        "sections": list(GATED_SECTIONS),
        "checks": checks,
    }


# --- the grader over a set --------------------------------------------------


def run_code_check(check: dict, submission: str, *, timeout: int = CODE_TIMEOUT) -> tuple[bool, str]:
    """Run a submission against a `code` check's assertions. (passed, detail).

    In a subprocess, not this one: the code is written by a model or by a learner, and
    neither should be able to hang a construction job or reach into the caller's
    namespace. A non-zero exit — an AssertionError like any other exception — is a fail.
    """
    source = f"{submission}\n\n# --- the check ---\n{check.get('test', '')}\n"
    try:
        compile(source, "<check>", "exec")
    except SyntaxError as exc:
        return False, f"that is not valid Python: {exc.msg} (line {exc.lineno})"
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-"], input=source, text=True,
            capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"the check timed out after {timeout}s"
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip()[-500:] or "the assertions passed"
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
    return False, "\n".join(tail) or "the assertions failed"


def check_failures(check: dict, *, runnable: bool = True, verify_code: bool = True) -> list[str]:
    """What is wrong with one check. Empty list == a learner could be graded on it."""
    where = check.get("id") or check.get("prompt", "")[:40]
    failures = []

    if len(check.get("prompt", "")) < MIN_PROMPT_CHARS:
        failures.append(f"{where}: the question is too short to answer meaningfully")
    if not check.get("section"):
        failures.append(
            f"{where}: 'section' must name one of the rubric sections: "
            f"{', '.join(GATED_SECTIONS)}"
        )

    kind = check.get("kind")
    if kind not in KINDS:
        failures.append(f"{where}: unknown kind {kind!r} — use one of {', '.join(KINDS)}")
        return failures

    if kind == "choice":
        options = check.get("options") or []
        if len(options) < MIN_OPTIONS:
            failures.append(
                f"{where}: a multiple-choice check needs >= {MIN_OPTIONS} options "
                f"(has {len(options)})"
            )
        if any(not o for o in options):
            failures.append(f"{where}: every option must have text")
        if len({o.strip().lower() for o in options if o}) != len([o for o in options if o]):
            failures.append(f"{where}: two options are the same")
        if not 0 <= check.get("answer", -1) < len(options):
            failures.append(
                f"{where}: 'answer' must be the 0-based index of the correct option "
                f"(got {check.get('answer')!r} for {len(options)} options)"
            )

    elif kind == "code":
        if not runnable:
            failures.append(
                f"{where}: this topic is not Python-runnable, so it cannot carry a "
                "'code' check — ask it as 'choice' or 'short' instead"
            )
        if "assert" not in check.get("test", ""):
            failures.append(
                f"{where}: 'test' must actually assert something — a check that asserts "
                "nothing passes any answer"
            )
        if not check.get("solution"):
            failures.append(
                f"{where}: 'solution' must hold a reference answer, so the check can be "
                "proved gradable before a learner ever sees it"
            )
        elif verify_code and runnable and "assert" in check.get("test", ""):
            ok, detail = run_code_check(check, check["solution"])
            if not ok:
                failures.append(
                    f"{where}: your own reference solution does not pass your test: {detail}"
                )

    elif kind == "short" and len(check.get("expected", "")) < MIN_EXPECTED_CHARS:
        failures.append(
            f"{where}: 'expected' must spell out the points a correct answer has to "
            "make, in enough detail to grade against"
        )

    return failures


def checkset_failures(doc: dict, *, verify_code: bool = True) -> list[str]:
    """The bar a set must clear before it may be written beside a notebook.

    `verify_code=False` skips running each `code` check's reference solution — the
    structural half, cheap enough to run on every load. Generation always verifies.
    """
    if not isinstance(doc, dict):
        return ["the checks file does not hold a JSON object"]
    if doc.get("version") != CHECKS_VERSION:
        return [f"unsupported checks version {doc.get('version')!r}"]

    checks = doc.get("checks")
    if not isinstance(checks, list) or not checks:
        return ["the set holds no checks"]

    runnable = bool(doc.get("runnable", True))
    failures = []
    for check in checks:
        if not isinstance(check, dict):
            failures.append("a check is not an object")
            continue
        failures += check_failures(check, runnable=runnable, verify_code=verify_code)

    covered = {c.get("section") for c in checks if isinstance(c, dict)}
    missing = [s for s in GATED_SECTIONS if s not in covered]
    if missing:
        failures.append(
            f"every rubric section needs at least one check — nothing tests: {missing}"
        )

    kinds = {c.get("kind") for c in checks if isinstance(c, dict)}
    wanted = ("choice", "short") + (("code",) if runnable else ())
    absent = [k for k in wanted if k not in kinds]
    if absent:
        failures.append(
            f"the set needs a mix of kinds — it has no {', '.join(absent)} check"
            f"{'s' if len(absent) > 1 else ''}"
        )
    if not runnable and "code" in kinds:
        failures.append("this topic is not Python-runnable, so it can carry no code checks")

    return failures


# --- grading one answer -----------------------------------------------------


@dataclass(frozen=True)
class CheckOutcome:
    """One graded answer. The learner's answer is kept verbatim — that is the record."""

    check_id: str
    kind: str
    section: str
    passed: bool
    answer: str
    detail: str = ""
    graded_by: str = "auto"   # "auto" for the two auto-graded kinds, else the model
    graded: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "kind": self.kind,
            "section": self.section,
            "passed": self.passed,
            "answer": self.answer,
            "detail": self.detail,
            "graded_by": self.graded_by,
            "graded": self.graded,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _outcome(check: dict, answer: object, passed: bool, detail: str, by: str) -> CheckOutcome:
    return CheckOutcome(
        check_id=str(check.get("id", "")),
        kind=str(check.get("kind", "")),
        section=str(check.get("section", "")),
        passed=passed,
        answer="" if answer is None else str(answer),
        detail=detail,
        graded_by=by,
        graded=_now(),
    )


def _grade_choice(check: dict, answer: object) -> tuple[bool, str]:
    picked = _answer_index(answer, check.get("options") or [])
    if picked < 0:
        return False, "that is not one of the options"
    passed = picked == check.get("answer")
    return passed, check.get("explanation", "") or (
        "correct" if passed else "not the answer we were looking for"
    )


def _grade_short(check: dict, answer: str, client: LLMClient) -> tuple[bool, str]:
    """Ask the model. Anything it doesn't answer cleanly is a failure, never a pass."""
    prompt = (
        "Grade this learner's answer.\n\n"
        f"<question>\n{check.get('prompt', '')}\n</question>\n\n"
        f"<marking-key>\n{check.get('expected', '')}\n</marking-key>\n\n"
        f"<learner-answer>\n{answer}\n</learner-answer>\n\n"
        'Return JSON only: {"passed": true|false, "feedback": "one or two sentences '
        'addressed to the learner, naming what they got right or what they missed"}\n'
        "Pass only an answer that shows the understanding the key describes. An empty, "
        "evasive or off-topic answer fails."
    )
    reply = client.complete(prompt, system=SHORT_GRADER_SYSTEM_PROMPT)
    try:
        data = extract_json(reply)
    except ValueError as exc:  # CurriculumError — a grader that won't answer cleanly
        raise LLMError(f"the grader's reply was not JSON: {exc}") from exc
    feedback = _text(data.get("feedback") or data.get("detail"))
    return bool(data.get("passed")), feedback or "graded"


def grade(check: dict, answer: object, *, client: LLMClient | None = None) -> CheckOutcome:
    """Grade one answer. Auto for `choice`/`code`; `short` needs a client, and says so."""
    kind = check.get("kind")
    if kind == "choice":
        passed, detail = _grade_choice(check, answer)
        return _outcome(check, answer, passed, detail, "auto")
    if kind == "code":
        passed, detail = run_code_check(check, str(answer or ""))
        return _outcome(check, answer, passed, detail, "auto")
    if kind == "short":
        if client is None:
            raise CheckError("a short-answer check is graded by the model — no client given")
        passed, detail = _grade_short(check, str(answer or ""), client)
        return _outcome(check, answer, passed, detail,
                        getattr(client.config, "model", "") or "model")
    raise CheckError(f"cannot grade a check of kind {kind!r}")


def checks_by_section(doc: dict) -> dict[str, list[dict]]:
    """The set indexed the way the gate reads it: section -> its checks, in order."""
    by_section: dict[str, list[dict]] = {s: [] for s in GATED_SECTIONS}
    for check in doc.get("checks", []) if isinstance(doc, dict) else []:
        if isinstance(check, dict) and check.get("section") in by_section:
            by_section[check["section"]].append(check)
    return by_section


# --- asking the model for a set ---------------------------------------------


def build_prompt(domain: Domain, topic: Topic, nb: dict, *, subject: Subject | None = None) -> str:
    """The instruction half of the call. The notebook is quoted, never summarized."""
    context = [f"Module: {domain.title}"]
    if subject:
        context.append(f"Curriculum: {subject.title}")
        if subject.goal:
            context.append(f"The learner's goal: {subject.goal}")
    kinds = (
        "`choice`, `short` and `code`" if topic.runnable else "`choice` and `short`"
    )
    code_rule = (
        "- `code` checks: `prompt` says what to write, `starter` is the stub the learner "
        "begins from, `solution` is a correct reference implementation, and `test` is "
        "Python that `assert`s the solution behaves correctly. `solution` + `test` are "
        "run together before this set is accepted, so the test must pass against your "
        "own solution, use only the standard library, need no network, and finish fast."
        if topic.runnable else
        "- Write NO `code` checks: this topic is not Python-runnable, so there is no "
        "code a learner could run to be graded on."
    )
    return f"""Write the knowledge checks that gate this tutorial, section by section.

<topic>
{topic.title}
</topic>

<context>
{chr(10).join(context)}
</context>

<notebook>
{notebook_text(nb)[:NOTEBOOK_EXCERPT]}
</notebook>

Return JSON matching exactly this schema, and nothing else:

{CHECK_SCHEMA}

Rules:
- Write AT LEAST ONE check for each of these sections, using these exact names in
  "section": {', '.join(GATED_SECTIONS)}.
- Use a mix of kinds suited to the material — {kinds} — and use each of them at least
  once across the set.
- A learner must only be able to pass by understanding the section. No questions
  answerable by matching the wording of the notebook, no trivia about names or version
  numbers, and no "which of these is not..." padding.
- `choice` checks: at least {MIN_OPTIONS} options, every distractor a mistake somebody
  would really make, and "answer" the 0-based index of the correct one.
{code_rule}
- `short` checks: `expected` is the marking key — the points an answer must make for
  another grader to mark it correct. Be specific; it is graded against, not displayed.
- Every check carries an `explanation` the learner sees after answering.
- No prose outside the JSON."""


def _repair_prompt(prompt: str, previous: list[dict], failures: list[str]) -> str:
    """Hand the model its own set and the grader's complaints, ask for a full redo."""
    draft = json.dumps({"checks": previous}, indent=1)[:16000]
    return (
        f"{prompt}\n\n"
        "Your previous set FAILED validation:\n\n"
        + "\n".join(f"- {f}" for f in failures)
        + "\n\nHere is that set:\n\n<draft>\n"
        + draft
        + "\n</draft>\n\nReturn the COMPLETE corrected set as JSON in the same schema — "
        "every check, not a patch, and fix every failure listed above."
    )


@dataclass(frozen=True)
class ChecksResult:
    """What one generation attempt did — the shape construct.py and the UI report."""

    path: Path
    slug: str
    title: str
    status: str  # "generated" | "skipped" | "failed"
    attempts: int = 0
    count: int = 0
    failures: tuple[str, ...] = ()
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("generated", "skipped")

    def summary(self) -> str:
        mark = {"generated": "✅", "skipped": "•", "failed": "⚠️"}[self.status]
        tail = (f" — {self.detail or '; '.join(self.failures)}"
                if self.status == "failed" else "")
        return f"{mark} {self.title} checks ({self.status}, {self.count}){tail}"


def generate_checks(
    domain: Domain,
    topic: Topic,
    *,
    notebook: dict | None = None,
    client: LLMClient | None = None,
    subject: Subject | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    force: bool = False,
    write: bool = True,
) -> ChecksResult:
    """Write the checks for one topic. Never writes a set that isn't gradable.

    Returns a ChecksResult rather than raising, for the same reason construct_topic
    does: one topic the model keeps getting wrong must not strand a whole curriculum.
    """
    path = topic_checks_path(domain, topic)
    existing = load_checks(path)
    if existing is not None and not force and not checkset_failures(existing, verify_code=False):
        return ChecksResult(
            path=path, slug=topic.slug, title=topic.title, status="skipped",
            count=len(existing.get("checks", [])), detail="already generated",
        )

    nb = notebook if notebook is not None else _read_notebook(topic_path(domain, topic))
    if nb is None:
        return ChecksResult(
            path=path, slug=topic.slug, title=topic.title, status="failed",
            detail=f"there is no notebook at {topic_path(domain, topic)} to write checks for",
        )
    status = status_from_dict(nb)[0]
    if status != "complete":
        return ChecksResult(
            path=path, slug=topic.slug, title=topic.title, status="failed",
            detail=(f"the notebook is {status!r}, not 'complete' — construct it before "
                    "writing checks against it"),
        )

    client = client or LLMClient()
    prompt = build_prompt(domain, topic, nb, subject=subject)
    failures: list[str] = ["no attempt was made"]
    detail = ""
    checks: list[dict] | None = None
    used = 0

    for used in range(1, max(1, attempts) + 1):
        ask = prompt if checks is None else _repair_prompt(prompt, checks, failures)
        try:
            reply = client.complete(ask, system=SYSTEM_PROMPT)
            checks = checks_from_reply(extract_json(reply), topic)
        except (LLMError, CheckError, ValueError) as exc:
            failures, detail, checks = [str(exc)], str(exc), None
            continue
        doc = build_checkset(domain, topic, checks,
                             model=getattr(client.config, "model", ""))
        failures = checkset_failures(doc)
        if not failures:
            if write:
                save_checks(path, doc)
            return ChecksResult(
                path=path, slug=topic.slug, title=topic.title, status="generated",
                attempts=used, count=len(checks),
            )

    return ChecksResult(
        path=path, slug=topic.slug, title=topic.title, status="failed",
        attempts=used, count=len(checks or []), failures=tuple(failures), detail=detail,
    )


def _read_notebook(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
