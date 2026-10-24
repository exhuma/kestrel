# Quickstart: Backend Concurrency Cap and Rate-Limit Backoff

## Prerequisites

- Run commands from the repository root.
- Python dependencies are installed with `uv sync` in `backend/`.

## Focused automated validation

```bash
cd backend
uv run pytest \
  tests/test_backend_limiter.py \
  tests/test_backend_config.py \
  tests/test_config.py \
  tests/test_rate_limit.py \
  tests/test_opencode_backend.py
```

Expected result: all tests pass. The tests exercise the configuration contract
in [contracts/config.md](contracts/config.md), queueing/cancellation behavior,

## Full quality validation

```bash
task quality
```

Expected result: every quality check passes.

## Manual configuration check

Configure an OpenCode backend conservatively:

```toml
[[backends]]
id = "azure-opencode"
type = "opencode"
base_url = "http://localhost:4096"
model = "azure/gpt-5"
max_concurrency = 1
rate_limit_retries = 3
rate_limit_backoff_seconds = 2.0
```

Start two workflows using `azure-opencode` and confirm through provider logs
that no more than one message request is active at a time. Confirm that a 429
with `Retry-After` causes a delayed retry and that a persistent 429 is reported
as a rate-limit error after three retries.
