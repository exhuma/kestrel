# Quickstart / Validation: Task-source configuration & poll tooling

Runnable scenarios that prove the feature end-to-end. Details live in
[data-model.md](./data-model.md) and [contracts/](./contracts/).

## Prerequisites

- `cd backend` and `uv sync` (no new dependency added).
- Tokens exported in the environment (never in the TOML):
  `KESTREL_GITHUB_TOKEN`, `KESTREL_JIRA_API_TOKEN`, and (for a self-hosted code
  host) `KESTREL_CODE_HOST_TOKEN`.
- A `config.toml` using the new shape — see
  [contracts/config-schema.md](./contracts/config-schema.md). Point at it with
  `KESTREL_CONFIG_FILE=config.toml`.

## Scenario 1 — Uniform configuration (US1 / SC-001)

1. Write a `config.toml` with `poll_interval_seconds`, one `[[task_sources]]`
   `github` entry and one `jira` entry (no legacy scalar keys).
2. Start the service: `uv run python -m app`.
3. **Expect**: startup log shows the GitHub reconcile loop and the Jira poll
   loop both enabled; no error about unknown keys. Removing all
   `[[task_sources]]` entries and restarting starts the service with no
   ingestion loop.

## Scenario 2 — Dry-run the poll (US2 / SC-003)

1. With the same config, run: `uv run python -m app poll`.
2. **Expect**: matched work items from **both** sources are printed, each with
   `ref`, title, and resolved repo; an RFC with an unresolvable repo is listed
   and marked unresolved.
3. **Expect**: no run is created (`GET /api/runs` unchanged) and no comment /
   attachment is written to any source. See
   [contracts/cli-poll.md](./contracts/cli-poll.md).

## Scenario 3 — Repo from a web link (US3 / SC-004)

1. In the `jira` entry, leave `repo_field` unset and set (or default)
   `repo_link_text = "Repository"`.
2. On a matching RFC, add a remote link titled "Repository" pointing at
   `https://<host>/<owner>/<name>`.
3. Run `uv run python -m app poll`.
4. **Expect**: the RFC resolves to `<owner>/<name>` from the link (see
   [contracts/jira-remote-link.md](./contracts/jira-remote-link.md)); a
   field-based RFC still resolves identically.

## Scenario 4 — One cadence (US4 / SC-005)

1. Set only `poll_interval_seconds` (no per-source interval keys — they no longer
   exist).
2. Start the service.
3. **Expect**: both loops re-check on that interval; a leftover
   `KESTREL_RECONCILE_INTERVAL_SECONDS` in the environment has no effect.

## Automated validation (Constitution III)

Run the backend suite and the mechanical quality gate:

```bash
cd backend && uv run pytest -q
cd .. && task quality
```

**Expect** green, including:
- new tests: `[[task_sources]]` parsing + per-type validation, `token()`
  resolution, unified `poll_interval_seconds`, `_repo_from_url` (github / gitlab
  subgroup / `.git` / junk), web-link resolution fallback, `list_work_items`
  (both services, starts no run), rewired webhook/reconcile/lifespan gating, and
  the `poll` command;
- updated 002/003 behaviour tests still passing on the new config shape (SC-006);
- `task quality` clean (no new grandfather exemptions; jscpd ≤3%).
