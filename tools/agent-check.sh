#!/usr/bin/env bash
#
# PostToolUse hook (Edit|Write|MultiEdit). Runs the FAST, per-file structural
# checks for the file an agent just edited. On a violation it prints the output
# to stderr and exits 2, so the agent is forced to address it before continuing.
# Otherwise it exits 0 silently. Only per-file checks run here (never the
# project-wide jscpd / import-linter / knip / vulture) so it stays within a
# couple of seconds. The full suite is `task quality`.
#
# It reads the hook payload as JSON on stdin and extracts the edited path.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RUFF_V=0.15.20
PYLINT_V=4.0.6

input="$(cat)"
file="$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get("tool_input") or {}
print(ti.get("file_path") or ti.get("notebook_path") or "")
')"

# Nothing to check: no path, missing file, or file outside our scope.
[ -n "$file" ] || exit 0
[ -f "$file" ] || exit 0
rel="${file#"$ROOT"/}"

out=""
rc=0

case "$rel" in
  backend/app/*.py | backend/tests/*.py)
    relpy="${rel#backend/}"
    out="$(cd "$ROOT/backend" && {
      st=0
      uvx "ruff@${RUFF_V}" check "$relpy" || st=1
      uvx "pylint@${PYLINT_V}" --disable=all --enable=too-many-lines \
        --max-module-lines=500 --score=n "$relpy" || st=1
      exit "$st"
    } 2>&1)" || rc=$?
    ;;
  frontend/src/*.ts | frontend/src/*.js | frontend/src/*.vue | \
  frontend/tests/*.ts | frontend/tests/*.js | frontend/tests/*.vue | \
  frontend/src/*.mts | frontend/src/*.cts)
    reljs="${rel#frontend/}"
    out="$(cd "$ROOT/frontend" && npx --no-install eslint "$reljs" 2>&1)" || rc=$?
    ;;
  *)
    exit 0
    ;;
esac

if [ "$rc" -ne 0 ]; then
  {
    echo "✗ Code-quality guardrail failed for: $rel"
    echo
    echo "$out"
    echo
    echo "Fix this before continuing. These are HARD limits: split the module or"
    echo "extract a function — do NOT raise the threshold or add a"
    echo "noqa / eslint-disable. If a limit genuinely seems wrong, stop and ask"
    echo "the developer. See AGENTS.md \"Code-quality guardrails\"."
  } >&2
  exit 2
fi
exit 0
