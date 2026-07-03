#!/bin/sh
# Container entrypoint: apply DB migrations, then serve the API + SPA.
set -e

cd /app

# Migrations are idempotent; safe to run on every start.
uv run alembic upgrade head

exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
