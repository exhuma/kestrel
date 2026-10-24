"""Tests for the decomposition candidate document (feature 030, R4)."""
import json

import pytest

from app.services.board.candidate import (
    DecompositionResultError,
    dump_candidate,
    load_candidate,
    parse_estimate,
)


def _doc(*tasks: dict, summary: object = "Short prose.") -> str:
    data: dict = {"tasks": list(tasks)}
    if summary is not None:
        data["summary"] = summary
    return json.dumps(data)


def _task(**overrides: object) -> dict:
    task: dict = {
        "title": "Do X", "body": "details", "classification": "coding",
    }
    task.update(overrides)
    return {k: v for k, v in task.items() if v is not None}


_ESTIMATE = {
    "size": "M", "confidence": "medium", "man_hours": 4,
    "agent_tokens": 1000, "review_hours": 1, "risks": [], "rationale": "r",
}


class TestStrict:
    def test_assigns_positional_ids_when_absent(self) -> None:
        candidate = load_candidate(
            _doc(_task(), _task(title="Do Y")), strict=True
        )
        assert [t.task_node_id for t in candidate.tasks] == ["t1", "t2"]

    def test_keeps_given_ids_and_fills_the_gaps(self) -> None:
        candidate = load_candidate(
            _doc(_task(task_node_id="db"), _task()), strict=True
        )
        assert [t.task_node_id for t in candidate.tasks] == ["db", "t2"]

    def test_an_assigned_id_colliding_with_a_given_one_is_rejected(
        self,
    ) -> None:
        """Ensure ids stay unique even after assignment."""
        with pytest.raises(DecompositionResultError, match="duplicate"):
            load_candidate(
                _doc(_task(), _task(task_node_id="t1")), strict=True
            )

    @pytest.mark.parametrize(
        "task",
        [
            _task(classification=None),
            _task(classification="maybe"),
            _task(title=""),
            _task(body=7),
            _task(prerequisites="t1"),
            _task(task_node_id=3),
        ],
        ids=[
            "unclassified", "bad-class", "empty-title", "non-string-body",
            "string-prereqs", "non-string-id",
        ],
    )
    def test_a_malformed_task_is_rejected(self, task: dict) -> None:
        with pytest.raises(DecompositionResultError):
            load_candidate(_doc(task), strict=True)

    @pytest.mark.parametrize("summary", [None, "", "   ", 5])
    def test_the_summary_prose_is_required(self, summary: object) -> None:
        with pytest.raises(DecompositionResultError, match="summary"):
            load_candidate(_doc(_task(), summary=summary), strict=True)

    @pytest.mark.parametrize(
        "raw", ["{not json", "[]", '{"tasks": []}', '{"tasks": "x"}']
    )
    def test_a_malformed_document_is_rejected(self, raw: str) -> None:
        with pytest.raises(DecompositionResultError):
            load_candidate(raw, strict=True)


class TestPrerequisites:
    """Strict prerequisite validation (feature 031, research R11)."""

    def test_valid_prerequisites_are_kept(self) -> None:
        candidate = load_candidate(
            _doc(_task(), _task(title="Do Y", prerequisites=["t1"])),
            strict=True,
        )
        assert candidate.tasks[1].prerequisites == ("t1",)

    @pytest.mark.parametrize(
        ("tasks", "match"),
        [
            ([_task(prerequisites=["t9"])], "unknown"),
            ([_task(prerequisites=["t1"])], "itself"),
            (
                [
                    _task(prerequisites=["t2"]),
                    _task(title="Do Y", prerequisites=["t1"]),
                ],
                "cycle",
            ),
        ],
        ids=["unknown", "self", "cycle"],
    )
    def test_a_bad_prerequisite_is_rejected(
        self, tasks: list[dict], match: str
    ) -> None:
        with pytest.raises(DecompositionResultError, match=match):
            load_candidate(_doc(*tasks), strict=True)

    def test_lenient_parsing_does_not_validate_them(self) -> None:
        """Ensure a gate approved before this feature still loads."""
        candidate = load_candidate(
            _doc(_task(prerequisites=["t9"])), strict=False
        )
        assert candidate.tasks[0].prerequisites == ("t9",)


class TestLenient:
    def test_a_legacy_candidate_defaults_to_coding(self) -> None:
        """Ensure a pre-030 gate target still reads (FR-019)."""
        candidate = load_candidate(
            '{"tasks": [{"title": "Do X", "body": "details"}]}', strict=False
        )
        task = candidate.tasks[0]
        assert task.classification == "coding"
        assert task.task_node_id == ""
        assert task.estimate is None
        assert candidate.summary == ""

    def test_an_invalid_classification_is_still_rejected(self) -> None:
        with pytest.raises(DecompositionResultError):
            load_candidate(
                _doc(_task(classification="maybe")), strict=False
            )


class TestRoundTrip:
    def test_dump_then_load_preserves_the_proposal(self) -> None:
        original = load_candidate(
            _doc(
                _task(estimate=_ESTIMATE),
                _task(title="Do Y", prerequisites=["t1"]),
            ),
            strict=True,
        )
        assert load_candidate(dump_candidate(original), strict=True) == (
            original
        )


class TestEstimateFields:
    def test_risks_are_trimmed_and_deduplicated(self) -> None:
        estimate = parse_estimate(
            {**_ESTIMATE, "risks": [" auth ", "auth", "", "migration"]}
        )
        assert estimate.risks == ("auth", "migration")

    def test_a_multiline_rationale_is_collapsed(self) -> None:
        estimate = parse_estimate({**_ESTIMATE, "rationale": "a\n  b"})
        assert estimate.rationale == "a b"

    @pytest.mark.parametrize(
        "override",
        [
            {"size": "XXL"},
            {"confidence": "sure"},
            {"man_hours": -1},
            {"man_hours": "4"},
            {"man_hours": True},
            {"agent_tokens": 1.5},
            {"review_hours": float("inf")},
            {"rationale": ""},
            {"risks": "auth"},
        ],
    )
    def test_a_malformed_field_is_rejected(self, override: dict) -> None:
        with pytest.raises(DecompositionResultError):
            parse_estimate({**_ESTIMATE, **override})
