"""Drive a generated tasklist through Chief's headless entry point, at zero API cost.

`praxis/tasklist.py` cuts the live library into units and writes the JSON Chief runs.
This is the other half: it **starts** that run with nobody in front of the terminal and
reads its result back. It constructs nothing and gates nothing either — the tasklist's
stories run `python3 -m praxis.backfill <dir>` / `python3 -m praxis.construct --subject
<slug>`, which is praxis's one batch loop, so a headless run's artifacts are the ones an
in-app run would have written, for the reason that it is the same code path.

Two contracts from the `chief` repo are consumed here, both by **reference** — a
documented CLI shape and two environment variables, never an import, a submodule or a
path into another checkout:

- **`chief run --headless`** (`chief:80-headless-programmatic-invocation`,
  `docs/guides/headless-invocation.md` over there). Headless adds *machine-readable*
  lines to the same engine: `chief: run-id=…` before the scheduler loop, and after it
  `chief: outcome=` / `chief: exit=` / `chief: summary={…}` — the whole run as one JSON
  object — plus an exit code that names the outcome. `parse_run` reads exactly those
  lines and the process's exit status. **The human summary block is never parsed**: it
  is prose written for a person, it is free to change, and a host that scraped it would
  report an outcome the engine never claimed. `records()` keeps `chief: <key>=<value>`
  lines and drops every other byte on the stream, which is what makes that a property
  of the code rather than an intention.
- **`chief run --local`** (`chief:82-local-inference-cost-avoidance-preset`,
  `docs/guides/local-inference-preset.md`). The preset resolves to OpenCode pointed at a
  local / self-hosted OpenAI-compatible server, so a run's tokens cost nothing. It is
  the *routing switch* and nothing else: `LocalPreset` supplies the two variables it
  requires and never a `--provider`/`--model` pair, which chief refuses next to
  `--local` rather than silently deciding who pays.

**The tradeoff is deliberate and is stated where it is taken.** A model small enough to
serve from one machine writes materially worse code than a frontier model. That is the
right trade *here* and would be the wrong one in the app: this band's value is in the
volume — 221 ungated seed notebooks — and every artifact is graded by the shipped
write-path gates (`construction_failures`, `checkset_failures` with `verify_code=True`,
`nbgrader validate`) before it lands. A weaker model therefore costs **iterations**, not
correctness: what it cannot get past the grader is not written, and the next pass picks
the topic up again. `praxis/coverage.py` counts what actually landed.

Nothing here is a fallback. `LocalPreset.failures()` is chief's own refusal made one
process earlier — an unconfigured preset stops the batch before it spawns instead of
quietly billing a paid provider for a run that was asked to be free.

Resumability is not implemented here either, and that is the whole safety argument for
retrying an unattended run: an already-✅ notebook is skipped by `construct_topic` and an
already-gated topic is not selected by `backfill.is_gated`, so re-running a tasklist that
came back `verify-failed`, `paused` or `failed` is a *resumed pass over the remainder* —
it cannot clobber a good notebook or a passing checkset. `unfinished()` is that list.

`docs/reference/chief-powered-construction.md` is the prose contract.

CLI:
    python3 -m praxis.headless                      # the plan: preset, units, exact argv
    python3 -m praxis.headless run gate-01-…        # drive it
    python3 -m praxis.headless run --jd <jd-id>     # the subjects accepted off a posting
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praxis import tasklist as tasklists  # noqa: E402
from praxis.tasklist import TasklistError, Unit  # noqa: E402

# --- chief's wire vocabulary, consumed by reference -------------------------
# One block, the way praxis/llm.py holds agora's. Every name below is a line chief
# prints or a variable it reads; none of it is imported from that repo.

RECORD_PREFIX = "chief: "

# The lines announced before the scheduler loop, and the ones printed after it.
RUN_KEYS = ("run-id", "run-file", "events", "state")
RESULT_KEYS = ("outcome", "exit", "summary")

# `chief run --headless`'s exit codes. The table is chief's; the name for `2` is
# praxis's, because chief's own table leaves that row unnamed — it is the one code that
# means the run never started, which is how an unconfigured preset comes back.
EXIT_OUTCOMES = {
    0: "merged",
    2: "config-error",
    3: "no-work",
    4: "verify-failed",
    5: "conflict",
    6: "failed",
    7: "paused",
    129: "signalled",
    130: "signalled",
    143: "signalled",
}

# Codes that are reported *instead of* a run: nothing was scheduled, so there is no
# run-id line to insist on.
NO_RUN_EXITS = frozenset({2, 129, 130, 143})

# A tasklist that reached one of these is finished. Everything else is remainder, and
# re-running it is a resumed pass (see `unfinished`).
DONE_OUTCOMES = frozenset({"merged", "complete-unmerged"})

PRESET = "local"
PRESET_ENDPOINT = "CHIEF_LOCAL_ENDPOINT"
PRESET_MODEL = "CHIEF_LOCAL_MODEL"
PRESET_ENDPOINT_ENV = "CHIEF_LOCAL_ENDPOINT_ENV"
PRESET_API_KEY = "CHIEF_LOCAL_API_KEY"
PRESET_API_KEY_ENV = "CHIEF_LOCAL_API_KEY_ENV"

# Where the driver is. An env override first so a host (or a test) can name a chief that
# is not on PATH — the same shape `praxis.checks` uses to resolve nbgrader.
CHIEF_BIN_ENV = "PRAXIS_CHIEF"


class HeadlessError(RuntimeError):
    """A run that could not be started, or a stream that did not carry the contract."""


# --- the routing switch -----------------------------------------------------


@dataclass(frozen=True)
class LocalPreset:
    """`chief run --local`'s two required values, plus its documented overrides.

    A preset, not a provider: what reaches the engine is `CHIEF_PRESET=local` and the
    endpoint/model pair it resolves to `opencode` + that model with. Praxis adds no
    default host — a hard-coded endpoint would be a machine this code cannot see.
    """

    endpoint: str = ""
    model: str = ""
    endpoint_env: str = ""
    api_key: str = ""
    api_key_env: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LocalPreset:
        source = os.environ if env is None else env
        return cls(
            endpoint=(source.get(PRESET_ENDPOINT) or "").strip(),
            model=(source.get(PRESET_MODEL) or "").strip(),
            endpoint_env=(source.get(PRESET_ENDPOINT_ENV) or "").strip(),
            api_key=(source.get(PRESET_API_KEY) or "").strip(),
            api_key_env=(source.get(PRESET_API_KEY_ENV) or "").strip(),
        )

    def failures(self) -> list[str]:
        """Why this preset cannot route a run — chief's refusal, one process earlier.

        Chief errors rather than falling back to a paid provider; so does this, and
        before anything is spawned, so an unattended batch asked for zero cost cannot
        discover it was billed by reading a log afterwards.
        """
        out = []
        if not self.endpoint:
            out.append(
                f"{PRESET_ENDPOINT} is not set — the base URL of your local "
                f"OpenAI-compatible server (e.g. http://127.0.0.1:11434/v1)"
            )
        if not self.model:
            out.append(
                f"{PRESET_MODEL} is not set — the model id to ask that server for "
                f"(list them with: chief models opencode)"
            )
        if out:
            out.append(
                "refusing to run without the preset configured: falling back to a paid "
                "provider is the one failure mode zero-cost construction must not have"
            )
        return out

    def environ(self) -> dict[str, str]:
        """What the child needs in its environment. Never a provider or a model flag."""
        env = {"CHIEF_PRESET": PRESET,
               PRESET_ENDPOINT: self.endpoint,
               PRESET_MODEL: self.model}
        for name, value in ((PRESET_ENDPOINT_ENV, self.endpoint_env),
                            (PRESET_API_KEY, self.api_key),
                            (PRESET_API_KEY_ENV, self.api_key_env)):
            if value:
                env[name] = value
        return env

    def describe(self) -> str:
        return f"{PRESET} → opencode · {self.model or '?'} @ {self.endpoint or '?'}"


# --- the outcome ------------------------------------------------------------


@dataclass(frozen=True)
class TasklistOutcome:
    """One tasklist's row of `chief: summary=`, as chief reported it."""

    name: str
    outcome: str
    state: str = ""
    status: str = ""
    attempts: int = 0
    log: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in DONE_OUTCOMES

    def summary(self) -> str:
        return f"{self.name:<34} {self.outcome:<18} {self.status or self.state}"


