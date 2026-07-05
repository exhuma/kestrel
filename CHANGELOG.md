# Changelog

All notable changes to kestrel are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [CalVer](docs/releasing.md) (`vYYYY.M.D` with a pre-release suffix).

## [Unreleased]

## [2026.7.5-alpha.1] - 2026-07-05

### Added

- `GET /healthz` now reports the running image version and verifies database
  readiness (HTTP 503 when the database is unreachable).
- Compose-level healthcheck and `host.docker.internal` mapping so host-run
  backends (Ollama, `opencode serve`) are reachable from the container.
- Unified logging: uvicorn and application logs share one stdout stream, with
  `KESTREL_LOG_FORMAT` (`text` default, or `json` for one document per line)
  and `KESTREL_LOG_LEVEL`. Launch via `python -m app`.
- Audience-split documentation under `docs/` (getting started, configuration,
  backends, troubleshooting, development, observability, architecture,
  releasing).

### Changed

- Backends are configured **only** via `KESTREL_BACKENDS_FILE` (or the
  `backends.toml` it names). The `KESTREL_BACKENDS`,
  `KESTREL_STEP_BACKENDS`, and `KESTREL_DEFAULT_SESSION_BACKEND` environment
  variables are no longer read.

## [2026.7.3-alpha.1] - 2026-07-03

First alpha. A single-user web tool to dispatch and monitor coding-agent
sessions.

### Added

- **Docker image** bundling the FastAPI backend, the built Vue/Vuetify SPA,
  and the `claude` CLI; serves the UI and API on port 8000.
- **Claude Code dispatch** — spawns `claude` sessions in per-run git
  workspaces and streams events over SSE to the UI. Host Claude login,
  MCP servers, and plugins are reused via read-only seed mounts.
- **Pluggable backends** — dispatch to `opencode` (via `opencode serve`) or a
  self-hosted OpenAI-compatible LLM, configured from a TOML file
  (`KESTREL_BACKENDS_FILE`), with per-workflow-step assignment and capability
  checking.
- **GitHub issue → PR workflow** — refine, clarify, plan, and implement with
  human approval gates; persisted to SQLite and resumable.
- **CalVer release pipeline** — tag-driven GHCR publish with cascading
  channel tags (`alpha`/`beta`/`rc`/`stable`) and no `latest`.

[Unreleased]: https://github.com/exhuma/kestrel/compare/v2026.7.5-alpha.1...HEAD
[2026.7.5-alpha.1]: https://github.com/exhuma/kestrel/compare/v2026.7.3-alpha.1...v2026.7.5-alpha.1
[2026.7.3-alpha.1]: https://github.com/exhuma/kestrel/releases/tag/v2026.7.3-alpha.1
