"""Provider-status normalization shared by CodeHost adapters."""
from __future__ import annotations

from app.ports import RequiredCiStatus


def github_status(name: str, entry: dict | None) -> RequiredCiStatus:
    """Map one GitHub check-run or legacy status to a portable state."""
    if entry is None:
        return RequiredCiStatus(name, "pending")
    conclusion = entry.get("conclusion") or entry.get("state")
    if conclusion in ("success", "neutral", "skipped"):
        return RequiredCiStatus(name, "passed")
    if conclusion in ("failure", "error", "cancelled", "timed_out"):
        return RequiredCiStatus(name, "failed", entry.get("details_url") or "")
    return RequiredCiStatus(name, "pending")


def gitlab_status(name: str, job: dict | None) -> RequiredCiStatus:
    """Map one GitLab job to a portable state."""
    if job is None:
        return RequiredCiStatus(name, "pending")
    status = job.get("status")
    if status in ("success", "skipped", "manual"):
        return RequiredCiStatus(name, "passed")
    if status in ("failed", "canceled"):
        return RequiredCiStatus(name, "failed", job.get("web_url") or "")
    return RequiredCiStatus(name, "pending")