@dataclass(frozen=True)
class HeadlessRun:
    """A finished headless run, read from the machine-readable records only."""

    run_id: str
    outcome: str
    exit_code: int
    tasklists: tuple[TasklistOutcome, ...] = ()
    run_file: str = ""
    events: str = ""
    state: str = ""
    dry_run: bool = False
    summary: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def named(self, name: str) -> TasklistOutcome | None:
        return next((t for t in self.tasklists if t.name == name), None)

    def report(self) -> str:
        lines = [f"run-id  {self.run_id or '(no run)'}",
                 f"outcome {self.outcome} (exit {self.exit_code})"]
        lines += [f"  {t.summary()}" for t in self.tasklists]
        if self.events:
            lines.append(f"events  {self.events}")
        return "\n".join(lines)


def records(stdout: str) -> dict[str, str]:
    """The `chief: <key>=<value>` lines, last one per key. Everything else is dropped.

    This is the anti-scraping boundary: the human schedule, the per-tasklist progress
    lines and the final summary block all share this stream, and none of them survive
    this function. A key printed twice (a run-id line then a summary that repeats it)
    keeps the later value, which is the one printed after the work happened.
    """
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith(RECORD_PREFIX):
            continue
        key, sep, value = line[len(RECORD_PREFIX):].partition("=")
        if sep and key.strip():
            out[key.strip()] = value.strip()
    return out


