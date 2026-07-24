#!/usr/bin/env bash
#
# Config guard. Fails if a change touches the code-quality THRESHOLD
# configuration or the GRANDFATHER list without an explicit override. The escape
# hatch is a commit-message trailer: put a line reading
#
#     [quality-override]
#
# in any commit in the range when the change to a limit is genuinely warranted
# (and say why in the commit body). See AGENTS.md "Code-quality guardrails".
#
# Usage: tools/check-config-guard.sh [BASE_REF]
#   BASE_REF defaults to HEAD^ (local use). CI passes the PR base / push "before"
#   SHA. The range examined is BASE_REF..HEAD.
set -uo pipefail

BASE="${1:-HEAD^}"
RANGE="${BASE}..HEAD"

# Files whose ENTIRE contents are threshold config or the grandfather list.
PROTECTED_FILES_RE='^(tools/agent-check\.sh|tools/check-config-guard\.sh|tools/quality\.sh|frontend/eslint\.config\.js|frontend/\.dependency-cruiser\.cjs|frontend/knip\.json|\.jscpd\.json|backend/\.importlinter|backend/\.vulture_allowlist\.py)$'

changed="$(git diff --name-only "$RANGE" 2>/dev/null)" || {
  echo "config-guard: could not diff ${RANGE}; skipping." >&2
  exit 0
}

reasons=""

# 1) Whole-file protected paths.
while IFS= read -r f; do
  [ -n "$f" ] || continue
  if printf '%s' "$f" | grep -qE "$PROTECTED_FILES_RE"; then
    reasons+="  - ${f}"$'\n'
  fi
done <<EOF
$changed
EOF

# 2) The threshold-bearing regions of backend/pyproject.toml (grep the diff
#    hunks so ordinary dependency edits to that file do NOT trip the guard).
if printf '%s\n' "$changed" | grep -qx 'backend/pyproject.toml'; then
  if git diff "$RANGE" -- backend/pyproject.toml \
      | grep -E '^[-+]' \
      | grep -qE 'max-complexity|max-args|max-branches|max-statements|max-returns|max-locals|per-file-ignores|extend-immutable-calls|lint\.(mccabe|pylint|flake8-bugbear)|select[[:space:]]*='; then
    reasons+="  - backend/pyproject.toml (Ruff threshold / grandfather section)"$'\n'
  fi
fi

# 3) In-source grandfather markers being added or removed anywhere.
if git diff "$RANGE" | grep -E '^[-+]' \
    | grep -qE 'pylint: disable=too-many-lines|TODO\(quality\)'; then
  reasons+="  - a grandfather marker (pylint disable / TODO(quality))"$'\n'
fi

if [ -z "$reasons" ]; then
  exit 0
fi

if git log --format='%B' "$RANGE" 2>/dev/null | grep -qF '[quality-override]'; then
  echo "config-guard: threshold/grandfather config changed, and a" \
       "[quality-override] trailer is present — allowing."
  exit 0
fi

{
  echo "config-guard: this change edits code-quality threshold config or the"
  echo "grandfather list:"
  printf '%s' "$reasons"
  echo
  echo "These are hard limits, deliberately not self-service. If the change is"
  echo "genuinely warranted, add a line reading '[quality-override]' to a commit"
  echo "message in this branch (and explain why). See AGENTS.md."
} >&2
exit 1
