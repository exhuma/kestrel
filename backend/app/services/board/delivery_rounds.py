"""The rounds of work after a change request was opened: requested
changes, a clarification, a CI repair.

Each delivery records which finished implementation cards it covered, in
a ``delivery.round`` board event. The cards finished since then are the
current round; its line (what it was for, and whether it brought commits)
joins the history kestrel's section of the description lists, and the
change request gets one comment for it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.documents import BulletList, Document, ListItem, Text, paragraph
from app.models_board import CardKind, CardState
from app.models_board_records import BoardEventRecord
from app.persistence.board_store import BoardStore
from app.services.board.agent_text import from_agent
from app.services.board.artifacts import (
    CARD_RESULT_LOGICAL_NAME,
    ArtifactsService,
)
from app.text_extract import extract_tag

#: The board event that records one delivery and the cards it covered.
ROUND_EVENT = "delivery.round"
_SUMMARY_TAG = "CHANGE_SUMMARY"


@dataclass(frozen=True)
class RoundWork:
    """One implementation card of the current round.

    :param summary: The coder's ``<CHANGE_SUMMARY>``, or ``""``.
    """

    card_id: str
    title: str
    summary: str


@dataclass(frozen=True)
class RoundHistory:
    """What earlier deliveries recorded, and the work since the last one.

    :param lines: One line per earlier round, oldest first.
    :param current: The cards finished since the last delivery.
    """

    lines: tuple[str, ...] = ()
    current: tuple[RoundWork, ...] = field(default_factory=tuple)


def history_of(
    workflow_id: str, store: BoardStore, artifacts: ArtifactsService
) -> RoundHistory:
    """The rounds recorded for *workflow_id*, and its current round."""
    covered: set[str] = set()
    lines: list[str] = []
    for event in store.list_events(workflow_id):
        if event.event_type != ROUND_EVENT:
            continue
        payload = json.loads(event.payload or "{}")
        covered.update(payload.get("cards", []))
        if payload.get("line"):
            lines.append(str(payload["line"]))
    current = tuple(
        RoundWork(card.id, card.title, _summary(card.id, artifacts))
        for card in store.list_cards(workflow_id)
        if card.kind == CardKind.IMPLEMENTATION.value
        and card.state == CardState.DONE.value
        and card.id not in covered
    )
    return RoundHistory(tuple(lines), current)


def _summary(card_id: str, artifacts: ArtifactsService) -> str:
    text = artifacts.latest_content_for_card(card_id, CARD_RESULT_LOGICAL_NAME)
    found = extract_tag(text or "", _SUMMARY_TAG)
    return " ".join(found.split()) if found else ""


def round_line(work: tuple[RoundWork, ...], commits: list[str]) -> str:
    """The section's line for a later round."""
    what = "; ".join(item.title for item in work) or "follow-up work"
    if commits:
        return f"{what}: {len(commits)} commit(s)"
    return f"{what}: no code changes were needed"


def round_comment(
    work: tuple[RoundWork, ...], commits: list[str]
) -> Document:
    """The change request's comment for a later round."""
    what = "; ".join(item.title for item in work) or "follow-up work"
    opening = (
        f"Changes pushed for: {what}." if commits
        else f"No code changes were needed for: {what}."
    )
    blocks = [paragraph(Text(opening))]
    if commits:
        blocks.append(BulletList(tuple(
            ListItem((paragraph(Text(commit)),)) for commit in commits
        )))
    for item in work:
        said = item.summary or "(no summary given; see the request in kestrel)"
        blocks.append(paragraph(Text(f"{item.title}: ")))
        blocks.extend(from_agent(said).blocks)
    return Document(tuple(blocks))


def record_round(
    store: BoardStore, card_id: str, work: RoundHistory, line: str | None
) -> None:
    """Record that the delivery card *card_id* covered the current round."""
    card = store.get_card(card_id)
    if card is None:
        return
    store.append_event(BoardEventRecord(
        workflow_id=card.workflow_id, card_id=card_id,
        event_type=ROUND_EVENT,
        payload=json.dumps({
            "cards": [item.card_id for item in work.current],
            "line": line or "",
            "detail": line or "delivered",
        }),
    ))
