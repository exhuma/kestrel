"""The understanding step: `pm` restates the request, the operator
confirms or corrects it (feature 032, #67).

Before any deeper work, kestrel states back what it understood the
request to be — the cheapest point to catch a misunderstanding. An
``understanding`` card has `pm` write a short restatement; only a
readable one opens the ``understanding_gate``, which targets it so the
cockpit can show it. A rejection carries the operator's correction, and
earns a redraft that sees both the rejected restatement and the
correction, up to a cap; past it, a coordinator review is opened
instead of redrafting for ever (research R6/R7) — see
``understanding_redraft.py``, split out so ``gates.py`` can call it
without an import cycle.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models_board import CardKind, CardState, WorkCard
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.retries import UnreadableResultError, live_attempts
from app.text_extract import extract_tag

if TYPE_CHECKING:
    from app.services.board.gates import GatesService

#: Logical name of the restatement an ``understanding`` card produces.
RESTATEMENT_LOGICAL_NAME = "restatement"

#: Where a resolved gate keeps the operator's free-text answer (see
#: ``gates.py``'s ``_RESPONSE_LOGICAL_NAME``).
_RESPONSE_LOGICAL_NAME = "response"


def route_understanding_result(
    text: str,
    card: WorkCard,
    gates: "GatesService",
    artifacts: ArtifactsService,
) -> None:
    """Open the understanding gate on *card*'s restatement, or escalate
    when there is none to show (fail closed, FR-010)."""
    restatement = (extract_tag(text, "UNDERSTANDING") or "").strip()
    if not restatement:
        raise UnreadableResultError(
            f"Unreadable restatement on card {card.id}",
            "no <UNDERSTANDING> block with a restatement",
        )
    artifact = artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name=RESTATEMENT_LOGICAL_NAME,
            revision=card.attempt_count,
            content=restatement,
            trust="agent_output",
            mime_type="text/markdown",
        )
    )
    gates.create_gate(
        card.workflow_id,
        kind=CardKind.UNDERSTANDING_GATE.value,
        title="Confirm understanding",
        requested_decision="confirm_understanding",
        target_artifact_id=artifact.id,
    )


def understanding_context(
    card: WorkCard, store: BoardStore, artifacts: ArtifactsService
) -> str:
    """For a redraft: the rejected restatement and the operator's
    correction. ``""`` for a first draft."""
    cards = store.list_cards(card.workflow_id)
    rejected = [
        c for c in cards
        if c.kind == CardKind.UNDERSTANDING_GATE.value
        and c.state == CardState.CANCELLED.value
    ]
    drafts = [
        c for c in live_attempts(cards)
        if c.kind == CardKind.UNDERSTANDING.value and c.id != card.id
    ]
    if not rejected or not drafts:
        return ""
    previous = artifacts.latest_content_for_card(
        drafts[-1].id, RESTATEMENT_LOGICAL_NAME
    )
    correction = artifacts.latest_content_for_card(
        rejected[-1].id, _RESPONSE_LOGICAL_NAME
    )
    return (
        "This is a redraft: the operator rejected your previous "
        "restatement. Take their correction into account.\n\n"
        f"Previous restatement:\n{previous or '(not recorded)'}\n\n"
        f"Operator's correction:\n{correction or '(none given)'}"
    )
