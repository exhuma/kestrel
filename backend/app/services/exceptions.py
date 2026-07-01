"""Domain exceptions raised by the service layer.

These cross the service -> router boundary and are mapped to HTTP
responses by handlers registered at app-factory time. Routers and
services never raise built-in exceptions (KeyError, RuntimeError) as
cross-layer error signals.
"""
from __future__ import annotations


class SessionNotFoundError(Exception):
    """Raised when an operation targets an unknown session id."""

    def __init__(self, session_id: str) -> None:
        """
        :param session_id: The session id that was not found.
        """
        self.session_id = session_id
        super().__init__(f"unknown session: {session_id}")


class SessionStartError(Exception):
    """Raised when a session subprocess yields no session id."""
