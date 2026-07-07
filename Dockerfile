# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build the Vue/Vite SPA.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend-build
WORKDIR /frontend

# Same-origin API in the packaged image: the backend serves this bundle, so
# API calls must be relative. Left empty on purpose (see frontend/src/api).
ARG VITE_API_BASE=

# Optional: full URL of the GitHub repository. When set, the header shows a
# "Source code" link; empty (default) hides it.
ARG VITE_GITHUB_REPO_URL=

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build   # -> /frontend/dist

# ---------------------------------------------------------------------------
# Stage 2: Python runtime that also bundles the claude CLI and serves the SPA.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# git: the backend performs git operations in session workspaces.
# nodejs: required to run the bundled claude CLI (a Node application).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# uv: dependency/venv manager used to install and run the backend.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install backend dependencies first for better layer caching.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code + migrations.
COPY backend/ ./
RUN uv sync --frozen --no-dev

# Built SPA served by the backend (see KESTREL_STATIC_DIR).
COPY --from=frontend-build /frontend/dist ./static

# Version baked in at build time so the running image reports its own version.
ARG KESTREL_VERSION=0.0.0-dev
ENV KESTREL_VERSION=${KESTREL_VERSION}

# Use the dependencies baked into the image at build time; never re-sync at
# container start. Without this, `uv run` would install dev deps into the venv
# on every start — slow, and it pollutes the (optionally JSON) log stream.
ENV UV_NO_SYNC=1

# Runtime defaults. /data (persisted): SQLite DB + the writable Claude HOME
# seeded from the host at startup. /workspaces (host bind mount): the git repos
# claude clones and edits, kept browsable on the host. /seed (read-only): where
# the host ~/.claude and ~/.claude.json are mounted for the entrypoint to copy.
ENV KESTREL_STATIC_DIR=/app/static \
    KESTREL_DATABASE_URL=sqlite:////data/kestrel.db \
    KESTREL_WORKSPACE_ROOT=/workspaces \
    CLAUDE_SEED_DIR=/seed \
    HOME=/data/home

# A container binds all interfaces *within its own network namespace*; the
# host is responsible for publishing the port to loopback only (see
# docker-compose.yml). Keep bytecode off and uv/tmp scratch under /tmp so the
# root filesystem can be mounted read-only at runtime.
ENV KESTREL_HOST=0.0.0.0 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_CACHE_DIR=/tmp/uv-cache

# Run as an unprivileged user. A prompt-injected agent runs as this user, so
# it must not be root. The writable runtime dirs (/data, its seeded Claude
# HOME, and /workspaces) are created and owned here so a named volume inherits
# that ownership; a host bind mount for /workspaces must be chown-able to this
# uid by the operator (documented in docs/security.md).
RUN useradd --system --uid 10001 --shell /usr/sbin/nologin kestrel \
    && mkdir -p /data /data/home /workspaces \
    && chown -R kestrel:kestrel /data /workspaces

VOLUME ["/data", "/workspaces"]

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER kestrel

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
