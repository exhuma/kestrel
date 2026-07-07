"""Tests for request-schema validation (security-relevant guards)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import CreateWorkflowIn


@pytest.mark.parametrize(
    "repo",
    [
        "octocat/hello-world",
        "a/b",
        "Org123/repo.name_v2",
        "user/repo-with-dots.and_underscores",
    ],
)
def test_valid_repo_slugs_accepted(repo: str) -> None:
    """Ensure ordinary owner/repo slugs pass validation."""
    assert CreateWorkflowIn(repo=repo, issue_number=1).repo == repo


@pytest.mark.parametrize(
    "repo",
    [
        "-oops/repo",           # leading dash: git/REST argument injection
        "owner/-oops",          # dash-led repo segment
        "../etc/passwd",        # path traversal
        "owner/../../etc",      # embedded traversal
        "owner/repo/extra",     # too many segments
        "ownerrepo",            # no slash
        "owner /repo",          # whitespace
        "owner/repo\n",         # control char / newline
        "owner/re po",          # inner whitespace
        "",                     # empty
        "owner/",               # empty repo segment
        "/repo",                # empty owner segment
        "https://evil/o/r",     # url-shaped
    ],
)
def test_malicious_repo_slugs_rejected(repo: str) -> None:
    """Ensure injection/traversal/malformed slugs raise a validation error."""
    with pytest.raises(ValidationError):
        CreateWorkflowIn(repo=repo, issue_number=1)
