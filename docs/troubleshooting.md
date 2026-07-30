# Troubleshooting

Common speed-bumps when running the alpha image, and how to clear them.

## Spawned sessions have no auth / fail immediately

The container logs a warning like:

```
kestrel: no Claude config seed mounted at /seed and none in $HOME;
kestrel: spawned sessions may lack auth, MCP servers and plugins.
```

Kestrel dispatches to the bundled `claude` CLI using **your host login**. Make
sure you have logged in on the host and that both seed mounts are present:

```bash
claude   # log in once on the host, then quit
```

The compose file mounts `~/.claude` and `~/.claude.json` read-only into
`/seed`. `~/.claude.json` is a separate **file** from the `~/.claude`
**directory** — both are needed. After re-logging-in on the host, run
`docker compose restart` so refreshed credentials are re-copied.

## MCP servers and plugins

Spawned `claude` sessions pick up **your** user-level MCP servers and plugins
because the container's `HOME` is seeded from your host `~/.claude` and
`~/.claude.json`. No extra setup is required beyond the seed mounts.

Supported MCP server runtimes are the ones bundled in the image: **node/npx**,
**uv/uvx**, **python**, and **git**. Not supported inside the container:

- MCP servers launched via **docker** or a **custom host binary** (those
  tools are not in the image);
- servers or config that point at **host-absolute paths** that do not exist
  in the container;
- project-scoped `.mcp.json` servers may need to be **pre-approved** on the
  host first (approval state is read from the seeded `~/.claude.json`).

> **Alpha limitation.** MCP works (HTTP/stdio servers whose runtime is in the
> image connect fine). **Plugin _enablement_**, however, is per-config /
> per-project state carried in your seeded config — a plugin that is not
> enabled for the spawned session's context on the host will not be active in
> the container either. Reliable plugin activation in dispatched sessions is
> deferred; expect to iterate here post-alpha.

## A backend at `localhost` is unreachable from the container

Inside the container `localhost` is the container itself, not the Docker host.
A host-run Ollama or `opencode serve` must be addressed as
`http://host.docker.internal:PORT` in `config.toml`, not `localhost`. See
[Backends → Reaching a backend from the Docker container](backends.md#reaching-a-backend-from-the-docker-container).

## Port 8000 is already in use

Change the host-side port in `docker-compose.yml`:

```yaml
ports:
  - "8080:8000"   # host:container — open http://localhost:8080
```

## The container shows `unhealthy`

`GET /readyz` (the healthcheck endpoint) returns 503 when the database is
unreachable. Check the logs (`docker compose logs kestrel`) for a migration or
database error, and verify the `/data` volume is writable. Confirm readiness
directly:

```bash
curl -s http://localhost:8000/readyz
# {"probe":"readyz","status":"ok","checked_at":"…","components":[…]}   when ready
```

## Which version am I running?

```bash
curl -sD - -o /dev/null http://localhost:8000/livez | grep -i x-kestrel-version
```

The `X-Kestrel-Version` header reports the baked-in image version. A
from-source run reports `0.0.0-dev`.

## Backend edits are not taking effect

`config.toml` is read **once at startup**. Restart after editing:

```bash
docker compose restart kestrel
```

Confirm the effective config with `GET /api/backends` or the startup log line
(`backends: … | ad-hoc sessions dispatch to: …`).

## Mount permission errors on `./workspaces`

The container runs as a non-root user by default (uid/gid `1000`, or
whatever `user:` you've set in `docker-compose.yml` — see
[Configuration → Running as a non-root user](configuration.md#running-as-a-non-root-user)).
The bind-mounted `./workspaces` directory must already exist on the host,
owned by that uid:gid, **before** the container starts — the entrypoint now
fails fast with an error like:

```
kestrel: FATAL: the workspace root (/workspaces) is not writable by uid 1000:1000.
```

Fix it:

```bash
mkdir -p workspaces
sudo chown 1000:1000 workspaces   # match your `user:` override, if any
```

The same applies to any other bind mount you add (e.g. `KESTREL_CONFIG_FILE`
or a `hooks_dir`) — Docker auto-creates a missing bind-mount source owned by
root, which this non-root default then rejects.

### Sharing `./workspaces` with another container (e.g. an opencode sidecar)

Both containers must agree on the same uid:gid so each can read/write files
the other created. Set `user: "uid:gid"` on both services (or arrange for
both images' default users to already match), and own `./workspaces` on the
host accordingly.
