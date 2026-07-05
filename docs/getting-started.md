# Getting started (Docker)

Run kestrel from the published container image. The image bundles the
backend, the built web UI, and the `claude` CLI, so the only host
requirements are Docker and a Claude login.

## Prerequisites

- **Docker** with Compose v2 (`docker compose`, not `docker-compose`).
- **A Claude login on the host.** Kestrel dispatches to the bundled `claude`
  CLI, which authenticates with *your* credentials — it does not ship an API
  key. Log in once on the host so `~/.claude` and `~/.claude.json` exist:

  ```bash
  claude   # run once, complete the login, then quit
  ```

  If you do not have the `claude` CLI on the host, install it
  (`npm install -g @anthropic-ai/claude-code`) and log in. Only the resulting
  config files are needed — the CLI itself is already inside the image.

## Quickstart

```bash
# Fetch the published compose file (or copy it from this repo), then:
docker compose up
```

Open <http://localhost:8000>.

The container, on startup, copies your host Claude config into its own
persisted `HOME`, applies database migrations, and starts serving the UI and
API on port 8000. First start pulls the image and may take a minute.

## Dispatch your first session

1. Open the **Sessions** panel in the UI.
2. Enter a prompt and start a session. Kestrel spawns a `claude` session in a
   fresh per-run workspace under `./workspaces` on the host.
3. Watch events stream live (server-sent events). The workspace is a real git
   directory you can inspect on the host while the session runs.

To confirm the service is healthy at any time:

```bash
curl -s http://localhost:8000/readyz
# {"probe":"readyz","status":"ok","checked_at":"…","components":[…]}
```

## Volumes

The published `docker-compose.yml` mounts four things:

| Mount | Mode | Purpose |
| --- | --- | --- |
| `kestrel-data` → `/data` | read-write | SQLite DB and the container's Claude `HOME`, persisted across restarts |
| `./workspaces` → `/workspaces` | read-write | The git repos claude clones and edits — **browsable on the host** |
| `~/.claude` → `/seed/.claude` | read-only | Seed: your host Claude config, plugins, and credentials |
| `~/.claude.json` → `/seed/claude.json` | read-only | Seed: your host Claude config file (MCP servers, plugin/approval state) |

`~/.claude.json` is a separate **file** from the `~/.claude` **directory** —
both are needed.

## How your host Claude config is used

Kestrel never re-implements Claude authentication. On each start the
entrypoint copies the two read-only seed mounts into the container's writable
`HOME` (on the `/data` volume):

- **Config and plugins** (`~/.claude`, `~/.claude.json`) are copied **once**,
  so container-side state (session history, plugin caches) survives restarts.
- **Credentials** (`~/.claude/.credentials.json`) are re-copied **every
  start**, so re-logging-in on the host propagates after a
  `docker compose restart`.

The container never writes back to your host config.

Because the container's `HOME` is seeded from your host, spawned `claude`
sessions pick up **your** user-level MCP servers and plugins with no extra
setup. There are caveats for MCP runtimes and plugin enablement inside a
container — see [Troubleshooting](troubleshooting.md#mcp-servers-and-plugins).

## Next steps

- [Configuration](configuration.md) — every setting, config file, and mount.
- [Backends](backends.md) — dispatch to opencode or a self-hosted LLM.
- [GitHub workflow](setup-github-workflow.md) — the issue → PR feature.
- [Troubleshooting](troubleshooting.md) — common speed-bumps.
