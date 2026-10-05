"""End-to-end: the coordinator-run interview, through the real dispatch
loop, to an approved PRD (feature 026 T078; feature 038).

Understanding approval starts the interview plan. The coordinator names
pm and dba; both draft, both ask the deadline; the review keeps it with
pm only. The operator answers; the coordinator brings in infosec for a
second batch; an empty plan then completes the interview, pm drafts the
PRD from every answer, and approving it records the approved scope.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.backends.base import TurnRequest, TurnResult
from app.services.board.dispatch_ready import dispatch_ready_work
from tests.interview_support import interview_stack

_DEADLINE = "What is the deadline?"
_STORAGE = "Where is the exported data stored?"
_PERSONAL = "Does the export contain personal data?"


def _questions(*prompts: str) -> str:
    return (
        "<REFINEMENT_QUESTIONS>"
        + json.dumps({"questions": list(prompts)})
        + "</REFINEMENT_QUESTIONS>"
    )


def _plan(*ids: str) -> str:
    entries = [{"specialist": sid, "reason": "test"} for sid in ids]
    body = json.dumps({"interviewers": entries})
    return f"<INTERVIEWERS>{body}</INTERVIEWERS>"


class _Scripted:
    """Answers each turn by card kind and specialist; records prompts."""

    def __init__(self) -> None:
        self.plans = [_plan("pm", "dba", "nobody"), _plan("infosec"), _plan()]
        self.reviews = [
            '<QUESTION_REVIEW>{"drop": [{"question": "dba-1", '
            '"duplicate_of": "pm-1"}]}</QUESTION_REVIEW>',
            '<QUESTION_REVIEW>{"drop": []}</QUESTION_REVIEW>',
        ]
        self.drafts = {
            "pm": _questions(_DEADLINE),
            "dba": _questions(_DEADLINE, _STORAGE),
            "infosec": _questions(_PERSONAL),
        }
        self.prompts: list[str] = []

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        self.prompts.append(req.prompt)
        text = self._answer(req.prompt)
        return TurnResult(session_id="turn", final_text=text)

    def _answer(self, prompt: str) -> str:
        if "Kind: interview_plan" in prompt:
            return self.plans.pop(0)
        if "Kind: question_review" in prompt:
            return self.reviews.pop(0)
        if "Kind: prd" in prompt:
            return "<PRD>Implement CSV export behind a feature flag.</PRD>"
        persona = prompt.split("You are ", 1)[1].split(".", 1)[0]
        return self.drafts[persona]


def _open_interviews(store, gates, artifacts) -> dict[str, list[str]]:
    """Open interview gates: persona -> the prompts it is asked."""
    cards = store.list_cards("wf-1")
    personas = gates.interview_personas(cards)
    found = {}
    for card in cards:
        if card.kind == "refinement_gate" and card.state == "awaiting_human":
            target = gates.get_gate(card.id).target_artifact_id
            found[personas[card.id]] = (
                json.loads(artifacts.read_content(target))["questions"]
            )
    return found


def _answer_all(store, gates, answers: dict[str, str]) -> None:
    for card in store.list_cards("wf-1"):
        if card.kind == "refinement_gate" and card.state == "awaiting_human":
            record = gates.get_gate(card.id)
            prompts = json.loads(
                gates._artifacts.read_content(record.target_artifact_id)
            )["questions"]
            gates.resolve(card.id, "approved", answer="\n\n".join(
                f"Q: {p}\nA: {answers[p]}" for p in prompts
            ))


_ANSWERS = {
    _DEADLINE: "Ship by Friday.",
    _STORAGE: "In the reporting database.",
    _PERSONAL: "Yes: customer names.",
}


class TestCoordinatedInterviewToPrd:
    @pytest.mark.asyncio
    async def test_plan_dedup_loop_in_and_prd(self, tmp_path: Path) -> None:
        services, store, gates, artifacts = interview_stack(tmp_path)
        backend = _Scripted()

        async def run() -> None:
            await dispatch_ready_work(
                "wf-1", services, lambda _s: backend, timeout_seconds=5
            )

        understanding = gates.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )
        gates.resolve(understanding.id, "approved")

        await run()  # the plan names pm and dba; both draft
        await run()  # the review keeps the deadline with pm only
        assert _open_interviews(store, gates, artifacts) == {
            "pm": [_DEADLINE], "dba": [_STORAGE],
        }

        _answer_all(store, gates, _ANSWERS)
        await run()  # the next plan brings in infosec, who drafts
        await run()  # its review (against the answers so far) keeps it
        assert _open_interviews(store, gates, artifacts) == {
            "infosec": [_PERSONAL],
        }

        _answer_all(store, gates, _ANSWERS)
        await run()  # an empty plan completes the interview; pm drafts
        (prd_gate,) = [
            c for c in store.list_cards("wf-1") if c.kind == "prd_gate"
        ]
        prd_prompt = next(p for p in backend.prompts if "Kind: prd" in p)
        for answer in _ANSWERS.values():
            assert answer in prd_prompt

        gates.resolve(prd_gate.id, "approved")
        assert store.get_workflow("wf-1").approved_prd.plain_text() == (
            "Implement CSV export behind a feature flag."
        )
