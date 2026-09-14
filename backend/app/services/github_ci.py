"""GitHub-specific required-CI retrieval behind the neutral CodeHost port."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.ports import RequiredCiStatus
from app.services.ci_status import github_status

if TYPE_CHECKING:
    from app.services.github import GitHubClient


async def required_ci_statuses(
    client: "GitHubClient", repo: str, number: int, names: list[str]
) -> list[RequiredCiStatus]:
    """Read a PR head's GitHub checks and normalize requested names."""
    pull = await client.get_pull_request(repo, number)
    sha = pull["head"]["sha"]
    checks = await client._request(
        "GET", f"/repos/{repo}/commits/{sha}/check-runs"
    )
    statuses = await client._request(
        "GET", f"/repos/{repo}/commits/{sha}/status"
    )
    entries = [
        *checks.json().get("check_runs", []),
        *statuses.json().get("statuses", []),
    ]
    by_name = {
        entry.get("name") or entry.get("context"): entry for entry in entries
    }
    return [github_status(name, by_name.get(name)) for name in names]
