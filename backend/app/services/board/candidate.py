"""The decomposition candidate document and its validation (feature 030).

One JSON shape travels from the ``pm``'s ``<DECOMPOSITION>`` block, via
the stored ``decomposition_candidate``, to the CAB-2 gate's
``cab2_proposal`` target — each stage a superset of the one before (the
proposal adds each task's :class:`TaskEstimate`). Parsing comes in two
modes (research R4):

- **strict**, for a fresh ``pm`` result: every task must be classified
  and the executive-summary prose present, and task ids are assigned
  where missing — so a task is never silently assumed agent-eligible;
- **lenient**, for reading back a gate target at publish time, which may
  predate this feature: a missing classification means ``coding``, a
  missing estimate means none (FR-019).
"""
import json
import math
from dataclasses import dataclass

CODING = "coding"
MANUAL = "manual"
CLASSIFICATIONS = (CODING, MANUAL)
SIZES = ("S", "M", "L", "XL")
CONFIDENCES = ("low", "medium", "high")


class DecompositionResultError(Exception):
    """Raised when a decomposition proposal cannot be trusted."""


@dataclass(frozen=True)
class TaskEstimate:
    """`developer`'s untrusted estimate of one task (data-model.md)."""

    size: str
    confidence: str
    man_hours: float
    agent_tokens: int
    review_hours: float
    risks: tuple[str, ...] = ()
    rationale: str = ""


@dataclass(frozen=True)
class DecompositionTask:
    """One task-source-ready follow-up task, its identity for dependency
    ordering, who can do it, and (once estimated) its estimate."""

    title: str
    body: str
    task_node_id: str = ""
    prerequisites: tuple[str, ...] = ()
    classification: str = CODING
    estimate: TaskEstimate | None = None


@dataclass(frozen=True)
class Candidate:
    """A whole decomposition proposal: summary prose plus its tasks."""

    tasks: tuple[DecompositionTask, ...]
    summary: str = ""

    def counts(self) -> tuple[int, int]:
        """``(coding, manual)`` task counts."""
        manual = sum(1 for t in self.tasks if t.classification == MANUAL)
        return len(self.tasks) - manual, manual


def load_candidate(raw: str, *, strict: bool) -> Candidate:
    """Parse one candidate JSON document.

    :raises DecompositionResultError: If it is malformed — always fail
        closed rather than guess.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DecompositionResultError(f"malformed result: {exc}") from exc
    if not isinstance(data, dict):
        raise DecompositionResultError("result must be a JSON object")
    entries = data.get("tasks")
    if not isinstance(entries, list) or not entries:
        raise DecompositionResultError("tasks must be a nonempty list")
    tasks = [_parse_task(entry, strict) for entry in entries]
    summary = _parse_summary(data.get("summary"), strict)
    if strict:
        tasks = _assign_ids(tasks)
        _check_prerequisites(tasks)
    return Candidate(tasks=tuple(tasks), summary=summary)


def dump_candidate(candidate: Candidate) -> str:
    """Serialize *candidate* back to the JSON shape :func:`load_candidate`
    reads — the normalized form every later stage sees."""
    return json.dumps(
        {
            "summary": candidate.summary,
            "tasks": [_task_json(task) for task in candidate.tasks],
        },
        indent=2,
    )


def parse_estimate(entry: dict[str, object]) -> TaskEstimate:
    """Validate one estimate's own fields (not the coding/manual rules,
    which need the task — see ``estimation.py``).

    :raises DecompositionResultError: On any malformed field.
    """
    return TaskEstimate(
        size=_choice(entry.get("size"), SIZES, "size"),
        confidence=_choice(
            entry.get("confidence"), CONFIDENCES, "confidence"
        ),
        man_hours=_number(entry.get("man_hours"), "man_hours"),
        agent_tokens=_tokens(entry.get("agent_tokens")),
        review_hours=_number(entry.get("review_hours"), "review_hours"),
        risks=_risks(entry.get("risks", [])),
        rationale=_rationale(entry.get("rationale")),
    )


def _parse_task(entry: object, strict: bool) -> DecompositionTask:
    if not isinstance(entry, dict):
        raise DecompositionResultError(f"malformed task entry: {entry!r}")
    raw_estimate = entry.get("estimate")
    return DecompositionTask(
        title=_text(entry.get("title"), "title"),
        body=_text(entry.get("body"), "body"),
        task_node_id=_optional_id(entry.get("task_node_id")),
        prerequisites=_string_list(
            entry.get("prerequisites", []), "prerequisites"
        ),
        classification=_classification(entry.get("classification"), strict),
        estimate=(
            parse_estimate(raw_estimate)
            if isinstance(raw_estimate, dict) else None
        ),
    )


def _parse_summary(value: object, strict: bool) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if strict:
        raise DecompositionResultError("summary must be a nonempty string")
    return ""


def _classification(value: object, strict: bool) -> str:
    if value is None and not strict:
        return CODING
    return _choice(value, CLASSIFICATIONS, "classification")


def _assign_ids(tasks: list[DecompositionTask]) -> list[DecompositionTask]:
    """Give every id-less task ``t<position>``; reject any duplicate."""
    assigned = [
        task if task.task_node_id
        else with_task_id(task, f"t{index}")
        for index, task in enumerate(tasks, start=1)
    ]
    ids = [task.task_node_id for task in assigned]
    if len(set(ids)) != len(ids):
        raise DecompositionResultError(f"duplicate task_node_id in {ids}")
    return assigned


def _check_prerequisites(tasks: list[DecompositionTask]) -> None:
    """Reject a prerequisite that names no task, the task itself, or
    closes a cycle (feature 031, research R11) — prerequisites become
    card dependencies, so a bad one would strand work for ever."""
    graph = {task.task_node_id: task.prerequisites for task in tasks}
    for node, prerequisites in graph.items():
        unknown = [p for p in prerequisites if p not in graph]
        if unknown:
            raise DecompositionResultError(
                f"task {node} has unknown prerequisite(s) {unknown}"
            )
        if node in prerequisites:
            raise DecompositionResultError(f"task {node} requires itself")
    _check_acyclic(graph)


def _check_acyclic(graph: dict[str, tuple[str, ...]]) -> None:
    """Kahn's algorithm: any node never freed sits on a cycle."""
    pending = {node: len(prereqs) for node, prereqs in graph.items()}
    freed = [node for node, count in pending.items() if count == 0]
    while freed:
        done = freed.pop()
        for node, prereqs in graph.items():
            if done in prereqs:
                pending[node] -= 1
                if pending[node] == 0:
                    freed.append(node)
    cyclic = sorted(node for node, count in pending.items() if count > 0)
    if cyclic:
        raise DecompositionResultError(
            f"prerequisites form a cycle through {cyclic}"
        )


