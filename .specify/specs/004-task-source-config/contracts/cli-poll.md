# Contract: `python -m app poll` command

A local operator CLI (not a network endpoint — the access model is unchanged).
Read-only dry-run of every configured task source's selection.

## Invocation

```text
python -m app            # default subcommand: serve (unchanged uvicorn launch)
python -m app serve      # explicit serve
python -m app poll       # dry-run listing across all configured sources
```

## `poll` behaviour

- Loads `Settings` (so `KESTREL_CONFIG_FILE` / `.env` apply exactly as for the
  server).
- Iterates `configured_poll_sources(settings)`; for each source, runs its
  **existing selection query** (the same query the live loop uses — FR-012) and
  resolves each matched item's repository.
- Prints, per source, one line per matched work item with: `ref`, `title`, and
  the resolved `code_repo` — or a clear **unresolved-repository** marker when the
  repo could not be resolved.
- Starts **no** run, posts **no** comment, writes **no** attachment — zero
  side effects (FR-010 / SC-003).
- With no sources configured, prints a "nothing configured" message and exits
  **0**.
- Fully enumerates paginated Jira results (the change-set-A pagination applies).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Listing completed (including the "no sources configured" case). |
| non-zero | Argument error, or an unrecoverable failure loading settings. |

A single source failing to reach its API SHOULD be reported inline for that
source without aborting the other sources' listings, consistent with the live
loops' per-source isolation.

## Output shape (illustrative, not asserted verbatim)

```text
github [owner/name]:
  owner/name#42   Fix flaky login test      -> owner/name
jira [https://acme.atlassian.net]:
  RFC-17          Add rate limiting          -> acme/gateway@main
  RFC-19          Spike: caching             -> (unresolved repository)
```

Tests assert the presence of each `ref`/repo and the no-side-effect invariant,
not the exact formatting.
