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
from collections.abc import Mapping

import httpx

from app.documents import Document, Heading, Text, document, paragraph
from app.models_board import WorkCard, Workflow
from app.ports import CodeHost
from app.services.board.agent_text import from_agent
from app.services.board.change_rounds import Round, start_round, summary_of
from app.services.board.interventions import (
    InvalidInterventionError,
    StaleInterventionError,
)
from app.services.board.materialise import MaterialiseTarget
from app.services.board.phases import DONE, outcome_of
from app.services.board.service import BoardService
from app.services.exceptions import GitError

_log = logging.getLogger("kestrel.board.requested_changes")

#: The event that records the request, and wakes the board.
REQUESTED_EVENT = "intervention.request_changes"
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
        """Start a round of changes from the person's feedback."""
        card = start_round(
            self._target, self._board_service, workflow_id,
            Round(
                title=f"Requested changes: {summary_of(feedback)}",
                spec=_task_spec(feedback),
                event_type=REQUESTED_EVENT,
                detail=feedback,
            ),
        )
        _log.info(
            "workflow %s: changes requested on delivered work (card %s)",
            workflow_id, card.id,
        )
        return card


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
