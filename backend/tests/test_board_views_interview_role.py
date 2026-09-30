"""An interview gate names the profile whose human answers it (038)."""
from __future__ import annotations

from dataclasses import replace

from app.models_board import SpecialistDefinition
from app.models_board_records import HumanGateRecord
from app.routers.board_views import card_summary, workflow_summary
from app.services.board.awaiting import Awaiting, awaiting_of
from app.services.board.specialists import SpecialistRoster
from tests.test_board_views import (
    _WORKFLOW,
    _card,
    _empty_lookups,
    _StubGates,
)

_DBA = SpecialistDefinition(
    id="dba", label="Database Specialist", purpose="data",
    allowed_card_types=("refinement",), required_abilities=(),
    model_policy="default", workspace_permission="read_only",
    retry_limit=1, prompt="",
)


def _gate():
    return _card("g1", kind="refinement_gate", state="awaiting_human")


def test_an_interview_gate_waits_on_its_profile() -> None:
    assert awaiting_of(_gate(), "dba") == Awaiting("role", "answer", "dba")
    # Without a known profile it falls back to the requester, as before.
    assert awaiting_of(_gate()).actor == "requester"


def test_the_snapshot_names_the_gates_profile() -> None:
    lookups = replace(
        _empty_lookups(),
        roster=SpecialistRoster({"dba": _DBA}),
        gates={"g1": HumanGateRecord(
            id="r1", card_id="g1", requested_decision="answer",
        )},
        gate_personas={"g1": "dba"},
    )

    summary = card_summary(_gate(), [], lookups)

    assert (summary.gate.persona.id, summary.gate.persona.label) == (
        "dba", "Database Specialist",
    )
    assert summary.awaiting.role.label == "Database Specialist"


class _PersonaGates(_StubGates):
    def interview_personas(self, _cards):
        return {"g1": "dba"}


def test_the_listing_names_the_profile_too() -> None:
    summary = workflow_summary(
        _WORKFLOW, [_gate()], _PersonaGates(),
        roster=SpecialistRoster({"dba": _DBA}),
    )

    (awaiting,) = summary.awaiting
    assert (awaiting.actor, awaiting.role.label) == (
        "role", "Database Specialist",
    )
