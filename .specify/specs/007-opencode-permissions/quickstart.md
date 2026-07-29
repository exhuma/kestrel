# Validation Guide

## Prerequisites

- Python dependencies installed through `uv` in `backend/`.

## Run the focused regression tests

```bash
uv run pytest tests/test_opencode_backend.py
```

Expected result: tests confirm that editable and read-only permission replies
use the OpenCode 1.18.7 session-scoped endpoint and `response` payload.

## Run the quality gate

```bash
task quality
```

Expected result: all repository quality checks pass.
