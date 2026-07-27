#!/usr/bin/env bash
#
# Quartermaster — Claude Code PostToolUse hook.
#
# Wire this to `matcher: "mcp__quartermaster__resolve_kits"` so it runs right
# after a successful resolve_kits call. It records the current session id under
# a gitignored cache dir; qm-edit-reminder.sh checks for that marker and goes
# silent once it exists, so the edit nudge fires at most once per session —
# before the first resolve, never after.
set -euo pipefail

input=$(cat)
session_id=$(printf '%s' "$input" | jq -r '.session_id // "unknown"')

state_dir="${XDG_CACHE_HOME:-$HOME/.cache}/quartermaster/sessions"
mkdir -p "$state_dir"
: > "$state_dir/$session_id"

