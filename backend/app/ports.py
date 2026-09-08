"""Task Source / Code Host ports and verification evidence (feature 003).

A run's origin is two distinct concerns: a **task source** (the ticket — read
it, comment on it, attach to it, deep-link to it) and a **code host** (the
repository — provision a working copy, open a merge/pull request). GitHub
implements both; Jira implements the task source and delegates the code host to
a configured, self-hostable git host (GitLab/Gitea). Keeping these as protocols
lets the workflow depend on roles, not on a concrete provider.

The verifier's grounding is modelled generically as ``Evidence`` (a list of
``Observation``s), entirely self-reported by the verifying agent while
exercising the running app for real (HTTP requests for an API boundary,
browser-driven interaction for a UI boundary — feature 005). Durable,
deterministic checks (tests, lint) are deliberately not part of this: that
coverage is the coder's TDD responsibility, not something verify
re-measures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
class Feedback:
    """One piece of marker-gated feedback read from a ticket or PR review.

    The port-level read result — not itself a database row (the persisted
    form is ``FeedbackItemRow``, ``persistence/tables.py``). ``external_id``
    is source-native and adapter-minted (e.g. GitHub's
    ``"gh-issue-comment:8812"``, Jira's ``"jira-comment:{issue}:{id}"``): it
    is what makes cross-transport dedup possible (feature 013, R3/R6) — the
    same webhook-vs-poll race a ``feedback_item`` primary key already
    guards against for other event classes in this project.
    """

    external_id: str
    origin: Literal["ticket", "review"]
    author: str
    body: str
    created_at: datetime


@dataclass
class ChangeRequest:
    """A pull/merge request's current lifecycle state (feature 013, US3/US4).

    Returned by ``CodeHost.get_change_request`` — the read a run's own
    review-feedback resume path (and, later, its terminal-run revive-vs-
    successor decision) branches on. ``state`` is deliberately the three-
    way GitHub/GitLab both expose natively rather than a boolean: a
    ``merged`` request is never conflated with a plain ``closed`` one,
    since only the latter is genuinely abandoned.
    """

    number: int
    state: Literal["open", "merged", "closed"]
    #: Browser-navigable URL, when the adapter has one to hand (best-effort).
    url: str = ""


@dataclass
class Observation:
    """One self-reported outcome the verifier weighs.

    ``kind`` distinguishes the boundary exercised: ``"http"`` (a real
    request against the running API) or ``"ui"`` (a browser-driven
    interaction). ``detail`` is a bounded excerpt — never full logs, never
    secrets.
    """

    name: str
    kind: Literal["http", "ui"]
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
        """Return failing observations (the failing-observation invariant)."""
        return [o for o in self.observations if not o.passed]


@dataclass
class LifecycleEvent:
    """One run-lifecycle transition, source-neutral (feature 006).

    Built by ``LifecycleTransitioner`` from a ``WorkflowRun`` at each
    lifecycle-worthy status change and passed to ``TaskSource.transition``
    and the operator hooks mechanism. ``kind`` is derived from
    ``run.status`` via a single exclusive mapping — a failed/escalated/
    rejected run can never produce ``kind="done"``.
    """

    kind: Literal["start", "done", "failed", "escalated", "rejected"]
    #: Cumulative active-work seconds at dispatch time, or ``None`` before
    #: time tracking has produced a value.
    active_seconds: float | None = None
    #: Cumulative time parked at a human gate, or ``None``.
    wait_seconds: float | None = None
    #: Kestrel UI deep-link to the run, or "" when no public base URL is
    #: configured.
    deep_link: str = ""


class Acknowledgeable(Protocol):
    """Shared by ``TaskSource`` and ``CodeHost`` (feature 013): whichever
    one a piece of ``Feedback`` actually came from is acknowledged the
    same way, so callers (``FeedbackIntakeService``, the poll transport)
    don't need to know or care which port they're holding."""

    async def acknowledge(
        self, feedback: Feedback, token: str = "eyes"
    ) -> bool:
        """Best-effort reaction on the triggering comment/note. Returns
        ``False`` (never raises) when the source has no such capability."""
        ...


class TaskSource(Protocol):
    """The ticket role, keyed by an opaque source-native ``ref``."""

    async def get_task(self, ref: str) -> Task:
        """Fetch the ticket's current title/body."""
        ...

    async def post_comment(self, ref: str, body: str) -> str:
        """Post a comment; return its URL (best-effort caller)."""
        ...

    async def attach(
        self, ref: str, name: str, data: bytes, mimetype: str
    ) -> None:
        """Attach a binary file to the ticket (may no-op on some sources).

        Carries raw ``data`` plus its ``mimetype`` so any file type (a
        text PRD, a PNG screenshot) can be uploaded; a source without an
        attachment API (GitHub issues) no-ops.
        """
        ...

    async def publish_refined(self, ref: str, content: str) -> None:
        """Record the approved PRD on the ticket (update body / attach)."""
        ...

    async def create_subtask(
        self, parent_ref: str, title: str, body: str
    ) -> str:
        """Create a follow-up task linked to ``parent_ref`` (feature 012).

        ``body`` is already final and self-contained (the caller has
        already run the completeness check) and already carries the
        ``SUBTASK_SENTINEL`` marker. Implementations MUST create the
        ticket without satisfying this source's own ingestion-trigger
        condition (e.g. GitHub: no ``trigger_label``), so publishing a
        follow-up task never itself starts a new run.

        :returns: The new ticket's source-native ref.
        """
        ...

    def display_label(self, ref: str) -> str:
        """Short human-readable identity for the ticket (feature 009).

        Pure formatting of ``ref`` — no I/O — so it's cheap to compute
        for every run in a list. Surfaced to the UI (workflow list and
        detail header) as the run's primary identifying label.
        """
        ...

    def deep_link_ref(self, ref: str) -> str:
        """Browser-navigable URL to the ticket, or "" (feature 009).

        "" means this source has no destination a browser can open for
        ``ref`` (e.g. a local file) — the UI shows ``display_label``
        as plain text instead of a link in that case.
        """
        ...

    async def transition(self, ref: str, event: LifecycleEvent) -> bool:
        """Best-effort native lifecycle-status transition (feature 006).

        Attempts the platform's native status mechanism for
        ``event.kind`` (e.g. a label, a workflow transition). When
        ``event.active_seconds`` is set and this source supports a native
        time field, also attempts that write — its outcome does not
        affect this method's return value.

        :returns: ``True`` iff the *status* aspect of this event was
            natively applied (a mechanism was configured for this
            ``event.kind`` and the call succeeded); ``False`` otherwise,
            including on a failed attempt (never raises). The caller
            then falls back to a comment-footer for whatever this
            returned ``False``/didn't cover.
        """
        ...

    def supports_time_spent(self) -> bool:
        """Whether this source has a configured native field for active time.

        Static per-source capability, not per-call. Time-spent support
        never varies across invocations, unlike the status transition.
        """
        ...

    def visibility(self) -> Literal["public", "private"]:
        """Whether this source's tickets are externally shared (feature 008).

        Static per-source capability, not per-call. ``"public"`` sources
        (GitHub, Jira) are externally visible and only ever move forward in
        time; ``"private"`` sources are local/disposable and safe to reset.
        The sole gate for the rerun action: rerun is refused unless this
        returns ``"private"``.
        """
        ...

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        """Comments on ``ref``, newest-cursor-forward (feature 013).

        ``since`` is this adapter's own opaque cursor (from a prior call's
        ``Feedback`` items, or a persisted ``feedback_cursor`` row), or
        ``None`` to read from the beginning. The port stays ignorant of
        each source's own pagination scheme (GitHub's ``since=``
        timestamp, Jira's ``startAt``, fixture's line offset).
        """
        ...

    async def acknowledge(
        self, feedback: Feedback, token: str = "eyes"
    ) -> bool:
        """Best-effort reaction on the triggering comment (feature 013).

        :returns: ``False`` (never raises) when this source has no such
            capability.
        """
        ...

    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe (feature 014).

        A single cheap, read-only, ticket-independent call (e.g. "who am
        I") — never a specific ``ref``, since this checks the adapter
        itself, not any one ticket. MUST NOT raise: any failure (network,
        auth, timeout, malformed response) is caught internally and
        reported as ``False`` (contracts/health-check-port.md).
        """
        ...


class CodeHost(Protocol):
    """The repository role, keyed by ``owner/name`` (or a GitLab path)."""

    async def get_default_branch(self, repo: str) -> str:
        """The repo's default branch.

        Requires a specific, already-valid ``repo`` — for a repo-
        independent reachability/auth check, see ``check_health``
        (feature 014).
        """
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

    async def get_change_request(
        self, repo: str, number: int
    ) -> ChangeRequest:
        """Fetch a pull/merge request's current lifecycle state.

        The read a review-feedback resume decides on (feature 013,
        US3/US4): an ``open`` request resumes the same branch, a
        ``merged``/``closed`` one instead starts a linked successor.
        """
        ...

    async def list_review_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[Feedback]:
        """Every reviewer-authored signal on the request, ``origin="review"``.

        Merges the request's conversation comments, review-body comments,
        and inline review comments into one newest-cursor-forward list —
        the same ``since``-cursor contract as ``TaskSource.list_comments``.
        """
        ...

    async def acknowledge(
        self, feedback: Feedback, token: str = "eyes"
    ) -> bool:
        """Best-effort reaction on the triggering review comment.

        :returns: ``False`` (never raises) when this source has no such
            capability, or ``feedback`` does not carry a reactable
            ``external_id`` (e.g. a review's own summary comment, which
            GitHub exposes no reaction endpoint for).
        """
        ...

    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe (feature 014).

        A single cheap, read-only, repo-independent call (e.g. "who am
        I"). MUST NOT raise: any failure (network, auth, timeout,
        malformed response) is caught internally and reported as
        ``False`` (contracts/health-check-port.md).
        """
        ...
