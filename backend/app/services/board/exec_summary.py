"""The CAB-2 executive summary, computed rather than written (feature 030).

Pure functions over an estimated :class:`Candidate`: the ``pm``'s prose
is quoted verbatim, and every figure beneath it is a plain sum or count
of the per-task estimates (SC-002) — the arithmetic is trustworthy even
though its inputs are untrusted agent output, which the header says in
so many words. kestrel itself recommends nothing (FR-014).
"""
from dataclasses import dataclass

from app.services.board.candidate import (
    MANUAL,
    SIZES,
    Candidate,
    DecompositionTask,
    TaskEstimate,
)

HEADER = (
    "_Agent estimates — unverified. kestrel makes no go/no-go "
    "recommendation._"
)


@dataclass(frozen=True)
class SummaryTotals:
    """Every aggregate the summary shows (data-model.md)."""

    size_counts: tuple[tuple[str, int], ...]
    man_hours: float
    agent_tokens: int
    review_hours: float
    low_confidence: int
    coding: int
    manual: int
    risks: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def task_count(self) -> int:
        """How many tasks the totals cover."""
        return self.coding + self.manual


def summary_totals(candidate: Candidate) -> SummaryTotals:
    """Aggregate *candidate*'s estimates.

    :raises ValueError: If any task is unestimated — a summary over
        partial estimates would understate the totals.
    """
    estimates = [_estimate_of(task) for task in candidate.tasks]
    coding, manual = candidate.counts()
    return SummaryTotals(
        size_counts=tuple(
            (size, count)
            for size in SIZES
            if (count := sum(1 for e in estimates if e.size == size))
        ),
        man_hours=sum(e.man_hours for e in estimates),
        agent_tokens=sum(e.agent_tokens for e in estimates),
        review_hours=sum(e.review_hours for e in estimates),
        low_confidence=sum(1 for e in estimates if e.confidence == "low"),
        coding=coding,
        manual=manual,
        risks=_risk_index(candidate.tasks),
    )


def render_executive_summary(candidate: Candidate) -> str:
    """The Markdown executive summary CAB-2 is decided on."""
    totals = summary_totals(candidate)
    sections = [
        "# Executive summary",
        HEADER,
        candidate.summary,
        "## Totals",
        _totals_block(totals),
    ]
    if totals.risks:
        sections += ["## Risks", _risks_block(totals)]
    sections += ["## Tasks", _task_table(candidate.tasks)]
    return "\n\n".join(sections) + "\n"


def size_label(totals: SummaryTotals) -> str:
    """Size counts as e.g. ``2×S, 1×L`` — zero buckets omitted."""
    return ", ".join(f"{count}×{size}" for size, count in totals.size_counts)


def _estimate_of(task: DecompositionTask) -> TaskEstimate:
    if task.estimate is None:
        raise ValueError(f"task {task.task_node_id!r} has no estimate")
    return task.estimate


def _risk_index(
    tasks: tuple[DecompositionTask, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Each distinct risk, in first-seen order, with the tasks naming it."""
    index: dict[str, list[str]] = {}
    for task in tasks:
        for risk in _estimate_of(task).risks:
            index.setdefault(risk, []).append(task.task_node_id)
    return tuple((risk, tuple(ids)) for risk, ids in index.items())


def _totals_block(totals: SummaryTotals) -> str:
    return "\n".join(
        [
            f"- **Tasks**: {totals.task_count} "
            f"({totals.coding} coding, {totals.manual} manual)",
            f"- **Size**: {size_label(totals)}",
            f"- **Human effort**: {totals.man_hours:.1f} man-hours "
            "(by hand, without an agent)",
            f"- **Agent tokens**: {totals.agent_tokens:,}",
            f"- **Review effort**: {totals.review_hours:.1f} hours",
            f"- **Low-confidence estimates**: {totals.low_confidence} "
            f"of {totals.task_count}",
        ]
    )


def _risks_block(totals: SummaryTotals) -> str:
    return "\n".join(
        f"- {risk} — {', '.join(ids)}" for risk, ids in totals.risks
    )


def _task_table(tasks: tuple[DecompositionTask, ...]) -> str:
    rows = [
        "| Id | Task | Kind | Size | Confidence | Man-hours | Tokens "
        "| Review h | Rationale |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows += [_task_row(task) for task in tasks]
    return "\n".join(rows)


def _task_row(task: DecompositionTask) -> str:
    estimate = _estimate_of(task)
    kind = "manual" if task.classification == MANUAL else "coding"
    cells = [
        task.task_node_id,
        task.title,
        kind,
        estimate.size,
        estimate.confidence,
        f"{estimate.man_hours:.1f}",
        f"{estimate.agent_tokens:,}",
        f"{estimate.review_hours:.1f}",
        estimate.rationale,
    ]
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def _cell(text: str) -> str:
    """Keep agent text from breaking the table's row structure."""
    return " ".join(text.split()).replace("|", "\\|")
