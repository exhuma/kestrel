"""Send a delivered request back for more work (stepping stone to spec 044).

Only a person says what to change here. Spec 044 will add review comments
on the pull/merge request as a second source of the same feedback, so
everything after "here is the feedback" lives in
:meth:`RequestChangesService.request`.

The feedback becomes the work's ``task_spec``, exactly as an approved
CAB-2 task does (``materialise.py``). The coder, the verifier and any
remediation therefore all work from it, the verification rounds are
capped, and a clean verification delivers to the same change request.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping

import httpx

from app.documents import Document, Heading, Text, document, paragraph
from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
    Workflow,
    WorkspacePermission,
)
from app.ports import CodeHost
from app.services.board.agent_text import from_agent
from app.services.board.interventions import (
    InvalidInterventionError,
    StaleInterventionError,
)
from app.services.board.materialise import (
    TASK_SPEC_LOGICAL_NAME,
    MaterialiseTarget,
)
from app.services.board.phases import DONE, outcome_of
from app.services.board.retries import detail_of
from app.services.board.service import BoardService
from app.services.exceptions import GitError

_log = logging.getLogger("kestrel.board.requested_changes")

#: The event that records the request, and wakes the board.
REQUESTED_EVENT = "intervention.request_changes"
#: The most of the feedback's first line a card's title shows.
_TITLE_LIMIT = 80
_HEADING_LEVEL = 1


class RequestChangesService:
    """Turns feedback on delivered work into more work on the same branch."""

    def __init__(
        self,
        target: MaterialiseTarget,
        board_service: BoardService,
        code_hosts: Mapping[str, CodeHost],
    ) -> None:
        """
        :param target: Where the new cards and their ``task_spec`` go.
        :param board_service: Starts the work and records why.
        :param code_hosts: By task source, to check the change request.
        """
        self._target = target
        self._board_service = board_service
        self._code_hosts = code_hosts

    async def request(
        self, workflow: Workflow, feedback: str, *, expected_revision: int
    ) -> WorkCard:
        """Start a round of changes on *workflow*'s delivered branch.

        :param workflow: The delivered request.
        :param feedback: What should change, in Markdown.
        :param expected_revision: The board revision the requester saw.
        :returns: The implementation card now ready to be worked.
        :raises StaleInterventionError: If the board has moved on.
        :raises InvalidInterventionError: If there is no feedback, the
            request is not delivered, or its change request is not open.
        """
        text = feedback.strip()
        if not text:
            raise InvalidInterventionError("say what should change")
        if workflow.revision != expected_revision:
            raise StaleInterventionError(
                f"expected revision {expected_revision}, "
                f"board is at {workflow.revision}"
            )
        cards = self._target.store.list_cards(workflow.id)
        if outcome_of(cards) != DONE:
            raise InvalidInterventionError(
                "changes can only be requested once the work is delivered "
                "and nothing else is open"
            )
        await self._require_open_change_request(workflow)
        return self._start(workflow.id, text)

    async def _require_open_change_request(self, workflow: Workflow) -> None:
        """Refuse work that could never reach a reviewer. A request with
        no change request (a local task source) has nothing to check."""
        code_host = self._code_hosts.get(workflow.source)
        number = workflow.change_request_number
        if code_host is None or number is None:
            return
        try:
            change = await code_host.get_change_request(workflow.repo, number)
        except (GitError, httpx.HTTPError) as exc:
            _log.warning(
                "workflow %s: could not read change request #%d",
                workflow.id, number, exc_info=exc,
            )
            raise InvalidInterventionError(
                "could not confirm the change request is still open; "
                "try again"
            ) from exc
        if change.state != "open":
            raise InvalidInterventionError(
                f"the change request is {change.state}; open a follow-up "
                "ticket instead"
            )

    def _start(self, workflow_id: str, feedback: str) -> WorkCard:
        """Create the fix and its verification, then start the fix last,
        so nothing can pick it up before its task text exists."""
        store = self._target.store
        node = f"changes-{uuid.uuid4().hex[:8]}"
        title = f"Requested changes: {_summary(feedback)}"
        fix = _card(workflow_id, node, title, CardKind.IMPLEMENTATION)
        check = _card(
            workflow_id, node, f"Verify: {title}", CardKind.VERIFICATION
        )
        store.create_card(fix)
        store.create_card(check)
        store.add_relation(
            CardRelation(
                card_id=check.id,
                depends_on_card_id=fix.id,
                kind=RelationKind.DEPENDENCY,
            ),
            created_by_action="request_changes",
        )
        self._target.artifacts.store_document(
            fix.id, TASK_SPEC_LOGICAL_NAME, 1, _task_spec(feedback),
            trust="operator_approved",
        )
        # The next push is new code, so its CI has to be watched again.
        store.record_ci_status(workflow_id, "pending")
        _log.info(
            "workflow %s: changes requested on delivered work (card %s)",
            workflow_id, fix.id,
        )
        return self._board_service.transition_card(
            fix.id, CardState.READY.value,
            event_type=REQUESTED_EVENT, payload=detail_of(feedback),
        )


def _card(
    workflow_id: str, node: str, title: str, kind: CardKind
) -> WorkCard:
    """One waiting card of this round of changes."""
    is_fix = kind == CardKind.IMPLEMENTATION
    return WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=kind.value,
        title=title,
        state=CardState.WAITING_DEPENDENCY.value,
        eligible_roles=("coder",) if is_fix else ("verifier",),
        workspace_permission=(
            WorkspacePermission.WRITE.value if is_fix
            else WorkspacePermission.READ_ONLY.value
        ),
        task_node_id=node,
    )


def _summary(feedback: str) -> str:
    """The feedback's first line, short enough for a card's title."""
    first = feedback.splitlines()[0].strip()
    if len(first) <= _TITLE_LIMIT:
        return first
    return f"{first[:_TITLE_LIMIT].rstrip()}…"


def _task_spec(feedback: str) -> Document:
    """The feedback as the text every card of this round works from."""
    return document(
        Heading(_HEADING_LEVEL, (Text("Requested changes"),)),
        paragraph(Text(
            "The delivered work was reviewed and needs these changes. "
            "Make them on the existing branch, and leave the rest as it is."
        )),
        *from_agent(feedback).blocks,
    )
