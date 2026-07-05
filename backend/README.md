# kestrel backend

FastAPI backend for kestrel: dispatches `claude` CLI sessions,
persists them to SQLite, and streams events to the frontend via
SSE.

## Running

```bash
cd backend
uv run alembic upgrade head   # apply schema migrations
uv run uvicorn app.main:app --reload
```

Both this command and `uv run python -m app` emit the application's own
logs (not just uvicorn access logs) on one stream; `KESTREL_LOG_LEVEL`
(e.g. `debug`) and `KESTREL_LOG_FORMAT` (`text` or `json`) control them.

Config via `KESTREL_*` env vars or `backend/.env`
(`KESTREL_DATABASE_URL`, `KESTREL_CLAUDE_BIN`,
`KESTREL_WORKSPACE_ROOT`, `KESTREL_PERMISSION_MODE`,
`KESTREL_MODEL_OVERRIDES`).

## Tests

```bash
cd backend
uv run pytest
```
