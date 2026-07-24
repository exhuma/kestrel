"""Task Source / Code Host ports and verification evidence (feature 003).

A run's origin is two distinct concerns: a **task source** (the ticket — read
it, comment on it, attach to it, deep-link to it) and a **code host** (the
repository — provision a working copy, open a merge/pull request). GitHub
implements both; Jira implements the task source and delegates the code host to
a configured, self-hostable git host (GitLab/Gitea). Keeping these as protocols
lets the workflow depend on roles, not on a concrete provider.

The verifier's grounding is modelled generically as ``Evidence`` (a list of
``Observation``s). v1 ships a ``kind="check"`` gatherer; the assumed behavioural
harness (run the app, exercise it via HTTP / Playwright → ``kind="http"``/
``"ui"`` observations) drops into the same shape without a workflow change
(FR-015a/FR-015b).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class Task:
    """A source ticket: its native ref plus title/body text."""

    #: Source-native ticket id (also the run's ``task_ref``): GitHub
    #: ``"owner/name#123"``, Jira the issue key ``"RFC-123"``.
    ref: str
    title: str
    body: str


@dataclass
class WorkItem:
    """A transient dry-run view of one polled item (feature 004).

    Produced by a source's non-ingesting listing (``python -m app poll``);
    persists nothing and starts no run. ``code_repo`` is ``None`` when the
    repository could not be resolved.
    """

    source: str
    ref: str
    title: str
    code_repo: str | None = None
    base_branch: str | None = None


@dataclass
class Observation:
    """One measured outcome the verifier weighs.

    ``kind`` distinguishes the evidence source: ``"check"`` (a configured
    command's pass/fail — the v1 gatherer), ``"http"`` (a real request against
    the running API), or ``"ui"`` (a browser-driven interaction). ``detail`` is
    a bounded excerpt — never full logs, never secrets.
    """

    name: str
    kind: Literal["http", "ui", "check"]
    passed: bool
    detail: str = ""


@dataclass
class Evidence:
    """The evidence bundle for one verify round (empty ⇒ judgment-only)."""

    observations: list[Observation] = field(default_factory=list)

    def all_passed(self) -> bool:
        """Return whether every observation passed (vacuously true if empty)."""
        return all(o.passed for o in self.observations)

    def failures(self) -> list[Observation]:
        """Return failing observations (the failing-check invariant)."""
        return [o for o in self.observations if not o.passed]


class TaskSource(Protocol):
    """The ticket role, keyed by an opaque source-native ``ref``."""

    async def get_task(self, ref: str) -> Task:
        """Fetch the ticket's current title/body."""
        ...

    async def post_comment(self, ref: str, body: str) -> str:
        """Post a comment; return its URL (best-effort caller)."""
        ...

    async def attach(self, ref: str, name: str, content: str) -> None:
        """Attach a file (the PRD) to the ticket (may no-op on some sources)."""
        ...

    async def publish_refined(self, ref: str, content: str) -> None:
        """Record the approved PRD on the ticket (update body / attach)."""
        ...

    def deep_link_ref(self, ref: str) -> str:
        """Source-native URL to the ticket (operator logs); may return ""."""
        ...


class CodeHost(Protocol):
    """The repository role, keyed by ``owner/name`` (or a GitLab path)."""

    async def get_default_branch(self, repo: str) -> str:
        """The repo's default branch (also the reachability probe)."""
        ...

    def clone_remote(self, repo: str) -> str:
        """The HTTPS git remote a worktree clones/fetches from."""
        ...

    def git_credential(self) -> tuple[str, str]:
        """The ``(username, token)`` for git-over-HTTPS Basic auth.

        ``x-access-token`` for GitHub, ``oauth2`` for GitLab — the username
        git's smart-HTTP endpoint expects alongside the code-host token.
        """
        ...

    async def open_change_request(
        self,
        repo: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool = True,
    ) -> str:
        """Open a pull/merge request; return its URL."""
        ...
