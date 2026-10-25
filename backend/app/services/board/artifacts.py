"""Card-result acceptance, dependency cascade, and reconciliation (feature
026, T030/T033/T039).

Accepting one card's result is the trigger point for two things policy
governs independently: cascading dependents toward ``ready`` once every
``dependency``-kind edge resolves (FR-010 depends on this to produce
ready work at all), and never letting one specialist's output silently
overwrite another's — a conflicting sibling output creates a
reconciliation card instead (FR-026). ``submit_result`` records the
result's body with it (FR-013) and derives ``content_hash`` from that
body, so the hash is always exactly what was stored rather than a
caller-asserted value.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from app.documents import Document
from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
)
from app.models_board_records import HandoffArtifact
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_store import BoardStore
from app.persistence.document_column import (
    DOCUMENT_MIME,
    decode_document,
    encode_document,
)
from app.services.board.dependents import advance_ready_dependents
from app.services.board.service import BoardService


@dataclass(frozen=True)
class ArtifactDraft:
    """A card result awaiting durable storage.

    Like :class:`HandoffArtifact` but with its content and without
    ``id``/``content_hash`` — :meth:`ArtifactsService.submit_result`
    derives both when it records the content.
    """

    producer_card_id: str
    logical_name: str
    revision: int
    content: str
    trust: str
    mime_type: str = "text/plain"
    input_artifacts: tuple[str, ...] = ()


#: The logical name every card's own turn result is stored under. It is
#: that card's result, not a deliverable shared with other cards, so two
#: of them differing is expected — never a conflict to reconcile (#70:
#: flagging them turned every second result into a reconciliation card
#: nobody could work). Real conflicts stay the coordinator's call.
CARD_RESULT_LOGICAL_NAME = "report"


class ArtifactsService:
    """Accepts card results, cascades dependents, and reconciles conflicts."""

    def __init__(
        self,
        store: BoardStore,
        artifact_store: BoardArtifactStore,
        board_service: BoardService,
    ) -> None:
        self._store = store
        self._artifact_store = artifact_store
        self._board_service = board_service

    def submit_result(self, draft: ArtifactDraft) -> WorkCard:
        """Record *draft* and accept it as its card's result.

        The artifact is recorded regardless of a detected conflict — a
        conflicting output is never overwritten, only flagged via a new
        reconciliation card (FR-026).
        """
        recorded = self._record(draft)
        card_id = draft.producer_card_id
        conflict = self._find_conflict(card_id, recorded)
        card = self._board_service.transition_card(
            card_id, CardState.DONE.value, event_type="card.result_accepted"
        )
        if conflict is not None:
            self._create_reconciliation_card(
                card.workflow_id, recorded, conflict
            )
        advance_ready_dependents(
            self._store, self._board_service, card.workflow_id
        )
        return card

    def store_reference_artifact(self, draft: ArtifactDraft) -> HandoffArtifact:
        """Durably store *draft*'s content as a plain reference, with no
        card-acceptance side effect (no state transition, no dependency
        cascade, no conflict check).

        For content a card produces *alongside* its own already-accepted
        result — e.g. a decomposition candidate a ``decomposition_gate``
        needs to reference (``HumanGateRecord.target_artifact_id``) once
        the producing card is already ``done``.
        """
        return self._record(draft)

    def store_document(
        self, producer_card_id: str, logical_name: str, revision: int,
        value: Document, *, trust: str = "agent_output",
    ) -> HandoffArtifact:
        """Store a document as a reference artifact (feature 046)."""
        return self.store_reference_artifact(ArtifactDraft(
            producer_card_id=producer_card_id, logical_name=logical_name,
            revision=revision, content=encode_document(value), trust=trust,
            mime_type=DOCUMENT_MIME,
        ))

    def read_document(self, artifact_id: str) -> Document | None:
        """One artifact as a document, or ``None`` if unknown."""
        content = self.read_content(artifact_id)
        return decode_document(content) if content is not None else None

    def latest_document_for_card(
        self, card_id: str, logical_name: str
    ) -> Document | None:
        """The newest ``logical_name`` artifact of *card_id* as a
        document, or ``None`` if there is none."""
        latest = self.latest_for_card(card_id, logical_name)
        return self.read_document(latest.id) if latest is not None else None

    def read_content(self, artifact_id: str) -> str | None:
        """Return one artifact's content by id, or ``None`` if unknown."""
        return self._artifact_store.read_content(artifact_id)

    def producer_card_id(self, artifact_id: str) -> str | None:
        """Return the card that produced *artifact_id*, or ``None`` if
        unknown (feature 028 — recovering a ``refinement_gate``'s
        persona from its target artifact's origin card, with no need
        for the gate card itself to carry that information)."""
        artifact = self._artifact_store.get(artifact_id)
        return artifact.producer_card_id if artifact is not None else None

    def latest_content_for_card(
        self, card_id: str, logical_name: str
    ) -> str | None:
        """Return the newest ``logical_name`` artifact's content for
        *card_id*, or ``None`` if none exists (T078 — e.g. a resolved
        gate's stored operator response).
        """
        latest = self.latest_for_card(card_id, logical_name)
        return self.read_content(latest.id) if latest is not None else None

    def latest_for_card(
        self, card_id: str, logical_name: str
    ) -> HandoffArtifact | None:
        """Return the newest ``logical_name`` artifact *card_id*
        produced, or ``None`` if there is none."""
        matches = [
            a for a in self._artifact_store.list_for_card(card_id)
            if a.logical_name == logical_name
        ]
        return max(matches, key=lambda a: a.revision) if matches else None

    def _record(self, draft: ArtifactDraft) -> HandoffArtifact:
        artifact = HandoffArtifact(
            id=f"artifact-{uuid.uuid4().hex[:8]}",
            producer_card_id=draft.producer_card_id,
            logical_name=draft.logical_name,
            revision=draft.revision,
            content_hash=hashlib.sha256(
                draft.content.encode("utf-8")
            ).hexdigest(),
            trust=draft.trust,
            mime_type=draft.mime_type,
            input_artifacts=draft.input_artifacts,
        )
        return self._artifact_store.record(artifact, draft.content)

    def _find_conflict(
        self, card_id: str, artifact: HandoffArtifact
    ) -> HandoffArtifact | None:
        """Return a sibling artifact sharing this logical name but not this
        content, if one exists — never for a card's own result."""
        if artifact.logical_name == CARD_RESULT_LOGICAL_NAME:
            return None
        card = self._store.get_card(card_id)
        for sibling in self._store.list_cards(card.workflow_id):
            if sibling.id == card_id:
                continue
            for existing in self._artifact_store.list_for_card(sibling.id):
                if (
                    existing.logical_name == artifact.logical_name
                    and existing.content_hash != artifact.content_hash
                ):
                    return existing
        return None

    def _create_reconciliation_card(
        self,
        workflow_id: str,
        first: HandoffArtifact,
        second: HandoffArtifact,
    ) -> WorkCard:
        card = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id,
            kind=CardKind.RECONCILIATION,
            title=f"Reconcile conflicting '{first.logical_name}'",
            state=CardState.READY,
        )
        self._store.create_card(card)
        producer_ids = (first.producer_card_id, second.producer_card_id)
        for producer_card_id in producer_ids:
            self._store.add_relation(
                CardRelation(
                    card.id,
                    producer_card_id,
                    kind=RelationKind.RECONCILIATION,
                )
            )
        return card
