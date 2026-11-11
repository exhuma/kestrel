"""Tests for the shared outbound-HTTP helpers."""
from __future__ import annotations

import pytest

from app.services.github import GitHubClient
from app.services.http_support import close_tracked_clients, truncate_body


def test_truncate_body_keeps_short_text() -> None:
    """Ensure a body within the limit is returned unchanged."""
    assert truncate_body("short", limit=10) == "short"


def test_truncate_body_cuts_long_text_with_marker() -> None:
    """Ensure an over-long body is cut and says how much was dropped."""
    assert truncate_body("x" * 30, limit=10) == (
        "x" * 10 + "... [20 more characters]"
    )


@pytest.mark.asyncio
async def test_close_tracked_clients_closes_github_clients() -> None:
    """Ensure the shutdown hook closes a GitHub client's connection pool."""
    client = GitHubClient("https://api.github.com", "tok")
    await close_tracked_clients()
    assert client._http.is_closed
