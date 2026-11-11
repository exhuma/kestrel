"""Canonical entrypoint (``python -m app``): dispatch to the CLI.

Subcommands live in :mod:`app.cli` — ``serve`` (default; launches uvicorn with
unified logging) and ``poll`` (a read-only dry-run of the configured task
sources). Host and port come from ``Settings`` (``KESTREL_HOST`` /
``KESTREL_PORT``), so a ``backend/.env`` value is honoured; dev auto-reload is
the ``--reload`` flag.
"""
from __future__ import annotations

from app.cli import load_env, main

if __name__ == "__main__":
    load_env()
    raise SystemExit(main())
