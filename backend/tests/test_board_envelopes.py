"""Card- and coordinator-turn envelope tests (feature 026, T034/T078).

Split out of ``test_board_scheduling.py`` to keep that module under the
repo's 500-line ceiling.
"""
from __future__ import annotations

from app.models_board import SpecialistDefinition, WorkCard, Workflow
from app.services.board.dispatch import (
    build_card_envelope,
    build_coordinator_envelope,
)

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)


def _specialist(role_id: str = "developer") -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id,
        label=role_id,
        purpose="test role",
        allowed_card_types=("analysis",),
        required_abilities=(),
        model_policy="default",
        workspace_permission="read_only",
        retry_limit=1,
        prompt="You are the developer specialist.",
    )


def _coordinator_specialist() -> SpecialistDefinition:
    return SpecialistDefinition(
        id="coordinator",
        label="coordinator",
        purpose="plans work",
        allowed_card_types=(),
        required_abilities=(),
        model_policy="default",
        workspace_permission="none",
        retry_limit=1,
        prompt="You are the COORDINATOR.",
    )


class TestCardEnvelope:
    """The card envelope carries the specialist's prompt and card context."""

    def test_envelope_includes_prompt_and_card_context(self) -> None:
        specialist = _specialist()
        card = WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate the bug",
            state="claimed",
        )
        envelope = build_card_envelope(specialist, _WORKFLOW, card)
        assert "You are the developer specialist." in envelope
        assert "Investigate the bug" in envelope
        assert "analysis" in envelope

    def test_envelope_includes_the_workflows_task_body(self) -> None:
        specialist = _specialist()
        workflow = Workflow(
            id="wf-1", source="github-issue", task_ref="owner/repo#1",
            repo="owner/repo", base_branch="main",
            source_visibility="public", title="Add a thing",
            task_body="Users need to export their data as CSV.",
        )
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="analysis",
            title="Investigate", state="claimed",
        )

        envelope = build_card_envelope(specialist, workflow, card)

        assert "Users need to export their data as CSV." in envelope

    def test_envelope_includes_the_approved_prd_once_set(self) -> None:
        specialist = _specialist()
        workflow = Workflow(
            id="wf-1", source="github-issue", task_ref="owner/repo#1",
            repo="owner/repo", base_branch="main",
            source_visibility="public", title="Add a thing",
            approved_prd="Implement CSV export behind a feature flag.",
        )
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="implementation",
            title="Build it", state="claimed",
        )

        envelope = build_card_envelope(specialist, workflow, card)

        assert "Implement CSV export behind a feature flag." in envelope

    def test_envelope_includes_caller_supplied_extra_context(self) -> None:
        specialist = _specialist()
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="prd",
            title="Draft PRD", state="claimed", eligible_roles=("pm",),
        )

        envelope = build_card_envelope(
            specialist, _WORKFLOW, card,
            extra_context="### requester interview\nShip by Friday.",
        )

        assert "Ship by Friday." in envelope


class TestCoordinatorEnvelope:
    """The coordinator envelope summarizes the workflow's current cards."""

    def test_envelope_includes_prompt_and_card_summary(self) -> None:
        specialist = _coordinator_specialist()
        workflow = _WORKFLOW
        cards = [
            WorkCard(
                id="card-1",
                workflow_id="wf-1",
                kind="analysis",
                title="Investigate",
                state="ready",
            )
        ]
        envelope = build_coordinator_envelope(specialist, workflow, cards)
        assert "You are the COORDINATOR." in envelope
        assert "card-1" in envelope
        assert "ready" in envelope

    def test_envelope_includes_the_workflows_task_body(self) -> None:
        specialist = _coordinator_specialist()
        workflow = Workflow(
            id="wf-1", source="github-issue", task_ref="owner/repo#1",
            repo="owner/repo", base_branch="main",
            source_visibility="public", title="Add a thing",
            task_body="Users need to export their data as CSV.",
        )

        envelope = build_coordinator_envelope(specialist, workflow, [])

        assert "Users need to export their data as CSV." in envelope

    def test_envelope_includes_extra_context_when_given(self) -> None:
        specialist = _coordinator_specialist()

        envelope = build_coordinator_envelope(
            specialist, _WORKFLOW, [],
            extra_context="### Prior rejection feedback\nToo vague.",
        )

        assert "Too vague." in envelope

    def test_envelope_omits_extra_context_section_when_empty(self) -> None:
        specialist = _coordinator_specialist()

        envelope = build_coordinator_envelope(
            specialist, _WORKFLOW, [], extra_context="",
        )

        assert "Prior rejection feedback" not in envelope