def _rows(summary: dict) -> tuple[TasklistOutcome, ...]:
    rows = summary.get("tasklists")
    if not isinstance(rows, list):
        return ()
    out = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("name") or "").strip():
            continue
        attempts = row.get("attempts")
        out.append(TasklistOutcome(
            name=str(row["name"]).strip(),
            outcome=str(row.get("outcome") or "").strip(),
            state=str(row.get("state") or "").strip(),
            status=str(row.get("status") or "").strip(),
            attempts=attempts if isinstance(attempts, int) else 0,
            log=str(row.get("log") or "").strip(),
        ))
    return tuple(out)


def parse_run(stdout: str, returncode: int) -> HeadlessRun:
    """Read a headless run's result out of its stream, or refuse to guess at one.

    The outcome comes from `chief: summary=`'s JSON, falling back to the `chief:
    outcome=` line and then to the exit-code table — three machine-readable sources, in
    order, and no fourth. If the stream carries no run-id and the exit code is not one
    that means "the run never started", this raises rather than reporting a made-up
    result: a host that cannot see the contract has not observed a run.
    """
    rec = records(stdout)
    summary: dict = {}
    raw = rec.get("summary")
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise HeadlessError(f"chief: summary= is not JSON ({exc}); the headless "
                                f"contract was not honoured") from exc
        if isinstance(parsed, dict):
            summary = parsed

    declared = rec.get("exit")
    if declared is not None and declared.strip().lstrip("-").isdigit():
        if int(declared) != returncode:
            raise HeadlessError(
                f"chief reported 'exit={declared}' but the process exited {returncode} — "
                f"refusing to report an outcome from a stream that disagrees with itself"
            )

    run_id = str(summary.get("runId") or rec.get("run-id") or "").strip()
    outcome = str(summary.get("outcome") or rec.get("outcome") or "").strip()
    if not outcome:
        outcome = EXIT_OUTCOMES.get(returncode, "failed")

    if not run_id and returncode not in NO_RUN_EXITS:
        raise HeadlessError(
            f"no 'chief: run-id=' line on the stream and the run exited {returncode} — "
            f"either --headless was not passed or the driver is not chief; refusing to "
            f"read an outcome out of human output"
        )
    return HeadlessRun(
        run_id=run_id,
        outcome=outcome,
        exit_code=returncode,
        tasklists=_rows(summary),
        run_file=rec.get("run-file", ""),
        events=rec.get("events", ""),
        state=str(summary.get("state") or rec.get("state") or ""),
        dry_run=rec.get("dry-run") == "1",
        summary=summary,
    )


