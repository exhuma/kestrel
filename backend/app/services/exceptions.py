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


class GitHubError(Exception):
    """Raised when a GitHub API call fails."""


class GitError(Exception):
    """Raised when a git subprocess fails."""


class UnconfirmedDirectPromptError(Exception):
    """A direct session prompt was not explicitly confirmed (FR-023).

    A direct session prompt intentionally addresses an agent, so it is
    not automatically quarantined like external/gate input — but it
    still requires an explicit, recorded injection-risk confirmation
    before dispatch.
    """


class DirectPromptTooLargeError(Exception):
    """A direct session prompt exceeded the configured input bound
    (FR-023)."""
