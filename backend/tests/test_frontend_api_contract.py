"""Every API call the frontend makes reaches a backend route.

Nothing else ties the two together: a route removed as unused while a
page still fetches it passes every other test, and the page just stays
empty.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.main import create_app

_FRONTEND_SRC = Path(__file__).parents[2] / "frontend" / "src"
#: An API path in a string or template literal.
_CALL = re.compile(r"[`'\"](?:\$\{API_BASE\})?(/api/[^`'\"?]+)")
#: A path parameter, in either side's spelling.
_PARAMETER = re.compile(r"\$?\{[^}]*\}")


def _normalised(path: str) -> str:
    return _PARAMETER.sub("{}", path).rstrip("/")


def _frontend_calls() -> dict[str, str]:
    """Each called path, with the file that calls it."""
    calls: dict[str, str] = {}
    for source in [*_FRONTEND_SRC.rglob("*.ts"), *_FRONTEND_SRC.rglob("*.vue")]:
        for line in source.read_text().splitlines():
            if line.lstrip().startswith(("*", "/*", "//")):
                continue
            for path in _CALL.findall(line):
                calls[_normalised(path)] = source.name
    return calls


def test_every_frontend_call_has_a_backend_route() -> None:
    """Ensure no page calls an endpoint that does not exist."""
    routes = {_normalised(path) for path in create_app().openapi()["paths"]}

    missing = {
        path: name
        for path, name in _frontend_calls().items()
        if path not in routes
    }

    assert missing == {}


def test_the_scan_finds_the_frontends_calls() -> None:
    """Ensure the check above is not passing by finding nothing."""
    assert "/api/board/workflows/{}/events" in _frontend_calls()
