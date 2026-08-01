#!/usr/bin/env bash
# Fill the Praxis seed tutorial notebooks with ralphy (michaelshimeles/ralphy).
#
# Each tasklist is a ralphy JSON file (tasks.json) with one task per notebook that
# isn't complete yet. ralphy fills the notebook to docs/notebook-rubric.md and the
# gate in tests/test_notebooks.py, auto-committing per task. Domains are independent
# (every notebook stands alone), so any order — or --parallel — is fine.
#
# Usage:
#   ./ralph/run.sh                 # run all domains in order
#   ./ralph/run.sh 8               # run only domain 8 (architectures)
#   ./ralph/run.sh 1 2 3           # run domains 1, 2, 3
#   FAST=1 ./ralph/run.sh 8        # pass --fast (skip tests+lint) for a quick smoke
#
# Prerequisites: ralphy on PATH, an authenticated Claude Code, git, and the dev/launch
# extras installed (pip install -e '.[dev,launch]') so the pytest gate can run.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Domains in number order. Independent of each other; pick any subset.
TASKLISTS=(
  "01-symbolic-ai-logic"
  "02-ai-ml-tooling"
  "03-llm-inference-training-optimization"
  "04-agentic-ai"
  "05-speech-audio"
  "07-proprietary-coding-ai"
  "08-architectures"
  "09-procedural-generation"
  "10-data-analysis-research"
  "11-devops-mlops-infra"
)

command -v ralphy >/dev/null 2>&1 || { echo "error: 'ralphy' not found on PATH"; exit 1; }

# ralphy auto-commits per task, so a git repo is required.
if [ ! -d .git ]; then
  echo "Initializing git repository (ralphy commits after each task)..."
  git init -b main >/dev/null
  git add -A
  git commit -m "chore: Praxis scaffolds, launcher, and ralphy tasklists" >/dev/null
fi

# Select which tasklists to run, BY DOMAIN NUMBER (the NN- prefix, not array
# position). Numbering has a gap (06 was removed), so `8` -> 08-architectures. No args = all.
if [ "$#" -eq 0 ]; then
  SELECTED=("${TASKLISTS[@]}")
else
  SELECTED=()
  for n in "$@"; do
    nn=$(printf '%02d' "$n" 2>/dev/null) || { echo "error: '$n' is not a number"; exit 1; }
    match=""
    for tl in "${TASKLISTS[@]}"; do
      case "$tl" in "$nn"-*) match="$tl"; break;; esac
    done
    [ -n "$match" ] || { echo "error: no tasklist for domain '$n' (try one of: ${TASKLISTS[*]%%-*})"; exit 1; }
    SELECTED+=("$match")
  done
fi

# Scalar (not an array): macOS bash 3.2 errors on empty-array expansion under `set -u`.
EXTRA_FLAGS=""
[ "${FAST:-0}" = "1" ] && EXTRA_FLAGS="--fast"

# Returns 0 only if every task in the given ralphy file is completed.
all_complete() {
  python3 - "$1" <<'PY'
import json, sys
tasks = json.load(open(sys.argv[1])).get("tasks", [])
incomplete = [t["title"] for t in tasks if not t.get("completed")]
if incomplete:
    print(f"  {len(incomplete)} of {len(tasks)} task(s) still incomplete:")
    for t in incomplete[:10]:
        print(f"    - {t}")
    if len(incomplete) > 10:
        print(f"    ... and {len(incomplete) - 10} more")
    sys.exit(1)
print(f"  all {len(tasks)} task(s) complete")
PY
}

total=${#SELECTED[@]}
n=0
for dir in "${SELECTED[@]}"; do
  n=$((n + 1))
  file="ralph/$dir/tasks.json"
  echo ""
  echo "==============================================================="
  echo "  [$n/$total] ralphy: $dir"
  echo "  file: $file"
  echo "==============================================================="

  ralphy --json "$file" --claude --max-retries 3 $EXTRA_FLAGS

  echo "Checking completion of $dir ..."
  if ! all_complete "$file"; then
    echo ""
    echo "Stopping: '$dir' did not finish. Resume it with:"
    echo "    ./ralph/run.sh $n"
    echo "(completed tasks are skipped on re-run, so it picks up where it left off)"
    exit 1
  fi
done

# Refresh the generated indices so badges/coverage reflect the new content.
python3 generate_docs.py >/dev/null 2>&1 || true

echo ""
echo "All $total selected tasklist(s) completed in order."
echo "Run 'python generate_docs.py' and 'praxis-launch' to see updated status."
