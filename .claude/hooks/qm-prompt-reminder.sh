#!/usr/bin/env bash
#
# Quartermaster — Claude Code UserPromptSubmit hook.
#
# For UserPromptSubmit, whatever this script prints to stdout is injected into
# the model's context for the current turn as plain text (no JSON envelope is
# required). We use it to re-assert the standing resolve_kits behavior on every
# prompt, so it never decays over a long session.
#
# Exit 0 with the reminder on stdout. This hook is purely additive; it never
# blocks the prompt.
set -euo pipefail

cat <<'EOF'
[Quartermaster] Before you edit or plan, call
mcp__quartermaster__resolve_kits(task="<plain description of the work>") to load
the right instruction kits — and re-call it whenever the work changes shape:
a new change/plan request, a new subsystem or aspect, a direction shift (e.g.
"add login" becoming OIDC), or right after a context compaction (re-resolve
before your next edit). Kit guidance loaded once decays; resolve per task.
EOF

