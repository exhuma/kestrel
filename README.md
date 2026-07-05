# kestrel

Dispatch and monitor [Claude Code](https://github.com/anthropics/claude-code)
CLI sessions from a web UI. Kestrel is a single-user tool: a FastAPI backend
spawns `claude` sessions in per-run workspaces, persists them to SQLite, and
streams events over SSE to a Vue 3 / Vuetify frontend. It can also dispatch to
[opencode](https://opencode.ai) or a self-hosted LLM — see
[Backends](docs/backends.md).

> **Status: alpha.** Interfaces and data formats may change between releases.

## Quickstart (Docker)

The published image bundles the backend, the built SPA, and the `claude` CLI.
Authentication reuses your **host** Claude login, mounted into the container.

```bash
# 1. Log in to Claude on the host once (creates ~/.claude):
claude   # run once, log in, then quit

# 2. Fetch docker-compose.yml from the release and start it:
docker compose up
```

Then open <http://localhost:8000>.

See **[Getting started](docs/getting-started.md)** for prerequisites, volumes,
and how your host Claude config is used.

## Documentation

- [Getting started](docs/getting-started.md) — run the image, first session,
  volumes, host-config seeding.
- [Configuration](docs/configuration.md) — every `KESTREL_*` setting, config
  files, and mounts.
- [Backends](docs/backends.md) — dispatch to opencode or a self-hosted LLM.
- [GitHub workflow](docs/setup-github-workflow.md) — the issue → PR feature.
- [Troubleshooting](docs/troubleshooting.md) — common speed-bumps.
- [Observability](docs/observability.md) — logs (text/JSON) and health.
- [Development](docs/development.md) — run from source and run the tests.
- [Architecture](docs/architecture.md) — how it fits together.
- [Versioning & releases](docs/releasing.md) — CalVer, channels, tagging.

## License

[MIT](LICENSE).
