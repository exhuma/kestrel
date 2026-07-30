#!/bin/sh
# Container entrypoint: seed the Claude config, apply DB migrations, then serve.
set -e

: "${HOME:=/data/home}"
: "${CLAUDE_SEED_DIR:=/seed}"
: "${KESTREL_WORKSPACE_ROOT:=/workspaces}"

# Fail fast with a clear message if a required path isn't writable by this
# container's user, instead of a confusing mid-script crash later (a raw
# `mkdir: Permission denied`, or alembic/sqlite failing deep in a stack
# trace). The image runs as a non-root user by default (see Dockerfile); the
# operator is responsible for provisioning bind-mounted paths (e.g.
# ./workspaces) owned by that user before starting the container. Named
# volumes (e.g. /data) don't need this — see
# docs/configuration.md#running-as-a-non-root-user.
require_writable() {
  path="$1"
  label="$2"
  if ! mkdir -p "$path" 2>/dev/null || [ ! -w "$path" ]; then
    echo "kestrel: FATAL: $label ($path) is not writable by uid $(id -u):$(id -g)." >&2
    echo "kestrel: create it on the host (or fix its ownership) so uid $(id -u):$(id -g) can write to it, then restart." >&2
    exit 1
  fi
}

require_writable /data "the /data volume"
require_writable "$HOME" "the Claude HOME directory"
require_writable "$KESTREL_WORKSPACE_ROOT" "the workspace root"

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

# `python -m app` launches uvicorn with unified logging (uvicorn + app logs
# on one stdout stream; KESTREL_LOG_FORMAT selects text or JSON).
exec uv run python -m app
