#!/usr/bin/env bash
#
# Single entrypoint for every code-quality guardrail (Python + JS/TS/Vue).
# Runs ALL checks, collecting failures instead of stopping at the first, then
# exits non-zero if any check failed. Run via `task quality`.
#
# These are HARD LIMITS. When a check fails, split the module / extract a
# function / remove the duplication — do NOT raise a threshold or add a
# suppression. See AGENTS.md "Code-quality guardrails".
#
# Tool versions are pinned and run on demand (uvx / npx), matching this repo's
# existing "uvx ruff@… / npx cspell@…" convention, so nothing is added to the
# frozen backend install.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- pinned versions ---------------------------------------------------------
RUFF_V=0.15.20
PYLINT_V=4.0.6
VULTURE_V=2.16
IMPORTLINTER_V=2.13
JSCPD_V=4.0.5

fail=0

run() {
  local name="$1"
  shift
  printf '\n\033[1m── %s\033[0m\n' "$name"
  if "$@"; then
    printf '\033[32m✓ %s\033[0m\n' "$name"
  else
    printf '\033[31m✗ %s FAILED\033[0m\n' "$name"
    fail=1
  fi
}

# --- Python (run from backend/, tools via uvx) -------------------------------
check_ruff() { ( cd backend && uvx "ruff@${RUFF_V}" check . ); }
check_pylint() {
  ( cd backend && uvx "pylint@${PYLINT_V}" --disable=all \
      --enable=too-many-lines --max-module-lines=500 app tests )
}
check_vulture() {
  ( cd backend && uvx "vulture@${VULTURE_V}" app .vulture_allowlist.py \
      --min-confidence 80 )
}
check_imports() {
  ( cd backend && uvx --from "import-linter==${IMPORTLINTER_V}" lint-imports )
}

# --- JS / TS / Vue (run from frontend/, local node_modules) ------------------
check_eslint() { ( cd frontend && npm run --silent lint ); }
check_depcruise() { ( cd frontend && npm run --silent depcruise ); }
check_knip() { ( cd frontend && npm run --silent knip ); }

# --- Cross-cutting (repo root) -----------------------------------------------
check_jscpd() { npx "jscpd@${JSCPD_V}" .; }

run "ruff — style + complexity + bugbear (python)" check_ruff
run "pylint — module length ≤ 500 (python)" check_pylint
run "vulture — dead code (python)" check_vulture
run "import-linter — layering + no cycles (python)" check_imports
run "eslint — size + complexity + sonarjs (js/ts/vue)" check_eslint
run "dependency-cruiser — layering + no cycles (js/ts)" check_depcruise
run "knip — dead files + deps (js/ts)" check_knip
run "jscpd — copy/paste ≤ 3% (python + js/ts)" check_jscpd

echo
if [ "$fail" -ne 0 ]; then
  printf '\033[31mQuality checks FAILED.\033[0m Fix the violations above.\n'
  echo "Do not raise thresholds or add suppressions (see AGENTS.md)."
  exit 1
fi
printf '\033[32mAll quality checks passed.\033[0m\n'