def with_task_id(
    task: DecompositionTask, task_node_id: str
) -> DecompositionTask:
    """*task* with its ``task_node_id`` set to *task_node_id*."""
    return DecompositionTask(
        title=task.title,
        body=task.body,
        task_node_id=task_node_id,
        prerequisites=task.prerequisites,
        classification=task.classification,
        estimate=task.estimate,
    )


def _task_json(task: DecompositionTask) -> dict[str, object]:
    data: dict[str, object] = {
        "task_node_id": task.task_node_id,
        "title": task.title,
        "body": task.body,
        "prerequisites": list(task.prerequisites),
        "classification": task.classification,
    }
    if task.estimate is not None:
        estimate = task.estimate
        data["estimate"] = {
            "size": estimate.size,
            "confidence": estimate.confidence,
            "man_hours": estimate.man_hours,
            "agent_tokens": estimate.agent_tokens,
            "review_hours": estimate.review_hours,
            "risks": list(estimate.risks),
            "rationale": estimate.rationale,
        }
    return data


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecompositionResultError(f"{name} must be a nonempty string")
    return value


def _optional_id(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DecompositionResultError("task_node_id must be a string")
    return value.strip()


def _string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise DecompositionResultError(f"{name} must be a list of strings")
    return tuple(value)


def _choice(value: object, allowed: tuple[str, ...], name: str) -> str:
    if value not in allowed:
        raise DecompositionResultError(
            f"{name} must be one of {', '.join(allowed)}, got {value!r}"
        )
    return str(value)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DecompositionResultError(f"{name} must be a number")
    if not math.isfinite(value) or value < 0:
        raise DecompositionResultError(f"{name} must be finite and >= 0")
    return float(value)


def _tokens(value: object) -> int:
    number = _number(value, "agent_tokens")
    if not number.is_integer():
        raise DecompositionResultError("agent_tokens must be an integer")
    return int(number)


def _risks(value: object) -> tuple[str, ...]:
    items = _string_list(value, "risks")
    seen: dict[str, None] = {}
    for item in items:
        if item.strip():
            seen.setdefault(item.strip(), None)
    return tuple(seen)


def _rationale(value: object) -> str:
    text = _text(value, "rationale")
    return " ".join(text.split())
