"""Tests for the code-built CAB-2 executive summary (feature 030)."""
import pytest

from app.services.board.candidate import (
    Candidate,
    DecompositionTask,
    TaskEstimate,
)
from app.services.board.exec_summary import (
    HEADER,
    render_executive_summary,
    size_label,
    summary_totals,
)


def _task(
    task_id: str, size: str, man_hours: float, *,
    manual: bool = False, **fields: object,
) -> DecompositionTask:
    """A task estimated at *size*/*man_hours*; *fields* override the
    remaining estimate fields (e.g. ``confidence``, ``risks``)."""
    estimate: dict = {
        "confidence": "medium",
        "agent_tokens": 0 if manual else 100_000,
        "review_hours": 0 if manual else 1.5,
        "risks": (),
        "rationale": f"why {task_id}",
        **fields,
    }
    return DecompositionTask(
        title=f"Task {task_id}",
        body="b",
        task_node_id=task_id,
        classification="manual" if manual else "coding",
        estimate=TaskEstimate(size=size, man_hours=man_hours, **estimate),
    )


_CANDIDATE = Candidate(
    summary="We add a table and ask legal.",
    tasks=(
        _task("t1", "S", 2, risks=("auth",)),
        _task("t2", "S", 3, confidence="low", risks=("auth", "migration")),
        _task("t3", "L", 16, manual=True),
    ),
)


class TestTotals:
    def test_totals_are_sums_and_counts_of_the_tasks(self) -> None:
        """Ensure every total is derived, never written (SC-002)."""
        totals = summary_totals(_CANDIDATE)
        assert size_label(totals) == "2×S, 1×L"
        assert (
            totals.man_hours, totals.agent_tokens, totals.review_hours,
        ) == (21, 200_000, 3)
        assert (totals.low_confidence, totals.coding, totals.manual) == (
            1, 2, 1,
        )

    def test_risks_are_grouped_by_flag_in_first_seen_order(self) -> None:
        totals = summary_totals(_CANDIDATE)
        assert totals.risks == (
            ("auth", ("t1", "t2")), ("migration", ("t2",)),
        )

    def test_an_unestimated_task_is_refused(self) -> None:
        """Ensure partial estimates never produce understated totals."""
        candidate = Candidate(
            tasks=(DecompositionTask(title="x", body="y", task_node_id="t1"),)
        )
        with pytest.raises(ValueError, match="no estimate"):
            summary_totals(candidate)


class TestRendering:
    def test_the_summary_leads_with_the_unverified_header(self) -> None:
        text = render_executive_summary(_CANDIDATE)
        assert text.index(HEADER) < text.index("We add a table")

    def test_the_summary_shows_totals_split_and_rows(self) -> None:
        text = render_executive_summary(_CANDIDATE)
        assert "- **Tasks**: 3 (2 coding, 1 manual)" in text
        assert "- **Size**: 2×S, 1×L" in text
        assert "- **Human effort**: 21.0 man-hours" in text
        assert "- **Agent tokens**: 200,000" in text
        assert "- **Review effort**: 3.0 hours" in text
        assert "- **Low-confidence estimates**: 1 of 3" in text
        assert "- auth — t1, t2" in text
        assert "| t3 | Task t3 | manual | L | medium | 16.0 | 0 | 0.0 |" in (
            text
        )

    def test_the_risks_section_is_omitted_when_there_are_none(self) -> None:
        candidate = Candidate(summary="s", tasks=(_task("t1", "M", 5),))
        assert "## Risks" not in render_executive_summary(candidate)

    def test_agent_text_cannot_break_the_table(self) -> None:
        task = _task("t1", "M", 5)
        piped = DecompositionTask(
            title="a | b\nc", body="b", task_node_id="t1",
            estimate=task.estimate,
        )
        text = render_executive_summary(Candidate(summary="s", tasks=(piped,)))
        assert "| a \\| b c |" in text
