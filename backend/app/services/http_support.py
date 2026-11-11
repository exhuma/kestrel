"""Shared helpers for the outbound HTTP clients (GitHub, ...)."""
from __future__ import annotations

from weakref import WeakSet

import httpx

#: Longest slice of a failed response body kept in an error message.
ERROR_BODY_LIMIT = 500

#: Every tracked client, so the app lifespan can close them in one place.
_tracked_clients: WeakSet[httpx.AsyncClient] = WeakSet()


def truncate_body(text: str, limit: int = ERROR_BODY_LIMIT) -> str:
    """
    Bound a response body so an error message stays readable.

    :param text: The raw response body.
    :param limit: Maximum characters to keep.
    :returns: *text*, cut to *limit* characters with a marker when cut.
    """
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [{len(text) - limit} more characters]"


def track_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """
    Register *client* to be closed by :func:`close_tracked_clients`.

    :param client: A long-lived client owned by an API wrapper.
    :returns: *client*, for use in an assignment.
    """
    _tracked_clients.add(client)
    return client


async def close_tracked_clients() -> None:
    """Close every tracked client (app shutdown)."""
    for client in list(_tracked_clients):
        await client.aclose()
