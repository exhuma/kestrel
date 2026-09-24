"""The event-driven board coordinator (feature 026, FR-004..FR-006).

The coordinator only *proposes* bounded, structured actions; it never
mutates the board directly. Every proposal is recorded in the ledger and
validated against deterministic policy before it can create, transition,
or link a card — an invalid or malformed proposal is rejected and
mutates nothing (Edge Cases). Only the coordinator creates downstream
cards (FR-006); specialists submit proposals, they don't act on them.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    CoordinatorActionRecord,
    RelationKind,
    WorkCard,
    WorkspacePermission,
)
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_store import BoardStore
from app.services.board.policy import is_valid_transition
from app.services.board.service import BoardService
from app.text_extract import extract_tag

_VALID_CARD_KINDS = frozenset(k.value for k in CardKind)
_VALID_WORKSPACE_PERMISSIONS = frozenset(p.value for p in WorkspacePermission)
_MIN_RECONCILIATION_CARDS = 2


@dataclass(frozen=True)
class CreateCardAction:
    """Propose a new card (FR-006). ``depends_on`` names existing cards."""

    kind: str
    title: str
    eligible_roles: tuple[str, ...] = ()
    workspace_permission: str = "none"
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransitionCardAction:
    """Propose moving an existing card to a new state."""

    card_id: str
    target_state: str


@dataclass(frozen=True)
class CreateReconciliationCardAction:
    """Propose a reconciliation card linking conflicting outputs (FR-026)."""

    title: str
    conflicting_card_ids: tuple[str, ...]


ProposedAction = (
    CreateCardAction | TransitionCardAction | CreateReconciliationCardAction
)

_ACTION_FIELDS = {
    "create_card": (
        CreateCardAction,
        (
            "kind",
            "title",
            "eligible_roles",
            "workspace_permission",
            "depends_on",
        ),
    ),
    "transition_card": (TransitionCardAction, ("card_id", "target_state")),
    "create_reconciliation_card": (
        CreateReconciliationCardAction,
        ("title", "conflicting_card_ids"),
    ),
}


def parse_coordinator_actions(text: str) -> list[ProposedAction] | None:
    """Parse the coordinator's ``<COORDINATOR_ACTIONS>`` block.

    Unknown action types are silently dropped rather than failing the
    whole batch — a partially-understood proposal still lets the known
    actions through policy validation. Returns ``None`` only when the tag
    is absent or the block isn't valid JSON of the right shape (treated
    by the caller as "propose nothing this cycle").
    """
    raw = extract_tag(text, "COORDINATOR_ACTIONS")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        entries = data["actions"]
        if not isinstance(entries, list):
            return None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    actions: list[ProposedAction] = []
    for entry in entries:
        action = _parse_one_action(entry)
        if action is not None:
            actions.append(action)
    return actions


def _parse_one_action(entry: object) -> ProposedAction | None:
    """Parse one action entry, or ``None`` if its shape is unrecognized."""
    if not isinstance(entry, dict):
        return None
    spec = _ACTION_FIELDS.get(entry.get("type"))
    if spec is None:
        return None
    action_cls, fields = spec
    try:
        kwargs = {
            field: tuple(entry[field]) if isinstance(entry[field], list)
            else entry[field]
            for field in fields
            if field in entry
        }
        return action_cls(**kwargs)
    except TypeError:
        return None


class CoordinatorService:
    """Validates and applies coordinator-proposed board actions."""

    def __init__(
        self,
        store: BoardStore,
        coordinator_store: BoardCoordinatorStore,
        board_service: BoardService,
    ) -> None:
        self._store = store
        self._coordinator_store = coordinator_store
        self._board_service = board_service

    def apply_actions(
        self,
        workflow_id: str,
        trigger: str,
        actions: list[ProposedAction],
    ) -> list[CoordinatorActionRecord]:
        """Validate and apply each proposed action, recording every one.

        Idempotent per ``(workflow_id, trigger)``: a second call for a
        trigger already recorded for this workflow is a no-op, so a
        replayed wake-up event cannot double-apply (event claiming).
        """
        prior = self._coordinator_store.list_actions(workflow_id)
        if any(record.trigger == trigger for record in prior):
            return []
        cards = {c.id: c for c in self._store.list_cards(workflow_id)}
        sequence = self._coordinator_store.next_sequence(workflow_id)
        results: list[CoordinatorActionRecord] = []
        for offset, action in enumerate(actions):
            results.append(
                self._apply_one(
                    workflow_id, trigger, sequence + offset, cards, action
                )
            )
        return results

    def _apply_one(
        self,
        workflow_id: str,
        trigger: str,
        sequence: int,
        cards: dict[str, WorkCard],
        action: ProposedAction,
    ) -> CoordinatorActionRecord:
        reason = _validate(cards, action)
        applied = False
        if reason is None:
            new_card = self._apply(workflow_id, action)
            if new_card is not None:
                cards[new_card.id] = new_card
            applied = True
        return self._coordinator_store.record_action(
            CoordinatorActionRecord(
                id=f"action-{uuid.uuid4().hex[:8]}",
                workflow_id=workflow_id,
                trigger=trigger,
                sequence=sequence,
                action_payload=json.dumps(_action_payload(action)),
                validation_decision="rejected" if reason else "accepted",
                rejection_reason=reason,
                applied=applied,
            )
        )

    def _apply(
        self, workflow_id: str, action: ProposedAction
    ) -> WorkCard | None:
        """Apply an already-validated action; returns a newly created card."""
        if isinstance(action, CreateCardAction):
            return self._create_card(workflow_id, action)
        if isinstance(action, TransitionCardAction):
            self._board_service.transition_card(
                action.card_id,
                action.target_state,
                event_type="coordinator.transition_card",
            )
            return None
        if isinstance(action, CreateReconciliationCardAction):
            return self._create_reconciliation_card(workflow_id, action)
        return None

    def _create_card(
        self, workflow_id: str, action: CreateCardAction
    ) -> WorkCard:
        state = (
            CardState.WAITING_DEPENDENCY
            if action.depends_on
            else CardState.READY
        )
        card = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id,
            kind=action.kind,
            title=action.title,
            state=state,
            eligible_roles=action.eligible_roles,
            workspace_permission=action.workspace_permission,
        )
        self._store.create_card(card)
        for dep in action.depends_on:
            self._store.add_relation(CardRelation(card.id, dep))
        return card

    def _create_reconciliation_card(
        self, workflow_id: str, action: CreateReconciliationCardAction
    ) -> WorkCard:
        card = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id,
            kind=CardKind.RECONCILIATION,
            title=action.title,
            state=CardState.READY,
        )
        self._store.create_card(card)
        for conflicting_id in action.conflicting_card_ids:
            self._store.add_relation(
                CardRelation(
                    card.id, conflicting_id, kind=RelationKind.RECONCILIATION
                )
            )
        return card


def _validate(
    cards: dict[str, WorkCard], action: ProposedAction
) -> str | None:
    """Return a rejection reason, or ``None`` if *action* is allowed."""
    if isinstance(action, CreateCardAction):
        return _validate_create_card(cards, action)
    if isinstance(action, TransitionCardAction):
        return _validate_transition(cards, action)
    if isinstance(action, CreateReconciliationCardAction):
        return _validate_reconciliation(cards, action)
    return "unrecognized action"


def _validate_create_card(
    cards: dict[str, WorkCard], action: CreateCardAction
) -> str | None:
    if action.kind not in _VALID_CARD_KINDS:
        return f"unsupported card kind: {action.kind}"
    if action.workspace_permission not in _VALID_WORKSPACE_PERMISSIONS:
        return f"unsafe workspace_permission: {action.workspace_permission}"
    missing = [dep for dep in action.depends_on if dep not in cards]
    if missing:
        return f"depends_on references unknown card(s): {missing}"
    # A newly created card cannot close a cycle: its edges only point at
    # already-existing cards, never at itself or a not-yet-created one.
    return None


def _validate_transition(
    cards: dict[str, WorkCard], action: TransitionCardAction
) -> str | None:
    card = cards.get(action.card_id)
    if card is None:
        return f"unknown card: {action.card_id}"
    try:
        target = CardState(action.target_state)
    except ValueError:
        return f"unknown target state: {action.target_state}"
    if not is_valid_transition(CardState(card.state), target):
        return f"illegal transition {card.state} -> {action.target_state}"
    return None


def _validate_reconciliation(
    cards: dict[str, WorkCard], action: CreateReconciliationCardAction
) -> str | None:
    if len(action.conflicting_card_ids) < _MIN_RECONCILIATION_CARDS:
        return "reconciliation requires at least two conflicting cards"
    missing = [
        cid for cid in action.conflicting_card_ids if cid not in cards
    ]
    if missing:
        return f"conflicting_card_ids references unknown card(s): {missing}"
    return None


def _action_payload(action: ProposedAction) -> dict[str, object]:
    """Safe, JSON-serializable record of a proposed action for the ledger."""
    payload = dict(action.__dict__)
    payload["type"] = _action_type_name(action)
    return payload


def _action_type_name(action: ProposedAction) -> str:
    for name, (cls, _fields) in _ACTION_FIELDS.items():
        if isinstance(action, cls):
            return name
    return "unknown"
