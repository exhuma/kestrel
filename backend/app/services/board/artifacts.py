"""Card-result acceptance, dependency cascade, and reconciliation (feature
026, T030/T033/T039).

Accepting one card's result is the trigger point for two things policy
governs independently: cascading dependents toward ``ready`` once every
``dependency``-kind edge resolves (FR-010 depends on this to produce
ready work at all), and never letting one specialist's output silently
overwrite another's — a conflicting sibling output creates a
reconciliation card instead (FR-026). ``submit_result`` additionally
writes the result's body to durable, content-addressed storage first
(FR-013), so ``content_hash`` is always exactly what was stored rather
than a caller-asserted value.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
)
from app.models_board_records import HandoffArtifact
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_store import BoardStore
from app.services.board.dependents import advance_ready_dependents
from app.services.board.service import BoardService


@dataclass(frozen=True)
class ArtifactDraft:
    """A card result awaiting durable storage.

    Like :class:`HandoffArtifact` but without ``id``/``content_ref``/
    ``content_hash`` — :meth:`ArtifactsService.submit_result` derives all
    three once the content is actually written.
    """

    producer_card_id: str
    logical_name: str
    revision: int
    content: str
    trust: str
    mime_type: str = "text/plain"
    retention: str = "standard"
    project_material: bool = False
    input_artifacts: tuple[str, ...] = ()


class ArtifactsService:
    """Accepts card results, cascades dependents, and reconciles conflicts."""

    def __init__(
        self,
        store: BoardStore,
        artifact_store: BoardArtifactStore,
        board_service: BoardService,
        content_store: BoardArtifactContentStore | None = None,
    ) -> None:
        self._store = store
        self._artifact_store = artifact_store
        self._board_service = board_service
        self._content_store = content_store

    def submit_result(self, draft: ArtifactDraft) -> WorkCard:
        """Durably store *draft*'s content and accept it as its card's
        result.

        :raises ValueError: If this service has no content store
            configured.
        """
        artifact = self._write(draft)
        return self.accept_result(draft.producer_card_id, artifact)

    def store_reference_artifact(self, draft: ArtifactDraft) -> HandoffArtifact:
        """Durably store *draft*'s content as a plain reference, with no
        card-acceptance side effect (no state transition, no dependency
        cascade, no conflict check).

        For content a card produces *alongside* its own already-accepted
        result — e.g. a decomposition candidate a ``decomposition_gate``
        needs to reference (``HumanGateRecord.target_artifact_id``) once
        the producing card is already ``done``.

        :raises ValueError: If this service has no content store
            configured.
        """
        artifact = self._write(draft)
        return self._artifact_store.record(artifact)

    def read_content(self, artifact_id: str) -> str | None:
        """Return one artifact's content by id, or ``None`` if unknown.

        :raises ValueError: If this service has no content store
            configured.
        """
        if self._content_store is None:
            raise ValueError("no content store configured")
        artifact = self._artifact_store.get(artifact_id)
        if artifact is None:
            return None
        return self._content_store.read(artifact.content_ref)

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

        :raises ValueError: If this service has no content store
            configured.
        """
        if self._content_store is None:
            raise ValueError("no content store configured")
        matches = [
            a for a in self._artifact_store.list_for_card(card_id)
            if a.logical_name == logical_name
        ]
        if not matches:
            return None
        latest = max(matches, key=lambda a: a.revision)
        return self._content_store.read(latest.content_ref)

    def _write(self, draft: ArtifactDraft) -> HandoffArtifact:
        if self._content_store is None:
            raise ValueError("no content store configured")
        content_ref, content_hash = self._content_store.write(draft.content)
        return HandoffArtifact(
            id=f"artifact-{uuid.uuid4().hex[:8]}",
            producer_card_id=draft.producer_card_id,
            logical_name=draft.logical_name,
            revision=draft.revision,
            content_ref=content_ref,
            content_hash=content_hash,
            trust=draft.trust,
            mime_type=draft.mime_type,
            retention=draft.retention,
            project_material=draft.project_material,
            input_artifacts=draft.input_artifacts,
        )

    def accept_result(
        self, card_id: str, artifact: HandoffArtifact
    ) -> WorkCard:
        """Record *artifact*, complete its card, and cascade the board.

        The artifact is recorded regardless of a detected conflict — a
        conflicting output is never overwritten, only flagged via a new
        reconciliation card (FR-026).
        """
        recorded = self._artifact_store.record(artifact)
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

    def _find_conflict(
        self, card_id: str, artifact: HandoffArtifact
    ) -> HandoffArtifact | None:
        """Return a sibling artifact sharing this logical name but not this
        content, if one exists."""
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
