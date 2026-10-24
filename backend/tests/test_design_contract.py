"""Tests for structured design contract parsing and artifact rendering."""
from __future__ import annotations

import json

from app.design_contract import (
    acceptance_markdown,
    check_contract_json,
    parse_design_contract,
    task_graph_json,
)


def _payload() -> str:
    """Return a valid minimal structured design response payload."""
    return json.dumps({
        "version": 1,
        "plan": "Add the requested setting.",
        "boundary": "http",
        "acceptance": [{
            "id": "AC-1",
            "parent_prd": "FR-1",
            "description": "A user can save the setting.",
            "disposition": "automated",
            "rationale": "A request test covers this behaviour.",
        }],
        "tasks": [{"id": "TASK-1", "title": "Implement setting",
                   "prerequisites": []}],
        "checks": [{"command": "pytest", "cwd": "backend",
                    "timeout_seconds": 60, "rationale": "Runs backend tests."}],
    })


def test_parse_design_contract_and_render_artifacts() -> None:
    """A valid contract produces readable and versioned handover artifacts."""
    contract = parse_design_contract(_payload())
    assert contract is not None
    assert "## AC-1" in acceptance_markdown(contract)
    assert "Parent PRD trace: FR-1" in acceptance_markdown(contract)
    assert json.loads(task_graph_json(contract))["tasks"][0]["id"] == "TASK-1"
    assert check_contract_json(contract).startswith('{\n  "version": 1')


def test_parse_design_contract_rejects_invalid_task_prerequisite() -> None:
    """Task dependencies must refer to another stable task ID in the graph."""
    data = json.loads(_payload())
    data["tasks"][0]["prerequisites"] = ["TASK-missing"]
    assert parse_design_contract(json.dumps(data)) is None


def test_parse_design_contract_rejects_cyclic_task_graph() -> None:
    """Task graph validation rejects indirect prerequisite cycles."""
    data = json.loads(_payload())
    data["tasks"] = [
        {"id": "TASK-1", "title": "First", "prerequisites": ["TASK-2"]},
        {"id": "TASK-2", "title": "Second", "prerequisites": ["TASK-1"]},
    ]
    assert parse_design_contract(json.dumps(data)) is None
