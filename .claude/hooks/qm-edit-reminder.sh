#!/usr/bin/env bash
#
# Quartermaster — Claude Code PreToolUse hook (Edit|Write|MultiEdit|NotebookEdit).
#
# Non-blocking nudge: if resolve_kits has NOT run yet this session, remind the
# agent to call it before editing. If it already ran (recorded by
# qm-record-resolve.sh), stay completely silent so we never nag.
#
# Claude Code passes the hook a JSON object on stdin; we read `session_id` from
# it (via jq) to scope the per-session state. To nudge, we print a PreToolUse
# `additionalContext` envelope to stdout:
#
#   {"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"…"}}
#
# Because we do NOT set `permissionDecision`, the edit is allowed to proceed —
# the text is injected as extra context only. To stay silent we simply exit 0
# with no output.
set -euo pipefail

input=$(cat)
session_id=$(printf '%s' "$input" | jq -r '.session_id // "unknown"')

state_dir="${XDG_CACHE_HOME:-$HOME/.cache}/quartermaster/sessions"

# Already resolved this session → say nothing.
if [ -f "$state_dir/$session_id" ]; then
  exit 0
fi

read -r -d '' msg <<'EOF' || true
[Quartermaster] You are about to edit files but have not called resolve_kits
this session. Consider calling
mcp__quartermaster__resolve_kits(task="<plain description of the work>") first so
the right kit guidance is loaded before you make changes.
EOF

jq -cn --arg m "$msg" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$m}}'

