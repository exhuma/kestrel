"""Domain exceptions raised by the service layer.

These cross the service -> router boundary and are mapped to HTTP
responses by handlers registered at app-factory time. Routers and
services never raise built-in exceptions (KeyError, RuntimeError) as
cross-layer error signals.
"""
from __future__ import annotations


class GitHubError(Exception):
    """Raised when a GitHub API call fails."""


class GitError(Exception):
    """Raised when a git subprocess fails."""
