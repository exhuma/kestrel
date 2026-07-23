"""Command-line entrypoint: ``serve`` (default) and ``poll`` (feature 004).

``serve`` launches uvicorn with unified logging (the historical behaviour of
``python -m app``). ``poll`` is a read-only dry-run that lists what every
configured task source currently matches — its work items and resolved repos —
without starting any run, so an operator can verify a source's configuration.
"""
from __future__ import annotations

import argparse
import asyncio

import uvicorn
from dotenv import load_dotenv

from app.config import Settings, get_settings
from app.logging_config import build_log_config
from app.ports import WorkItem
from app.services.poll_source import configured_poll_sources


def load_env() -> None:
    """Load ``backend/.env`` into the process environment.

    ``pydantic-settings`` reads ``.env`` into ``Settings`` fields, but the
    dynamic named-secret lookups (a source's ``token_env`` / a backend's
    ``api_key_env``, and the standard ``OTEL_*`` vars) resolve against
    ``os.environ`` — which ``.env`` does not otherwise populate. Loading it
    here, at the real entrypoint (not in library code, so tests stay isolated),
    makes ``.env`` authoritative for the whole process. Existing environment
    values win (``override=False``), matching pydantic's env>dotenv precedence.
    """
    load_dotenv(".env")


def cmd_serve(settings: Settings) -> int:
    """Start uvicorn for ``app.main:app`` with the configured logging."""
    log_config = build_log_config(settings.log_level, settings.log_format)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=log_config,
        reload=settings.reload,
    )
    return 0


def _print_items(name: str, items: list[WorkItem]) -> None:
    """Print one source's matched work items (or an empty marker)."""
    print(f"{name}:")
    if not items:
        print("  (no matching work items)")
        return
    for item in items:
        repo = item.code_repo or "(unresolved repository)"
        print(f"  {item.ref}\t{item.title}\t-> {repo}")


async def _run_poll(settings: Settings) -> int:
    """List every configured source's work items; start no runs."""
    sources = configured_poll_sources(settings)
    if not sources:
        print("No task sources configured.")
        return 0
    for source in sources:
        try:
            items = await source.list_work_items()
        except Exception as exc:  # noqa: BLE001 — report, keep going
            print(f"{source.name}: error listing work items: {exc}")
            continue
        _print_items(source.name, items)
    return 0


def cmd_poll(settings: Settings) -> int:
    """Run the read-only poll dry-run across all sources."""
    return asyncio.run(_run_poll(settings))


def build_parser() -> argparse.ArgumentParser:
    """Build the ``serve`` / ``poll`` argument parser (serve is default)."""
    parser = argparse.ArgumentParser(prog="app")
    parser.set_defaults(func=cmd_serve)
    sub = parser.add_subparsers()
    sub.add_parser("serve", help="run the API server (default)").set_defaults(
        func=cmd_serve
    )
    sub.add_parser("poll", help="dry-run: list matching items").set_defaults(
        func=cmd_poll
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected command."""
    args = build_parser().parse_args(argv)
    return args.func(get_settings())
