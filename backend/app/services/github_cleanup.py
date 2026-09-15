"""Idempotent cleanup requests for GitHub-owned workflow artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.exceptions import GitHubError

if TYPE_CHECKING:
    from app.services.github import GitHubClient


async def close_issue(client: "GitHubClient", repo: str, number: int) -> None:
    """Close an issue, treating an already-gone item as successfully cleaned."""
    try:
        await client._request(
            "PATCH", f"/repos/{repo}/issues/{number}", json={"state": "closed"}
        )
    except GitHubError as exc:
        if "-> 404:" not in str(exc):
            raise


async def delete_issue_comment(
    client: "GitHubClient", repo: str, comment_id: int
) -> None:
    """Delete a Kestrel-owned comment, treating an absent comment as clean."""
    try:
        await client._request(
            "DELETE", f"/repos/{repo}/issues/comments/{comment_id}"
        )
    except GitHubError as exc:
        if "-> 404:" not in str(exc):
            raise
