#!/bin/sh
# Container entrypoint: seed the Claude config, apply DB migrations, then serve.
set -e

: "${HOME:=/data/home}"
: "${CLAUDE_SEED_DIR:=/seed}"
: "${KESTREL_WORKSPACE_ROOT:=/workspaces}"

mkdir -p /data "$HOME" "$KESTREL_WORKSPACE_ROOT"

# Seed the spawned claude CLI's config (MCP servers, plugins, credentials) from
# a read-only mount of the host ~/.claude + ~/.claude.json into the writable,
# persisted HOME. The container never writes back to the host.
#
# Config and plugins are copied ONCE so container-side state (session history,
# plugin caches) survives restarts; credentials are refreshed every start so a
# host re-login propagates without wiping the /data volume.
seeded=0
if [ -d "$CLAUDE_SEED_DIR/.claude" ]; then
  seeded=1
  if [ ! -d "$HOME/.claude" ]; then
    cp -a "$CLAUDE_SEED_DIR/.claude" "$HOME/.claude"
  fi
fi
if [ -f "$CLAUDE_SEED_DIR/claude.json" ]; then
  seeded=1
  if [ ! -f "$HOME/.claude.json" ]; then
    cp "$CLAUDE_SEED_DIR/claude.json" "$HOME/.claude.json"
  fi
fi
if [ -f "$CLAUDE_SEED_DIR/.claude/.credentials.json" ]; then
  mkdir -p "$HOME/.claude"
  cp "$CLAUDE_SEED_DIR/.claude/.credentials.json" "$HOME/.claude/.credentials.json"
fi

if [ "$seeded" -eq 0 ] && [ ! -f "$HOME/.claude.json" ]; then
  echo "kestrel: no Claude config seed mounted at $CLAUDE_SEED_DIR and none in \$HOME;" >&2
  echo "kestrel: spawned sessions may lack auth, MCP servers and plugins." >&2
fi

cd /app

# Migrations are idempotent; safe to run on every start.
uv run alembic upgrade head

exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
