"""Canonical entrypoint (``python -m app``): dispatch to the CLI.

Subcommands live in :mod:`app.cli` — ``serve`` (default; launches uvicorn with
unified logging) and ``poll`` (a read-only dry-run of the configured task
sources). Host, port and the dev auto-reload toggle come from ``Settings``
(``KESTREL_HOST`` / ``KESTREL_PORT`` / ``KESTREL_RELOAD``), so a
``backend/.env`` value is honoured.
"""
from __future__ import annotations

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
