"""Structured design-contract parsing and artifact rendering."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence

_DISPOSITIONS = frozenset({"automated", "manual", "not-applicable"})


@dataclass(frozen=True)
class AcceptanceScenario:
    """One PRD-traceable acceptance scenario and its disposition."""

    id: str
    parent_prd: str
    description: str
    disposition: str
    rationale: str


@dataclass(frozen=True)
class TaskNode:
    """One stable task-graph node and the node IDs it depends on."""

    id: str
    title: str
    prerequisites: list[str]


@dataclass(frozen=True)
class CheckCommand:
    """One proposed deterministic command with execution constraints."""

    command: str
    cwd: str
    timeout_seconds: int
    rationale: str


@dataclass(frozen=True)
class DesignContract:
    """The validated, versioned output accepted from the design agent."""

    plan: str
    boundary: str | None
    acceptance: list[AcceptanceScenario]
    tasks: list[TaskNode]
    checks: list[CheckCommand]


def _string(value: object) -> str | None:
    """Return a non-empty trimmed string, or ``None`` for any other value."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unique_ids(ids: Sequence[str]) -> bool:
    """Return whether all supplied object IDs are unique."""
    return len(ids) == len(set(ids))


def _parse_acceptance(data: object) -> list[AcceptanceScenario] | None:
    """Parse acceptance entries with stable IDs and disposition rationale."""
    if not isinstance(data, list):
        return None
    entries: list[AcceptanceScenario] = []
    for item in data:
        if not isinstance(item, dict):
            return None
        values = [_string(item.get(key)) for key in (
            "id", "parent_prd", "description", "disposition", "rationale"
        )]
        if any(value is None for value in values):
            return None
        scenario = AcceptanceScenario(*(value or "" for value in values))
        if scenario.disposition not in _DISPOSITIONS:
            return None
        entries.append(scenario)
    return entries if _unique_ids([entry.id for entry in entries]) else None


def _task_node(item: object) -> TaskNode | None:
    """Parse one task node, returning ``None`` when its shape is invalid."""
    if not isinstance(item, dict):
        return None
    node_id = _string(item.get("id"))
    title = _string(item.get("title"))
    prerequisites = item.get("prerequisites")
    if node_id is None or title is None or not isinstance(prerequisites, list):
        return None
    if not all(_string(value) is not None for value in prerequisites):
        return None
    return TaskNode(node_id, title, list(prerequisites))


def _parse_tasks(data: object) -> list[TaskNode] | None:
    """Parse task nodes, requiring valid stable IDs and prerequisites."""
    if not isinstance(data, list):
        return None
    entries = [_task_node(item) for item in data]
    if any(entry is None for entry in entries):
        return None
    tasks = [entry for entry in entries if entry is not None]
    known_ids = {entry.id for entry in tasks}
    valid_references = all(
        prerequisite in known_ids and prerequisite != entry.id
        for entry in tasks
        for prerequisite in entry.prerequisites
    )
    valid_ids = _unique_ids([entry.id for entry in tasks])
    valid_graph = valid_ids and valid_references and _is_acyclic(tasks)
    return tasks if valid_graph else None


def _is_acyclic(tasks: Sequence[TaskNode]) -> bool:
    """Return whether task prerequisites form a directed acyclic graph."""
    prerequisites = {task.id: set(task.prerequisites) for task in tasks}
    resolved: set[str] = set()
    visiting: set[str] = set()

    def visit(task_id: str) -> bool:
        """Resolve one node, rejecting a back-edge in its dependency path."""
        if task_id in resolved:
            return True
        if task_id in visiting:
            return False
        visiting.add(task_id)
        valid = all(visit(parent) for parent in prerequisites[task_id])
        visiting.remove(task_id)
        if valid:
            resolved.add(task_id)
        return valid

    return all(visit(task.id) for task in tasks)


def _check_command(item: object) -> CheckCommand | None:
    """Parse one command proposal, enforcing a positive integer timeout."""
    if not isinstance(item, dict):
        return None
    command = _string(item.get("command"))
    cwd = _string(item.get("cwd"))
    rationale = _string(item.get("rationale"))
    timeout = item.get("timeout_seconds")
    if (
        command is None
        or cwd is None
        or rationale is None
        or not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        return None
    return CheckCommand(command, cwd, timeout, rationale)


def _parse_checks(data: object) -> list[CheckCommand] | None:
    """Parse command proposals from the structured design output."""
    if not isinstance(data, list):
        return None
    entries = [_check_command(item) for item in data]
    if not all(entries):
        return None
    return [entry for entry in entries if entry is not None]


def parse_design_contract(raw: str) -> DesignContract | None:
    """Validate a ``<DESIGN_CONTRACT>`` JSON payload, or return ``None``."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    plan = _string(data.get("plan"))
    boundary = data.get("boundary")
    valid_boundary = boundary is None or boundary in {
        "http", "ui", "both", "none"
    }
    acceptance = _parse_acceptance(data.get("acceptance"))
    tasks = _parse_tasks(data.get("tasks"))
    checks = _parse_checks(data.get("checks"))
    if plan is None or not valid_boundary:
        return None
    if acceptance is None or tasks is None or checks is None:
        return None
    return DesignContract(plan, boundary, acceptance, tasks, checks)


def _json_artifact(items: Sequence[TaskNode | CheckCommand], key: str) -> str:
    """Serialize one versioned contract collection deterministically."""
    return json.dumps(
        {"version": 1, key: [dict(item.__dict__) for item in items]}, indent=2
    ) + "\n"


def task_graph_json(contract: DesignContract) -> str:
    """Render the task-DAG artifact from a parsed design contract."""
    return _json_artifact(contract.tasks, "tasks")


def check_contract_json(contract: DesignContract) -> str:
    """Render the proposed command-contract artifact from a design contract."""
    return _json_artifact(contract.checks, "commands")


def acceptance_markdown(contract: DesignContract) -> str:
    """Render a readable, PRD-traceable acceptance contract artifact."""
    lines = ["# Acceptance Contract", "", "Contract version: 1", ""]
    for scenario in contract.acceptance:
        lines.extend([
            f"## {scenario.id}",
            "",
            f"Parent PRD trace: {scenario.parent_prd}",
            "",
            scenario.description,
            "",
            f"Disposition: {scenario.disposition}",
            "",
            f"Rationale: {scenario.rationale}",
            "",
        ])
    return "\n".join(lines)
