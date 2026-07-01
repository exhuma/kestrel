"""Model-selection policy mapping workflow steps to models."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings

#: Default step -> model map (spec SRD 2.7). Opus is never on
#: the default path; enable it per step via
#: ``KESTREL_MODEL_OVERRIDES``.
DEFAULT_MODELS: dict[str, str] = {
    "gap_analysis": "haiku",
    "clarify": "haiku",
    "describe": "sonnet",
    "plan": "sonnet",
    "implement": "sonnet",
}


class ModelPolicy:
    """Resolves which claude model a workflow step uses."""

    def __init__(self, overrides: dict[str, str]) -> None:
        self._map = {**DEFAULT_MODELS, **overrides}

    def model_for(self, step: str) -> str:
        """
        Return the model alias for a workflow step.

        :param step: Workflow step name, e.g. ``"plan"``.
        :returns: Alias to pass to ``claude --model``.
        :raises KeyError: If the step is unknown.
        """
        return self._map[step]


@lru_cache
def get_policy() -> ModelPolicy:
    """
    Return the process-wide ModelPolicy singleton.

    :returns: The cached model policy instance.
    """
    return ModelPolicy(get_settings().model_overrides)