def unfinished(run: HeadlessRun) -> list[str]:
    """The tasklists that did not finish — safe to re-run, and that is the point.

    A retry is a resumed pass: skip-if-✅ (`construct_topic`) and skip-if-gated
    (`backfill.is_gated`) mean the next run selects only what is still missing, so
    nothing the failed run *did* land is rewritten.
    """
    return [t.name for t in run.tasklists if not t.ok]


# --- the invocation ---------------------------------------------------------


def chief_executable(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    override = (source.get(CHIEF_BIN_ENV) or "").strip()
    if override:
        return override
    found = shutil.which("chief")
    if not found:
        raise HeadlessError(
            "chief is not on PATH — install it, or point "
            f"{CHIEF_BIN_ENV} at the `chief` executable to drive a run from here"
        )
    return found


def routing(preset: LocalPreset | None = None,
            env: dict[str, str] | None = None) -> LocalPreset:
    """The preset a run will be routed through, or the refusal to start one at all.

    Checked before anything is written and before anything is spawned, so a batch asked
    for zero cost cannot get as far as a paid provider — or leave a half-generated
    tasklist behind on its way to finding out.
    """
    resolved = preset if preset is not None else LocalPreset.from_env(env)
    failures = resolved.failures()
    if failures:
        raise HeadlessError("the local-inference preset is not configured: "
                            + "; ".join(failures))
    return resolved


def command(
    names: Sequence[str],
    *,
    parallel: int | None = None,
    dry_run: bool = False,
    no_merge: bool = False,
    chief: str = "chief",
) -> list[str]:
    """The argv of the run: `chief run --headless --preset=local [-p N] [names…]`.

    No `--provider` and no `--model`. The preset *is* the provider choice, and chief
    refuses the pair next to it rather than guessing which one is paying — so the way
    to change the routing is the two environment variables, not a flag here.
    """
    argv = [chief, "run", "--headless", f"--preset={PRESET}"]
    if parallel is not None:
        argv += ["-p", str(int(parallel))]
    if no_merge:
        argv.append("--no-merge")
    if dry_run:
        argv.append("--dry-run")
    return argv + list(names)


def run_tasklists(
    names: Sequence[str],
    *,
    preset: LocalPreset | None = None,
    parallel: int | None = None,
    dry_run: bool = False,
    no_merge: bool = False,
    root: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    runner=subprocess.run,
) -> HeadlessRun:
    """Start one headless, locally-routed Chief run and read its outcome back.

    The stream is captured rather than inherited, so the machine-readable lines can be
    parsed; a caller that also wants a human to watch can print what comes back.
    """
    if not names:
        raise HeadlessError("name at least one tasklist to run "
                            "(`python3 -m praxis.tasklist` lists the units)")
    resolved = routing(preset, env)
    repo = Path(root) if root is not None else tasklists.repo_root()
    child = dict(os.environ if env is None else env)
    child.update(resolved.environ())
    child["CHIEF_PROJECT"] = str(repo)

    argv = command(names, parallel=parallel, dry_run=dry_run, no_merge=no_merge,
                   chief=chief_executable(child))
    try:
        proc = runner(argv, cwd=str(repo), env=child, capture_output=True, text=True,
                      check=False, timeout=timeout)
    except FileNotFoundError as exc:
        raise HeadlessError(f"could not start the driver: {' '.join(argv)} ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise HeadlessError(
            f"the headless run did not finish within {timeout}s; it is still recorded in "
            f"chief's run registry (chief ps) — re-running it later is a resumed pass"
        ) from exc

    stdout = proc.stdout or ""
    try:
        return parse_run(stdout, proc.returncode)
    except HeadlessError as exc:
        detail = (proc.stderr or "").strip().splitlines()
        raise HeadlessError(f"{exc}" + (f" | stderr: {detail[-1]}" if detail else "")) from exc


# --- the praxis units, driven ----------------------------------------------


def ensure_tasklist(unit: Unit, *, root: Path | None = None) -> Path:
    """The tasklist Chief will run, generated from the live library if it is not there.

    An existing one is left alone — its `passes` flags are chief's bookkeeping, and
    `write_tasklist` refuses to overwrite an active or retired tasklist for that reason.
    """
    path = tasklists.tasklist_dir(root) / f"{unit.name}.json"
    if path.is_file():
        return path
    return tasklists.write_tasklist(unit, root=root)


def units_for(names: Sequence[str], jd_id: str = "") -> list[Unit]:
    """Resolve what to drive: named units, plus the subjects accepted off a posting."""
    units = [tasklists.unit_for(name) for name in names]
    if jd_id:
        units += tasklists.accepted_units(jd_id)
    if not units:
        raise TasklistError("name a unit to drive, or pass --jd <id> "
                            "(`python3 -m praxis.tasklist` lists the units)")
    return units


def run_units(
    units: Iterable[Unit],
    *,
    root: Path | None = None,
    preset: LocalPreset | None = None,
    env: dict[str, str] | None = None,
    **kwargs,
) -> HeadlessRun:
    """Write what is missing, then drive the lot as one run.

    The routing is resolved **first**: an unconfigured preset refuses here, before a
    tasklist is generated, so a run that cannot start leaves nothing on disk.
    """
    resolved = routing(preset, env)
    names = []
    for unit in units:
        ensure_tasklist(unit, root=root)
        names.append(unit.name)
    return run_tasklists(names, root=root, preset=resolved, env=env, **kwargs)


# --- CLI --------------------------------------------------------------------


def plan(units: Sequence[Unit], preset: LocalPreset, *, parallel: int | None) -> str:
    """What a run would do, without doing any of it — the dry half, and no spawn."""
    lines = [f"preset  {preset.describe()}"]
    for failure in preset.failures():
        lines.append(f"  ! {failure}")
    lines.append("")
    lines += [u.summary() for u in units]
    lines.append("")
    lines.append(f"{sum(len(u.pending) for u in units)} topics pending across "
                 f"{len(units)} units")
    lines.append("argv    " + " ".join(
        command([u.name for u in units], parallel=parallel, chief="chief")))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415  (a CLI convenience, not an import-time dependency)

    parser = argparse.ArgumentParser(
        description="Drive praxis's construction/gating tasklists through Chief, "
                    "headlessly, on local inference"
    )
    sub = parser.add_subparsers(dest="cmd")
    for name, help_text in (("plan", "what a run would drive — no spawn, no model call"),
                            ("run", "start one headless run and report its outcome")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("names", nargs="*", help="unit names (default: every unit with work)")
        cmd.add_argument("--jd", default="", help="the subjects accepted off a posting")
        cmd.add_argument("-p", "--parallel", type=int, default=None)
        if name == "run":
            cmd.add_argument("--dry-run", action="store_true",
                             help="chief schedules but runs nothing")
            cmd.add_argument("--no-merge", action="store_true")
    args = parser.parse_args(argv)

    preset = LocalPreset.from_env()
    try:
        names = getattr(args, "names", [])
        jd_id = getattr(args, "jd", "")
        if names or jd_id:
            units = units_for(names, jd_id)
        else:
            units = [u for u in tasklists.library_units(subjects=True) if u.pending]
            if not units:
                print("nothing to drive: every unit is complete and gated")
                return 0
        if args.cmd != "run":
            print(plan(units, preset, parallel=getattr(args, "parallel", None)))
            return 0
        run = run_units(units, preset=preset, parallel=args.parallel,
                        dry_run=args.dry_run, no_merge=args.no_merge)
    except (TasklistError, HeadlessError) as exc:
        print(f"praxis.headless: {exc}", file=sys.stderr)
        return 2

    print(run.report())
    remainder = unfinished(run)
    if remainder:
        print(f"\nre-run the remainder — a retry is a resumed pass, not a rewrite:\n"
              f"  python3 -m praxis.headless run {' '.join(remainder)}")
    return run.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
