"""Untrusted-input screening shared by the workflow gate/answer routes.

Split out of ``workflows.py`` for module-length budget. Untrusted
human-gate input (an edit, answer, or change request) must clear the
same fail-closed boundary as external input (FR-018): the original gate
stays unresolved and a security review is created instead of applying
the content (US4 AC4).
"""
from __future__ import annotations

from app.services.board.quarantine import (
    ExistingWorkflowIntake,
    QuarantineService,
)


async def screen_gate_input(
    quarantine: QuarantineService,
    workflow_id: str,
    category: str,
    content: str,
) -> dict[str, object] | None:
    """Screen operator-submitted gate content before it resolves a gate.

    Empty content (e.g. an approval with no edited deliverable) needs no
    screening.

    :returns: A ``{"status": "quarantined", ...}`` body when blocked, or
        ``None`` when the content is safe and the caller should proceed.
    """
    if not content:
        return None
    outcome = await quarantine.intake_for_existing_workflow(
        ExistingWorkflowIntake(
            identity_ref=workflow_id, category=category, content=content
        )
    )
    if outcome.released:
        return None
    return {
        "status": "quarantined",
        "security_review_id": outcome.security_review_id,
    }


def answers_text(answers: dict[str, object]) -> str:
    """Flatten a questionnaire answer set into one screenable blob."""
    return "\n".join(f"{k}: {v}" for k, v in answers.items())
