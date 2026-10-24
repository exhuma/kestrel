# kestrel

Dispatch and monitor coding-agent sessions from a web UI: the
[Claude Code](https://github.com/anthropics/claude-code) CLI, an
[opencode](https://opencode.ai) server, or a self-hosted LLM. Kestrel is a
single-user tool: a FastAPI backend
ingests tasks from GitHub, Jira, or local task folders into an event-driven
**work board** of typed cards claimed by configurable specialist agents (see
[Architecture](docs/architecture.md)), persists everything to SQLite, and
streams live state over SSE to a Vue 3 / Vuetify frontend. See
[Backends](docs/backends.md) for choosing what agents run on.

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
and how your host Claude config is used. The Claude login is only needed for
the `claude_cli` backend; with an opencode or self-hosted backend configured
you do not need it. To run kestrel on a cluster, see
**[Deploying on Kubernetes](docs/deploy-kubernetes.md)**.

## Documentation

- [Getting started](docs/getting-started.md) — run the image, first session,
  volumes, host-config seeding.
- [Deploying on Kubernetes](docs/deploy-kubernetes.md) — one pod with an
  opencode sidecar behind an authenticating proxy, for a Jira walk-through.
- [Configuration](docs/configuration.md) — every `KESTREL_*` setting, config
  files, and mounts.
- [Backends](docs/backends.md) — dispatch to opencode or a self-hosted LLM.
- [GitHub workflow](docs/setup-github-workflow.md) — watch a repo's issues.
- [Jira workflow](docs/setup-jira-workflow.md) — poll a Jira project's RFCs.
- [Local tasks workflow](docs/setup-local-tasks.md) — disposable local
  tasks for testing.
- [Feedback intake](docs/feedback-intake.md) — removed in the Phase 10
  clean break; kept as a pointer to what replaces it.
- [Next steps](docs/next-steps.md) — where the open work is tracked.
- [Operator hooks](docs/hooks.md) — custom actions on lifecycle events.
- [Troubleshooting](docs/troubleshooting.md) — common speed-bumps.
- [Observability](docs/observability.md) — logs (text/JSON) and health.
- [Development](docs/development.md) — run from source and run the tests.
- [Architecture](docs/architecture.md) — how it fits together.
- [Versioning & releases](docs/releasing.md) — CalVer, channels, tagging.
- [Quartermaster alignment](docs/qm-alignment.md) — kit-alignment audit and
  the work-package backlog it produced.

## License

[MIT](LICENSE).
