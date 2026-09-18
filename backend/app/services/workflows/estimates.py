"""Delivery-estimate normalization and CAB-decision rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from app.backends.base import Capability, ModelInfo

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService


async def coding_model_catalog(
    service: "WorkflowService",
) -> list[dict[str, object]]:
    """Return safe, serializable catalogues for the analysis turn."""
    result: list[dict[str, object]] = []
    for backend in service.backends.backends():
        if Capability.FILE_EDITS not in backend.caps:
            continue
        try:
            catalogue = await backend.list_models()
        except Exception:
            catalogue = None
        models: list[dict[str, object]] = []
        if catalogue is not None and catalogue.state == "available":
            models = [_model_data(model) for model in catalogue.models]
        result.append(
            {
                "backend_id": backend.id,
                "state": (
                    catalogue.state if catalogue is not None else "unknown"
                ),
                "models": models,
            }
        )
    return result


def normalize_task(
    task: dict[str, object], catalogues: list[dict[str, object]]
) -> None:
    """Supply bounded estimates and validate a recommendation."""
    task["effort_man_days"] = _positive_number(
        task.get("effort_man_days"), 1.0
    )
    task["coding_agent_token_estimate"] = _positive_int(
        task.get("coding_agent_token_estimate"), 10000
    )
    if _recommendation_is_eligible(
        task.get("recommended_backend_id"),
        task.get("recommended_model_id"),
        catalogues,
    ):
        task["model_recommendation_state"] = "available"
        return
    task["model_recommendation_state"] = "unknown"
    task["recommended_backend_id"] = None
    task["recommended_model_id"] = None


def delivery_estimate(task: dict[str, object]) -> str:
    """Render one task's approved delivery values for its source-task body."""
    return (
        "\n\n## Delivery estimate\n\n"
        f"- Effort: {task['effort_man_days']} man-days\n"
        f"- Coding-agent budget: {task['coding_agent_token_estimate']} tokens\n"
        f"- Recommended coding model: {_model_name(task)}"
    )


def cab_summary(tasks: list[dict[str, object]]) -> str:
    """Render the concise, decision-only final CAB comment."""
    effort = sum(cast(float, task["effort_man_days"]) for task in tasks)
    tokens = sum(
        cast(int, task["coding_agent_token_estimate"]) for task in tasks
    )
    allocation = "; ".join(
        f"{task['id']}: {_model_name(task)}" for task in tasks
    )
    return (
        "# CAB REVIEW REQUIRED\n\n"
        "- Scope: Approved requirements decomposed for delivery\n"
        f"- Child tasks: {len(tasks)}\n"
        f"- Estimated effort: {effort:g} man-days\n"
        f"- Coding-agent budget: {tokens} tokens\n"
        f"- Model allocation: {allocation}\n"
        "- Decision factors: See technical analysis; no additional blockers "
        "identified."
    )


def _model_data(model: ModelInfo) -> dict[str, object]:
    """Translate a model descriptor into JSON-ready catalogue data."""
    return {
        "id": model.id,
        "coding_quality": model.coding_quality,
        "input_cost_per_million": model.input_cost_per_million,
        "output_cost_per_million": model.output_cost_per_million,
    }


def _positive_number(value: object, fallback: float) -> float:
    """Return a positive numeric estimate or the conservative fallback."""
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return fallback


def _positive_int(value: object, fallback: int) -> int:
    """Return a positive integer estimate or the conservative fallback."""
    return value if isinstance(value, int) and value > 0 else fallback


def _recommendation_is_eligible(
    backend_id: object,
    model_id: object,
    catalogues: list[dict[str, object]],
) -> bool:
    """Check that a recommendation names a cost-qualified discovered model."""
    if not isinstance(backend_id, str) or not isinstance(model_id, str):
        return False
    for catalogue in catalogues:
        if catalogue["backend_id"] != backend_id:
            continue
        models = catalogue["models"]
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, dict) or model.get("id") != model_id:
                continue
            return all(
                isinstance(model.get(field), (int, float))
                and model[field] > 0
                for field in (
                    "coding_quality",
                    "input_cost_per_million",
                    "output_cost_per_million",
                )
            )
    return False


def _model_name(task: dict[str, object]) -> str:
    """Return an approved model name or explicit unknown marker."""
    if task.get("model_recommendation_state") != "available":
        return "unknown"
    return f"{task['recommended_backend_id']}/{task['recommended_model_id']}"
